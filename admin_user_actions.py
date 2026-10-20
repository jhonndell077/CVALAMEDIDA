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
import account_writes

ACTIONS = frozenset({'reset', 'delete_data', 'delete_user', 'recover_access'})
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


def _recovery_reasons(store, user, queue):
    """Do not confuse a deliberate tombstone or an untracked action with failure."""
    fence = queue.get('maintenance')
    if getattr(user, 'disabled', False):
        return ['La identidad está deshabilitada. Recuperar acceso no habilita identidades.']
    if not fence:
        return ['La cuenta no tiene un bloqueo administrativo que recuperar.']
    if not isinstance(fence, dict) or fence.get('action') != 'delete_user':
        return ['El bloqueo es de causa desconocida; requiere investigación administrativa.']
    if fence.get('state') != 'failed':
        return ['El bloqueo no acredita una eliminación fallida y detenida. Puede ser una operación activa, completada o un registro antiguo sin trazabilidad; requiere revisión antes de retirarlo.']
    identifier = fence.get('planId')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        return ['Falta el registro verificable de la operación administrativa original.']
    original, _ = store.read(_key(identifier))
    if not isinstance(original, dict) or original.get('id') != identifier or original.get('uid') != user.uid or original.get('action') != 'delete_user' or original.get('state') not in ('failed', 'cancelled'):
        return ['La operación administrativa original no confirma un fallo terminal de esta cuenta.']
    if original.get('deleteAttempted') is not False:
        return ['Se intentó eliminar la identidad o falta esa confirmación. Hay que verificar el resultado externo antes de retirar el bloqueo.']
    return []


def _delete_step(core, store, plan, stage, *, delete_attempted=False):
    """An executing action must still own its fence before every external step."""
    if account_writes.current():
        account_writes.current().check()
    queue, version = store.read(admission_policy.queue_key(plan['uid']))
    fence = (queue or {}).get('maintenance') or {}
    current, generation = store.read(_key(plan['id']))
    if fence.get('planId') != plan['id'] or fence.get('state') != 'executing' or not current or current.get('state') != 'executing':
        raise core.AppError('La acción administrativa cambió. No se ejecutará el siguiente paso.', 409)
    current.update(stage=stage, deleteAttempted=delete_attempted, updatedAt=time.time())
    store.write(_key(plan['id']), current, generation)
    store.write(admission_policy.queue_key(plan['uid']), {**queue, 'maintenance': {**fence, 'stage': stage}}, version)


def _finish_delete(store, plan, outcome):
    # Never replace another operation's fence or expose provider exception text.
    for attempt in range(3):
        current, version = store.read(_key(plan['id']))
        if not current or current.get('state') not in {'executing', 'completed', 'failed'}:
            return
        terminal = current.get('state') if current.get('state') in {'completed', 'failed'} else outcome
        evidence = dict(state=terminal, code='admin_delete_' + terminal,
            stage=current.get('stage', 'fenced'), correlationId=current['correlationId'],
            finishedAt=current.get('finishedAt') or time.time())
        try:
            if current.get('state') == 'executing':
                account_writes.write_terminal(store, plan['uid'], plan['id'], _key(plan['id']), {**current, **evidence}, version)
            queue, version = store.read(admission_policy.queue_key(plan['uid']))
            fence = (queue or {}).get('maintenance') or {}
            if fence.get('planId') == plan['id'] and fence.get('state') == 'executing':
                account_writes.write_terminal(store, plan['uid'], plan['id'], admission_policy.queue_key(plan['uid']), {**queue, 'maintenance': {**fence, **evidence}}, version)
            return
        except PreconditionFailed:
            if attempt == 2:
                raise


