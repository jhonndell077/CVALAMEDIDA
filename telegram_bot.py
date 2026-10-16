"""Private Telegram CV workflow. Secrets stay in Secret Manager, jobs in GCS."""
from __future__ import annotations

import base64

import job_runtime as runtime
from job_runtime import (JobError as TelegramError, JobStore, configuration,
    save_configuration, task_secret, cloud_request, enqueue, PROJECT, SECRET, QUEUE, BUCKET, WORKER)
import hashlib
import hmac
import json
import os
import re
import time
import traceback
from email.message import EmailMessage
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from pathlib import PurePosixPath
from urllib.parse import quote, urlencode

import requests
from flask import jsonify, request
from google.api_core.exceptions import NotFound, PreconditionFailed
import user_accounts
import telegram_accounts as accounts
import web_notifications as encrypted

ORIGIN = "https://cvalamedida.web.app"
ALLOWED_ORIGINS = {ORIGIN, "https://cvalamedida.firebaseapp.com", "https://cv-a-la-medida-jhonn.web.app", "https://cv-a-la-medida-jhonn.firebaseapp.com"}












def telegram(config, method, data, files=None):
    try:
        response = requests.post(f"https://api.telegram.org/bot{config['bot_token']}/{method}",
            data=data if files else None, json=None if files else data, files=files,
            timeout=5 if method in {'editMessageText','answerCallbackQuery','sendChatAction'} else 8 if method=='sendMessage' else 40)
        result = response.json()
        if not response.ok or not result.get("ok"):
            raise runtime.JobError("Telegram no confirmó la operación.")
        return result["result"]
    except runtime.JobError:
        raise
    except Exception:
        # Never expose a URL containing the bot token in exception messages.
        raise runtime.JobError("No se pudo conectar con Telegram.") from None


def reply_to(message_id):
    return {"reply_parameters": json.dumps({"message_id": message_id, "allow_sending_without_reply": True})} if isinstance(message_id, int) else {}


def say(config, text, message_id=None):
    return telegram(config, "sendMessage", {"chat_id": config["owner_id"], "text": text, **reply_to(message_id)})

def acknowledge(config, query_id, text):
    try: telegram(config,'answerCallbackQuery',{'callback_query_id':query_id,'text':text[:180]})
    except runtime.JobError: pass


def progress(config, identifier, store, stage, text, keyboard=None):
    """One persistent notice per request, driven exclusively by actual stages."""
    try:
        job, version=store.read(identifier)
        if not job or (job.get('owner_id') and job['owner_id']!=config['owner_id']) or (job.get('owner_uid') and job['owner_uid']!=config.get('owner_uid')):
            return
        if job.get('progress_stage')==stage and job.get('progress_text')==text: return
        notice_id=job.get('progress_message_id')
        job.update(progress_stage=stage,progress_text=text,progress_at=time.time())
        creating=not notice_id and not job.get('progress_started')
        if creating: job['progress_started']=True
        store.write(identifier,job,version)
        if job.get('progress_delivery_failed') and stage not in {'done','failed','uncertain'}: return
        payload={'chat_id':config['owner_id'],'text':text[:4000],
                 'reply_markup':json.dumps(keyboard or {'inline_keyboard':[]},ensure_ascii=False)}
        if notice_id:
            telegram(config,'editMessageText',{**payload,'message_id':notice_id})
        elif creating:
            sent=telegram(config,'sendMessage',{**payload,**reply_to(job.get('source_message_id'))})
            if isinstance(sent,dict) and isinstance(sent.get('message_id'),int):
                current,generation=store.read(identifier)
                current['progress_message_id']=sent['message_id']
                store.write(identifier,current,generation)
    except Exception:
        # A visual update must never cancel a CV or trigger another delivery.
        try:
            current,generation=store.read(identifier)
            if current:
                current['progress_delivery_failed']=True
                store.write(identifier,current,generation)
        except Exception: pass


def status_summary(config, store):
    uid=config.get('owner_uid','')
    queue_key='vacancy-queue' + ('-'+hashlib.sha256(uid.encode()).hexdigest() if uid else '')
    queue,_=store.read(queue_key)
    lines=[]
    for entry in (queue or {}).get('pending',[])[-10:]:
        job,_=store.read(entry['id'])
        if not job or job.get('owner_id', (job.get('message') or {}).get('from',{}).get('id'))!=config['owner_id'] or (job.get('owner_uid') and job['owner_uid']!=uid): continue
        label=job.get('selected_position') or job.get('position') or 'Anuncio '+entry['id']
        detail=job.get('progress_text') or {'queued':'⏳ En cola','processing':'🔄 Procesando','awaiting_selection':'👉 Esperando que elijas una vacante','done':'✅ Completado','failed':'❌ Detenido','delivery_started':'⚠️ Entrega pendiente de confirmación'}.get(job.get('state'),'Solicitud guardada')
        lines.append(label[:140]+':\n'+detail[:260])
    return ('📋 Estado de tus solicitudes\n\n'+'\n\n'.join(lines))[:4000] if lines else 'No hay solicitudes recientes en tu cola. Envía un anuncio para comenzar.'




def allowed_message(update, config):
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict) or not isinstance(update.get("update_id"), int):
        return None
    chat, sender = message.get("chat", {}), message.get("from", {})
    owner = config.get("owner_id")
    if not owner or chat.get("type") != "private" or chat.get("id") != owner or sender.get("id") != owner or sender.get("is_bot"):
        return None
    return message


def private_callback(update, config):
    query = update.get("callback_query") if isinstance(update, dict) else None
    if not isinstance(query, dict) or not isinstance(update.get("update_id"), int):
        return None
    sender, chat = query.get("from", {}), query.get("message", {}).get("chat", {})
    owner = config.get("owner_id")
    if not owner or sender.get("id") != owner or sender.get("is_bot") or chat.get("type") != "private" or chat.get("id") != owner:
        return None
    return query


