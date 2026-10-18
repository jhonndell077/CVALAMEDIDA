"""Administrator quota configuration and minimal registered-account consumption.

Dedicated CAS documents in the existing private job bucket; never edits Firebase
users or professional profiles. Enumeration selects only the displayed fields.
"""
import re
import time
from datetime import datetime, timedelta, timezone

from google.api_core.exceptions import PreconditionFailed
from firebase_admin import auth
import admin_connections
import admission_policy
import job_runtime
import plan_catalog

ORIGINS = frozenset({'https://cvalamedida.web.app', 'https://cv-a-la-medida-jhonn.web.app',
                     'https://cv-a-la-medida-jhonn.firebaseapp.com'})


def _text(value, maximum):
    return ''.join(char for char in (value if isinstance(value, str) else '') if ord(char) >= 32)[:maximum]


def register_routes(core):
    def reply(**data):
        response = core.jsonify(**data)
        response.headers['Cache-Control'] = 'no-store, private'
        return response

    @core.app.get('/api/admin/usage')
    def admin_usage():
        admin_connections.require_admin(core)
        size = core.request.args.get('pageSize', '20')
        token = core.request.args.get('pageToken')
        if not re.fullmatch(r'[0-9]{1,2}', size) or not 1 <= int(size) <= 50 or (token is not None and (not token or len(token) > 2048)):
            raise core.AppError('La página solicitada no es válida.', 400)
        try:
            store = job_runtime.JobStore()
            global_override, generation = admission_policy.read_policy(store)
            defaults = dict(zip(('daily', 'monthly'), admission_policy.limits()))
            global_policy = global_override or defaults
            catalog, catalog_generation = plan_catalog.load(store, global_policy)
            page = auth.list_users(page_token=token, max_results=int(size))
            timestamp = time.time()
            accounts = []
            for user in page.users:
                uid = user.uid
                document, version = admission_policy.read_policy_document(store, uid)
                override = ({key: document[key] for key in ('daily', 'monthly')} if document else None)
                if document and document.get('plan', {}).get('name') == 'basic':
                    override = dict(global_policy)
                policy = override or global_policy
                queue, _ = store.read(admission_policy.queue_key(uid))
                accounts.append(dict(uid=uid, email=_text(user.email, 320), displayName=_text(user.display_name, 200),
                    disabled=user.disabled is True, limits=policy, plan=(document or {}).get('plan'),
                    override=({**override, 'generation': str(version)} if override is not None else None),
                    overrideGeneration=str(version), usage=admission_policy.usage_summary(queue, timestamp, policy)))
            now = datetime.fromtimestamp(timestamp, timezone.utc)
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            next_month = now.replace(year=now.year + (now.month == 12), month=now.month % 12 + 1,
                                     day=1, hour=0, minute=0, second=0, microsecond=0)
            return reply(at=now.isoformat(), timeZone='UTC', defaults=defaults,
                **{'global': {**global_policy, 'generation': str(generation)}}, accounts=accounts,
                planCatalog=catalog, catalogGeneration=str(catalog_generation),
                resets={'daily': tomorrow.isoformat(), 'monthly': next_month.isoformat()},
                nextPageToken=page.next_page_token or None)
        except Exception as error:
            if isinstance(error, core.AppError):
                raise
            raise core.AppError('No se pudieron consultar las cuentas y sus consumos. Reintenta.', 503) from None

    @core.app.put('/api/admin/usage/limits')
    def admin_usage_limits():
        admin_connections.require_admin(core)
        if core.request.headers.get('Origin') not in ORIGINS or core.request.headers.get('X-Requested-With') != 'XmlHttpRequest':
            raise core.AppError('El origen del cambio no es válido.', 403)
        data = core.request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('scope'), str) or data.get('scope') not in {'global', 'account'}:
            raise core.AppError('La configuración no es válida.', 400)
        account = data['scope'] == 'account'
        inheriting = data.get('inherit') is True
        expected = {'scope', 'generation'} | ({'uid'} if account else set()) | ({'inherit'} if inheriting else {'daily', 'monthly'})
        version = data.get('generation')
        uid = data.get('uid', '')
        if set(data) != expected or (inheriting and not account) or not isinstance(version, str) or not re.fullmatch(r'[0-9]{1,30}', version):
            raise core.AppError('La configuración no es válida.', 400)
        if account and (not isinstance(uid, str) or not 1 <= len(uid) <= 128 or any(ord(char) < 32 for char in uid)):
            raise core.AppError('La cuenta no es válida.', 400)
        try:
            policy = {'inherit': True} if inheriting else admission_policy.validate_limits({key: data[key] for key in ('daily', 'monthly')})
        except ValueError:
            raise core.AppError('Los límites deben ser enteros entre 0 y 10000.', 400) from None
        try:
            store = job_runtime.JobStore()
            # Verify existence without modifying the account; reject arbitrary orphan config.
            if account:
                auth.get_user(uid)
            if account and not inheriting:
                previous, current_generation = admission_policy.read_policy_document(store, uid)
                if str(current_generation) != version:
                    raise PreconditionFailed('configuration changed')
                if previous and previous.get('plan'):
                    if previous['plan']['name'] == 'basic':
                        global_policy, _ = admission_policy.read_policy(store)
                        policy = global_policy or dict(zip(('daily', 'monthly'), admission_policy.limits()))
                        policy['plan'] = {key: value for key, value in previous['plan'].items() if key != 'customLimits'}
                    else:
                        policy['plan'] = {**previous['plan'], 'customLimits': True}
            store.write(admission_policy.policy_key(uid), policy, int(version))
            _, new_generation = store.read(admission_policy.policy_key(uid))
            return reply(ok=True, scope=data['scope'], uid=uid if account else None, generation=str(new_generation),
                         limits=None if inheriting else policy, inherit=inheriting)
        except PreconditionFailed:
            raise core.AppError('Otro cambio actualizó los límites. Recarga antes de guardar.', 409) from None
        except auth.UserNotFoundError:
            raise core.AppError('La cuenta ya no existe.', 404) from None
        except Exception:
            raise core.AppError('No se pudieron guardar los límites. Recarga para comprobar su estado.', 503) from None
