"""Bounded sanitized evidence with optional shared persistence; no provider probes."""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock
import time
import re
import diagnostic_store
from uuid import uuid4

import admin_connections

RETENTION_SECONDS = 3600
MAX_EVENTS = 400


def _node(identifier, label, kind, source, services=(), endpoints=(), dependencies=()):
    return dict(id=identifier, label=label, description=label, kind=kind,
                source=source, services=list(services), endpoints=list(endpoints), dependencies=list(dependencies))


NODES = [
    _node('user', 'Usuario', 'functional', 'static/index.html', ('hosting',)),
    _node('google', 'Google Authentication', 'functional', 'app.py:verify_google_identity', ('firebase-auth', 'api')),
    _node('bank', 'Banco de datos central', 'functional', 'profile_routes.py:register_routes', ('drive-api', 'api'), ('/api/bank/status', '/api/bank/sync', '/api/profile/information', '/api/profile', '/api/profile-summary')),
    _node('drive', 'Google Drive', 'functional', 'app.py:archive_generated_resume', ('drive-api', 'api'), ('/api/drive/check',)),
    _node('telegram', 'Telegram', 'functional', 'telegram_bot.py:register_routes', ('telegram-api', 'worker', 'tasks', 'storage', 'secrets', 'drive-api', 'pdf-generator', 'firebase-auth'), ('/telegram/webhook', '/telegram/work', '/api/telegram/status')),
    _node('pdf', 'PDF / CV', 'functional', 'resume_routes.py:export_resume', ('api', 'pdf-generator', 'drive-api', 'storage'), ('/api/export/<format_name>', '/api/draft')),
    _node('diagnostics', 'Diagnóstico Firebase', 'functional', 'admin_connections.py:register_routes', ('api',), ('/api/admin/architecture',)),
    _node('hosting', 'Firebase Hosting', 'technical', 'firebase.json', dependencies=('api',)),
    _node('api', 'Cloud Functions · api', 'technical', 'main.py:api', endpoints=('/api/export/<format_name>', '/api/bank/sync'), dependencies=('firebase-auth',)),
    _node('firebase-auth', 'Firebase Authentication', 'technical', 'app.py:verify_google_identity', endpoints=('verify_google_identity',)),
    _node('drive-api', 'Google Drive API', 'technical', 'drive_bank.py:DriveBank', endpoints=('DriveBank.request', 'drive_request', 'archive_generated_resume')),
    _node('pdf-generator', 'Generador PDF', 'technical', 'cv_documents.py:make_pdf', endpoints=('make_pdf',)),
    _node('vertex', 'Vertex AI', 'technical', 'app.py:vertex_json'),
    _node('worker', 'Cloud Functions · telegram_worker', 'technical', 'main.py:telegram_worker', endpoints=('/telegram/work',), dependencies=('storage', 'vertex', 'drive-api', 'telegram-api')),
    _node('storage', 'Cloud Storage · trabajos y archivos', 'technical', 'job_runtime.py:JobStore'),
    _node('tasks', 'Cloud Tasks', 'technical', 'job_runtime.py:enqueue', dependencies=('worker',)),
    _node('secrets', 'Secret Manager', 'technical', 'job_runtime.py:configuration'),
    _node('telegram-api', 'Telegram Bot API', 'technical', 'telegram_bot.py', endpoints=('/telegram/webhook', '/telegram/work')),
    _node('gmail', 'Gmail API', 'technical', 'app.py:gmail_request'),
    _node('push', 'Web Push', 'technical', 'web_notifications.py'),
]

