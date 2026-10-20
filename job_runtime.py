"""Shared durable jobs and authenticated task dispatch for web and Telegram."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from google.api_core.exceptions import NotFound, PreconditionFailed
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage
import google.auth
import admission_policy
import account_writes
from diagnostic_stages import observe

PROJECT = "cv-a-la-medida-jhonn"


SECRET = f"projects/{PROJECT}/secrets/cv-telegram-config"


QUEUE = f"projects/{PROJECT}/locations/us-central1/queues/cv-telegram"


BUCKET = f"{PROJECT}-telegram-private"


WORKER = f"https://us-central1-{PROJECT}.cloudfunctions.net/telegram_worker/telegram/work"


_session = None


class JobError(Exception):
    def __init__(self, message, *, code='job_service_unavailable'):
        super().__init__(message)
        self.public_code = code if code in JOB_MESSAGES else 'job_service_unavailable'


JOB_MESSAGES = {
    'job_service_unavailable': 'El servicio temporal no está disponible. Vuelve a intentarlo.',
    'job_account_maintenance': 'Esta cuenta tiene una acción administrativa pendiente. El administrador debe revisarla antes de continuar.',
    'job_queue_busy': 'La cola está recibiendo cambios simultáneos. Espera unos segundos y vuelve a intentarlo.',
    'job_policy_unavailable': 'No se pudo comprobar el plan de esta cuenta. El administrador debe revisar sus límites.',
    'job_dispatch_unavailable': 'La solicitud está guardada, pero falta confirmar su envío al procesador. Reintenta la misma acción para recuperarla.',
}


class AdmissionLimit(JobError):
    def __init__(self, period, retry_after):
        self.period = period
        self.retry_after = retry_after
        label = 'diario' if period == 'day' else 'mensual'
        super().__init__(f'Alcanzaste el límite {label} de procesos de esta cuenta. '
                         'Podrás iniciar nuevos procesos al comenzar el siguiente periodo UTC.')


def cloud_request(method, url, **kwargs):
    global _session
    if _session is None:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(credentials)
    response = _session.request(method, url, timeout=25, **kwargs)
    if not response.ok:
        raise JobError("No se pudo consultar la configuración privada de Telegram.")
    return response.json()


def configuration():
    data = cloud_request("GET", f"https://secretmanager.googleapis.com/v1/{SECRET}/versions/latest:access")
    return json.loads(base64.b64decode(data["payload"]["data"]))


def save_configuration(config):
    cloud_request("POST", f"https://secretmanager.googleapis.com/v1/{SECRET}:addVersion",
        json={"payload": {"data": base64.b64encode(json.dumps(config).encode()).decode()}})


def task_secret(config):
    return hmac.new(config["webhook_secret"].encode(), b"cv-telegram-worker", hashlib.sha256).hexdigest()


class JobStore:
    def __init__(self):
        self.bucket = storage.Client(project=PROJECT).bucket(BUCKET)

    @observe(None, 'storage', 'storage-read')
    def read(self, identifier):
        for _ in range(3):
            blob = self.bucket.blob(f"jobs/{identifier}.json")
            try:
                blob.reload()
            except NotFound:
                return None, 0
            generation = blob.generation
            try:
                return json.loads(blob.download_as_text(if_generation_match=generation)), generation
            except (NotFound, PreconditionFailed):
                # Without object versioning, a concurrent replacement removes
                # the generation just loaded. It does not remove the job itself.
                continue
        raise JobError("El registro está cambiando. Vuelve a consultarlo en unos segundos.", code='job_queue_busy')

    @observe(None, 'storage', 'storage-write')
    def write(self, identifier, data, generation):
        # CAS on named objects makes a lost metadata response safe to reconcile.
        uid = data.get('owner_uid') if isinstance(data, dict) else None
        with account_writes.effect(self, uid, uncertain_on_error=False):
            self.bucket.blob(f"jobs/{identifier}.json").upload_from_string(json.dumps(data),
                content_type="application/json", if_generation_match=generation)

    def admit(self, identifier, owner_uid='', *, charge=True, probe=False):
        try:
            with account_writes.reserve(self, owner_uid, 'admission'):
                return _admit_account(self, identifier, owner_uid, charge=charge, probe=probe)
        except account_writes.WriteBlocked as error:
            if error.code == 'job_account_maintenance':
                raise JobError(str(error), code=error.code) from None
            raise

    def put_pdf(self, identifier, content):
        with account_writes.effect(self):
            self.bucket.blob(f"temporary/{identifier}.pdf").upload_from_string(content, content_type="application/pdf")

    def pdf(self, identifier):
        return self.bucket.blob(f"temporary/{identifier}.pdf").download_as_bytes()

    def remove_pdf(self, identifier):
        try:
            with account_writes.effect(self):
                self.bucket.blob(f"temporary/{identifier}.pdf").delete()
        except NotFound:
            pass

    def put_artifact(self, identifier, content, mime):
        with account_writes.effect(self):
            self.bucket.blob(f"temporary/{identifier}.artifact").upload_from_string(content, content_type=mime)

    def artifact(self, identifier):
        blob = self.bucket.blob(f"temporary/{identifier}.artifact")
        blob.reload()
        return blob.download_as_bytes(if_generation_match=blob.generation), blob.content_type


def _admit_account(self, identifier, owner_uid='', *, charge=True, probe=False):
    # Storage generation preconditions keep the ten-slot limit atomic across instances.
    queue_key = admission_policy.queue_key(owner_uid)
    for _ in range(5):
        queue, generation = self.read(queue_key)
        queue = queue or {}
        if (queue or {}).get('maintenance'):
            raise JobError('La cuenta está bloqueada para una acción administrativa. Contacta al administrador.', code='job_account_maintenance')
        pending = []
        for item in (queue or {}).get("pending", []):
            job, job_generation = self.read(item["id"])
            # An undispatched request cannot acquire fresh permissions after an hour.
            # CAS arbitrates with the worker: never expire active or uncertain writes.
            if (job and job.get('owner_uid', '') == owner_uid and
                    job.get('state') == 'queued' and not job.get('external_started') and
                    not job.get('result') and not job.get('drive_url') and
                    isinstance(job.get('created_at'), (int, float)) and
                    time.time() - job['created_at'] > 3600 and
                    job.get('lease_until', 0) <= time.time()):
                expired = {**job, 'state': 'failed', 'lease_until': 0,
                           'completed_at': time.time(), 'errorCode': 'job_authorization_expired',
                           'error': 'La autorización de esta solicitud pendiente venció. Inicia nuevamente la acción.',
                           'stage': 'Solicitud pendiente vencida'}
                import error_contract
                expired.update(error_contract.details('job_authorization_expired',stage='authorization',source=job))
                expired.pop('credentials', None)
                try:
                    account_writes.current().check()
                    self.write(item['id'], expired, job_generation)
                    job = expired
                except PreconditionFailed:
                    # Keep this slot: a worker may now own it.
                    pending.append(item)
                    continue
            abandoned = (not job and time.time() - item['created_at'] > 1800) or (
                job and item['id'].startswith('direct-') and job.get('state') == 'processing'
                and job.get('lease_until', 0) < time.time())
            failed = job and job.get('state') in {'failed', 'rejected'} and not job.get('drive_url') and not job.get('result')
            if abandoned or failed:
                refunded = admission_policy.refund(queue, item['id'])
                if refunded is not None:
                    queue = {**queue, 'usage': refunded}
            if job and job.get("state") in {"done", "failed", "rejected"}:
                continue
            if job and job.get('state') == 'delivery_started' and job.get('lease_until', 0) < time.time():
                continue
            if job and item['id'].startswith('direct-') and job.get('lease_until', 0) < time.time():
                continue
            if not job and time.time() - item["created_at"] > 1800:
                continue
            pending.append(item)
        if any(item["id"] == identifier for item in pending):
            return True
        if len(pending) >= 10:
            return False
        try:
            policy = admission_policy.effective_limits(self, owner_uid) if charge else None
            usage = (admission_policy.reserve(queue or {}, identifier, time.time(), policy)
                     if charge else (queue or {}).get('usage', {}))
        except admission_policy.QuotaExceeded as error:
            raise AdmissionLimit(error.period, error.retry_after) from None
        except ValueError:
            raise JobError('La política de admisión no está disponible.', code='job_policy_unavailable') from None
        if usage is None:
            return True
        if probe:
            return True
        pending.append({"id": identifier, "created_at": time.time()})
        try:
            account_writes.current().check()
            self.write(queue_key, {**(queue or {}), "pending": pending, "usage": usage}, generation)
            return True
        except PreconditionFailed:
            continue
    raise JobError("La cola está ocupada; vuelve a enviar la vacante en unos segundos.", code='job_queue_busy')



def refund_usage(store, identifier, owner_uid='', *, release=False):
    # Compensation is account-owned metadata; maintenance must not lose a receipt.
    with account_writes.reserve(store, owner_uid, 'receipt-refund', maintenance=True):
        return _refund_usage(store, identifier, owner_uid, release=release)


def _refund_usage(store, identifier, owner_uid='', *, release=False):
    """CAS-protected, idempotent rollback; never resets another job's usage."""
    key = admission_policy.queue_key(owner_uid)
    for _ in range(10):
        queue, generation = store.read(key)
        usage = admission_policy.refund(queue, identifier)
        pending = [item for item in (queue or {}).get('pending', []) if item['id'] != identifier]
        if usage is None and (not release or pending == (queue or {}).get('pending', [])):
            return
        updated = {**queue}
        if usage is not None:
            updated['usage'] = usage
        if release:
            updated['pending'] = pending
        try:
            store.write(key, updated, generation)
            return
        except PreconditionFailed:
            continue
    raise JobError('No se pudo liberar la reserva de generación. Reintenta la consulta.')


def enqueue(identifier, config, task_identifier=None, kind=None):
    # A deterministic task name also prevents duplicate enqueue after lost responses.
    global _session
    if _session is None:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(credentials)
    body = {"task": {"name": f"{QUEUE}/tasks/update-{task_identifier or identifier}", "dispatchDeadline": "300s",
        "httpRequest": {"httpMethod": "POST", "url": WORKER,
            "headers": {"Content-Type": "application/json", "X-CV-Telegram-Worker": task_secret(config)},
            "body": base64.b64encode(json.dumps({"update_id": identifier, **({"kind": kind} if kind else {})}).encode()).decode()}}}
    started = time.monotonic()
    with account_writes.effect(uid=config.get('owner_uid')):
        response = _session.post(f"https://cloudtasks.googleapis.com/v2/{QUEUE}/tasks", json=body, timeout=25)
    from diagnostic_stages import provider_response
    provider_response(response, started, component="telegram" if kind != "web_analysis" else "bank",
                      service="tasks", stage="task-dispatched", success=response.ok or response.status_code == 409)
    if response.status_code != 409 and not response.ok:
        raise JobError("No se pudo poner la vacante en la cola de generación.")