def application_contacts(analysis):
    vacancy = analysis.get("vacancy", {}) if isinstance(analysis, dict) else {}
    emails = [value.strip() for value in vacancy.get("application_emails", [])
              if isinstance(value, str) and len(value) <= 254 and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value.strip())][:4]
    phones = []
    for value in vacancy.get("application_whatsapp", []):
        if not isinstance(value, str):
            continue
        number = re.sub(r"[^0-9]", "", value)
        if number.startswith("00"):
            number = number[2:]
        if len(number) == 10 and number.startswith(("809", "829", "849")):
            number = "1" + number
        if 8 <= len(number) <= 15 and not number.startswith("0") and number not in phones:
            phones.append(number)
    return {"emails": list(dict.fromkeys(emails)), "whatsapp": phones[:4]}


def application_message(position, name=''):
    return (f"Asunto: Postulación a {position}\n\nSaludos,\nMe interesa postularme a la vacante de {position}. "
            "Adjunto mi hoja de vida para su consideración. Quedo disponible para ampliar información y coordinar una entrevista.\n\n"
            "Atentamente,\n" + name)


def application_buttons(identifier, job):
    contacts = job.get("contacts", {})
    rows = []
    for phone in contacts.get("whatsapp", []):
        rows.append([{"text": "Preparar WhatsApp" + (f" · +{phone}" if len(contacts["whatsapp"]) > 1 else ""),
                      "url": "https://wa.me/" + phone + "?" + urlencode({"text": application_message(job["position"],job.get('candidate_name',''))})}])
    if not contacts.get("whatsapp"):
        rows.append([{"text": "WhatsApp · sin número en la vacante", "callback_data": "missing:phone"}])
    return {"inline_keyboard": rows}


def auto_send_application(core, config, identifier, store):
    job, _ = store.read(identifier)
    if not job or not job.get("contacts", {}).get("emails"):
        say(config, "No se envió por Gmail: la vacante no indica un correo de postulación.")
        return
    try:
        process_application(core, config, {"source_job": identifier, "recipient_index": 0}, store)
    except Exception as error:
        core.app.logger.warning("No se confirmó el envío automático de Telegram %s (%s)", identifier, type(error).__name__)
        detail = str(error)[:700] if isinstance(error, (runtime.JobError, core.AppError)) else "Revisa Enviados en Gmail antes de volver a postular."
        say(config, "El PDF está disponible. No pude confirmar el envío automático por Gmail: " + detail)


