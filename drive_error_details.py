"""Safe Google error classification; never retain provider text or identifiers."""
import json
from urllib.parse import urlsplit

REASONS = {
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
        payload = json.loads(body)
        reasons = payload.get('error', {}).get('errors', [])
        reason = next((item.get('reason') for item in reasons if isinstance(item, dict) and item.get('reason') in REASONS), None)
    except (ValueError, TypeError, AttributeError):
        pass
    if reason:
        return REASONS[reason]
    identity = urlsplit(url).path.endswith('/userinfo')
    if status == 401:
        return 'google_authorization_expired', 'La autorización de Google venció o fue revocada. Vuelve a conectar tu cuenta.'
    if identity:
        return 'google_identity_check_failed', f'Google rechazó la comprobación de identidad (HTTP {status}). Vuelve a autorizar con la misma cuenta. No se ha confirmado un problema de carpetas.'
    if status in (403, 404):
        return 'drive_access_undetermined', f'Google Drive rechazó la operación (HTTP {status}). Causa no determinada: no se pudo confirmar si faltan permisos o si el archivo o carpeta ya no está disponible.'
    return 'google_request_failed', f'Google no pudo completar la operación (HTTP {status}). Inténtalo de nuevo.'
