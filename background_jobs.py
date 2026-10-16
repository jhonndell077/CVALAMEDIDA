"""Recoverable operations: server-owned queue, measured stages, private results."""
import re
import time
import uuid
import hashlib
import json
from flask import jsonify, request, send_file, g
import io
import job_runtime as bot
import web_notifications as notifications
import user_accounts

PATHS = {'/api/draft': 'draft', '/api/profile/information': 'information',
         '/api/export/pdf': 'export', '/api/export/docx': 'export',
         '/api/gmail/send': 'gmail', '/api/applications': 'application',
         '/api/bank/sync': 'bank_sync', '/api/analyze': 'analysis'}


def enforce_request_quota(core):
    """Reserve one shared per-account slot for synchronous expensive requests."""
    if request.method != 'POST' or request.path not in PATHS or not user_accounts.owner():
        return
    store = bot.JobStore()
    identifier = 'direct-' + str(uuid.uuid4())
    if not store.admit(identifier, user_accounts.owner()):
        raise core.AppError('Tienes diez procesos pendientes. Espera a que termine uno para continuar.', 429)
    store.write(identifier, {'state': 'processing', 'created_at': time.time(), 'lease_until': time.time() + 600}, 0)
    g.cv_request_slot = (store, identifier)


def release_request_quota():
    slot = getattr(g, 'cv_request_slot', None)
    if not slot:
        return
    g.cv_request_slot = None
    store, identifier = slot
    job, generation = store.read(identifier)
    if job:
        store.write(identifier, {'state': 'done', 'completed_at': time.time()}, generation)


def valid_id(identifier):
    return isinstance(identifier, str) and bool(re.fullmatch(r'web-[0-9a-f-]{36}', identifier))


def process_job(core, identifier, store):
    job, _ = store.read(identifier)
    if job and job.get('owner_uid'):
        if job.get('state') in {'done', 'failed'}:
            return
        try:
            headers = notifications.unprotect(store, job.get('credentials'), identifier)
            identity = {'uid':job['owner_uid'], 'email':job['owner_email'], 'name':job.get('owner_name','')}
            account_scope = user_accounts.scope(core, identity, headers, store)
            account_scope.__enter__()
        except core.AppError as error:
            job, generation = store.read(identifier)
            if job.get('state') in {'done', 'failed'}: return
            job.pop('credentials', None)
            job.pop('payload', None)
            job.update(state='failed', error=str(error), stage='Conecta nuevamente tu cuenta de Drive', lease_until=0)
            store.write(identifier, job, generation)
            try: notifications.notify(store, identifier, job)
            except Exception: core.app.logger.warning('No se pudo entregar la notificación del proceso.')
            return
        try:
            return _process_job(core, identifier, store)
        finally:
            account_scope.__exit__(None, None, None)
    return _process_job(core, identifier, store)