def process_application(core, config, action, store):
    source, generation = store.read(action["source_job"])
    index = action["recipient_index"]
    emails = (source or {}).get("contacts", {}).get("emails", [])
    if not source or source.get("owner_id") != config["owner_id"] or (source.get('owner_uid') and source['owner_uid'] != config.get('owner_uid')) or (source.get('binding_id') and source['binding_id'] != config.get('binding_id')) or source.get("state") != "done" or not isinstance(index, int) or index < 0 or index >= len(emails):
        raise runtime.JobError("Este CV ya no está disponible para envío desde el bot. Genera uno nuevo.")
    recipient = emails[index]
    dispatches = source.setdefault("gmail_dispatches", {})
    if recipient in dispatches:
        say(config, "Este envío ya está registrado: " + dispatches[recipient] + ". Revisa Enviados en Gmail antes de intentar otra postulación.")
        return
    token = drive_token(config)
    folder = core.verify_drive_access(token)
    file_id = source.get("drive_url", "").split("/file/d/")[-1].split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise runtime.JobError("No se pudo identificar el PDF guardado.")
    metadata = core.drive_request(f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=parents,mimeType&supportsAllDrives=true", token)
    if folder["id"] not in metadata.get("parents", []) or metadata.get("mimeType") != "application/pdf":
        raise runtime.JobError("El PDF no se encuentra en CV GENERADOS.")
    response = requests.get(f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true",
                            headers={"Authorization": "Bearer " + token}, timeout=35, stream=True)
    try:
        if not response.ok:
            raise runtime.JobError("No se pudo leer el PDF de Drive.")
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 15 * 1024 * 1024:
                raise runtime.JobError("El PDF es demasiado grande para enviarlo.")
    finally:
        response.close()
    sender = core.ARCHIVE_CONFIG["allowed_email"]
    identity = core.gmail_request("https://www.googleapis.com/oauth2/v3/userinfo", token)
    if identity.get("email_verified") is not True or identity.get("email", "").casefold() != sender.casefold():
        raise runtime.JobError("La autorización de Gmail no corresponde al propietario.")
    application_id = str(uuid5(NAMESPACE_URL, f"{runtime.PROJECT}:telegram:{action['source_job']}:{recipient}"))
    record = {"application_id": application_id, "position": source["position"], "recipient": recipient, "channel": "gmail",
              "status": "sending", "cv_url": source["drive_url"], "date": datetime.now(timezone.utc).isoformat(), "origin": "telegram"}
    # Reserve in GCS before any send: concurrent/repeated clicks cannot send twice.
    dispatches[recipient] = "en proceso o sin confirmar"
    store.write(action["source_job"], source, generation)
    try:
        core.save_application_record(record, token, folder)
        mail = EmailMessage()
        mail["From"], mail["To"] = sender, recipient
        mail["Subject"] = source["position"].replace("\r", " ").replace("\n", " ")
        mail["Message-ID"] = f"<{application_id}@cvalamedida.web.app>"
        mail.set_content(application_message(source["position"],source.get('candidate_name',config.get('owner_name',''))))
        mail.add_attachment(bytes(content), maintype="application", subtype="pdf", filename=source["filename"])
        result = core.gmail_request("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", token,
                                    json.dumps({"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode()}).encode())
        if not result.get("id"):
            raise runtime.JobError("Gmail no confirmó el envío. Revisa Enviados antes de reintentar.")
    except Exception:
        record["status"] = "send_unknown"
        try:
            core.save_application_record(record, token, folder)
        except Exception:
            pass
        raise
    current, version = store.read(action["source_job"])
    current["gmail_dispatches"][recipient] = "confirmado por Gmail"
    store.write(action["source_job"], current, version)
    record.update(status="gmail_accepted", gmail_message_id=result["id"])
    try:
        core.save_application_record(record, token, folder)
        history = "El historial está actualizado en la app web."
    except Exception:
        history = "No se pudo actualizar el historial. No vuelvas a enviar: comprueba Enviados."
    say(config, f"Gmail confirmó el envío a {recipient}.\nAsunto: {source['position']}\nPDF adjunto. {history}")




def vacancy_payload(message, config, max_bytes):
    payload = {"text": message.get("text") or message.get("caption") or ""}
    file = None
    if isinstance(message.get("document"), dict):
        file = message["document"]
        filename = PurePosixPath(file.get("file_name", "vacante.pdf")).name
        if PurePosixPath(filename).suffix.lower() not in {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}:
            raise runtime.JobError("Envía texto, una imagen, PDF o Word de la vacante.")
    elif message.get("photo"):
        file = max(message["photo"], key=lambda photo: photo.get("width", 0) * photo.get("height", 0))
        filename = "vacante.jpg"
    if file:
        if file.get("file_size", 0) > max_bytes:
            raise runtime.JobError("El archivo supera 10 MB. Envía una versión más pequeña.")
        info = telegram(config, "getFile", {"file_id": file["file_id"]})
        path = info.get("file_path", "")
        if not path or ".." in path.split("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
            raise runtime.JobError("Telegram no devolvió un archivo válido.")
        try:
            response = requests.get(f"https://api.telegram.org/file/bot{config['bot_token']}/{path}", timeout=35, stream=True)
            try:
                if not response.ok:
                    raise runtime.JobError("No se pudo descargar la vacante.")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise runtime.JobError("El archivo supera 10 MB. Envía una versión más pequeña.")
            finally:
                response.close()
        except runtime.JobError:
            raise
        except Exception:
            raise runtime.JobError("No se pudo descargar la vacante de Telegram.") from None
        payload.update(file_name=filename, file_data=base64.b64encode(content).decode())
    if not payload["text"].strip() and not file:
        raise runtime.JobError("Envía la vacante como texto, imagen, PDF o Word.")
    return payload


def drive_token(config):
    if config.get('_access_token') and config.get('_access_until',0)>time.time():
        return config['_access_token']
    if not config.get("drive_refresh_token") or not config.get("drive_connected"):
        raise runtime.JobError("Abre CV a la medida y pulsa Autorizar Drive para Telegram una vez antes de enviar vacantes.")
    response = requests.post("https://oauth2.googleapis.com/token", data={"client_id": config["client_id"],
        "client_secret": config["client_secret"], "refresh_token": config["drive_refresh_token"], "grant_type": "refresh_token"}, timeout=25)
    data = response.json()
    if not response.ok or not data.get("access_token"):
        raise runtime.JobError("La autorización de Drive venció o fue revocada. Vuelve a autorizar Drive para Telegram en la app.")
    return data["access_token"]


def archive_pdf(core, config, identifier, filename, content):
    token = drive_token(config)
    folder = core.verify_drive_access(token)
    query = f"'{folder['id']}' in parents and trashed=false and appProperties has {{ key='telegramUpdateId' and value='{identifier}' }}"
    existing = core.drive_request("https://www.googleapis.com/drive/v3/files?" + urlencode({"q": query, "fields": "files(id,webViewLink)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}), token)
    if existing.get("files"):
        file = existing["files"][0]
        return file.get("webViewLink") or f"https://drive.google.com/file/d/{file['id']}/view"
    metadata = json.dumps({"name": filename, "parents": [folder["id"]], "appProperties": {"telegramUpdateId": identifier}}).encode()
    boundary = "telegram_" + identifier
    body = f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode() + metadata
    body += f"\r\n--{boundary}\r\nContent-Type: application/pdf\r\n\r\n".encode() + content + f"\r\n--{boundary}--\r\n".encode()
    created = core.drive_request("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id&supportsAllDrives=true", token, body, f"multipart/related; boundary={boundary}")
    file_id = created.get("id", "")
    if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise runtime.JobError("Drive no confirmó el CV guardado.")
    saved = core.drive_request(f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,parents,webViewLink&supportsAllDrives=true", token)
    if folder["id"] not in saved.get("parents", []):
        raise runtime.JobError("No se pudo verificar el PDF en CV GENERADOS.")
    return saved.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"


def process_job(core, config, identifier, store):
    job,_=store.read(identifier)
    if not job or job.get('state') in {'done','failed','delivery_started','awaiting_selection','rejected'}: return
    if job.get('lease_until',0)>time.time(): raise runtime.JobError('La vacante sigue en proceso.')
    identity=None
    if job.get('owner_uid'):
        linked=accounts.account_binding(store,job['owner_uid'])
        if not linked or linked['telegram_id']!=job.get('owner_id') or linked['binding_id']!=job.get('binding_id'):
            current,version=store.read(identifier)
            current.update(state='failed',message=None,lease_until=0,error='La vinculación de Telegram cambió.')
            store.write(identifier,current,version)
            return
        identity=linked
    else:
        mapped,_=store.read(accounts.key('chat',config.get('owner_id',0)))
        if mapped:
            linked=accounts.binding(store,config.get('owner_id',0))
            if not linked or linked['email'].casefold()!=core.ORIGINAL_OWNER_EMAIL:
                current,version=store.read(identifier)
                current.update(state='failed',message=None,lease_until=0)
                store.write(identifier,current,version)
                return
            identity=linked
    if not identity: return _process_job(core,config,identifier,store)
    recipient_config=None
    try:
        recipient_config=accounts.runtime(core,config,identity,store)
        token=drive_token(recipient_config)
        recipient_config.update(_access_token=token,_access_until=time.time()+300)
        with user_accounts.scope(core,identity,{'X-Drive-Access-Token':token},store):
            return _process_job(core,recipient_config,identifier,store)
    except (runtime.JobError,core.AppError) as error:
        current,version=store.read(identifier)
        if current.get('state') not in {'done','delivery_started'}:
            current.update(state='failed',message=None,cached_input=None,lease_until=0,error=str(error))
            store.write(identifier,current,version)
            if recipient_config:
                progress(recipient_config,identifier,store,'failed','❌ Solicitud detenida\n'+str(error)[:900])
                try: say(recipient_config,'No pude completar tu solicitud: '+str(error)[:900])
                except runtime.JobError: pass

def _process_job(core, config, identifier, store):
    job, generation = store.read(identifier)
    if not job or job.get("state") in {"done", "failed", "delivery_started", "awaiting_selection", "rejected"}:
        return
    if job.get("lease_until", 0) > time.time():
        raise runtime.JobError("La vacante sigue en proceso.")
    job.update(state="processing", lease_until=time.time() + 330)
    source_message_id = job.get("source_message_id") or (job.get("message") or {}).get("message_id")
    store.write(identifier, job, generation)
    def checkpoint(**values):
        nonlocal job
        current, version = store.read(identifier)
        job = {**current, **values}
        store.write(identifier, job, version)
    try:
        if job.get("action"):
            if job.get("owner_id") != config["owner_id"]:
                raise runtime.JobError("Solicitud no autorizada.")
            progress(config,identifier,store,'gmail','📧 Solicitud recibida\nPreparando el PDF y el envío por Gmail…')
            process_application(core, config, job["action"], store)
            checkpoint(state="done", lease_until=0)
            progress(config,identifier,store,'done','✅ Solicitud de Gmail finalizada\nRevisa el mensaje de confirmación del bot.')
            return
        message = job["message"]
        if allowed_message({"update_id": int(identifier), "message": message}, config) is None:
            checkpoint(state="failed", message=None, lease_until=0)
            return
        command = (message.get("text") or "").split()[0].split("@")[0] if message.get("text") else ""
        if command in {"/start", "/help", "/ayuda", "/estado"}:
            ready = bool(config.get("drive_connected"))
            say(config, "Soy CV a la medida, tu asistente privado. Envía una vacante en texto, imagen, PDF o Word y te devolveré tu CV en PDF.\n\n" +
                ("Drive está conectado: guardaré una copia en CV GENERADOS." if ready else "Para activarlo, abre la app y pulsa Autorizar Drive para Telegram: " + ORIGIN) +
                "\nSolo tu cuenta puede utilizar este bot. Cada mensaje de vacante genera un CV; envía un archivo completo por mensaje.")
            checkpoint(state="done", message=None, lease_until=0)
            return
        if not job.get("pdf_ready"):
            drive_token(config)  # Fail early before spending an AI request.
            progress(config,identifier,store,'bank','✅ Anuncio recibido\n🔄 Revisando tu Banco de Datos…')
            status = core.load_drive_bank()
            if status.get("pending"):
                before = status['pending']
                progress(config,identifier,store,'bank_read',f'✅ Anuncio recibido\n🔄 Leyendo documentos del banco: {before} pendientes…')
                status = core.load_drive_bank(process=True)
                stalled = job.get('bank_stalled', 0) + 1 if status.get('pending', 0) >= before else 0
                if stalled >= 3:
                    raise runtime.JobError('No se pudo leer un archivo del banco tras varios intentos. Revisa su estado en la app.')
                if status.get('pending'):
                    step = job.get('bank_step', 0) + 1
                    checkpoint(state='queued', lease_until=0, bank_step=step, bank_stalled=stalled)
                    progress(config,identifier,store,'bank_wait',f'🔄 Banco en actualización\nQuedan {status["pending"]} archivos por leer. La solicitud continúa en el servidor.')
                    runtime.enqueue(identifier, config, task_identifier=f'{identifier}-bank-{step}')
                    return
            if job.get('cached_input'):
                cached=encrypted.unprotect(store,job['cached_input'],'telegram-input-'+identifier)
                text,images=cached['text'],cached['images']
                checkpoint(cached_input=None)
            else:
                progress(config,identifier,store,'reading','✅ Banco revisado\n📄 Cargando y leyendo el anuncio…')
                payload = vacancy_payload(message, config, core.MAX_FILE_BYTES)
                text, images = core.extract_vacancy(payload)
            selected=job.get('selected_position','')
            progress(config,identifier,store,'analyzing','✅ Anuncio cargado\n'+(f'✅ Vacante seleccionada: {selected[:140]}\n' if selected else '')+'🔎 Analizando requisitos y tu experiencia…')
            try:
                analysis = core.analyze_with_model(core.VERTEX_MODEL, text, images, job["selected_position"]) if job.get("selected_position") else core.analyze_with_model(core.VERTEX_MODEL, text, images)
            except core.VacancySelectionRequired as choice:
                checkpoint(state="awaiting_selection", positions=choice.positions, source_message_id=source_message_id, lease_until=0,
                           cached_input=encrypted.protect(store,{'text':text,'images':images},'telegram-input-'+identifier))
                buttons = {"inline_keyboard": [[{"text": position[:64], "callback_data": f"position:{identifier}:{index}"}] for index, position in enumerate(choice.positions)]}
                progress(config,identifier,store,'awaiting_selection','✅ Anuncio cargado\nEncontré varias vacantes. Selecciona el puesto al que quieres aplicar:',buttons)
                return
            progress(config,identifier,store,'building','✅ Análisis completado\n📝 Preparando tu CV y creando el PDF…')
            draft = core.make_draft(analysis)
            content = core.make_pdf(draft).getvalue()
            filename = re.sub(r"[^A-Za-z0-9_-]+", "_", f"CV_{draft['position']}").strip("_") + f"_{identifier}.pdf"
            store.put_pdf(identifier, content)
            checkpoint(pdf_ready=True, filename=filename, position=draft["position"],
                       contacts=application_contacts(analysis), owner_id=config["owner_id"], candidate_name=draft.get('candidate',{}).get('name',config.get('owner_name','')))
        content = store.pdf(identifier)
        if not job.get("drive_url"):
            progress(config,identifier,store,'saving','✅ PDF preparado\n☁️ Guardando una copia en tu carpeta CV Generados…')
            url = archive_pdf(core, config, identifier, job["filename"], content)
            checkpoint(drive_url=url)
        # Persist before sending. An interrupted send is never automatically repeated.
        checkpoint(state="delivery_started", message=None)
        progress(config,identifier,store,'sending','✅ CV guardado en Drive\n📤 Enviando el PDF a este chat…')
        delivered = telegram(config, "sendDocument", {"chat_id": config["owner_id"],
            **reply_to(source_message_id),
            "caption": f"CV para {job['position'][:180]}\nGuardado en CV GENERADOS:\n{job['drive_url']}\n\nGmail: enviaré automáticamente la postulación al primer correo de la vacante.\nWhatsApp: abre el mensaje; adjunta el PDF de este chat y pulsa Enviar.",
            "reply_markup": json.dumps(application_buttons(identifier, job), ensure_ascii=False)},
            files={"document": (job["filename"], content, "application/pdf")})
        checkpoint(state="done", telegram_message_id=delivered.get("message_id"), lease_until=0)
        auto_send_application(core, config, identifier, store)
        progress(config,identifier,store,'done',f'✅ Solicitud completada\nCV para {job["position"][:140]} guardado en Drive y entregado en este chat.')
        try: store.remove_pdf(identifier)
        except Exception: core.app.logger.warning('No se pudo limpiar el PDF temporal ya entregado: %s',identifier)
    except Exception as error:
        uncertain = job.get("state") == "delivery_started"
        failed_stage = store.read(identifier)[0].get("progress_stage", "processing")
        checkpoint(state="delivery_started" if uncertain else "failed", message=None, cached_input=None, lease_until=0,
                   failed_stage=failed_stage, error_type=type(error).__name__)
        detail = str(error) if isinstance(error, (runtime.JobError, core.AppError)) else f"No se pudo completar la etapa {failed_stage}. Referencia: {identifier}. Inténtalo de nuevo; si continúa, comparte esta referencia."
        progress(config,identifier,store,'uncertain' if uncertain else 'failed',('⚠️ El CV está guardado, pero la entrega en Telegram no pudo confirmarse.' if uncertain else '❌ Solicitud detenida\n'+detail[:900]))
        core.app.logger.warning("Telegram job %s failed (%s), stage=%s, frames=%s", identifier, type(error).__name__, failed_stage,
                                [(PurePosixPath(frame.filename.replace(chr(92), "/")).name, frame.name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)])
        try:
            say(config, ("El CV está en Drive, pero no pude confirmar su entrega en este chat. " + job.get("drive_url", "")) if uncertain else "No pude completar tu solicitud: " + detail[:900], source_message_id)
        except runtime.JobError:
            pass


def register_routes(app, core):
    def account_context(config, store):
        if os.environ.get('CV_MULTI_ACCOUNT') != '1': return config
        identity=user_accounts.CURRENT.get()
        if not identity: raise core.AppError('Inicia sesión para configurar Telegram.',401)
        accounts.legacy(core,config,identity,store)
        return accounts.runtime(core,config,identity,store)

    def browser_origin():
        if request.headers.get('Origin') not in ALLOWED_ORIGINS or request.headers.get('X-Requested-With')!='XmlHttpRequest':
            raise core.AppError('El origen de la vinculación no es válido.',403)

    @app.get("/api/telegram/status")
    def telegram_status():
        try:
            config = runtime.configuration()
        except Exception:
            return jsonify(configured=False, drive_connected=False, client_id="", message="Telegram aún no está configurado.")
        store=runtime.JobStore() if os.environ.get('CV_MULTI_ACCOUNT')=='1' else None
        config=account_context(config,store)
        configured = bool(config.get("bot_token"))
        username = config.get("bot_username", "")
        pending=accounts.pending_link(store,user_accounts.owner()) if store else None
        linked=bool(config.get('owner_id'))
        return jsonify(configured=configured, drive_connected=bool(config.get("drive_connected")),
            client_id=config.get("client_id", ""), bot_url=f"https://t.me/{username}" if configured and linked and re.fullmatch(r"[A-Za-z0-9_]+", username) else "",
            linked=linked, multi_account=os.environ.get('CV_MULTI_ACCOUNT')=='1',
            pending={field:pending.get(field,'') for field in ('telegram_id','telegram_name','telegram_username')} if pending and pending.get('telegram_id') else None,
            message="Tu Telegram está vinculado a esta cuenta." if linked else "Vincula tu Telegram y autoriza Drive para usar tu banco desde el bot.")

    @app.post('/api/telegram/link')
    def telegram_link():
        browser_origin()
        identity=user_accounts.CURRENT.get()
        if not identity: raise core.AppError('Inicia sesión para vincular Telegram.',401)
        config=runtime.configuration(); username=config.get('bot_username','')
        if not config.get('bot_token') or not re.fullmatch(r'[A-Za-z0-9_]+',username):
            raise core.AppError('El bot no está disponible.',503)
        token=accounts.create_link(core,identity,runtime.JobStore())
        return jsonify(bot_url=f'https://t.me/{username}?start={token}',expires_in=600)

    @app.post('/api/telegram/link/confirm')
    def telegram_link_confirm():
        browser_origin()
        identity=user_accounts.CURRENT.get()
        if not identity: raise core.AppError('Inicia sesión para confirmar Telegram.',401)
        accounts.confirm_link(core,identity,runtime.JobStore())
        return jsonify(message='Telegram vinculado a tu cuenta. Ya puedes autorizar su Drive.')

    @app.post('/api/telegram/disconnect')
    def telegram_disconnect():
        browser_origin()
        if not user_accounts.owner(): raise core.AppError('Inicia sesión para desvincular Telegram.',401)
        accounts.disconnect(runtime.JobStore(),user_accounts.owner())
        return jsonify(message='Telegram desvinculado. El bot ya no puede usar tu banco ni generar CV para esta vinculación.')

    @app.post("/api/telegram/drive/authorize")
    def telegram_drive_authorize():
        if request.headers.get("Origin") not in ALLOWED_ORIGINS or request.headers.get("X-Requested-With") != "XmlHttpRequest":
            raise core.AppError("El origen de la autorización no es válido.", 403)
        payload = request.get_json(silent=True) or {}
        code = payload.get("code")
        if not isinstance(code, str) or not code or len(code) > 4000:
            raise core.AppError("Google no devolvió un código de autorización válido.")
        store=runtime.JobStore() if os.environ.get('CV_MULTI_ACCOUNT')=='1' else None
        config = account_context(runtime.configuration(),store)
        response = requests.post("https://oauth2.googleapis.com/token", data={"client_id": config["client_id"],
            "client_secret": config["client_secret"], "code": code, "grant_type": "authorization_code", "redirect_uri": request.headers["Origin"]}, timeout=25)
        tokens = response.json()
        if not response.ok or not tokens.get("access_token"):
            raise core.AppError("Google no pudo autorizar el guardado automático. Vuelve a intentarlo.", 403)
        user = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": "Bearer " + tokens["access_token"]}, timeout=25)
        identity = user.json()
        if not user.ok or not identity.get("email_verified") or identity.get("email", "").casefold() != core.ARCHIVE_CONFIG["allowed_email"].casefold():
            raise core.AppError("Autoriza únicamente con el correo propietario del banco.", 403)
        scopes=set(tokens.get('scope','').split())
        required={'https://www.googleapis.com/auth/drive.file'}
        if store: required.add('https://www.googleapis.com/auth/drive.readonly')
        if not required.issubset(scopes) and 'https://www.googleapis.com/auth/drive' not in scopes:
            raise core.AppError("Falta el permiso de Drive solicitado.", 403)
        refresh = tokens.get("refresh_token") or config.get("drive_refresh_token")
        if not refresh:
            raise core.AppError("Google no devolvió la autorización permanente. Revoca el acceso de esta app en Google y vuelve a autorizar.", 403)
        if store: accounts.save_oauth(store,user_accounts.owner(),refresh)
        else:
            config.update(drive_refresh_token=refresh, drive_connected=False)
            runtime.save_configuration(config)
        result = jsonify(access_token=tokens['access_token'], expires_in=tokens.get('expires_in', 3600),
                         scope=tokens.get('scope', ''))
        result.headers['Cache-Control'] = 'no-store'
        return result

    @app.post('/api/telegram/drive/session')
    def telegram_drive_session():
        browser_origin()
        store=runtime.JobStore() if os.environ.get('CV_MULTI_ACCOUNT')=='1' else None
        config=account_context(runtime.configuration(),store)
        if not config.get('drive_connected') or not config.get('drive_refresh_token'):
            raise core.AppError('Autoriza Google una vez con Sincronizar todo.',409)
        response=requests.post('https://oauth2.googleapis.com/token',data={
            'client_id':config['client_id'],'client_secret':config['client_secret'],
            'refresh_token':config['drive_refresh_token'],'grant_type':'refresh_token'},timeout=25)
        tokens=response.json()
        if not response.ok or not tokens.get('access_token'):
            if tokens.get('error')=='invalid_grant':
                raise core.AppError('El permiso de Google fue revocado. Vuelve a autorizar con Sincronizar todo.',409)
            raise core.AppError('No se pudo renovar la conexion de Google. Intentalo de nuevo.',503)
        scopes=set(tokens.get('scope','').split())
        required={'https://www.googleapis.com/auth/drive.file'}
        if store: required.add('https://www.googleapis.com/auth/drive.readonly')
        if not required.issubset(scopes) and 'https://www.googleapis.com/auth/drive' not in scopes:
            raise core.AppError('Faltan permisos de Drive. Autoriza con Sincronizar todo.',409)
        identity=requests.get('https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization':'Bearer '+tokens['access_token']},timeout=25)
        account=identity.json()
        if not identity.ok or not account.get('email_verified') or account.get('email','').casefold()!=core.ARCHIVE_CONFIG['allowed_email'].casefold():
            raise core.AppError('La autorizacion no pertenece a esta cuenta.',403)
        result=jsonify(access_token=tokens['access_token'],expires_in=tokens.get('expires_in',3600),scope=tokens.get('scope',''))
        result.headers['Cache-Control']='no-store'
        return result

    @app.post("/api/telegram/drive/confirm")
    def telegram_drive_confirm():
        browser_origin()
        store=runtime.JobStore() if os.environ.get('CV_MULTI_ACCOUNT')=='1' else None
        config = account_context(runtime.configuration(),store)
        provisional = {**config, "drive_connected": True}
        core.verify_drive_access(drive_token(provisional))
        if store: accounts.save_oauth(store,user_accounts.owner(),config['drive_refresh_token'],True)
        else:
            config["drive_connected"] = True
            runtime.save_configuration(config)
        return jsonify(message="Guardado automático en Drive autorizado para tu bot privado.")

    @app.post("/telegram/webhook")
    def telegram_webhook():
        config = runtime.configuration()
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        expected = config.get("webhook_secret", "")
        if not expected or not hmac.compare_digest(supplied, expected) or not config.get("bot_token"):
            return jsonify(error="Unauthorized"), 403
        update = request.get_json(silent=True)
        store=runtime.JobStore()
        if os.environ.get('CV_MULTI_ACCOUNT')=='1':
            raw=(update or {}).get('message') or (update or {}).get('callback_query',{}).get('message',{})
            sender=(update or {}).get('message',{}).get('from',{}) or (update or {}).get('callback_query',{}).get('from',{})
            chat=raw.get('chat',{})
            telegram_id=sender.get('id')
            if not isinstance((update or {}).get('update_id'),int) or not isinstance(telegram_id,int) or telegram_id<=0 or sender.get('is_bot') or chat.get('type')!='private' or chat.get('id')!=telegram_id:
                return jsonify(ok=True)
            linked = accounts.binding(store, telegram_id)
            personal_config = {**config, 'owner_id': telegram_id}
            callback = (update or {}).get('callback_query', {})
            if str(callback.get('data', '')).startswith('unlink:'):
                try:
                    email = accounts.disconnect_chat(core, store, telegram_id, callback['data'])
                    acknowledge(personal_config, callback['id'], 'Telegram desvinculado')
                    say(personal_config, 'Desvinculado de ' + email + '.\nAbre ' + ORIGIN + ', inicia sesión con la cuenta correcta y pulsa Vincular mi Telegram y Drive. Luego vuelve a la app para confirmar.')
                except core.AppError as error:
                    acknowledge(personal_config, callback['id'], str(error))
                return jsonify(ok=True)
            def offer_disconnect(text):
                telegram(personal_config, 'sendMessage', {'chat_id': telegram_id, 'text': text,
                    'reply_markup': {'inline_keyboard': [[{'text': 'Desvincular', 'callback_data': accounts.disconnect_callback(linked)}]]}})
            command = (raw.get('text') or '').strip().split(' ')[0].lower().split('@')[0]
            if linked and command in {'/start', '/help', '/ayuda', '/estado', '/desvincular'} and not re.search(r'\s', (raw.get('text') or '').strip()):
                offer_disconnect('Tu Telegram está vinculado a ' + linked.get('email', '') + '.\nPuedes enviar una vacante para crear tu CV. Para usar otra cuenta, pulsa Desvincular y vincula la cuenta correcta desde la app.' +
                    ('\n\n' + status_summary(accounts.runtime(core, config, linked, store), store) if command == '/estado' else ''))
                return jsonify(ok=True)
            pairing=re.fullmatch(r'/start(?:@[A-Za-z0-9_]+)?\s+([A-Za-z0-9_-]{43})',(raw.get('text') or '').strip())
            if pairing:
                try:
                    accounts.stage_link(core,pairing[1],raw,store)
                    say({**config,'owner_id':telegram_id},'Vuelve a la app y confirma que esta es tu cuenta de Telegram. Hasta que confirmes, el bot no tendrá acceso a tu banco.',raw.get('message_id'))
                except core.AppError as error:
                    if linked:
                        offer_disconnect(str(error).replace('Desvincúlalo desde esa cuenta.', 'Pulsa Desvincular para cambiar de cuenta.'))
                    else:
                        say(personal_config,str(error),raw.get('message_id'))
                return jsonify(ok=True)
            linked=accounts.binding(store,telegram_id)
            mapped,_=store.read(accounts.key('chat',telegram_id))
            if linked:
                config=accounts.runtime(core,config,linked,store)
            elif telegram_id!=config.get('owner_id') or mapped:
                if (update or {}).get('callback_query'):
                    telegram(config,'answerCallbackQuery',{'callback_query_id':update['callback_query']['id'],'text':'Vincula tu cuenta desde la app antes de usar el bot.','show_alert':True})
                else:
                    say({**config,'owner_id':telegram_id},'Abre '+ORIGIN+', inicia sesión con Google y pulsa Vincular mi Telegram. Cada usuario trabaja con su propio banco.',raw.get('message_id'))
                return jsonify(ok=True)
        owner_fields={field:config[field] for field in ('owner_uid','owner_email','owner_name','binding_id') if config.get(field)}
        query = private_callback(update, config)
        if query:
            data = query.get("data", "")
            selection = re.fullmatch(r"position:([0-9]{1,20}):([0-9]{1,2})", data)
            if selection:
                source_id, index = selection[1], int(selection[2])
                store = runtime.JobStore()
                job, generation = store.read(source_id)
                callback_id = str(update["update_id"])
                positions = (job or {}).get("positions", [])
                if not job or job.get("owner_id", config["owner_id"]) != config["owner_id"] or (job.get('owner_uid') and job['owner_uid']!=config.get('owner_uid')) or (job.get('binding_id') and job['binding_id']!=config.get('binding_id')) or index >= len(positions):
                    telegram(config, "answerCallbackQuery", {"callback_query_id": query["id"], "text": "Esta selección ya no está disponible.", "show_alert": True})
                    return jsonify(ok=True)
                if job.get("state") == "awaiting_selection":
                    job.update(state="queued", selected_position=positions[index], selection_update_id=callback_id, lease_until=0)
                    try:
                        store.write(source_id, job, generation)
                    except PreconditionFailed:
                        return jsonify(error="Selection busy"), 503
                elif job.get("state") != "queued" or job.get("selection_update_id") != callback_id:
                    telegram(config, "answerCallbackQuery", {"callback_query_id": query["id"], "text": "Ya elegiste un puesto para este anuncio."})
                    return jsonify(ok=True)
                acknowledge(config,query['id'],'Vacante seleccionada: '+positions[index][:100])
                progress(config,source_id,store,'selected',f'✅ Vacante seleccionada: {positions[index][:140]}\n⏳ Solicitud guardada. Preparando tu CV…')
                runtime.enqueue(source_id, config, task_identifier=callback_id)
                return jsonify(ok=True)
            match = re.fullmatch(r"gmail:([0-9]{1,20}):([0-3])", data)
            if not match:
                telegram(config, "answerCallbackQuery", {"callback_query_id": query["id"], "text": "La vacante no incluye ese contacto.", "show_alert": True})
                return jsonify(ok=True)
            identifier = str(update["update_id"])
            store = runtime.JobStore()
            source,_=store.read(match[1])
            if not source or source.get('owner_id')!=config['owner_id'] or (source.get('owner_uid') and source['owner_uid']!=config.get('owner_uid')) or (source.get('binding_id') and source['binding_id']!=config.get('binding_id')):
                telegram(config,'answerCallbackQuery',{'callback_query_id':query['id'],'text':'Este CV pertenece a otra cuenta o vinculación.','show_alert':True})
                return jsonify(ok=True)
            job, generation = store.read(identifier)
            if job and job.get('state')!='queued':
                telegram(config,'answerCallbackQuery',{'callback_query_id':query['id'],'text':'Esta solicitud ya está registrada. Revisa su confirmación en el chat.'})
                return jsonify(ok=True)
            if not job:
                try:
                    store.write(identifier, {"state": "queued", "owner_id": config["owner_id"], **owner_fields,
                        "action": {"channel": "gmail", "source_job": match[1], "recipient_index": int(match[2])}, "created_at": time.time()}, 0)
                except PreconditionFailed:
                    pass
            acknowledge(config,query['id'],'Preparando envío por Gmail…')
            progress(config,identifier,store,'received','📧 Envío solicitado\n⏳ Solicitud guardada. Preparando la postulación…')
            if not job or job.get("state") == "queued":
                runtime.enqueue(identifier, config)
            return jsonify(ok=True)
        message = allowed_message(update, config)
        if message is None:
            return jsonify(ok=True)
        identifier = str(update["update_id"])
        store = runtime.JobStore()
        job, generation = store.read(identifier)
        if not job:
            command = (message.get("text") or "").strip().split(" ")[0].lower()
            if command.split('@')[0]=='/estado':
                say(config,status_summary(config,store),message.get('message_id'))
                store.write(identifier,{'state':'done','owner_id':config['owner_id'],**owner_fields,'created_at':time.time()},0)
                return jsonify(ok=True)
            admitted=True if command in {"/start", "/help", "/ayuda", "/estado"} else (store.admit(identifier,config['owner_uid']) if config.get('owner_uid') else store.admit(identifier))
            if not admitted:
                try:
                    store.write(identifier, {"state": "rejected", "created_at": time.time()}, 0)
                except PreconditionFailed:
                    return jsonify(ok=True)
                say(config, "Ya hay 10 vacantes pendientes. Espera a que termine alguna y vuelve a enviar esta vacante.", message.get("message_id"))
                return jsonify(ok=True)
            try:
                store.write(identifier, {"state": "queued", "message": message, "source_message_id": message.get("message_id"), "created_at": time.time(), 'owner_id':config['owner_id'], **owner_fields}, 0)
            except PreconditionFailed:
                pass
        elif job.get("state") != "queued":
            return jsonify(ok=True)
        if (message.get('text') or '').strip().split(' ')[0].lower() not in {'/start','/help','/ayuda','/estado'}:
            progress(config,identifier,store,'received','✅ Anuncio recibido\n⏳ Solicitud guardada en la cola. Te informaré aquí de cada etapa; puedes salir de la app.')
        runtime.enqueue(identifier, config)
        return jsonify(ok=True)

    @app.post("/telegram/work")
    def telegram_work():
        config = runtime.configuration()
        if not hmac.compare_digest(request.headers.get("X-CV-Telegram-Worker", ""), runtime.task_secret(config)):
            return jsonify(error="Unauthorized"), 403
        payload = request.get_json(silent=True) or {}
        identifier = payload.get("update_id")
        if payload.get("kind") == "web_analysis":
            import analysis_jobs
            if not analysis_jobs.valid_id(identifier):
                return jsonify(error="Invalid job"), 400
            try:
                store = runtime.JobStore()
                job, _ = store.read(identifier)
                if job and job.get("operation"):
                    import background_jobs
                    background_jobs.process_job(core, identifier, store)
                else:
                    analysis_jobs.process_job(core, identifier, store)
            except (PreconditionFailed, runtime.JobError):
                return jsonify(error="Job busy"), 503
            return jsonify(ok=True)
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9]{1,20}", identifier):
            return jsonify(error="Invalid update"), 400
        try:
            process_job(core, config, identifier, runtime.JobStore())
        except (PreconditionFailed, runtime.JobError):
            return jsonify(error="Job busy"), 503
        return jsonify(ok=True)
