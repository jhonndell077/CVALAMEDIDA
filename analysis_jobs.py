"""Durable web analysis, dispatched through the existing private worker."""
import re
import time
import uuid
from flask import jsonify, request
import job_runtime as bot
import user_accounts


def valid_id(identifier):
    return isinstance(identifier, str) and bool(re.fullmatch(r"web-[0-9a-f-]{36}", identifier))


def process_job(core, identifier, store):
    job, generation = store.read(identifier)
    if not job or job.get("state") in {"done", "failed"}:
        return
    if job.get("lease_until", 0) > time.time():
        raise bot.JobError("Job busy")
    job.update(state="processing", lease_until=time.time() + 300)
    store.write(identifier, job, generation)
    try:
        bank = core.load_drive_bank()
        if bank.get("pending"):
            raise core.AppError("Sincroniza los documentos pendientes del banco antes de analizar la vacante.", 409)
        payload = job["payload"]
        text, images = core.extract_vacancy(payload)
        model = core.require_model(payload.get("model"))
        selected = payload.get("selected_position")
        try:
            analysis = core.analyze_with_model(model, text, images, selected) if selected else core.analyze_with_model(model, text, images)
            result = {"analysis": analysis, "model": model}
        except core.VacancySelectionRequired as choice:
            result = {"selection_required": True, "positions": choice.positions, "model": model}
        job.update(state="done", result=result)
    except core.AppError as error:
        job.update(state="failed", error=str(error))
    job.pop("payload", None)
    job["lease_until"] = 0
    _, generation = store.read(identifier)
    store.write(identifier, job, generation)


def register_routes(app, core):
    @app.post("/api/analyze/jobs")
    def submit():
        if user_accounts.CURRENT.get():
            raise core.AppError('Utiliza la versión actual de la app para iniciar un análisis por cuenta.', 410)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError("La solicitud no tiene un formato JSON válido.")
        selected = payload.get("selected_position")
        if selected is not None and (not isinstance(selected, str) or not selected.strip() or len(selected) > 140):
            raise core.AppError("El puesto elegido no es válido.")
        request_id = payload.pop("request_id", None)
        try:
            identifier = "web-" + str(uuid.UUID(request_id)) if request_id else "web-" + str(uuid.uuid4())
        except (ValueError, TypeError, AttributeError):
            raise core.AppError("El identificador de la solicitud no es válido.") from None
        store = bot.JobStore()
        job, generation = store.read(identifier)
        if not job:
            store.write(identifier, {"state": "queued", "created_at": time.time(), "payload": payload}, generation)
        if not job or job.get("state") == "queued":
            bot.enqueue(identifier, bot.configuration(), kind="web_analysis")
        return jsonify(job_id=identifier)

    @app.post("/api/analyze/jobs/<identifier>")
    def status(identifier):
        if not valid_id(identifier):
            raise core.AppError("El análisis no existe.", 404)
        job, _ = bot.JobStore().read(identifier)
        if not job:
            raise core.AppError("El análisis no existe.", 404)
        user_accounts.require_owner(core, job)
        return jsonify({key: job[key] for key in ("state", "result", "error") if key in job})
