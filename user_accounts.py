"""Verified account ownership and isolated request/worker bank contexts."""
import copy
import hashlib
import json
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlencode
import requests
import account_writes
from google.api_core.exceptions import PreconditionFailed

CURRENT = ContextVar('cv_account', default=None)
SETUP_GUARD = ContextVar('cv_setup_guard', default=None)
SECTIONS = ['Informacion personal', 'Informacion Laboral', 'Estudios', 'Referencias', 'Conocimiento o aprendizaje']
GLOBALS = ('MASTER_PROFILE', 'EXPERIENCE_BY_ID', 'SKILL_BY_ID', 'COURSE_BY_ID', 'BANK_CONFIG',
           'ARCHIVE_CONFIG', 'BANK_CLIENT', 'BANK_PHOTO_PATH', 'BANK_READ_STATUS', 'BANK_READ_AT', 'BANK_PHOTO_DIGEST')

def account_key(uid):
    return 'account-' + hashlib.sha256(uid.encode()).hexdigest()

def owner():
    return (CURRENT.get() or {}).get('uid', '')

def blank_profile(identity):
    return {'candidate': {'name': identity.get('name') or identity['email'], 'email': identity['email'], 'phones': [],
        'national_id': '', 'address': '', 'residence': '', 'photo': 'data/hoja_de_vida.jpeg'},
        'experiences': [], 'skills': [], 'courses': [], 'education': [], 'projects': [], 'references': [], 'not_documented': []}

def legacy_record(core, identity):
    if identity['email'].casefold() == core.ARCHIVE_CONFIG.get('allowed_email', '').casefold():
        return {'uid': identity['uid'], 'email': identity['email'], 'name': identity.get('name', ''),
                'bank': copy.deepcopy(core.BANK_CONFIG), 'archive_id': core.ARCHIVE_CONFIG['folder_id'], 'legacy': True}
    return None

@contextmanager
def scope(core, identity, headers=None, store=None):
    # Each request or worker owns its bank/profile values through a ContextVar.
    import job_runtime
    from drive_bank import DriveBank
    store = store or job_runtime.JobStore()
    saved = {key: getattr(core, key) for key in GLOBALS}
    record, _ = store.read(account_key(identity['uid']))
    record = record or legacy_record(core, identity)
    token = (headers or {}).get('X-Drive-Access-Token', '')
    state_token = core.account_state.enter(saved)
    marker = CURRENT.set({**identity, 'record': record, 'drive_token': token})
    try:
        core.MASTER_PROFILE = blank_profile(identity)
        core.refresh_profile_indexes()
        core.BANK_CONFIG = copy.deepcopy((record or {}).get('bank', {}))
        core.ARCHIVE_CONFIG = {**saved['ARCHIVE_CONFIG'], 'allowed_email': identity['email'],
            'folder_id': (record or {}).get('archive_id', '')}
        core.BANK_CLIENT = None
        if record:
            if record.get('legacy'):
                core.BANK_CLIENT = DriveBank(core.BANK_CONFIG)
            elif token:
                assert_drive_identity(core, token, identity)
                session = requests.Session()
                session.headers['Authorization'] = 'Bearer ' + token
                core.BANK_CLIENT = DriveBank(core.BANK_CONFIG, session=session)
        core.BANK_PHOTO_PATH = None
        core.BANK_READ_STATUS = None
        core.BANK_READ_AT = 0
        core.BANK_PHOTO_DIGEST = None
        yield
    finally:
        try:
            if core.BANK_CLIENT and not (record or {}).get('legacy') and core.BANK_CLIENT._session:
                core.BANK_CLIENT._session.close()
        finally:
            try:
                core.account_state.exit(state_token)
            finally:
                CURRENT.reset(marker)

