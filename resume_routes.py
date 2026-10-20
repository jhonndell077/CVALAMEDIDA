"""HTTP routes; business operations are provided by the explicit core dependency."""
from __future__ import annotations
from typing import Any
import application_mail
import hashlib
import time
import job_runtime
import user_accounts
import requests
from google.api_core.exceptions import PreconditionFailed


def _dispatch_key(owner, application_id):
    return 'gmail-dispatch-' + hashlib.sha256((owner + ':' + application_id).encode()).hexdigest()


def _reserve_dispatch(core, store, key, digest):
    """A generation-zero create is the cross-instance at-most-once boundary."""
    reservation = {'request_digest': digest, 'state': 'reserved', 'created_at': time.time()}
    try:
        store.write(key, reservation, 0)
        return reservation, False
    except PreconditionFailed:
        existing, generation = store.read(key)
        if not existing or existing.get('request_digest') != digest:
            raise core.AppError('Este identificador ya corresponde a otra solicitud de envío.', 409) from None
        if existing.get('state') == 'not_started':
            existing['state'] = 'reserved'
            store.write(key, existing, generation)
            return existing, False
        if existing.get('state') == 'gmail_accepted':
            return existing, True
        raise core.AppError('Este envío está en proceso o sin confirmar. Revisa Enviados en Gmail antes de volver a enviarlo.', 409) from None


def _save_dispatch(store, key, reservation, **values):
    current, generation = store.read(key)
    if not current or current.get('request_digest') != reservation['request_digest']:
        raise job_runtime.JobError('No se pudo conservar la confirmación del envío.')
    current.update(values)
    store.write(key, current, generation)
    reservation.update(values)


