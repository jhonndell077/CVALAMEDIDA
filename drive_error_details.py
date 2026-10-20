"""Safe Google error classification; never retain provider text or identifiers."""
import json
from urllib.parse import urlsplit

REASONS = {
    'authError': ('google_authorization_expired', 'La autorización de Google venció o fue revocada. Vuelve a conectar tu cuenta.'),
    'storageQuotaExceeded': ('drive_storage_full', 'Google Drive confirmó que esta cuenta no tiene espacio disponible. Libera espacio en su almacenamiento y vuelve a sincronizar.'),
    'insufficientPermissions': ('google_permissions_missing', 'Google confirmó permisos insuficientes. Vuelve a autorizar Drive con la misma cuenta y concede los permisos solicitados.'),
    'insufficientFilePermissions': ('drive_folder_permission', 'Google Drive confirmó que esta cuenta no tiene permiso sobre el archivo o carpeta. Selecciona carpetas propias de esta cuenta.'),
    'accessNotConfigured': ('google_api_disabled', 'Google indicó que la API requerida no está habilitada para este proyecto. El administrador debe revisar su configuración.'),
    'rateLimitExceeded': ('google_rate_limit', 'Google limitó temporalmente las solicitudes. Espera y vuelve a intentar la sincronización.'),
    'userRateLimitExceeded': ('google_rate_limit', 'Google limitó temporalmente las solicitudes de esta cuenta. Espera antes de reintentar.'),
    'dailyLimitExceeded': ('google_daily_limit', 'Google confirmó que se alcanzó un límite diario de su API. El administrador debe revisar la cuota del proyecto.'),
}

def classify(url, status, body):
    reason = None
    try:
        payload = json.loads(body[:16384])
        reasons = payload.get('error', {}).get('errors', [])
        reason = next((item.get('reason') for item in reasons if isinstance(item, dict) and isinstance(item.get('reason'),str) and item.get('reason') in REASONS), None)
        if not reason:
            aliases = {'SERVICE_DISABLED':'accessNotConfigured','RATE_LIMIT_EXCEEDED':'rateLimitExceeded', 'AUTHENTICATION_ERROR':'authError'}
            reason = next((aliases[item['reason']] for item in payload.get('error',{}).get('details',[])
                if isinstance(item,dict) and isinstance(item.get('reason'),str) and item['reason'] in aliases),None)
    except (ValueError, TypeError, AttributeError):
        pass
    identity = urlsplit(url).path.endswith('/userinfo')
    if status == 401:
        return 'google_authorization_expired', 'La autorización de Google venció o fue revocada. Vuelve a conectar tu cuenta.'
    if reason:
        return REASONS[reason]
    if status == 429:
        return REASONS['rateLimitExceeded']
    if identity:
        return 'google_identity_check_failed', f'Google rechazó la comprobación de identidad (HTTP {status}). Vuelve a autorizar con la misma cuenta. No se ha confirmado un problema de carpetas.'
    if status in (403, 404):
        return 'drive_access_undetermined', f'Google Drive rechazó la operación (HTTP {status}). Causa no determinada: no se pudo confirmar si faltan permisos o si el archivo o carpeta ya no está disponible.'
    return 'google_request_failed', f'Google no pudo completar la operación (HTTP {status}). Inténtalo de nuevo.'

def translate(error_type, url, status, body, *, stage):
    code, message = classify(url,status,body)
    public_status = 401 if code == 'google_authorization_expired' else 429 if code == 'google_rate_limit' else 403 if status in {403,404} else 502
    error = error_type(message,public_status)
    error.code, error.stage = code, stage
    error.provider_http_status = status
    return error