def assert_drive_identity(core, token, identity):
    if not token or len(token) > 4096 or '\n' in token or '\r' in token:
        raise core.AppError('Conecta el Drive de esta cuenta para continuar.', 401)
    account = core.drive_request('https://www.googleapis.com/oauth2/v3/userinfo', token)
    if not account.get('email_verified') or account.get('email', '').casefold() != identity['email'].casefold():
        raise core.AppError('La cuenta de Drive debe coincidir con la sesión de Google.', 403)

def api(core, token, method, path, payload=None):
    guard = SETUP_GUARD.get()
    if guard:
        guard()
    if method == 'GET':
        return core.drive_request('https://www.googleapis.com/drive/v3/' + path, token)
    with account_writes.effect():
        response = requests.request(method, 'https://www.googleapis.com/drive/v3/' + path,
            headers={'Authorization': 'Bearer ' + token}, json=payload, timeout=45)
    if not response.ok:
        raise core.AppError('Drive no pudo preparar las carpetas. Puedes seleccionar tus carpetas manualmente y volver a intentarlo.', 403 if response.status_code in {401,403,404} else 503)
    return response.json()

def existing(core, token, name, parent='root'):
    name = name.replace('\\', '\\\\').replace("'", "\\'")
    query = f"'{parent}' in parents and trashed=false"
    items = []
    page = None
    while True:
        params = {'q': query, 'fields': 'nextPageToken,files(id,name,mimeType,owners(emailAddress))', 'pageSize':100}
        if page: params['pageToken'] = page
        result = api(core, token, 'GET', 'files?' + urlencode(params))
        items.extend(item for item in result.get('files', []) if item.get('name', '').casefold() == name.casefold())
        page = result.get('nextPageToken')
        if not page: break
    if len(items) > 1:
        raise core.AppError(f'Hay varias carpetas o archivos llamados {name}. Selecciona manualmente la carpeta que deseas usar.', 409)
    return items[0] if items else None

