"""Authenticated browser reports are unconfirmed signals, never provider evidence."""
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from time import monotonic

_windows = OrderedDict()
_lock = Lock()
_codes = {'access_denied', 'popup_closed', 'popup_failed_to_open', 'oauth_error', 'origin_mismatch', 'redirect_uri_mismatch', 'authorization_pending', 'authorization_timeout'}
_origins = {'https://cvalamedida.web.app', 'https://cvalamedida.firebaseapp.com',
            'https://cv-a-la-medida-jhonn.web.app', 'https://cv-a-la-medida-jhonn.firebaseapp.com'}


def _admit(uid):
    key = sha256(uid.encode()).hexdigest()
    now = monotonic()
    with _lock:
        at, count = _windows.get(key, (now, 0))
        if now - at >= 60:
            at, count = now, 0
        _windows[key] = (at, count + 1)
        _windows.move_to_end(key)
        while len(_windows) > 256:
            _windows.popitem(last=False)
        return count < 12


def register_routes(core):
    @core.app.post('/api/diagnostics/client')
    def browser_diagnostic():
        identity = getattr(core.g, 'google_identity', None)
        if not identity or not identity.get('uid'):
            core.verify_google_identity()
            identity = getattr(core.g, 'google_identity', None) or {}
        if not identity.get('uid'):
            raise core.AppError('Inicia sesión para registrar una señal.', 401)
        origin = core.request.headers.get('Origin', '')
        local_origin = core.request.host_url.rstrip('/')
        local = local_origin.startswith(('http://localhost:', 'http://127.0.0.1:'))
        if origin not in _origins and not (local and origin == local_origin):
            raise core.AppError('Origen de diagnóstico no permitido.', 403)
        if (core.request.content_length or 0) > 1024:
            raise core.AppError('Señal de diagnóstico demasiado grande.', 413)
        data = core.request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) - {'component'} != {'service', 'stage', 'result', 'code'}:
            raise core.AppError('Señal de diagnóstico inválida.', 400)
        if not isinstance(data.get('code'), str):
            raise core.AppError('Señal de diagnóstico inválida.', 400)
        oauth = (data.get('service') == 'drive-api' and data.get('stage') == 'oauth-authorization'
                 and data.get('component', 'google') in ('google', 'telegram') and data.get('code') in _codes)
        network = (data.get('service') == 'api' and data.get('stage') == 'browser-request'
                   and data.get('component') in ('bank', 'pdf', 'google', 'drive', 'telegram')
                   and data.get('code') in ('network_error', 'request_timeout'))
        if not isinstance(data.get('code'), str) or data.get('result') not in ('error', 'pending') or not (oauth or network):
            raise core.AppError('Señal de diagnóstico inválida.', 400)
        if (data['code'] == 'authorization_pending') != (data['result'] == 'pending'):
            raise core.AppError('Señal de diagnóstico inválida.', 400)
        if not _admit(str(identity['uid'])):
            raise core.AppError('Demasiadas señales; espera un minuto.', 429)
        import architecture_diagnostics
        architecture_diagnostics.record_stage(core, component=data.get('component', 'google'), service=data['service'],
            endpoint='/api/diagnostics/client', stage=data['stage'],
            result='warning', code=data['code'], confirmed=False)
        response = core.jsonify(accepted=True, confirmed=False)
        response.headers['Cache-Control'] = 'no-store, private'
        return response
