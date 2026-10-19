"""Read-only verification of the current account's synchronization permissions."""
from urllib.parse import quote, urlencode

import architecture_diagnostics
import user_accounts


DRIVE_SCOPES = {'https://www.googleapis.com/auth/drive.readonly',
                'https://www.googleapis.com/auth/drive.file'}
GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.send'


def verify(core, grant_operation):
    """Use only the authenticated account context and the existing OAuth validator."""
    if not getattr(core.g, 'google_identity', None):
        core.verify_google_identity()
    identity = getattr(core.g, 'google_identity', None) or {}
    if not isinstance(identity.get('uid'), str) or not identity['uid']:
        raise core.AppError('Inicia sesión con Google para verificar las conexiones de esta cuenta.', 401)
    current = user_accounts.CURRENT.get()
    if current is not None and not current.get('record'):
        raise core.AppError('Configura el Banco de Datos y la carpeta de archivo antes de sincronizar.', 409)
    checks = []
    with architecture_diagnostics.stage(core, 'google', 'drive-api', 'oauth-authorization'):
        grant = grant_operation().get_json()
        scopes = set(grant.get('scope', '').split())
        if not DRIVE_SCOPES.issubset(scopes):
            raise core.AppError('Faltan permisos de Drive para leer el banco y archivar CV. Vuelve a autorizar Google.', 403)
    checks.append(dict(id='drive-authorization', state='ok', detail='Identidad y permisos de lectura y archivo de Drive verificados por Google.'))
    with architecture_diagnostics.stage(core, 'google', 'gmail', 'oauth-authorization'):
        if GMAIL_SCOPE not in scopes:
            raise core.AppError('Falta el permiso de envío de Gmail. Vuelve a autorizar Google antes de sincronizar.', 403)
    checks.append(dict(id='gmail-authorization', state='ok', detail='Permiso gmail.send verificado; no se envió correo.'))
    token = core.request.headers.get('X-Drive-Access-Token', '')
    for identifier, component, folder in (
        ('bank', 'bank', core.account_state.BANK_CONFIG.get('folder_id')),
        ('archive', 'drive', core.account_state.ARCHIVE_CONFIG.get('folder_id')),
    ):
        with architecture_diagnostics.stage(core, component, 'drive-api', 'drive-readback'):
            if not isinstance(folder, str) or not folder:
                raise core.AppError('Falta configurar la carpeta del banco o del archivo de esta cuenta.', 409)
            url = 'https://www.googleapis.com/drive/v3/files/' + quote(folder, safe='') + '?' + urlencode(
                {'fields': 'id,mimeType,trashed,capabilities(canListChildren,canAddChildren)', 'supportsAllDrives': 'true'})
            try:
                data = core.drive_request(url, token)
                if data.get('trashed') is True or data.get('mimeType') != 'application/vnd.google-apps.folder':
                    raise core.AppError('La carpeta del banco o archivo no está disponible. Revisa el acceso de esta cuenta.', 403)
                capability = 'canListChildren' if identifier == 'bank' else 'canAddChildren'
                if (data.get('capabilities') or {}).get(capability) is not True:
                    message = ('Google no confirmó permiso para listar los documentos del banco.' if identifier == 'bank'
                               else 'Google no confirmó permiso para agregar CV a la carpeta de archivo.')
                    raise core.AppError(message + ' Revisa el acceso de esta cuenta.', 403)
            except core.AppError:
                raise
            except Exception:
                raise core.AppError('No se pudo verificar la carpeta del banco o archivo. Reintenta la sincronización.', 503) from None
        checks.append(dict(id=identifier, state='ok', detail=(
            'Google confirmó lectura de metadatos y permiso para listar el banco.' if identifier == 'bank'
            else 'Google confirmó permiso para agregar documentos al archivo; no se realizó una escritura de prueba.')))
    response = core.jsonify(ok=True, checks=checks,
        scope='Permisos OAuth y lectura de carpetas verificados. No se escribieron documentos ni se enviaron mensajes.')
    response.headers['Cache-Control'] = 'no-store, private'
    return response
