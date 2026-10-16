"""Bounded operator probes. Never return provider payloads or exception strings."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import threading
import time
from urllib.parse import quote
import requests
import job_runtime

_lock = threading.Lock()
_cache = {}
_push_pending = {}


def send_push_probe(identity, endpoint, nonce):
    import json
    import re
    import web_notifications
    from pywebpush import webpush
    if not isinstance(endpoint,str) or len(endpoint)>2048 or not isinstance(nonce,str) or not re.fullmatch(r'[a-f0-9-]{36}',nonce):
        raise ProbeFailure('La prueba Push no tiene un identificador válido.')
    with _lock:
        previous=_push_pending.get(identity['uid'])
        if previous and time.monotonic()-previous[1]<60:
            raise ProbeFailure('Espera un minuto antes de repetir la prueba Push.', 'unknown')
    store=job_runtime.JobStore()
    record,_=store.read(web_notifications.subscription_key(identity['uid']))
    subscription=next((item for item in (record or {}).get('subscriptions',{}).values() if item.get('endpoint')==endpoint),None)
    if not subscription or not web_notifications.valid_subscription(subscription):
        raise ProbeFailure('La suscripción no pertenece al administrador o no es válida.')
    config=web_notifications.configuration(store)
    # Reserve before sending: an uncertain response must not trigger an automatic resend.
    with _lock:_push_pending[identity['uid']]=(nonce,time.monotonic())
    webpush(subscription_info=subscription,data=json.dumps({'type':'cv-admin-probe','nonce':nonce}),
        vapid_private_key=config['private_key'],vapid_claims={'sub':'mailto:'+identity['email']},ttl=60,timeout=10)
    return 'El proveedor aceptó la notificación de prueba; esperando recepción en este navegador.'


def confirm_push_probe(uid, nonce):
    with _lock:
        pending=_push_pending.get(uid)
        if not pending or pending[0]!=nonce or time.monotonic()-pending[1]>90:
            raise ProbeFailure('La confirmación Push no corresponde a una prueba reciente.', 'unknown')
        _push_pending.pop(uid,None)
    return remember(uid,checked('push',lambda:'El navegador confirmó recepción Push y mostró la notificación de prueba. No acredita recepción con la app cerrada.'),300)


def cached_check(uid, identifier):
    key = (hashlib.sha256(uid.encode()).hexdigest(), identifier)
    with _lock:
        saved = _cache.get(key)
    return dict(saved[1]) if saved and time.monotonic() < saved[0] else None


def remember(uid, result, seconds):
    key = (hashlib.sha256(uid.encode()).hexdigest(), result['id'])
    result = {**result, 'validForSeconds':seconds}
    with _lock:
        _cache[key] = (time.monotonic()+seconds, result)
    return result


def gmail(identity, token):
    if not isinstance(token, str) or not token or len(token)>4096 or '\n' in token or '\r' in token:
        raise ProbeFailure('Autoriza Google para verificar Gmail.', 'unknown')
    headers = {'Authorization':'Bearer '+token}
    user = response_json(requests.get('https://www.googleapis.com/oauth2/v3/userinfo',headers=headers,timeout=12))
    if user.get('email_verified') is not True or user.get('email','').casefold()!=identity['email'].casefold():
        raise ProbeFailure('La autorización OAuth no corresponde al administrador.')
    grant = response_json(requests.post('https://oauth2.googleapis.com/tokeninfo',headers=headers,timeout=12))
    if 'https://www.googleapis.com/auth/gmail.send' not in grant.get('scope','').split():
        raise ProbeFailure('Google no concedió gmail.send.', 'unknown')
    return 'Google respondió y confirmó gmail.send vigente para el administrador. No se envió correo ni se acredita entrega.'


class ProbeFailure(Exception):
    def __init__(self, detail, state='error'):
        self.detail, self.state = detail, state


def checked(identifier, operation, now=time.monotonic):
    started = now()
    try:
        detail = operation()
        state = 'ok'
    except ProbeFailure as error:
        detail, state = error.detail, error.state
    except Exception:
        detail, state = 'No se pudo completar la comprobación. Revisa disponibilidad y permisos del servicio.', 'unknown'
    return dict(id=identifier, state=state, detail=detail,
                checkedAt=datetime.now(timezone.utc).isoformat(), ms=round((now()-started)*1000))


def response_json(response):
    if response.status_code in (401, 403):
        raise ProbeFailure('El servicio rechazó la credencial o falta permiso para esta comprobación.', 'unknown')
    if not response.ok:
        raise ProbeFailure(f'El servicio respondió HTTP {response.status_code}.')
    return response.json()


def cloud_get(url):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    with AuthorizedSession(credentials) as session:
        return response_json(session.get(url, timeout=12))


def drive(config, archive, uid=None):
    from drive_bank import DriveBank
    if uid:
        import user_accounts
        record,_ = job_runtime.JobStore().read(user_accounts.account_key(uid))
        if record:
            config=dict(record.get('bank') or {})
            archive={**archive,'folder_id':record.get('archive_id')}
    if not config.get('service_account'):
        raise ProbeFailure('El banco requiere una autorización OAuth de Drive para comprobar sus carpetas.', 'unknown')
    folders = [config.get('folder_id'), archive.get('folder_id')]
    if not all(folders):
        raise ProbeFailure('Falta una carpeta del banco o archivo.', 'unknown')
    client = DriveBank(config)
    try:
        for folder in set(folders):
            data = response_json(client.session.get('https://www.googleapis.com/drive/v3/files/' + quote(folder, safe=''),
                params={'fields':'id,mimeType,trashed','supportsAllDrives':'true'}, timeout=12))
            if data.get('trashed') or data.get('mimeType') != 'application/vnd.google-apps.folder':
                raise ProbeFailure('Una carpeta del banco o archivo no está disponible.')
    finally:
        if client._session:
            client._session.close()
    return 'Drive respondió y permitió leer los metadatos de ambas carpetas del administrador. No se modificaron documentos.'


def storage():
    from google.cloud import storage as gcs
    with gcs.Client(project=job_runtime.PROJECT) as client:
        list(client.list_blobs(job_runtime.BUCKET, prefix='jobs/account-', max_results=1, timeout=12))
    return 'Cloud Storage respondió a una lectura de metadatos del almacén privado. No prueba escritura ni restauración.'


def tasks():
    data = cloud_get('https://cloudtasks.googleapis.com/v2/' + job_runtime.QUEUE + '?fields=state')
    if data.get('state') != 'RUNNING':
        raise ProbeFailure('La cola existe, pero no está en estado RUNNING.')
    return 'Cloud Tasks respondió y la cola está RUNNING. No se creó ni despachó un trabajo de prueba.'


def worker():
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    audience = 'https://us-central1-' + job_runtime.PROJECT + '.cloudfunctions.net/telegram_worker'
    token = id_token.fetch_id_token(Request(), audience)
    data = response_json(requests.get(audience + '/telegram/health',
        headers={'Authorization':'Bearer ' + token}, timeout=15))
    if data.get('ok') is not True or data.get('service') != 'telegram_worker':
        raise ProbeFailure('El worker devolvió un contrato de salud inesperado.')
    return 'El proceso del worker respondió a una solicitud autenticada. No prueba generación ni entrega de un trabajo.'


def worker_health(request):
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    audience = 'https://us-central1-' + job_runtime.PROJECT + '.cloudfunctions.net/telegram_worker'
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer '):
        return {'error':'Unauthorized'}, 401
    try:
        identity = id_token.verify_oauth2_token(authorization[7:], Request(), audience=audience)
        if identity.get('email') != 'cv-runtime@'+job_runtime.PROJECT+'.iam.gserviceaccount.com' or identity.get('email_verified') is not True:
            return {'error':'Forbidden'}, 403
    except Exception:
        return {'error':'Unauthorized'}, 401
    return {'ok':True,'service':'telegram_worker'}, 200


def vertex(model):
    from google import genai
    from google.genai import types
    import os
    client = genai.Client(vertexai=True, project=job_runtime.PROJECT,
        location=os.environ.get('GOOGLE_CLOUD_LOCATION','global'),
        http_options=types.HttpOptions(timeout=20000, retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        result = client.models.generate_content(model=model, contents='Responde únicamente con el objeto JSON {"ok":true}.',
            config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0,
                max_output_tokens=512, thinking_config=types.ThinkingConfig(thinking_level='MINIMAL') if model.startswith('gemini-3') else None))
        import json
        if json.loads(result.text or '{}').get('ok') is not True:
            raise ProbeFailure('Vertex respondió, pero no completó correctamente el JSON de prueba.')
    finally:
        client.close()
    return 'El modelo configurado generó correctamente un JSON sintético. Prueba facturable breve, con caché de 15 minutos; sin datos personales.'


def telegram():
    config = job_runtime.configuration()
    token = config.get('bot_token')
    if not token:
        raise ProbeFailure('El bot no tiene configuración disponible.', 'unknown')
    results = []
    for method in ('getMe','getWebhookInfo'):
        data = response_json(requests.get('https://api.telegram.org/bot'+token+'/'+method, timeout=12))
        if not data.get('ok'):
            raise ProbeFailure('Telegram rechazó la consulta del bot.')
        results.append(data.get('result') or {})
    expected = 'https://us-central1-' + job_runtime.PROJECT + '.cloudfunctions.net/api/telegram/webhook'
    allowed = {expected, 'https://cvalamedida.web.app/telegram/webhook',
               'https://cv-a-la-medida-jhonn.web.app/telegram/webhook'}
    if not results[0].get('is_bot') or results[1].get('url') not in allowed:
        raise ProbeFailure('El bot respondió, pero el webhook no coincide con el proyecto.')
    last_error = results[1].get('last_error_date', 0)
    if isinstance(last_error, (int, float)) and time.time()-last_error < 900:
        raise ProbeFailure('Telegram registra un error reciente de entrega al webhook. Revisa el receptor y su disponibilidad.')
    return 'Telegram respondió a getMe y getWebhookInfo; webhook del proyecto sin errores en los últimos 15 minutos. No se enviaron mensajes.'


def push(uid):
    import web_notifications
    from google.cloud import storage as gcs
    with gcs.Client(project=job_runtime.PROJECT) as client:
        bucket = client.bucket(job_runtime.BUCKET)
        for key in (web_notifications.CONFIG_ID, web_notifications.subscription_key(uid)):
            if bucket.get_blob('jobs/'+key+'.json', timeout=12) is None:
                raise ProbeFailure('Falta la configuración o una suscripción Push del administrador.', 'unknown')
    raise ProbeFailure('Configuración y registro de suscripciones accesibles. Falta confirmar recepción Push en un dispositivo propio; no equivale a entrega.', 'unknown')


def inspect(core, identity):
    # Configuration captured before threads; no account ContextVar is shared.
    config = dict(core.account_state.BANK_CONFIG)
    archive = dict(core.account_state.ARCHIVE_CONFIG)
    operations = dict(drive=lambda:drive(config,archive,identity['uid']), storage=storage, tasks=tasks,
        worker=worker, vertex=lambda:vertex(core.VERTEX_MODEL), telegram=telegram,
        push=lambda:push(identity['uid']))
    owner = hashlib.sha256(identity['uid'].encode()).hexdigest()
    def run(item):
        identifier, operation = item
        key = (owner, identifier)
        # One computation per process; concurrency=1 limits duplicate cloud probes.
        with _lock:
            saved = _cache.get(key)
        if saved and time.monotonic() < saved[0]:
            return dict(saved[1])
        result = checked(identifier, operation)
        ttl = (900 if identifier == 'vertex' else 300) if result['state']=='ok' else 60
        result['validForSeconds'] = ttl
        with _lock:
            _cache[key] = (time.monotonic()+ttl, result)
        return result
    with ThreadPoolExecutor(max_workers=7) as pool:
        return list(pool.map(run, operations.items()))