def _process_job(core, identifier, store):
    job, generation = store.read(identifier)
    if not job or job.get('state') in {'done', 'failed'}:
        return
    if job.get('lease_until', 0) > time.time():
        raise bot.JobError('Job busy')
    uncertain = job.get('external_started', False)
    job.update(state='processing', lease_until=time.time() + 330)
    store.write(identifier, job, generation)

    def checkpoint(progress, stage, **values):
        job.update(progress=max(job.get('progress', 1), progress), stage=stage, **values)
        _, current = store.read(identifier)
        store.write(identifier, job, current)

    try:
        if uncertain:
            raise core.AppError('El servidor perdió la confirmación de la operación. Revisa Drive o Enviados antes de repetirla.', 409)
        if time.time() - job['created_at'] > 3600:
            raise core.AppError('La autorización de este proceso venció. Vuelve a iniciarlo.', 401)
        operation = job['operation']
        if operation in {'analysis', 'bank_sync', 'draft', 'export', 'gmail'} and core.bank_enabled():
            checkpoint(3, 'Consultando el banco de Drive')
            status = core.load_drive_bank()
            if operation == 'bank_sync' and not status.get('pending'):
                checkpoint(92, 'Verificando el índice del banco')
                status = core.load_drive_bank(process=True)
            if status.get('pending'):
                before = status['pending']
                total = max(job.get('bank_total', 0), before)
                status = core.load_drive_bank(process=True)
                remaining = status['pending']
                stalled = job.get('bank_stalled', 0) + 1 if remaining >= before else 0
                progress = 3 + int((total - remaining) / total * (92 if operation == 'bank_sync' else 32))
                checkpoint(progress, f'Leyendo el banco: {total - remaining} de {total} archivos',
                           bank_total=total, bank_stalled=stalled)
                if stalled >= 3:
                    raise core.AppError('No se pudo leer un archivo del banco después de tres intentos. Revisa los avisos y vuelve a sincronizar.', 503)
                if remaining:
                    step = job.get('step', 0) + 1
                    checkpoint(progress, job['stage'], step=step, state='queued', lease_until=0)
                    bot.enqueue(identifier, bot.configuration(), task_identifier=f'{identifier}-{step}', kind='web_analysis')
                    return
            if operation == 'bank_sync':
                result = status
            else:
                result = None
        else:
            result = None
        if operation == 'analysis':
            checkpoint(40, 'Banco revisado; leyendo la vacante')
            payload = job['payload']
            text, images = core.extract_vacancy(payload)
            model = core.require_model(payload.get('model'))
            checkpoint(55, 'Vacante leída; esperando el análisis de IA')
            selected = payload.get('selected_position')
            try:
                analysis = core.analyze_with_model(model, text, images, selected) if selected else core.analyze_with_model(model, text, images)
                result = {'analysis': analysis, 'model': model}
            except core.VacancySelectionRequired as choice:
                result = {'selection_required': True, 'positions': choice.positions, 'model': model,
                          'selection_payload': payload}
            checkpoint(90, 'Análisis recibido; guardando el resultado')
        elif operation != 'bank_sync':
            checkpoint(45, 'Preparando el documento' if operation in {'draft', 'export'} else 'Procesando la solicitud')
            headers = notifications.unprotect(store, job.get('credentials'), identifier)
            if operation in {'export', 'gmail', 'application'}:
                checkpoint(45, job['stage'], external_started=True)
            with core.app.test_request_context(job['path'], method='POST', json=job['payload'], headers=headers):
                endpoint, values = core.app.url_map.bind('localhost').match(job['path'], method='POST')
                response = core.app.make_response(core.app.view_functions[endpoint](**values))
                if response.status_code >= 400:
                    raise core.AppError((response.get_json(silent=True) or {}).get('error', 'No se pudo completar la solicitud.'), response.status_code)
                checkpoint(90, 'Operación completada; guardando el resultado')
                if operation == 'export':
                    response.direct_passthrough = False
                    store.put_artifact(identifier, response.get_data(), response.mimetype)
                    filename = re.search(r'filename="?([^";]+)', response.headers.get('Content-Disposition', ''))
                    result = {'download_url': f'/api/background/jobs/{identifier}/file',
                              'fileName': filename.group(1) if filename else 'CV.' + job['path'].split('/')[-1],
                              'driveUrl': response.headers.get('X-CV-Drive-URL', '')}
                    response.close()
                else:
                    result = response.get_json()
        job.pop('payload', None)
        job.pop('credentials', None)
        checkpoint(100, 'Completado', state='done', result=result, lease_until=0, completed_at=time.time())
    except core.AppError as error:
        job.pop('payload', None)
        job.pop('credentials', None)
        checkpoint(job.get('progress', 1), 'El proceso necesita atención', state='failed', error=str(error), lease_until=0)
    except Exception:
        # Durable failure avoids repeating external writes after an uncertain outcome.
        job.pop('payload', None)
        job.pop('credentials', None)
        checkpoint(job.get('progress', 1), 'El proceso necesita atención', state='failed',
                   error='No se pudo confirmar el resultado. Revisa el estado del proceso antes de repetirlo.', lease_until=0)
    try:
        notifications.notify(store, identifier, job)
    except Exception:
        core.app.logger.warning('No se pudo entregar la notificación del proceso.')


