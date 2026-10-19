"""Account-owned shared evidence. Browser state never decides server health."""
import hashlib
import json
from pathlib import Path

import architecture_diagnostics
import diagnostic_store


def summarize(events, account_key):
    latest = {}
    for event in events:
        if event.get('accountKey') != account_key or event.get('confirmed') is not True:
            continue
        if event.get('result') not in {'success', 'error'}:
            continue
        key = tuple(event.get(field) for field in ('operationId', 'component', 'service', 'endpoint', 'stage'))
        if not all(isinstance(value, str) for value in key):
            continue
        if key not in latest or str(event.get('at', '')) > str(latest[key].get('at', '')):
            latest[key] = event
    incidents = []
    for key, event in latest.items():
        if event['result'] != 'error':
            continue
        incidents.append(dict(id=hashlib.sha256(json.dumps(key).encode()).hexdigest()[:24],
            component=event['component'], service=event['service'], endpoint=event['endpoint'],
            stage=event['stage'], code=event.get('code'), at=event.get('at')))
    incidents.sort(key=lambda item: item['id'])
    revision = hashlib.sha256(json.dumps(incidents, sort_keys=True).encode()).hexdigest()
    return dict(revision=revision, errorCount=len(incidents), incidents=incidents)


def register_routes(core):
    @core.app.get('/api/session/state')
    def functional_session_state():
        identity = getattr(core.g, 'google_identity', None) or {}
        if not identity.get('uid'):
            core.verify_google_identity()
            identity = getattr(core.g, 'google_identity', None) or {}
        if not identity.get('uid'):
            raise core.AppError('Inicia sesión para consultar el estado compartido.', 401)
        if core.request.args:
            raise core.AppError('El estado corresponde exclusivamente a tu cuenta.', 400)
        shared = core.app.extensions.get('architecture_shared_diagnostics')
        try:
            # Never merge an instance's private memory into a shared snapshot.
            if shared is not None:
                events = shared.snapshot()
                source = 'shared'
            elif not diagnostic_store.cloud_runtime():
                events = core.app.extensions['architecture_diagnostics'].snapshot()
                source = 'local-development'
            else:
                raise RuntimeError('shared snapshot unavailable')
            account = hashlib.sha256(identity['uid'].encode()).hexdigest()
            result = dict(available=True, source=source, **summarize(events, account))
        except Exception:
            result = dict(available=False, source='unavailable', revision=None, errorCount=None, incidents=[])
        try:
            version = json.loads((Path(core.app.static_folder) / 'version.json').read_text(encoding='utf-8')).get('buildId')
        except (OSError, ValueError, TypeError):
            version = None
        response = core.jsonify(**result, buildId=version, retentionSeconds=architecture_diagnostics.RETENTION_SECONDS,
            scope='account', health='not-inferred', pollSeconds=20)
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Vary'] = 'Authorization'
        return response
