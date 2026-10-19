"""Optional initial CV collection. Drive files remain the source of truth."""
import io
import json
import hashlib
import time
import uuid
from contextlib import contextmanager
from google.api_core.exceptions import PreconditionFailed
from urllib.parse import quote
from PIL import Image, ImageOps, UnidentifiedImageError
import user_accounts as users

FIELDS = {"education": ("Estudios", "Formacion academica - formulario.txt", "FORMACION ACADEMICA"),
          "courses": ("Estudios", "Cursos realizados - formulario.txt", "CURSOS REALIZADOS"),
          "experiences": ("Informacion Laboral", "Experiencias laborales - formulario.txt", "EXPERIENCIAS LABORALES"),
          "projects": ("Conocimiento o aprendizaje", "Proyectos - formulario.txt", "PROYECTOS Y EXPERIENCIA PRACTICA"),
          "references": ("Referencias", "Referencias personales - formulario.txt", "REFERENCIAS PERSONALES")}
PERSONAL = {"name", "address", "phones", "national_id", "email"}

RECORD_FIELDS = {
    'education': {'title', 'institution', 'date'},
    'courses': {'title', 'institution', 'date'},
    'experiences': {'title', 'employer', 'category', 'start_date', 'end_date', 'responsibilities'},
    'projects': {'title', 'description', 'url', 'technologies'},
    'references': {'name', 'role', 'phone'},
}


def structured_values(core, key, values):
    if len(values) > (10 if key == 'phones' else 40):
        raise core.AppError('Hay demasiados registros en una sección.')
    result = []
    for value in values:
        if key in {'phones', 'skills', 'responsibilities', 'technologies'}:
            limit = {'phones': 100, 'skills': 300, 'responsibilities': 1500, 'technologies': 200}[key]
            if not isinstance(value, str) or len(value) > limit or '\n' in value or '\r' in value:
                raise core.AppError('Escribe cada dato en un campo separado, usando el botón Añadir.')
            if value.strip(): result.append(value.strip())
            continue
        if key not in RECORD_FIELDS or not isinstance(value, dict) or set(value) - RECORD_FIELDS[key]:
            raise core.AppError('El registro no tiene un formato válido.')
        record = {}
        for field, item in value.items():
            if field in {'responsibilities', 'technologies'}:
                if not isinstance(item, list): raise core.AppError('Añade cada función o herramienta por separado.')
                record[field] = structured_values(core, field, item)
            else:
                limit = 2000 if field == 'description' else 1000 if field == 'url' else 200
                if not isinstance(item, str) or len(item) > limit or (field != 'description' and ('\n' in item or '\r' in item)):
                    raise core.AppError('Revisa el formato y la longitud de los campos.')
                record[field] = item.strip()
        if not any(record.values()): continue
        required = ('name', 'role', 'phone') if key == 'references' else ('title', 'description') if key == 'projects' else ('title',)
        if any(not record.get(field) for field in required):
            raise core.AppError('Completa los campos obligatorios del registro o quítalo.')
        result.append(record)
    return result

def marker(uid): return "onboarding-" + hashlib.sha256(uid.encode()).hexdigest()

def status(core, store):
    identity=users.CURRENT.get()
    record=identity.get("record")
    completed,_=store.read(marker(identity["uid"]));completed=completed or {}
    if not record: return {"needed": not completed.get("completed",False), "drive_required": True}
    bank=core.load_drive_bank()
    profile=core.MASTER_PROFILE
    evidence=any(profile.get(key) for key in ("experiences","education","courses","projects","references","skills"))
    personal=profile.get("candidate",{})
    evidence=evidence or any(personal.get(key) for key in ("address","national_id","phones")) or bool(bank.get("photo"))
    return {"needed":not evidence and not completed.get("completed") and not bank.get("pending"),
            "pending":bank.get("pending",0),"drive_required":False}

def put(core, token, folder, name, mime, raw):
    item=users.existing(core,token,name,folder)
    if item:
        url = "https://www.googleapis.com/upload/drive/v3/files/"+quote(item["id"],safe="")+"?uploadType=media&fields=id"
        response=users.requests.patch(url,
            headers={"Authorization":"Bearer "+token,"Content-Type":mime},data=raw,timeout=45)
        if not response.ok:
            from drive_error_details import classify
            code, message = classify(url, response.status_code, response.content[:16384])
            error = core.AppError(message, 401 if response.status_code == 401 else 403 if response.status_code in {403, 404} else 502)
            error.code = code
            raise error
        return response.json()["id"]
    boundary="cv-form-"+hashlib.sha256(name.encode()).hexdigest()[:16]
    metadata=json.dumps({"name":name,"mimeType":mime,"parents":[folder]}).encode()
    body=(f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()+metadata+
          f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()+raw+f"\r\n--{boundary}--\r\n".encode())
    return core.drive_request("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",token,body,
                              "multipart/related; boundary="+boundary)["id"]