def register_routes(core):
    @core.app.post("/api/analyze")
    def analyze() -> Any:
        payload = core.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError("La solicitud no tiene un formato JSON válido.")
        text, images = core.extract_vacancy(payload)
        model = core.require_model(payload.get("model"))
        selected = payload.get("selected_position")
        if selected is not None and (not isinstance(selected, str) or not selected.strip() or len(selected) > 140):
            raise core.AppError("El puesto elegido no es válido.", 400)
        try:
            analysis = core.analyze_with_model(model, text, images, selected) if selected else core.analyze_with_model(model, text, images)
        except core.VacancySelectionRequired as choice:
            return core.jsonify({"selection_required": True, "positions": choice.positions, "model": model})
        return core.jsonify({"analysis": analysis, "model": model})

    core.analyze = analyze

    @core.app.post("/api/draft")
    def draft() -> Any:
        payload = core.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError("La solicitud no tiene un formato JSON válido.")
        return core.jsonify({"draft": core.make_draft(payload.get("analysis"))})

    core.draft = draft

    @core.app.post("/api/drive/check")
    def check_drive() -> Any:
        folder = core.verify_drive_access(core.request.headers.get("X-Drive-Access-Token", ""))
        return core.jsonify({"folder_id": folder["id"], "folder_name": folder["name"]})

    core.check_drive = check_drive

    @core.app.post('/api/google/grant')
    def google_grant():
        # Popup credentials omit granted scopes. Inspect once, without tokens in URLs.
        token = core.request.headers.get('X-Drive-Access-Token', '')
        if not token or len(token) > 4096 or '\n' in token or '\r' in token:
            raise core.AppError('Autoriza Google para comprobar los permisos.', 401)
        identity = core.drive_request('https://www.googleapis.com/oauth2/v3/userinfo', token)
        if identity.get('email_verified') is not True or identity.get('email', '').casefold() != core.account_state.ARCHIVE_CONFIG.get('allowed_email', '').casefold():
            raise core.AppError('La autorización de Google no pertenece a esta cuenta.', 403)
        try:
            response = requests.post('https://oauth2.googleapis.com/tokeninfo', headers={
                'Authorization': 'Bearer ' + token, 'Content-Type': 'application/x-www-form-urlencoded'}, timeout=25)
            if not response.ok:
                raise core.AppError('No se pudieron comprobar los permisos de Google. Vuelve a autorizar.',
                                    401 if response.status_code in {400, 401, 403} else 503)
            data = response.json()
            scope = data.get('scope')
            expires = int(data.get('expires_in', 0))
            if not isinstance(scope, str) or not scope or expires <= 0:
                raise ValueError('Invalid grant metadata')
        except (requests.RequestException, ValueError, TypeError):
            raise core.AppError('No se pudieron comprobar los permisos de Google. Vuelve a intentarlo.', 503) from None
        result = core.jsonify(scope=scope, expires_in=expires)
        result.headers['Cache-Control'] = 'no-store'
        return result

    @core.app.post('/api/account/connections/verify')
    def verify_synchronization_connections():
        import synchronization_checks
        return synchronization_checks.verify(core, google_grant)

    @core.app.route("/api/applications", methods=["GET", "POST"])
    def applications_history() -> Any:
        token = core.request.headers.get("X-Drive-Access-Token", "")
        folder = core.verify_drive_access(token)
        if core.request.method == "GET":
            cursor = core.request.args.get('cursor', '')
            if len(cursor) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in cursor):
                raise core.AppError('El cursor del historial no es válido.', 400)
            parameters = {
                "q": f"'{folder['id']}' in parents and trashed=false and appProperties has {{ key='cvDispatch' and value='1' }}",
                "fields": "files(id,description),nextPageToken", "pageSize": 100,
                "orderBy": "createdTime desc", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
            }
            if cursor:
                parameters['pageToken'] = cursor
            params = core.urllib.parse.urlencode(parameters)
            files = core.drive_request("https://www.googleapis.com/drive/v3/files?" + params, token)
            entries = {}
            for item in files.get("files", []):
                try:
                    record = core.json.loads(item.get("description", ""))
                    if isinstance(record, dict) and isinstance(record.get("application_id"), str):
                        entries.setdefault(record["application_id"], record)
                except (ValueError, TypeError):
                    continue
            return core.jsonify({"entries": list(entries.values()), "has_more": bool(files.get("nextPageToken")),
                                 "next_cursor": files.get('nextPageToken') or None})
        payload = core.request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise core.AppError("Los datos de la postulación no son válidos.", 400)
        channel = payload.get("channel")
        status = payload.get("status", "prepared")
        if channel not in {"gmail", "whatsapp"} or status not in {"prepared", "confirmed_by_user", "whatsapp_opened"} or (status == "whatsapp_opened" and channel != "whatsapp"):
            raise core.AppError("El canal o estado de la postulación no es válido.", 400)
        recipient = core._short_text(payload.get("recipient"), 254)
        if (channel == "gmail" and not core.re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", recipient)) or (channel == "whatsapp" and not core.re.fullmatch(r"[1-9]\d{7,14}", recipient)):
            raise core.AppError("Revisa el destinatario de la postulación.", 400)
        application_id = payload.get("application_id") or str(core.uuid4())
        if not isinstance(application_id, str) or not core.re.fullmatch(r"[a-f0-9-]{36}", application_id):
            raise core.AppError("El identificador de la postulación no es válido.", 400)
        position = core._short_text(payload.get("position"), 140)
        if not position:
            raise core.AppError("Indica el nombre de la vacante.", 400)
        cv_url = core._short_text(payload.get("cv_url"), 200)
        if cv_url and not core.re.fullmatch(r"https://drive\.google\.com/file/d/[A-Za-z0-9_-]+/view", cv_url):
            raise core.AppError("El enlace del CV no es válido.", 400)
        record = {"application_id": application_id, "position": position, "recipient": recipient,
                  "channel": channel, "status": status, "cv_url": cv_url,
                  "date": core.datetime.now(core.timezone.utc).isoformat()}
        core.save_application_record(record, token, folder)
        return core.jsonify({"entry": record})

    core.applications_history = applications_history

    @core.app.post("/api/gmail/send")
    def send_gmail_application() -> Any:
        payload = core.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError("La solicitud de envío no es válida.", 400)
        recipient = payload.get("recipient", "")
        message_text = payload.get("message", "")
        application_id = payload.get("application_id", "")
        if not isinstance(recipient, str) or len(recipient) > 254 or not core.re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", recipient):
            raise core.AppError("Indica un correo válido para enviar el CV.", 400)
        if not isinstance(message_text, str) or not message_text.strip() or len(message_text) > 5000:
            raise core.AppError("Revisa el mensaje antes de enviar.", 400)
        if not isinstance(application_id, str) or not core.re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", application_id):
            raise core.AppError("La solicitud no tiene un identificador de envío válido.", 400)
        gmail_token = core.request.headers.get("X-Gmail-Access-Token", "")
        if not gmail_token or len(gmail_token) > 4096 or "\n" in gmail_token or "\r" in gmail_token:
            raise core.AppError("Autoriza Gmail antes de enviar el CV.", 401)
        identity = core.gmail_request("https://www.googleapis.com/oauth2/v3/userinfo", gmail_token)
        sender = core.account_state.ARCHIVE_CONFIG.get("allowed_email", "")
        if identity.get("email_verified") is not True or identity.get("email", "").casefold() != sender.casefold():
            raise core.AppError("Autoriza Gmail con la cuenta permitida para esta aplicación.", 403)
        try:
            application_mail.verify_grant(gmail_token)
        except ValueError as error:
            raise core.AppError(str(error), 403) from None
        drive_token = core.request.headers.get("X-Drive-Access-Token", "")
        folder = core.verify_drive_access(drive_token)
        store = job_runtime.JobStore()
        digest = hashlib.sha256(core.json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        key = _dispatch_key(user_accounts.owner() or sender.casefold(), application_id)
        reservation, already_sent = _reserve_dispatch(core, store, key, digest)
        if already_sent:
            return core.jsonify({'entry': reservation['entry'], 'already_sent': True})
        query = core.urllib.parse.urlencode({"q": f"'{folder['id']}' in parents and trashed=false and appProperties has {{ key='cvApplicationId' and value='{application_id}' }}",
                                       "fields": "files(description)", "orderBy": "createdTime desc", "pageSize": 1})
        previous = core.drive_request("https://www.googleapis.com/drive/v3/files?" + query, drive_token).get("files", [])
        if previous:
            try:
                prior = core.json.loads(previous[0]["description"])
            except (ValueError, KeyError):
                raise core.AppError("No se pudo comprobar el envío anterior. Revisa Gmail antes de reintentar.", 409)
            if prior.get("status") == "gmail_accepted":
                _save_dispatch(store, key, reservation, state='gmail_accepted', entry=prior)
                return core.jsonify({"entry": prior, "already_sent": True})
            if prior.get("status") != "failed":
                raise core.AppError("Este envío está en proceso o sin confirmar. Revisa Enviados en Gmail antes de volver a enviarlo.", 409)
        draft_data = core.make_draft(payload.get("analysis"))
        position = draft_data["position"]
        pdf = core.make_pdf(draft_data).getvalue()
        try:
            mail_payload, mail_details = application_mail.compose(sender, recipient,
                draft_data['candidate']['name'], position, application_id, pdf, message_text)
        except ValueError as error:
            raise core.AppError(str(error), 422) from None
        cv_url = core.archive_generated_resume(f"{core.uuid4().hex[:8]}_{mail_details['filename']}", "pdf", pdf)
        record = {"application_id": application_id, "position": position, "recipient": recipient, "channel": "gmail",
                  "status": "sending", "sender": sender, "rfc_message_id": f"{application_id}@cvalamedida.web.app",
                  "cv_url": cv_url, "date": core.datetime.now(core.timezone.utc).isoformat(),
                  "owner_uid": user_accounts.owner(), "origin": "web", "correlation_id": application_id,
                  "pdf_id": cv_url.split("/file/d/")[-1].split("/")[0],
                  "recipient_origin": "vacancy" if recipient.casefold() in [v.casefold() for v in application_mail.contacts((payload.get("analysis") or {}).get("vacancy", {}).get("application_emails", []))] else "manual", **mail_details}
        try:
            application_mail.reserve_rate(store, user_accounts.owner() or sender, recipient, position)
        except ValueError as error:
            record['status'] = 'failed'
            _save_dispatch(store, key, reservation, state='not_started', entry=record)
            raise core.AppError(str(error), 429) from None
        core.save_application_record(record, drive_token, folder)
        # Persist before contacting Gmail. A lost response must never cause a resend.
        _save_dispatch(store, key, reservation, state='send_started')
        try:
            result = core.gmail_request("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", gmail_token,
                                   core.json.dumps(mail_payload).encode())
            if not result.get("id"):
                raise core.AppError("Gmail no confirmó el envío. Revisa Enviados antes de reintentar.", 502)
        except Exception as error:
            record["status"] = "failed" if isinstance(error, core.AppError) and error.status_code in {401, 403, 422} else "send_unknown"
            try:
                _save_dispatch(store, key, reservation, state=record['status'], entry=record)
            except Exception:
                core.app.logger.warning('No se pudo actualizar la reserva del envío; continúa bloqueada contra duplicados.')
            try:
                core.save_application_record(record, drive_token, folder)
            except core.AppError:
                pass
            if isinstance(error, core.AppError):
                raise
            raise core.AppError("No se pudo confirmar el envío. Comprueba Enviados antes de repetirlo.", 502) from None
        record.update(status="gmail_accepted", gmail_message_id=result["id"], date=core.datetime.now(core.timezone.utc).isoformat())
        warning = ""
        try:
            _save_dispatch(store, key, reservation, state='gmail_accepted', entry=record)
        except Exception:
            warning = 'Gmail confirmó el envío, pero no se pudo conservar la confirmación. No vuelvas a enviarlo; comprueba Enviados.'
        try:
            core.save_application_record(record, drive_token, folder)
        except core.AppError:
            warning = "Gmail confirmó el envío, pero no se pudo actualizar el historial en Drive. No vuelvas a enviarlo; comprueba Enviados."
        return core.jsonify({"entry": record, "warning": warning})

    core.send_gmail_application = send_gmail_application

    @core.app.post("/api/export/<format_name>")
    def export_resume(format_name: str) -> Any:
        if format_name not in {"pdf", "docx"}:
            raise core.AppError("Formato no admitido. Usa PDF o DOCX.")
        payload = core.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError("La solicitud no tiene un formato JSON válido.")
        draft_data = core.make_draft(payload.get("analysis"))
        if format_name == "pdf":
            file_data = core.make_pdf(draft_data)
            mimetype = "application/pdf"
        else:
            file_data = core.make_docx(draft_data)
            mimetype = (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            )
        filename = core.re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            f"{draft_data['candidate']['name']}_{draft_data['position']}",
        ).strip("_")
        archive_path = (
            f"{filename}_{core.datetime.now():%Y%m%d_%H%M%S}_{core.uuid4().hex[:8]}.{format_name}"
        )
        archived_location = core.archive_generated_resume(
            archive_path,
            format_name,
            file_data.getvalue(),
        )
        core.app.logger.info("CV generado archivado en %s", archived_location)
        file_data.seek(0)
        response = core.send_file(
            file_data,
            mimetype=mimetype,
            as_attachment=True,
            download_name=f"{filename}.{format_name}",
        )
        if archived_location.startswith("https://drive.google.com/"):
            response.headers["X-CV-Drive-URL"] = archived_location
        return response

    core.export_resume = export_resume

