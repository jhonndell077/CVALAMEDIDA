"""Owner-only, reviewed account actions using short-lived, single-use CAS plans.

Quota reset and Firebase UID deletion are implemented separately. Full data
cleanup is deliberately blocked until an
exhaustive Drive ownership inventory and account-wide maintenance fence exist;
removing an account pointer would otherwise revive the owner's legacy bank.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone

from firebase_admin import auth
from google.api_core.exceptions import PreconditionFailed
import admin_connections
import admin_usage
import admission_policy
import job_runtime
import user_accounts
import telegram_accounts

ACTIONS = frozenset({'reset', 'delete_data', 'delete_user'})
TTL_SECONDS = 120
PLAN_PATTERN = re.compile(r'^([a-f0-9]{32})\.([a-f0-9]{64})$')


def _signature(plan):
    payload = json.dumps({field: plan[field] for field in ('id', 'admin', 'uid', 'action', 'expiresAt', 'queueGeneration')},
                         sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(bytes.fromhex(plan['proofKey']), payload, hashlib.sha256).hexdigest()


def _key(identifier):
    return 'admin-user-action-' + identifier


def _guard(core):
    admin_connections.require_admin(core)
    if core.request.headers.get('Origin') not in admin_usage.ORIGINS or core.request.headers.get('X-Requested-With') != 'XmlHttpRequest':
        raise core.AppError('El origen de la acción no es válido.', 403)


def _target(core, data, expected):
    if not isinstance(data, dict) or set(data) != expected:
        raise core.AppError('La acción no es válida.', 400)
    uid, action = data.get('uid'), data.get('action')
    if not isinstance(uid, str) or not 1 <= len(uid) <= 128 or any(ord(char) < 32 for char in uid):
        raise core.AppError('La cuenta no es válida.', 400)
    if not isinstance(action, str) or action not in ACTIONS:
        raise core.AppError('La acción no es válida.', 400)
    return uid, action


def _preview(core, store, user, action):
    uid = user.uid
    queue, generation = store.read(admission_policy.queue_key(uid))
    queue = queue or {}
    if not isinstance(queue, dict) or not isinstance(queue.get('pending', []), list):
        raise core.AppError('No se pudo verificar la cola de esta cuenta.', 409)
    active = 0
    for item in queue.get('pending', []):
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            raise core.AppError('No se pudo verificar la cola de esta cuenta.', 409)
        job, _ = store.read(item['id'])
        if not job or job.get('state') not in {'done', 'failed', 'rejected'}:
            active += 1
    record, _ = store.read(user_accounts.account_key(uid))
    reasons = []
    if action != 'reset':
        if active:
            reasons.append('Hay procesos pendientes o activos. Deben finalizar antes de eliminar datos.')
        if action == 'delete_user' and ((user.email or '').casefold() == core.ORIGINAL_OWNER_EMAIL.strip().casefold() or uid == core.g.google_identity['uid']):
            reasons.append('La cuenta del administrador está protegida frente a eliminación.')
        if action == 'delete_data' and record and (record.get('bank') or record.get('archive_id')):
            reasons.append('El banco y los CV están en Google Drive. Falta un inventario verificable de archivos exclusivos de la app y autorización del propietario; no se borran carpetas seleccionadas que puedan contener documentos ajenos.')
        if action == 'delete_data':
            reasons.append('La eliminación integral está bloqueada hasta disponer de un inventario exhaustivo y un bloqueo de escrituras de toda la cuenta. Borrar únicamente el vínculo local no elimina sus datos y puede reactivar el banco heredado.')
    summary = {'activeJobs': active, 'queueGeneration': str(generation),
        'preservesPending': True, 'preservesReceipts': True,
        'driveConfigured': bool(record and (record.get('bank') or record.get('archive_id'))),
        'scope': ('Reinicia únicamente el consumo diario y mensual; conserva usuarios, datos, procesos y recibos idempotentes.' if action == 'reset' else
                  ('Elimina exclusivamente el UID de Firebase Authentication y revoca sesiones y vinculación Telegram. Los datos de Drive y registros internos se conservan; no equivale a eliminar todos los datos.' if action == 'delete_user' else 'Borrado integral no disponible: no se modifican usuarios, archivos ni credenciales.')),
        'externalExclusions': 'No se eliminan correos ya enviados ni mensajes o archivos ya entregados por Telegram.'}
    return queue, generation, reasons, summary


def register_routes(core):
    def reply(**payload):
        response = core.jsonify(**payload)
        response.headers['Cache-Control'] = 'no-store, private'
        return response

    @core.app.post('/api/admin/users/action/preview')
    def preview_action():
        _guard(core)
        uid, action = _target(core, core.request.get_json(silent=True), {'uid', 'action'})
        try:
            user = auth.get_user(uid)
            store = job_runtime.JobStore()
            _, generation, reasons, summary = _preview(core, store, user, action)
            now = time.time()
            plan = {'id': secrets.token_hex(16), 'proofKey': secrets.token_hex(32),
                    'admin': core.g.google_identity['uid'], 'uid': uid, 'action': action,
                    'createdAt': now, 'expiresAt': now + TTL_SECONDS, 'queueGeneration': str(generation),
                    'state': 'ready', 'blocked': bool(reasons), 'summary': summary, 'reasons': reasons}
            store.write(_key(plan['id']), plan, 0)
            return reply(planId=plan['id'] + '.' + _signature(plan), expiresAt=plan['expiresAt'],
                         uid=uid, action=action, blocked=plan['blocked'], reasons=reasons, summary=summary)
        except auth.UserNotFoundError:
            raise core.AppError('La cuenta ya no existe.', 404) from None
        except Exception as error:
            if isinstance(error, core.AppError):
                raise
            raise core.AppError('No se pudo preparar una vista previa segura. No se realizaron cambios en la cuenta.', 503) from None

    @core.app.post('/api/admin/users/action/execute')
    def execute_action():
        _guard(core)
        data = core.request.get_json(silent=True)
        uid, action = _target(core, data, {'uid', 'action', 'planId', 'confirmation'})
        token = data['planId']
        match = PLAN_PATTERN.fullmatch(token) if isinstance(token, str) else None
        if not match or data['confirmation'] != uid:
            raise core.AppError('Confirma escribiendo el identificador exacto de la cuenta.', 400)
        try:
            store = job_runtime.JobStore()
            plan, plan_generation = store.read(_key(match[1]))
            if not plan or plan.get('admin') != core.g.google_identity['uid'] or plan.get('uid') != uid or plan.get('action') != action or not hmac.compare_digest(match[2], _signature(plan)):
                raise core.AppError('La vista previa no pertenece a esta acción o administrador.', 403)
            if plan.get('state') != 'ready' or plan.get('expiresAt', 0) < time.time():
                raise core.AppError('La vista previa venció o ya fue utilizada. Prepara otra.', 409)
            if plan.get('blocked') or action == 'delete_data':
                raise core.AppError('La eliminación integral sigue bloqueada. Consulta los motivos de la vista previa.', 409)
            user = auth.get_user(uid)
            if action == 'delete_user':
                _, _, reasons, _ = _preview(core, store, user, action)
                if reasons:
                    raise core.AppError('La cuenta tiene procesos activos o está protegida. Prepara otra vista previa.', 409)
            queue, generation = store.read(admission_policy.queue_key(uid))
            if str(generation) != plan['queueGeneration']:
                raise core.AppError('La cuenta registró una operación después de la vista previa. Revísala otra vez.', 409)
            if not isinstance(queue or {}, dict):
                raise core.AppError('El registro de consumo no se pudo verificar.', 409)
            queue = dict(queue or {})
            if action == 'delete_user':
                plan.update(state='executing')
                store.write(_key(plan['id']), plan, plan_generation)
                queue['maintenance'] = {'action': 'delete_user', 'at': time.time()}
                store.write(admission_policy.queue_key(uid), queue, generation)
                for kind, replacement in (('account', {'uid': uid, 'revoked': True}), ('oauth', {'revoked': True}), ('pending', {})):
                    identifier = telegram_accounts.key(kind, uid)
                    _, version = store.read(identifier)
                    store.write(identifier, replacement, version)
                auth.revoke_refresh_tokens(uid)
                auth.delete_user(uid)
                return reply(ok=True, status='completed', uid=uid, action=action, dataDeleted=False,
                    detail='UID eliminado de Firebase Authentication; sesiones y Telegram revocados. Los archivos de Drive y registros internos se conservan.')
            usage = dict(queue.get('usage') or {})
            now = datetime.now(timezone.utc)
            month = now.strftime('%Y-%m')
            usage.update(day=now.strftime('%Y-%m-%d'), month=month, daily=0, monthly=0)
            queue['usage'] = usage
            plan.update(state='executing')
            store.write(_key(plan['id']), plan, plan_generation)
            store.write(admission_policy.queue_key(uid), queue, generation)
            # A claimed plan cannot be replayed even if final acknowledgement fails.
            return reply(ok=True, status='completed', uid=uid, action=action,
                         detail='Consumo diario y mensual reiniciado. Datos, procesos y recibos conservados.')
        except PreconditionFailed:
            raise core.AppError('La cuenta o la vista previa cambió. Actualiza antes de reintentar.', 409) from None
        except auth.UserNotFoundError:
            raise core.AppError('La cuenta ya no existe.', 404) from None
        except Exception as error:
            if isinstance(error, core.AppError):
                raise
            raise core.AppError('No se pudo confirmar toda la acción. Puede haber revocaciones o cambios parciales; actualiza las cuentas antes de reintentar.', 503) from None
