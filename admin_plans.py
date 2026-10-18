"""Manual per-account plan metadata and atomic quota assignment; no billing API."""
import re
import uuid
from firebase_admin import auth
from google.api_core.exceptions import PreconditionFailed
import admin_connections
import admin_usage
import admission_policy
import job_runtime
import plan_catalog


def register_routes(core):
    @core.app.put('/api/admin/users/plan')
    def admin_assign_plan():
        admin_connections.require_admin(core)
        if core.request.headers.get('Origin') not in admin_usage.ORIGINS or core.request.headers.get('X-Requested-With') != 'XmlHttpRequest':
            raise core.AppError('El origen de la configuración no es válido.', 403)
        data = core.request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'uid', 'name', 'priceMinor', 'currency', 'daily', 'monthly', 'generation'}:
            raise core.AppError('La configuración del plan no es válida.', 400)
        uid, generation = data['uid'], data['generation']
        if not isinstance(uid, str) or not 1 <= len(uid) <= 128 or any(ord(char) < 32 for char in uid):
            raise core.AppError('La cuenta no es válida.', 400)
        if not isinstance(generation, str) or not re.fullmatch(r'[0-9]{1,30}', generation):
            raise core.AppError('La versión de la configuración no es válida.', 400)
        try:
            limits = admission_policy.validate_limits({key: data[key] for key in ('daily', 'monthly')})
            plan = admission_policy.validate_plan({key: data[key] for key in ('name', 'priceMinor', 'currency')} | {
                'interval': 'month', 'collection': 'manual', 'paymentStatus': 'unverified'})
        except ValueError:
            raise core.AppError('Verifica plan, moneda, precio en centavos y límites enteros. El plan básico es gratuito.', 400) from None
        try:
            auth.get_user(uid)
            store = job_runtime.JobStore()
            catalog, _ = plan_catalog.load(store)
            preset = next((item for item in catalog if item['id'] == plan['name']), None)
            if plan['name'] == 'basic':
                limits = {key: catalog[0][key] for key in ('daily', 'monthly')}
            elif preset is None or any(limits[key] != preset[key] for key in ('daily', 'monthly')):
                plan['customLimits'] = True
            plan['assignmentId'] = uuid.uuid4().hex
            store.write(admission_policy.policy_key(uid), {**limits, 'plan': plan}, int(generation))
            _, new_generation = store.read(admission_policy.policy_key(uid))
            response = core.jsonify(ok=True, uid=uid, plan=plan, limits=limits, generation=str(new_generation))
            response.headers['Cache-Control'] = 'no-store, private'
            return response
        except PreconditionFailed:
            raise core.AppError('La configuración cambió. Actualiza antes de asignar el plan.', 409) from None
        except auth.UserNotFoundError:
            raise core.AppError('La cuenta ya no existe.', 404) from None
        except Exception:
            raise core.AppError('No se pudo confirmar la asignación. Actualiza la cuenta antes de reintentar.', 503) from None