DESCRIPTIONS = {
    'user': 'Acceso a CV a la Medida desde la web; no se conserva identidad personal en los eventos.',
    'google': 'Identidad Firebase validada en backend. Los permisos OAuth de Drive se conceden por separado.',
    'bank': 'Perfil profesional central y documentos de evidencia en Drive; guardado condicionado por versión.',
    'drive': 'Autorización, consultas y archivo de documentos. Una respuesta HTTP no confirma por sí sola persistencia.',
    'telegram': 'Solicitud por bot, webhook, trabajo con identidad vinculada e idempotencia, banco, CV y respuesta.',
    'pdf': 'Generación local del PDF y flujo de archivo. Las etapas de generación y almacenamiento tienen evidencia independiente.',
    'diagnostics': 'Lectura administrativa de evidencia técnica, sin acciones de reparación ni acceso a contenido de usuarios.',
    'hosting': 'Sirve los recursos web y dirige rutas /api y /telegram a la función api según firebase.json.',
    'api': 'Entrada Flask de Cloud Functions. Un error HTTP de una solicitud no demuestra caída de la función.',
    'firebase-auth': 'Verificación del token de identidad con revocación; distinta de la autorización OAuth de Google APIs.',
    'drive-api': 'Google Drive REST: lecturas, escrituras condicionales y archivo con comprobación posterior.',
    'pdf-generator': 'ReportLab genera el documento; estado de generación independiente del archivo posterior.',
    'vertex': 'Generación y análisis mediante Vertex AI según proveedor configurado; sin sondas desde este módulo.',
    'worker': 'Procesa trabajos Telegram con vínculo de identidad, reserva y control de reintentos.',
    'storage': 'JobStore utiliza Cloud Storage; el archivo CV también puede usarlo según configuración.',
    'tasks': 'Despacha trabajos al worker cuando está configurado; no se ejecuta desde los diagramas.',
    'secrets': 'Configuración del bot mediante Secret Manager; no se leen ni exponen valores en diagnóstico.',
    'telegram-api': 'Respuestas del proveedor observadas durante operaciones normales; las demos nunca envían mensajes.',
    'gmail': 'Envío de postulaciones con OAuth separado. Inventariado, sin sondas desde este módulo.',
    'push': 'Notificaciones Web Push existentes; inventariadas sin enviar pruebas desde los diagramas.'
}
for node in NODES:
    node['description'] = DESCRIPTIONS.get(node['id'], node['label'])

IDS = frozenset(n['id'] for n in NODES)
EDGES = [{'from': n['id'], 'to': target} for n in NODES for target in n['services'] + n['dependencies']]
EDGES += [{'from': a, 'to': b} for a, b in [('user', 'google'), ('google', 'bank'), ('bank', 'drive'), ('bank', 'telegram'), ('bank', 'pdf'), ('drive', 'diagnostics'), ('telegram', 'diagnostics'), ('pdf', 'diagnostics'), ('api', 'vertex'), ('api', 'tasks'), ('api', 'storage'), ('api', 'gmail'), ('api', 'push')]]
ROUTES = {endpoint: n['id'] for n in NODES if n['kind'] == 'functional' for endpoint in n['endpoints']}
ROUTES.update({'/api/analyze': 'pdf', '/api/analyze/jobs': 'pdf', '/api/background/jobs': 'pdf', '/api/google/grant': 'google', '/api/profile': 'bank', '/api/diagnostics/client': 'google', '/api/account': 'google'})


class EventStore:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.events = deque(maxlen=MAX_EVENTS)
        self.lock = RLock()

    def append(self, event):
        with self.lock:
            self.events.append((self.clock(), dict(event)))

    def snapshot(self):
        with self.lock:
            cutoff = self.clock() - RETENTION_SECONDS
            while self.events and self.events[0][0] < cutoff:
                self.events.popleft()
            return [dict(event) for _, event in self.events]


def record_stage(core, *, component, service, endpoint, stage, result, code=None, duration_ms=None, confirmed=True):
    """Record only fixed identifiers; callers must observe the stage themselves."""
    try:
        if component not in IDS or service not in IDS or endpoint not in ROUTES:
            return
        if stage not in {'http-backend', 'pdf-generated', 'drive-upload', 'drive-readback', 'drive-request', 'telegram-request', 'bank-sync', 'identity-verified', 'oauth-authorization', 'browser-signin', 'task-dispatched', 'vertex-response', 'gmail-request', 'storage-read', 'storage-write'}:
            return
        if result not in {'success', 'error', 'warning'}:
            return
        context = getattr(core.g, 'architecture_observation', None)
        if not context:
            return
        event = dict(id=uuid4().hex, correlationId=context['id'], operationId=context.get('operationId', context['id']),
                     component=component, service=service, endpoint=endpoint,
                     at=datetime.now(timezone.utc).isoformat(), durationMs=None,
                     result=result, code=None, stage=stage, confirmed=confirmed is True, dependencies=[])
        if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
            event['code'] = code
        elif stage in {'oauth-authorization', 'browser-signin'} and confirmed is False and isinstance(code, str) and code in diagnostic_store.CLIENT_CODES:
            event['code'] = code
        if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool) and 0 <= duration_ms <= 86400000:
            event['durationMs'] = round(duration_ms, 2)
        core.app.extensions['architecture_diagnostics'].append(event)
        context.setdefault('events', []).append(event)
    except Exception:
        pass


