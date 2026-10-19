"""Published manual plan catalog; no checkout, charges or automatic assignment."""
import re
import hashlib
import json
import time
from google.api_core.exceptions import PreconditionFailed
import admin_connections
import admission_policy
import job_runtime

CATALOG_KEY = 'admin-plan-catalog'


def _text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or any(ord(char) < 32 for char in value):
        raise ValueError('Texto inválido en el catálogo.')
    return value.strip()


def validate_entries(entries):
    if not isinstance(entries, list) or not 2 <= len(entries) <= 3:
        raise ValueError('Configura Plus y Pro, y opcionalmente Personalizado.')
    clean, seen = [], set()
    required = {'id', 'label', 'daily', 'monthly', 'priceMinor', 'benefits'}
    for item in entries:
        if not isinstance(item, dict) or set(item) not in (required, required | {'published'}):
            raise ValueError('Entrada de catálogo inválida.')
        identifier = item['id']
        if not isinstance(identifier, str) or identifier not in {'plus', 'pro', 'custom'} or identifier in seen:
            raise ValueError('Identificador de plan inválido o duplicado.')
        seen.add(identifier)
        quotas = admission_policy.validate_limits({key: item[key] for key in ('daily', 'monthly')})
        price = item['priceMinor']
        if price is not None and (type(price) is not int or not 1 <= price <= 100000000):
            raise ValueError('El precio de pago debe ser positivo o quedar sin configurar.')
        benefits = item['benefits']
        if not isinstance(benefits, list) or len(benefits) > 8:
            raise ValueError('Máximo ocho beneficios por plan.')
        published = item.get('published', True)
        if type(published) is not bool:
            raise ValueError('Publicación inválida.')
        clean.append(dict(id=identifier, label=_text(item['label'], 60), **quotas, priceMinor=price,
                          benefits=[_text(value, 160) for value in benefits], published=published))
    if not {'plus', 'pro'} <= seen:
        raise ValueError('Faltan los planes Plus o Pro.')
    return clean


def load(store, global_limits=None):
    if global_limits is None:
        global_limits, _ = admission_policy.read_policy(store)
        global_limits = global_limits or dict(zip(('daily', 'monthly'), admission_policy.limits()))
    document, generation = store.read(CATALOG_KEY)
    if document is None:
        entries = validate_entries([{**item, 'benefits': []} for item in admission_policy.PLAN_CATALOG if item['id'] != 'basic'])
    elif isinstance(document, dict) and set(document) == {'plans'}:
        entries = validate_entries(document['plans'])
    else:
        raise ValueError('El catálogo no se pudo verificar.')
    basic = dict(id='basic', label='Básico', daily=global_limits['daily'], monthly=global_limits['monthly'],
                 priceMinor=0, benefits=[], published=True)
    return [basic, *entries], generation


def register_routes(core):
    @core.app.put('/api/admin/plans/catalog')
    def save_catalog():
        admin_connections.require_admin(core)
        import admin_usage
        if core.request.headers.get('Origin') not in admin_usage.ORIGINS or core.request.headers.get('X-Requested-With') != 'XmlHttpRequest':
            raise core.AppError('El origen de la configuración no es válido.', 403)
        data = core.request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'generation', 'plans'} or not isinstance(data['generation'], str) or not re.fullmatch(r'[0-9]{1,30}', data['generation']):
            raise core.AppError('La versión del catálogo no es válida.', 400)
        try:
            entries = validate_entries(data['plans'])
        except ValueError:
            raise core.AppError('Revisa los planes Plus y Pro, cupos de 0 a 10000, precio positivo o vacío, nombre de hasta 60 caracteres y hasta ocho beneficios de 160 caracteres.', 400) from None
        try:
            store = job_runtime.JobStore()
            store.write(CATALOG_KEY, {'plans': entries}, int(data['generation']))
            catalog, generation = load(store)
            response = core.jsonify(ok=True, planCatalog=catalog, catalogGeneration=str(generation))
            response.headers['Cache-Control'] = 'no-store, private'
            return response
        except PreconditionFailed:
            raise core.AppError('El catálogo cambió. Actualiza antes de guardar.', 409) from None
        except Exception:
            raise core.AppError('No se pudo confirmar el catálogo. Actualiza antes de reintentar.', 503) from None

    @core.app.get('/api/subscription')
    def own_subscription():
        identity = getattr(core.g, 'google_identity', None) or {}
        uid = identity.get('uid')
        if not uid:
            raise core.AppError('Inicia sesión para consultar tu plan.', 401)
        try:
            store = job_runtime.JobStore()
            document, version = admission_policy.read_policy_document(store, uid)
            plan = (document or {}).get('plan')
            global_limits, global_version = admission_policy.read_policy(store)
            global_limits = global_limits or dict(zip(('daily', 'monthly'), admission_policy.limits()))
            limits = ({key: document[key] for key in ('daily', 'monthly')} if document and (not plan or plan['name'] != 'basic') else global_limits)
            catalog, generation = load(store, global_limits)
            entry = next((item for item in catalog if item['id'] == (plan or {}).get('name', 'basic')), None)
            queue, _ = store.read(admission_policy.queue_key(uid))
            usage = admission_policy.usage_summary(queue, time.time(), limits)
            response = core.jsonify(plan=plan, limits=limits, usage=usage,
                changeVersion=hashlib.sha256(json.dumps([str(version), str(global_version), limits], sort_keys=True).encode()).hexdigest(),
                benefits=(entry or {}).get('benefits', []), planLabel=(entry or {}).get('label', 'Personalizado'),
                assignmentVersion=(plan.get('assignmentId') or hashlib.sha256(json.dumps({key: value for key, value in plan.items() if key != 'customLimits'}, sort_keys=True).encode()).hexdigest()) if plan and plan['name'] != 'basic' else None,
                planCatalog=[item for item in catalog if item['published']], catalogGeneration=str(generation),
                payment={'collection': 'manual', 'status': 'unverified'}, timeZone='UTC')
            response.headers['Cache-Control'] = 'no-store, private'
            return response
        except Exception:
            raise core.AppError('No se pudo verificar tu plan y consumo. Reintenta.', 503) from None