def register_routes(app, core):
    @app.post('/api/background/jobs')
    def submit_background_job():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or data.get('path') not in PATHS or not isinstance(data.get('payload'), dict):
            raise core.AppError('La operación en segundo plano no es válida.')
        selected = data['payload'].get('selected_position')
        if selected is not None and (not isinstance(selected, str) or not selected.strip() or len(selected) > 140):
            raise core.AppError('El puesto elegido no es válido.')
        try:
            identifier = 'web-' + str(uuid.UUID(data['request_id']))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise core.AppError('El identificador del proceso no es válido.') from None
        store = bot.JobStore()
        job, generation = store.read(identifier)
        if job:
            user_accounts.require_owner(core, job)
        digest = hashlib.sha256(json.dumps({'path': data['path'], 'payload': data['payload']}, sort_keys=True).encode()).hexdigest()
        if job and job.get('request_digest') != digest:
            raise core.AppError('Este identificador ya corresponde a otra solicitud.', 409)
        if not job:
            if not store.admit(identifier, user_accounts.owner()):
                raise core.AppError('Tienes diez procesos pendientes. Espera a que termine uno para continuar.', 429)
            headers = {key: request.headers[key] for key in ('X-Drive-Access-Token', 'X-Gmail-Access-Token') if request.headers.get(key)}
            job = {'operation': PATHS[data['path']], 'path': data['path'], 'payload': data['payload'],
                   'state': 'queued', 'created_at': time.time(), 'progress': 1, 'stage': 'Solicitud guardada en la cola',
                   'request_digest': digest,
                   'credentials': notifications.protect(store, headers, identifier)}
            if user_accounts.owner():
                identity = user_accounts.CURRENT.get()
                job.update(owner_uid=identity['uid'], owner_email=identity['email'], owner_name=identity.get('name',''))
            try:
                store.write(identifier, job, generation)
            except bot.PreconditionFailed:
                # Concurrent retries may share an ID; only the first payload wins.
                job, _ = store.read(identifier)
                if not job:
                    raise core.AppError('No se pudo recuperar la solicitud. Vuelve a intentarlo.', 503) from None
                user_accounts.require_owner(core, job)
                if job.get('request_digest') != digest:
                    raise core.AppError('Este identificador ya corresponde a otra solicitud.', 409) from None
        if job['state'] == 'queued':
            bot.enqueue(identifier, bot.configuration(), task_identifier=f"{identifier}-{job.get('step', 0)}", kind='web_analysis')
        return jsonify(job_id=identifier), 202

    @app.post('/api/background/jobs/<identifier>')
    def background_job_status(identifier):
        if not valid_id(identifier):
            raise core.AppError('El proceso no existe.', 404)
        job, _ = bot.JobStore().read(identifier)
        if not job:
            raise core.AppError('El proceso no existe.', 404)
        user_accounts.require_owner(core, job)
        return jsonify({key: job[key] for key in ('state', 'result', 'error', 'progress', 'stage', 'path', 'operation') if key in job})

    @app.get('/api/background/jobs/<identifier>/file')
    def background_job_artifact(identifier):
        if not valid_id(identifier):
            raise core.AppError('El archivo no existe.', 404)
        store = bot.JobStore()
        job, _ = store.read(identifier)
        if job:
            user_accounts.require_owner(core, job)
        if not job or job.get('state') != 'done' or job.get('operation') != 'export':
            raise core.AppError('El archivo no está disponible.', 404)
        data, mime = store.artifact(identifier)
        return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=job['result']['fileName'])

    @app.post('/api/notifications/config')
    def push_config():
        return jsonify(public_key=notifications.configuration(bot.JobStore())['public_key'])

    @app.post('/api/notifications/subscribe')
    def push_subscribe():
        subscription = request.get_json(silent=True)
        try:
            valid = notifications.valid_subscription(subscription)
        except ValueError:
            valid = False
        if not valid:
            raise core.AppError('La suscripción de notificaciones no es válida.')
        notifications.subscribe(bot.JobStore(), subscription, user_accounts.owner())
        return jsonify(ok=True)
