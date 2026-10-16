"""Owner-only read-only diagnostics, without external availability assumptions."""
from datetime import datetime, timezone


def require_admin(core):
    identity = getattr(core.g, 'google_identity', None) or {}
    owner = core.ORIGINAL_OWNER_EMAIL.strip().casefold()
    if not owner or not identity.get('uid') or identity.get('email', '').casefold() != owner:
        raise core.AppError('Esta vista está reservada al administrador.', 403)


def register_routes(core):
    @core.app.get('/api/admin/connections')
    def admin_connections_status():
        require_admin(core)
        checked = datetime.now(timezone.utc).isoformat()
        response = core.jsonify(at=checked, intervalSeconds=60, checks=[{
            'id': 'api', 'state': 'ok', 'checkedAt': checked, 'ms': 0,
            'detail': 'La API respondió y validó la sesión del administrador. No comprueba Vertex, Drive ni el worker.',
        }])
        response.headers['Cache-Control'] = 'no-store, private'
        return response

    @core.app.get('/admin/conexiones')
    @core.app.get('/admin/conexiones/')
    def admin_connections_page():
        return core.send_from_directory(core.app.static_folder, 'admin-connections.html')