def _recovery_receipt(store, plan):
    result = dict(ok=True, status='completed', uid=plan['uid'], action='recover_access',
        detail='Acceso recuperado. Banco, CV, consumo y procesos conservados. Vuelve a autorizar Drive o Telegram si sus permisos fueron revocados.')
    current, generation = store.read(_key(plan['id']))
    store.write(_key(plan['id']), {**current, 'state': 'completed', 'finishedAt': time.time(),
        'code': 'admin_access_recovered', 'stage': 'access-recovered', 'result': result}, generation)
    return result


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
    if action == 'recover_access':
        reasons.extend(_recovery_reasons(store, user, queue))
        if active:
            reasons.append('Hay procesos activos o pendientes; la recuperación no los cancela.')
    elif action != 'reset':
        if action == 'delete_user' and queue.get('maintenance'):
            reasons.append('Ya existe un bloqueo administrativo; investígalo antes de iniciar otra eliminación.')
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
        'scope': ('Retira únicamente un bloqueo de una eliminación fallida y verificablemente detenida. Conserva banco, CV, consumo, procesos y recibos. Los permisos ya revocados deben autorizarse de nuevo.' if action == 'recover_access' else 'Reinicia únicamente el consumo diario y mensual; conserva usuarios, datos, procesos y recibos idempotentes.' if action == 'reset' else
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
                    'correlationId': secrets.token_hex(16),
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
        deletion_started = False
        writer = None
        try:
            store = job_runtime.JobStore()
            plan, plan_generation = store.read(_key(match[1]))
            if not plan or plan.get('admin') != core.g.google_identity['uid'] or plan.get('uid') != uid or plan.get('action') != action or not hmac.compare_digest(match[2], _signature(plan)):
                raise core.AppError('La vista previa no pertenece a esta acción o administrador.', 403)
            if action == 'recover_access' and plan.get('state') == 'completed' and isinstance(plan.get('result'), dict):
                return reply(**plan['result'])
            reservation = account_writes.reserve(store, uid, 'admin-' + action,
                maintenance=plan['id'] if action == 'delete_user' else True)
            reservation.__enter__()
            writer = reservation
            if action == 'recover_access':
                if plan.get('state') == 'completed' and isinstance(plan.get('result'), dict):
                    return reply(**plan['result'])
                if plan.get('state') == 'executing':
                    previous_queue, _ = store.read(admission_policy.queue_key(uid))
                    if (previous_queue or {}).get('lastAccessRecovery', {}).get('planId') == plan['id']:
                        return reply(**_recovery_receipt(store, plan))
            allowed = {'ready', 'executing'} if action == 'recover_access' else {'ready'}
            if plan.get('state') not in allowed or plan.get('expiresAt', 0) < time.time():
                raise core.AppError('La vista previa venció o ya fue utilizada. Prepara otra.', 409)
            if plan.get('blocked') or action == 'delete_data':
                raise core.AppError('La acción sigue bloqueada. Consulta los motivos de la vista previa.', 409)
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
            if action == 'recover_access':
                _, _, reasons, _ = _preview(core, store, user, action)
                if reasons:
                    raise core.AppError('La recuperación no es segura: ' + ' '.join(reasons), 409)
                original, original_generation = store.read(_key(queue['maintenance']['planId']))
                plan.update(state='executing')
                store.write(_key(plan['id']), plan, plan_generation)
                # Claim the failed original before removing its matching fence.
                if original.get('state') != 'cancelled' or original.get('recoveredBy') != plan['id']:
                    store.write(_key(original['id']), {**original, 'state': 'cancelled', 'recoveredBy': plan['id']}, original_generation)
                queue.pop('maintenance')
                queue['lastAccessRecovery'] = {'planId': plan['id'], 'at': time.time()}
                store.write(admission_policy.queue_key(uid), queue, generation)
                return reply(**_recovery_receipt(store, plan))
            if action == 'delete_user':
                if queue.get('maintenance'):
                    raise core.AppError('La cuenta ya tiene un bloqueo administrativo. Revísalo antes de iniciar otra eliminación.', 409)
                plan.update(state='executing', deleteAttempted=False, stage='fenced')
                store.write(_key(plan['id']), plan, plan_generation)
                queue['maintenance'] = {'action': 'delete_user', 'at': time.time(), 'planId': plan['id'], 'state': 'executing', 'stage': 'fenced'}
                store.write(admission_policy.queue_key(uid), queue, generation)
                deletion_started = True
                for kind, replacement in (('account', {'uid': uid, 'revoked': True}), ('oauth', {'revoked': True}), ('pending', {})):
                    _delete_step(core, store, plan, 'telegram-revoke')
                    identifier = telegram_accounts.key(kind, uid)
                    _, version = store.read(identifier)
                    store.write(identifier, replacement, version)
                _delete_step(core, store, plan, 'auth-revoke')
                # Revocation may have succeeded even on timeout; recovery never
                # restores that credential, so reconciliation remains idempotent.
                with account_writes.effect(store, uid, uncertain_on_error=False):
                    auth.revoke_refresh_tokens(uid)
                _delete_step(core, store, plan, 'auth-delete', delete_attempted=True)
                with account_writes.effect(store, uid):
                    auth.delete_user(uid)
                _finish_delete(store, plan, 'completed')
                deletion_started = False
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
        except account_writes.WriteBlocked as failure:
            error = core.AppError(str(failure), failure.status_code)
            error.code = failure.code
            raise error from None
        except PreconditionFailed:
            raise core.AppError('La cuenta o la vista previa cambió. Actualiza antes de reintentar.', 409) from None
        except auth.UserNotFoundError:
            raise core.AppError('La cuenta ya no existe.', 404) from None
        except Exception as error:
            if isinstance(error, core.AppError):
                raise
            raise core.AppError('No se pudo confirmar toda la acción. Puede haber revocaciones o cambios parciales; actualiza las cuentas antes de reintentar.', 503) from None
        finally:
            if deletion_started:
                try:
                    _finish_delete(store, plan, 'failed')
                except Exception:
                    # Unknown outcomes must remain fenced; no automatic unlocking.
                    pass
            if writer:
                try:
                    writer.__exit__(None, None, None)
                except Exception:
                    core.app.logger.warning('No se pudo confirmar la liberación de la reserva administrativa.')