def reference_file(core, reference):
    from pathlib import Path
    name = (reference.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    suffix = Path(name).suffix.lower()
    types = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    if suffix not in types:
        raise core.AppError('Selecciona tu hoja de vida en PDF o Word (.docx).', 422)
    raw = reference.read(10*1024*1024+1)
    if not raw or len(raw)>10*1024*1024:
        raise core.AppError('La hoja de vida debe contener datos y pesar como maximo 10 MB.', 422)
    try:
        if suffix == '.pdf':
            import pymupdf
            with pymupdf.open(stream=raw, filetype='pdf') as document:
                if document.needs_pass or document.page_count == 0:
                    raise ValueError('PDF protegido o vacio')
        else:
            from docx import Document
            Document(io.BytesIO(raw))
    except Exception as error:
        raise core.AppError('No se pudo leer la hoja de vida. Usa un PDF sin contrasena o un Word valido.', 422) from error
    # Preserve distinct source documents; retries of the same upload are idempotent.
    filename = 'CV de referencia - ' + hashlib.sha256(raw).hexdigest()[:16] + suffix
    return ('Informacion personal', filename, types[suffix], raw)


def collect(core, payload, photo=None, reference=None):
    if not isinstance(payload,dict) or set(payload)-PERSONAL-set(FIELDS)-{"skills"}:
        raise core.AppError("El formulario no tiene un formato valido.")
    values={}
    for key,value in payload.items():
        if isinstance(value, list) and key in set(FIELDS) | {'phones', 'skills'}:
            values[key] = structured_values(core, key, value)
            continue
        limit=500 if key in PERSONAL else 12000
        if not isinstance(value,str) or len(value)>limit: raise core.AppError("Revisa la longitud y el formato del formulario.")
        values[key]=value.strip()
    candidate={key:values[key] for key in PERSONAL-{"phones"} if values.get(key)}
    if values.get("phones"):
        candidate['phones'] = values['phones'] if isinstance(values['phones'], list) else [v.strip() for v in values["phones"].replace(";", "\n").splitlines() if v.strip()][:10]
    files=[]
    if candidate:
        files.append(("Informacion personal","Datos personales - formulario.json","application/json",
                      json.dumps({"cv_bank_form":1,"candidate":candidate},ensure_ascii=False).encode()))
    for key,(folder,name,title) in FIELDS.items():
        if isinstance(values.get(key), list):
            if values[key]: files.append((folder,name.replace('.txt', '.json'), 'application/json', json.dumps({'cv_bank_form': 1, key: values[key]}, ensure_ascii=False).encode()))
        elif values.get(key): files.append((folder,name,"text/plain",(title+"\n\n"+values[key]).encode()))
    if values.get("skills"):
        skills=values['skills'] if isinstance(values['skills'], list) else [v.strip() for v in values["skills"].replace(",", "\n").splitlines() if v.strip()]
        files.append(("Conocimiento o aprendizaje","Habilidades - formulario.json","application/json",
                      json.dumps({"cv_bank_form":1,"skills":skills},ensure_ascii=False).encode()))
    if photo:
        raw=photo.read(8*1024*1024+1)
        if len(raw)>8*1024*1024: raise core.AppError("La foto debe pesar como maximo 8 MB.",422)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height>20_000_000: raise core.AppError("Reduce la resolucion de la fotografia.",422)
                image=ImageOps.exif_transpose(image).convert("RGB");image.thumbnail((1200,1600))
                output=io.BytesIO();image.save(output,format="JPEG",quality=90)
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError) as error:
            raise core.AppError("Selecciona una fotografia valida en JPG, PNG o WebP.",422) from error
        files.append(("Informacion personal","hoja_de_vida.jpeg","image/jpeg",output.getvalue()))
    if reference:
        files.append(reference_file(core, reference))
    return files

