"""HTTP routes; business operations are provided by the explicit core dependency."""
from __future__ import annotations
from typing import Any
import job_runtime
import onboarding


def register_routes(core):
    @core.app.get("/api/bank/status")
    def bank_status() -> Any:
        if not core.bank_enabled():
            raise core.AppError("El banco de Drive no está activado en este servidor.", 404)
        return core.jsonify(core.load_drive_bank())

    core.bank_status = bank_status

    @core.app.post("/api/bank/sync")
    def sync_bank() -> Any:
        if not core.bank_enabled():
            raise core.AppError("El banco de Drive no está activado en este servidor.", 404)
        return core.jsonify(core.load_drive_bank(process=True))

    core.sync_bank = sync_bank

    @core.app.get('/api/account')
    def account_status():
        if not core.user_accounts.CURRENT.get(): raise core.AppError('Inicia sesión para consultar tu cuenta.', 401)
        return core.jsonify(core.user_accounts.public(core.user_accounts.CURRENT.get()['record']))

    core.account_status = account_status

    @core.app.post('/api/account/setup')
    def setup_account():
        if not core.user_accounts.CURRENT.get(): raise core.AppError('Inicia sesión para preparar tu cuenta.', 401)
        identity = core.user_accounts.CURRENT.get()
        selection = core.request.get_json(silent=True) or {}
        if set(selection) - {'bank_id', 'archive_id'}: raise core.AppError('Selección de carpetas inválida.')
        record = core.user_accounts.prepare(core, identity, core.request.headers.get('X-Drive-Access-Token', ''), selection or None)
        return core.jsonify(core.user_accounts.public(record))

    core.setup_account = setup_account

    @core.app.get('/api/account/onboarding')
    def onboarding_status():
        identity=core.user_accounts.CURRENT.get()
        if not identity: raise core.AppError('Inicia sesi\u00f3n para consultar tu banco.',401)
        if identity.get('record') and core.account_state.BANK_CLIENT is None:
            return core.jsonify(needed=False,drive_required=True)
        return core.jsonify(onboarding.status(core,job_runtime.JobStore()))

    core.onboarding_status = onboarding_status

    @core.app.post('/api/account/onboarding/dismiss')
    def dismiss_onboarding():
        identity=core.user_accounts.CURRENT.get()
        if not identity: raise core.AppError('Inicia sesi\u00f3n para continuar.',401)
        store=job_runtime.JobStore(); key=onboarding.marker(identity['uid'])
        current,generation=store.read(key)
        store.write(key,{'completed':True},generation)
        return core.jsonify(completed=True)

    core.dismiss_onboarding = dismiss_onboarding

    @core.app.post('/api/account/onboarding/import')
    def import_onboarding_reference():
        if not core.user_accounts.CURRENT.get():
            raise core.AppError('Inicia sesión para leer tu hoja de vida.', 401)
        return core.jsonify(onboarding.import_reference(core, core.request.files.get('reference_cv')))

    @core.app.post('/api/account/onboarding')
    def save_onboarding():
        if not core.user_accounts.CURRENT.get(): raise core.AppError('Inicia sesi\u00f3n para guardar tu informaci\u00f3n.',401)
        try: payload=core.json.loads(core.request.form.get('data','{}'))
        except (ValueError,TypeError) as error: raise core.AppError('El formulario no es valido.') from error
        return core.jsonify(onboarding.save(core,payload,core.request.files.get('photo'),job_runtime.JobStore(),reference=core.request.files.get('reference_cv')))

    core.save_onboarding = save_onboarding

    @core.app.get("/api/profile-summary")
    def profile_summary() -> Any:
        return core.jsonify(
            {
                "experiences": [
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "employer": item["employer"],
                        "responsibilities": item["responsibilities"],
                    }
                    for item in core.account_state.MASTER_PROFILE["experiences"]
                ],
                "skills": core.account_state.MASTER_PROFILE["skills"],
            }
        )

    core.profile_summary = profile_summary

    @core.app.get("/api/knowledge-map")
    def get_knowledge_map() -> Any:
        core.require_local_knowledge_map()
        return core.jsonify(core.load_knowledge_map())

    core.get_knowledge_map = get_knowledge_map

    @core.app.post("/api/knowledge-map/documents")
    def process_knowledge_documents() -> Any:
        core.require_local_knowledge_map()
        files = core.request.files.getlist("files")
        if not files:
            raise core.AppError("Selecciona al menos un documento histórico.")
        if len(files) > core.MAX_KNOWLEDGE_FILES:
            raise core.AppError(
                f"Puedes procesar hasta {core.MAX_KNOWLEDGE_FILES} documentos por carga."
            )
        modified_times_payload = core.request.form.get("modifiedTimes", "[]")
        try:
            modified_times = core.json.loads(modified_times_payload)
        except core.json.JSONDecodeError as error:
            raise core.AppError("Los metadatos de los documentos no son válidos.") from error
        if not isinstance(modified_times, list) or len(modified_times) != len(files):
            raise core.AppError("Faltan metadatos de modificación para los documentos.")

        results: list[dict[str, Any]] = []
        for index, uploaded_file in enumerate(files):
            filename = (uploaded_file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            if not filename or len(filename) > 240 or "\x00" in filename:
                results.append(
                    {"fileName": filename or "archivo sin nombre", "status": "error",
                     "error": "El nombre del archivo no es válido."}
                )
                continue
            modified_time = modified_times[index]
            if modified_time is not None and (
                not isinstance(modified_time, str) or len(modified_time) > 80
            ):
                results.append(
                    {
                        "fileName": filename,
                        "status": "error",
                        "error": "La fecha de modificación del archivo no es válida.",
                    }
                )
                continue
            if modified_time is not None:
                try:
                    parsed_modified_time = core.datetime.fromisoformat(
                        modified_time.replace("Z", "+00:00")
                    )
                except ValueError:
                    parsed_modified_time = None
                if (
                    parsed_modified_time is None
                    or parsed_modified_time.tzinfo is None
                ):
                    results.append(
                        {
                            "fileName": filename,
                            "status": "error",
                            "error": "La fecha de modificación no tiene un formato ISO válido.",
                        }
                    )
                    continue
            raw = uploaded_file.read(core.MAX_FILE_BYTES + 1)
            if len(raw) > core.MAX_FILE_BYTES:
                results.append(
                    {
                        "fileName": filename,
                        "status": "error",
                        "error": "El documento supera el límite de 10 MB.",
                    }
                )
                continue
            file_id = f"local:{filename.casefold()}"
            try:
                result = core.update_knowledge_map_from_document(
                    file_id,
                    filename,
                    modified_time,
                    raw,
                    core._document_hash(raw),
                )
                results.append(
                    {
                        "fileId": file_id,
                        "fileName": filename,
                        "status": result["status"],
                        "lastProcessedAt": result["document"]["lastProcessedAt"],
                        "revisionCount": result["document"]["revisionCount"],
                        "evidenceCount": len(result["document"]["evidenceIds"]),
                    }
                )
            except core.AppError as error:
                results.append(
                    {"fileName": filename, "status": "error", "error": str(error)}
                )
        if all(item["status"] == "error" for item in results):
            raise core.AppError(
                "No se pudo procesar ningún documento: "
                + " ".join(item["error"] for item in results),
            )
        return core.jsonify(
            {
                "results": results,
                "knowledge_map": core.load_knowledge_map(),
                "message": "Los documentos se registraron como evidencia pendiente; "
                "no se modificó el banco maestro.",
            }
        )

    core.process_knowledge_documents = process_knowledge_documents

    @core.app.get("/api/profile")
    def get_profile() -> Any:
        return core.jsonify(core.account_state.MASTER_PROFILE)

    core.get_profile = get_profile

    @core.app.post("/api/profile/information")
    def add_profile_information():
        section, record = core.new_information_record(core.request.get_json(silent=True))
        with core.NEW_INFORMATION_LOCK:
            if core.bank_enabled():
                from drive_bank import BankError
                try:
                    core.load_drive_bank()
                    saved_id=core.account_state.BANK_CLIENT.add_record(section, record, core.validate_profile) or record["id"]
                    core.load_drive_bank(force=True)
                    if not any(item.get('id') == saved_id for item in core.account_state.MASTER_PROFILE[section]):
                        raise core.AppError('El registro se guardó pero no está disponible en el perfil. Revisa si fue eliminado anteriormente.', 409)
                except BankError as error:
                    raise core.AppError(str(error), error.status_code) from error
            else:
                if core.os.environ.get("CV_ALLOW_REMOTE") == "1":
                    raise core.AppError("El banco de Drive no está configurado.", 503)
                profile = core.json.loads(core.PROFILE_PATH.read_text(encoding="utf-8"))
                from profile_records import consolidate, add_information
                profile=consolidate(profile)
                try: saved_id=add_information(profile,section,record)
                except ValueError as error: raise core.AppError(str(error),409) from error
                core.validate_profile(profile)
                core.save_master_profile(profile)
                core.account_state.MASTER_PROFILE = profile
                core.refresh_profile_indexes()
        return core.jsonify({"message": "Información guardada en tu banco. Ya está disponible para generar CV.", "record_id": saved_id, "profile": core.account_state.MASTER_PROFILE})

    core.add_profile_information = add_profile_information

    @core.app.post('/api/profile/delete')
    def delete_profile_record():
        from profile_deletions import deletion_for, apply_deletions
        from drive_bank import BankError
        payload = core.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError('Selecciona el registro que deseas eliminar.')
        with core.NEW_INFORMATION_LOCK:
            try:
                if core.bank_enabled():
                    core.load_drive_bank()
                elif core.os.environ.get('CV_ALLOW_REMOTE') == '1':
                    raise core.AppError('El banco de Drive no está configurado.', 503)
                selector = deletion_for(core.account_state.MASTER_PROFILE, payload.get('path'), payload.get('expected'))
                if core.bank_enabled():
                    core.account_state.BANK_CLIENT.delete_record(selector)
                    core.load_drive_bank(force=True)
                else:
                    profile = core.json.loads(core.PROFILE_PATH.read_text(encoding='utf-8'))
                    profile.setdefault('_deleted_records', []).append(selector)
                    profile = apply_deletions(profile)
                    core.validate_profile(profile)
                    core.save_master_profile(profile)
                    core.account_state.MASTER_PROFILE = profile
                    core.refresh_profile_indexes()
            except ValueError as error:
                raise core.AppError(str(error), 409) from error
            except BankError as error:
                raise core.AppError(str(error), error.status_code) from error
        return core.jsonify({'profile': core.account_state.MASTER_PROFILE, 'message': 'Registro eliminado. No se incluirá en los próximos CV.'})

    core.delete_profile_record = delete_profile_record

    @core.app.put("/api/profile")
    def update_profile() -> Any:
        if core.bank_enabled():
            from drive_bank import BankError
            payload=core.request.get_json(silent=True)
            if not isinstance(payload,dict) or not isinstance(payload.get('profile'),dict) or not isinstance(payload.get('expected_profile'),dict):
                raise core.AppError('Envía el perfil y su versión original.',400)
            with core.NEW_INFORMATION_LOCK:
                core.load_drive_bank(force=True)
                if payload['expected_profile']!=core.account_state.MASTER_PROFILE:
                    raise core.AppError('El banco cambió. Sincroniza antes de guardar para conservar los cambios.',409)
                updated=core.validate_profile(payload['profile'])
                if any(updated.get(key)!=payload['expected_profile'].get(key) for key in set(updated)|set(payload['expected_profile']) if key.startswith('_')):
                    raise core.AppError('Los metadatos del banco no se pueden editar.',400)
                if updated['candidate'].get('photo')!=core.account_state.MASTER_PROFILE['candidate'].get('photo'):
                    raise core.AppError('La fotografía se actualiza desde el banco de documentos.',400)
                try:
                    core.account_state.BANK_CLIENT.edit_profile(core.account_state.MASTER_PROFILE,updated,core.validate_profile)
                    core.load_drive_bank(force=True)
                except BankError as error: raise core.AppError(str(error),error.status_code) from error
            return core.jsonify(profile=core.account_state.MASTER_PROFILE,message='Cambios guardados y verificados en tu banco.')
        if (
            core.bank_enabled()
            or core.os.environ.get("CV_ALLOW_REMOTE") == "1"
            or core.os.environ.get("CV_AUTH_REQUIRED") == "1"
        ):
            raise core.AppError(
                "La edición del banco solo está disponible en la aplicación local.",
                403,
            )
        payload = core.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise core.AppError("El banco enviado no tiene un formato JSON válido.")
        profile = core.validate_profile(payload)
        core.save_master_profile(profile)
        core.account_state.MASTER_PROFILE = profile
        core.refresh_profile_indexes()
        return core.jsonify({"profile": core.account_state.MASTER_PROFILE, "message": "Banco guardado."})

    core.update_profile = update_profile

    @core.app.get("/api/profile-photo")
    def profile_photo() -> Any:
        photo_path = core.current_photo_path()
        if not photo_path.is_file():
            raise core.AppError("No se encontró la fotografía del perfil.", 404)
        return core.send_file(photo_path, mimetype="image/jpeg", conditional=True)

    core.profile_photo = profile_photo
