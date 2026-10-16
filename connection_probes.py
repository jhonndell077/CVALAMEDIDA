"""Bounded operator probes. Never return provider payloads or exception strings."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import threading
import time
from collections import deque
from urllib.parse import quote
import requests
import job_runtime

_lock = threading.Lock()
_cache = {}
PUSH_RECEIPT_TTL = 900
PUSH_PROOF_TTL = 86400
_receipt_window = deque()


def allow_push_receipt():
    with _lock:
        now=time.monotonic()
        while _receipt_window and now-_receipt_window[0]>=60:_receipt_window.popleft()
        if len(_receipt_window)>=30:return False
        _receipt_window.append(now)
        return True


def push_record(uid):
    return 'admin-push-receipt-' + hashlib.sha256(uid.encode()).hexdigest()


def push_proof(record):
    confirmed = (record or {}).get('confirmed_at', 0)
    if not isinstance(confirmed,(int,float)) or confirmed<=0 or not 0 <= time.time()-confirmed < PUSH_PROOF_TTL:
        raise ProbeFailure('No hay una recepción Push confirmada durante las últimas 24 horas. Ejecuta una nueva prueba.', 'unknown')
    stamp=datetime.fromtimestamp(confirmed,timezone.utc).isoformat()
    return 'Recepción Push y notificación confirmadas por el service worker ('+stamp+'). Registro persistente; no implica disponibilidad permanente.'


def send_push_probe(identity, endpoint, nonce):
    import json
    import re
    import web_notifications
    from pywebpush import webpush
    if not isinstance(endpoint,str) or len(endpoint)>2048 or not isinstance(nonce,str) or not re.fullmatch(r'[a-f0-9-]{36}',nonce):
        raise ProbeFailure('La prueba Push no tiene un identificador válido.')
    store=job_runtime.JobStore()
    key=push_record(identity['uid'])
    previous,generation=store.read(key)
    if previous and time.time()-previous.get('created_at',0)<60:
        raise ProbeFailure('Espera un minuto antes de repetir la prueba Push.', 'unknown')
    record,_=store.read(web_notifications.subscription_key(identity['uid']))
    subscription=next((item for item in (record or {}).get('subscriptions',{}).values() if item.get('endpoint')==endpoint),None)
    if not subscription or not web_notifications.valid_subscription(subscription):
        raise ProbeFailure('La suscripción no pertenece al administrador o no es válida.')
    config=web_notifications.configuration(store)
    import secrets
    proof_token=secrets.token_urlsafe(32)
    # Durable CAS reservation survives a new process; store only a token digest.
    store.write(key,{'nonce':nonce,'created_at':time.time(),'confirmed_at':0,
        'token_hash':hashlib.sha256(proof_token.encode()).hexdigest()},generation)
    webpush(subscription_info=subscription,data=json.dumps({'type':'cv-admin-probe','nonce':nonce,
        'receipt':key.removeprefix('admin-push-receipt-'),'receipt_token':proof_token}),
        vapid_private_key=config['private_key'],vapid_claims={'sub':'mailto:'+identity['email']},ttl=60,timeout=10)
    return 'El proveedor aceptó la notificación de prueba; esperando recepción en este navegador.'


def confirm_push_probe(uid, nonce):
    store=job_runtime.JobStore()
    for _ in range(3):
        record,generation=store.read(push_record(uid))
        if not record or record.get('nonce')!=nonce or not 0<=time.time()-record.get('created_at',0)<=PUSH_RECEIPT_TTL:
            raise ProbeFailure('La confirmación Push no corresponde a una prueba reciente.', 'unknown')
        if record.get('confirmed_at'):
            return remember(uid,checked('push',lambda:push_proof(record)),300)
        record['confirmed_at']=time.time()
        try:store.write(push_record(uid),record,generation)
        except job_runtime.PreconditionFailed:continue
        return remember(uid,checked('push',lambda:push_proof(record)),300)
    raise ProbeFailure('La confirmación está cambiando. Reintenta actualizar el estado.', 'unknown')


def receive_push_proof(receipt, token):
    import hmac
    import re
    if not isinstance(receipt,str) or not re.fullmatch(r'[a-f0-9]{64}',receipt) or not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
        raise ProbeFailure('Confirmación Push inválida.')
    store=job_runtime.JobStore()
    key='admin-push-receipt-'+receipt
    for _ in range(3):
        record,generation=store.read(key)
        if not record or not 0<=time.time()-record.get('created_at',0)<=PUSH_RECEIPT_TTL or not hmac.compare_digest(record.get('token_hash',''),hashlib.sha256(token.encode()).hexdigest()):
            raise ProbeFailure('Confirmación Push inválida.')
        if record.get('confirmed_at'):return
        record['confirmed_at']=time.time()
        try:store.write(key,record,generation)
        except job_runtime.PreconditionFailed:continue
        return
    raise ProbeFailure('Confirmación Push temporalmente ocupada.', 'unknown')


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
        import sys
        error = sys.exception()
        code = getattr(error,'code',None) or getattr(error,'status_code',None)
        code = code if isinstance(code,int) else None
        kind = type(error).__name__
        detail = f'Comprobación no completada ({kind}' + (f', HTTP {code}' if code else '') + '). Revisa permisos, capacidad y configuración.'
        state = 'error' if code in {400,404,429,500,503,504} else 'unknown'
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


def drive(config, archive, uid=None, session=None):
    from drive_bank import DriveBank
    if uid:
        import user_accounts
        record,_ = job_runtime.JobStore().read(user_accounts.account_key(uid))
        if record:
            config=dict(record.get('bank') or {})
            archive={**archive,'folder_id':record.get('archive_id')}
    if not config.get('service_account') and session is None:
        raise ProbeFailure('El banco requiere una autorización OAuth de Drive para comprobar sus carpetas.', 'unknown')
    folders = [config.get('folder_id')] if session is None else [config.get('folder_id'), archive.get('folder_id')]
    if not all(folders):
        raise ProbeFailure('Falta una carpeta del banco o archivo.', 'unknown')
    client = DriveBank(config,session=session)
    try:
        for folder in set(folders):
            data = response_json(client.session.get('https://www.googleapis.com/drive/v3/files/' + quote(folder, safe=''),
                params={'fields':'id,mimeType,trashed','supportsAllDrives':'true'}, timeout=12))
            if data.get('trashed') or data.get('mimeType') != 'application/vnd.google-apps.folder':
                raise ProbeFailure('Una carpeta del banco o archivo no está disponible.')
    finally:
        if client._session:
            client._session.close()
    return ('Drive respondió y permitió leer los metadatos del banco y archivo mediante OAuth del administrador.' if session is not None
            else 'Drive respondió y permitió leer los metadatos del banco con su cuenta de servicio. El archivo utiliza OAuth del usuario y requiere su comprobación separada.') + ' No se modificaron documentos.'


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
                max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level='LOW') if model.startswith('gemini-3') else None))
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
    record,_=job_runtime.JobStore().read(push_record(uid))
    return push_proof(record)


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
        if identifier=='push':
            # Read durable delivery receipts on every poll; never mask a new
            # confirmation behind the previous unknown result's cache.
            return checked(identifier,operation)
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