@contextmanager
def stage(core, component, service, stage):
    """Observe a real operation; telemetry must never affect its result."""
    started = time.monotonic()
    try:
        yield
    except BaseException as error:
        try:
            context = getattr(core.g, 'architecture_observation', None)
            if context:
                code = getattr(error, 'code', None)
                if not isinstance(code, int):
                    code = getattr(error, 'status_code', None)
                record_stage(core, component=component, service=service, endpoint=context['endpoint'],
                             stage=stage, result='error', code=code,
                             duration_ms=(time.monotonic()-started)*1000)
        except Exception:
            pass
        raise
    else:
        try:
            context = getattr(core.g, 'architecture_observation', None)
            if context:
                record_stage(core, component=component, service=service, endpoint=context['endpoint'],
                             stage=stage, result='success', duration_ms=(time.monotonic()-started)*1000)
        except Exception:
            pass


def register_routes(core):
    if 'architecture_diagnostics' in core.app.extensions:
        return
    core.app.extensions['architecture_diagnostics'] = EventStore()
    core.app.extensions['architecture_shared_diagnostics'] = diagnostic_store.DiagnosticStore(IDS, ROUTES) if diagnostic_store.cloud_runtime() else None

    @core.app.before_request
    def architecture_begin():
        try:
            rule = core.request.url_rule
            if rule and rule.rule in ROUTES and not rule.rule.startswith('/api/admin/'):
                identifier = uuid4().hex
                operation = core.request.headers.get('X-CV-Operation-ID', '')
                if not re.fullmatch(r'(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})', operation):
                    operation = identifier
                core.g.architecture_observation = {'id': identifier, 'operationId': operation.lower(), 'start': time.monotonic(), 'endpoint': rule.rule, 'events': []}
        except Exception:
            pass

    @core.app.after_request
    def architecture_finish(response):
        try:
            context = getattr(core.g, 'architecture_observation', None)
            if context:
                endpoint = context['endpoint']
                response.headers['X-Correlation-ID'] = context['id']
                record_stage(core, component=ROUTES[endpoint], service='worker' if endpoint == '/telegram/work' else 'api', endpoint=endpoint,
                             stage='http-backend', result='error' if response.status_code >= 400 else 'success',
                             code=response.status_code, duration_ms=(time.monotonic()-context['start'])*1000)
                shared = core.app.extensions.get('architecture_shared_diagnostics')
                if shared is not None:
                    shared.append_batch(context.get('events', []))
        except Exception:
            pass
        return response

    @core.app.get('/api/admin/architecture')
    def admin_architecture():
        admin_connections.require_admin(core)
        try:
            events = core.app.extensions['architecture_diagnostics'].snapshot()
        except Exception:
            events = []
        shared = core.app.extensions.get('architecture_shared_diagnostics')
        shared_available = False
        if shared is not None:
            try:
                events = shared.sanitize(shared.snapshot() + events)
                shared_available = True
            except Exception:
                pass
        scope = ('Historial compartido en el bucket privado de trabajos; más evidencia local pendiente.' if shared_available else
                 'Solo memoria de esta instancia: historial compartido no disponible; no prueba ausencia de incidentes.')
        response = core.jsonify(nodes=NODES, edges=EDGES, events=events,
            retention={'seconds': RETENTION_SECONDS, 'maxEvents': MAX_EVENTS, 'scope': scope, 'sharedAvailable': shared_available},
            limitations=['HTTP confirma únicamente la etapa del backend; no acredita PDF, Drive ni otras dependencias.',
                         'Sin consulta a producción ni verificación de dominios, OAuth, IAM o disponibilidad.',
                         'Causa no determinada — requiere investigación cuando no hay evidencia de una etapa.',
                         'Retención lógica de una hora y 400 eventos; objetos vencidos se reemplazan al siguiente guardado, sin borrado programado.',
                         'El historial compartido depende del acceso al bucket existente; la falta de eventos significa No verificado.',
                         'Correlación por solicitud y operación: el identificador de operación enlaza reintentos sin demostrar causalidad por sí solo.',
                         'Servicios y alternativas de almacenamiento inventariados desde el código; no todos están necesariamente habilitados.',
                         'No se importan logs de Google Cloud; reportes OAuth del navegador se distinguen como evidencia no confirmada por el proveedor.'])
        response.headers['Cache-Control'] = 'no-store, private'
        return response
