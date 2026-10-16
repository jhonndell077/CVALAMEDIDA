"""Owner-only read-only diagnostics, without external availability assumptions."""
from datetime import datetime, timezone


def require_admin(core):
    identity = getattr(core.g, 'google_identity', None) or {}
    owner = core.ORIGINAL_OWNER_EMAIL.strip().casefold()
    if not owner or not identity.get('uid') or identity.get('email', '').casefold() != owner:
        raise core.AppError('Esta vista está reservada al administrador.', 403)


def register_routes(core):
    def same_origin():
        if core.request.headers.get('Origin') not in {'https://cvalamedida.web.app','https://cv-a-la-medida-jhonn.web.app'} or core.request.headers.get('X-Requested-With') != 'XmlHttpRequest':
            raise core.AppError('El origen de la comprobación no es válido.',403)

    @core.app.get('/api/admin/connections')
    def admin_connections_status():
        require_admin(core)
        import connection_probes
        identity = core.g.google_identity
        probes = connection_probes.inspect(core, identity)
        checked = datetime.now(timezone.utc).isoformat()
        gmail = connection_probes.cached_check(identity['uid'],'gmail') or {
            'id':'gmail','state':'unknown','checkedAt':checked,'ms':0,
            'detail':'Pulsa «Verificar permiso Gmail» para autorizar y comprobar gmail.send. No se enviará correo.'}
        response = core.jsonify(at=checked, intervalSeconds=60, checks=[{
            'id': 'api', 'state': 'ok', 'checkedAt': checked, 'ms': 0,
            'detail': 'La API respondió y validó la sesión del administrador. No comprueba Vertex, Drive ni el worker.',
        }, {'id':'google','state':'ok','checkedAt':checked,'ms':0,
            'detail':'Firebase verificó identidad, correo y revocación de la sesión del administrador. No acredita permisos OAuth de Drive/Gmail.'},
            gmail,
            *probes])
        response.headers['Cache-Control'] = 'no-store, private'
        return response

    @core.app.post('/api/admin/connections/google')
    def admin_connections_google():
        require_admin(core)
        same_origin()
        import connection_probes
        identity = core.g.google_identity
        token = core.request.headers.get('X-Drive-Access-Token','')
        result = connection_probes.checked('gmail',lambda:connection_probes.gmail(identity,token))
        result = connection_probes.remember(identity['uid'],result,300 if result['state']=='ok' else 60)
        response = core.jsonify(check=result)
        response.headers['Cache-Control']='no-store, private'
        return response

    @core.app.post('/api/admin/connections/push/test')
    def admin_connections_push_test():
        require_admin(core)
        same_origin()
        import connection_probes
        data=core.request.get_json(silent=True)
        if not isinstance(data,dict):raise core.AppError('La prueba Push no es válida.',400)
        result=connection_probes.checked('push',lambda:connection_probes.send_push_probe(core.g.google_identity,data.get('endpoint'),data.get('nonce')))
        # Provider acceptance alone is never a green delivery result.
        if result['state']=='ok':result['state']='unknown'
        response=core.jsonify(check=result)
        response.headers['Cache-Control']='no-store, private'
        return response

    @core.app.post('/api/admin/connections/push/confirm')
    def admin_connections_push_confirm():
        require_admin(core)
        same_origin()
        import connection_probes
        data=core.request.get_json(silent=True)
        if not isinstance(data,dict):raise core.AppError('La confirmación Push no es válida.',400)
        try:result=connection_probes.confirm_push_probe(core.g.google_identity['uid'],data.get('nonce'))
        except connection_probes.ProbeFailure:raise core.AppError('No hay una recepción Push reciente que coincida.',409) from None
        response=core.jsonify(check=result)
        response.headers['Cache-Control']='no-store, private'
        return response

    @core.app.get('/admin/conexiones')
    @core.app.get('/admin/conexiones/')
    def admin_connections_page():
        return core.send_from_directory(core.app.static_folder, 'admin-connections.html')
