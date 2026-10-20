"""One-time, global application reauthentication barrier. No account data changes.

Keep this cutoff stable across ordinary releases. Advancing it is an explicit
operator action, not a build/version side effect. Firebase auth_time (not iat)
prevents a refresh token from bypassing the required new sign-in.
"""
import math

REAUTHENTICATE_AFTER = 1792497230  # 2026-10-20, explicit global session closure.
MESSAGE = 'Cerramos las sesiones anteriores para aplicar las mejoras. Inicia sesión nuevamente con Google. Tus datos se conservan.'


def requires_reauthentication(identity):
    authenticated_at = identity.get('auth_time')
    return (isinstance(authenticated_at, bool)
            or not isinstance(authenticated_at, (int, float))
            or not math.isfinite(authenticated_at)
            or authenticated_at < REAUTHENTICATE_AFTER)