@contextmanager
def save_lease(core, store, uid):
    """Serialize folder setup and form writes for one verified account."""
    key = 'setup-' + users.account_key(uid)
    holder = uuid.uuid4().hex
    for attempt in range(11):
        lease, generation = store.read(key)
        if lease and lease.get('expires_at', 0) > time.time():
            if attempt == 10:
                raise users._setup_busy(core)
            time.sleep(.05)
            continue
        try:
            store.write(key, {'holder': holder, 'expires_at': time.time() + 180}, generation)
            break
        except PreconditionFailed:
            if attempt == 10:
                raise users._setup_busy(core) from None

    def renew():
        lease, generation = store.read(key)
        if not lease or lease.get('holder') != holder or lease.get('expires_at', 0) <= time.time():
            raise core.AppError('La reserva de guardado venció. Tus datos siguen en el formulario; vuelve a guardar.', 409)
        try:
            store.write(key, {**lease, 'expires_at': time.time() + 180}, generation)
        except PreconditionFailed:
            raise core.AppError('El banco cambió en otra sesión. Tus datos siguen en el formulario; vuelve a guardar.', 409) from None

    try:
        yield renew
    finally:
        try:
            lease, generation = store.read(key)
            if lease and lease.get('holder') == holder:
                store.write(key, {**lease, 'expires_at': 0}, generation)
        except Exception:
            core.app.logger.warning('La reserva de guardado se liberará al vencer.')


def mark_completed(core, store, uid):
    # A concurrent/legacy completion is already success, not a failed save.
    for attempt in range(3):
        current, generation = store.read(marker(uid))
        if current and current.get('completed') is True:
            return
        try:
            store.write(marker(uid), {**(current or {}), 'completed': True}, generation)
            return
        except PreconditionFailed:
            if attempt == 2:
                latest, _ = store.read(marker(uid))
                if latest and latest.get('completed') is True:
                    return
                raise core.AppError('Los archivos se guardaron. Vuelve a guardar para confirmar la consolidación.', 409) from None


def save(core, payload, photo, store, reference=None):
    identity=users.CURRENT.get();record=identity.get("record") or {}
    if not record.get("bank") or not record.get("sections"):
        raise core.AppError("Conecta Drive para preparar las carpetas de tu cuenta.",409)
    token=identity.get("drive_token","");users.assert_drive_identity(core,token,identity)
    files=collect(core,payload,photo,reference) # Validate everything before the first write.
    with save_lease(core, store, identity["uid"]) as renew:
        latest, _ = store.read(users.account_key(identity['uid']))
        if latest is not None and any(latest.get(field) != record.get(field) for field in ('bank', 'sections')):
            raise core.AppError('Las carpetas de tu cuenta cambiaron en otra sesión. Vuelve a sincronizar antes de guardar; tus datos siguen en el formulario.', 409)
        if photo:
            matches=[item for item in core.BANK_CLIENT.inventory().values() if item.get("name","").casefold()=="hoja_de_vida.jpeg" and item.get("mimeType","").startswith("image/")]
            if matches:
                normalized_photo = next(raw for section, name, mime, raw in files if name == 'hoja_de_vida.jpeg')
                existing_photo = core.BANK_CLIENT.download(matches[0])[0] if len(matches) == 1 else None
                if existing_photo != normalized_photo:
                    raise core.AppError("Ya hay una fotografia en tu banco. Cambiala desde Informacion personal y vuelve a sincronizar.",409)
                # A retry after saving or consolidation must not reject the same photo.
                files = [item for item in files if item[1] != 'hoja_de_vida.jpeg']
        saved=[]
        for section,name,mime,raw in files:
            renew()
            saved.append(put(core,token,record["sections"][section],name,mime,raw))
        renew()
        mark_completed(core, store, identity["uid"])
        return {"saved":len(saved),"sync_required":bool(saved)}


def import_reference(core, reference):
    """Read an uploaded CV into an editable draft, without writing to Drive."""
    if reference is None:
        raise core.AppError('Selecciona una hoja de vida en PDF o Word.', 422)
    from drive_bank import extract_facts
    _, name, mime, raw = reference_file(core, reference)
    facts = extract_facts(name, mime, raw, '')
    candidate = facts.get('candidate', {})
    fields = {key: candidate.get(key, '') for key in PERSONAL - {'phones'}}
    fields['address'] = candidate.get('address') or candidate.get('residence', '')
    fields['phones'] = candidate.get('phones', [])
    fields['skills'] = facts.get('skills', [])
    for key, allowed in RECORD_FIELDS.items():
        fields[key] = [{field: value for field, value in item.items() if field in allowed}
                       for item in facts.get(key, [])]
    if not any(fields.values()):
        raise core.AppError('No se encontraron datos legibles en el CV. Prueba otro archivo o completa los campos manualmente.', 422)
    return {'fields': fields, 'notes': facts.get('notes', [])}