def folder(core, token, identity, name, parent='root', selected=None):
    if selected:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', selected): raise core.AppError('La carpeta seleccionada no es válida.')
        item = api(core, token, 'GET', 'files/' + selected + '?fields=id,name,mimeType,owners(emailAddress)')
    else:
        item = existing(core, token, name, parent)
    if item:
        if item['mimeType'] != 'application/vnd.google-apps.folder' or not any(
            person.get('emailAddress', '').casefold() == identity['email'].casefold() for person in item.get('owners', [])):
            raise core.AppError('Utiliza una carpeta propia de la cuenta con la que iniciaste sesión.', 403)
        return item['id']
    return api(core, token, 'POST', 'files?fields=id', {'name': name,
        'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent]})['id']

def json_file(core, token, name, parent, initial):
    item = existing(core, token, name, parent)
    if item:
        if item['mimeType'] != 'application/json': raise core.AppError(f'{name} debe ser un archivo JSON válido.', 409)
        return item['id']
    boundary = 'cv-account-' + hashlib.sha256(name.encode()).hexdigest()[:16]
    metadata = json.dumps({'name':name, 'mimeType':'application/json', 'parents':[parent]}).encode()
    body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode() + metadata +
        f'\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n'.encode() + json.dumps(initial, ensure_ascii=False).encode() + f'\r\n--{boundary}--\r\n'.encode())
    guard = SETUP_GUARD.get()
    if guard:
        guard()
    return core.drive_request('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id',
        token, body, 'multipart/related; boundary=' + boundary)['id']

def _setup_busy(core):
    error = core.AppError('Tu banco se está preparando desde otra sesión. Espera unos segundos y vuelve a sincronizar.', 409)
    error.setup_busy = True
    return error


def prepare(core, identity, token, selection=None, store=None):
    import job_runtime
    store = store or job_runtime.JobStore()
    with account_writes.boundary(core, store, identity['uid'], 'prepare'):
        return _prepare_reserved(core, identity, token, selection, store)


def _prepare_reserved(core, identity, token, selection, store):
    assert_drive_identity(core, token, identity)
    # The lease precedes all Drive writes and is shared across server instances.
    key = 'setup-' + account_key(identity['uid'])
    holder = uuid.uuid4().hex
    for attempt in range(11):
        lease, version = store.read(key)
        if lease and lease.get('expires_at', 0) > time.time():
            if attempt == 10:
                raise _setup_busy(core)
            time.sleep(.05)
            continue
        try:
            store.write(key, {'holder': holder, 'expires_at': time.time() + 180}, version)
            break
        except PreconditionFailed:
            if attempt == 10:
                raise _setup_busy(core) from None

    def renew():
        account_writes.current().check()
        lease, version = store.read(key)
        if not lease or lease.get('holder') != holder or lease.get('expires_at', 0) <= time.time():
            raise core.AppError('La preparación del banco venció. Vuelve a sincronizar para continuar.', 409)
        try:
            store.write(key, {**lease, 'expires_at': time.time() + 180}, version)
        except PreconditionFailed:
            raise core.AppError('La preparación cambió en otra sesión. Vuelve a sincronizar.', 409) from None

    marker = SETUP_GUARD.set(renew)
    try:
        return _prepare(core, identity, token, selection, store, renew)
    finally:
        SETUP_GUARD.reset(marker)
        try:
            lease, version = store.read(key)
            if lease and lease.get('holder') == holder:
                store.write(key, {**lease, 'expires_at': 0}, version)
        except Exception:
            core.app.logger.warning('La reserva de preparación se liberará al vencer.')


def _prepare(core, identity, token, selection, store, renew):
    current, generation = store.read(account_key(identity['uid']))
    current = current or (CURRENT.get() or {}).get('record')
    if current and not selection:
        bank_id = folder(core, token, identity, 'Banco de Datos', selected=current['bank']['folder_id'])
        archive_id = folder(core, token, identity, 'CV Generados', selected=current['archive_id'])
    else:
        bank_id = folder(core, token, identity, 'Banco de Datos', selected=(selection or {}).get('bank_id'))
        archive_id = folder(core, token, identity, 'CV Generados', selected=(selection or {}).get('archive_id'))
    if bank_id == archive_id: raise core.AppError('Banco de Datos y CV Generados deben ser carpetas diferentes.')
    sections = {name: folder(core, token, identity, name, bank_id) for name in SECTIONS}
    if current and current.get('legacy') and current['bank']['folder_id'] == bank_id:
        config = current['bank']
    else:
        config = {'folder_id': bank_id, 'base_file_id': json_file(core, token, 'perfil_base.json', bank_id, blank_profile(identity)),
            'index_file_id': json_file(core, token, 'indice_banco.json', bank_id, {'version':1,'documents':{}}),
            'readme_file_id': '', 'photo_file_name':'hoja_de_vida.jpeg', 'photo_optional':True}
    record = {'uid':identity['uid'], 'email':identity['email'], 'name':identity.get('name',''),
        'bank':config, 'archive_id':archive_id, 'sections':sections, 'legacy': bool(current and current.get('legacy') and config == current['bank']),
        'initial_sync_completed': bool(current and current.get('initial_sync_completed', True))}
    renew()
    try:
        store.write(account_key(identity['uid']), record, generation)
    except PreconditionFailed:
        raise core.AppError('La cuenta cambió durante la preparación. Vuelve a sincronizar para cargar su estado actual.', 409) from None
    return record

def public(record):
    return {'ready':bool(record), 'initial_sync_completed': bool(record and record.get('initial_sync_completed', True)), 'bank_id': (record or {}).get('bank', {}).get('folder_id',''),
        'archive_id':(record or {}).get('archive_id',''), 'sections':(record or {}).get('sections',{})}

def require_owner(core, job):
    current = owner()
    if current and job.get('owner_uid') != current:
        # Existing jobs belong only to the original account, never arbitrary users.
        if job.get('owner_uid') or not ((CURRENT.get() or {}).get('record') or {}).get('legacy'):
            raise core.AppError('El proceso no existe.', 404)
