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

PROJECT = "cv-a-la-medida-jhonn"


SECRET = f"projects/{PROJECT}/secrets/cv-telegram-config"


QUEUE = f"projects/{PROJECT}/locations/us-central1/queues/cv-telegram"


BUCKET = f"{PROJECT}-telegram-private"


WORKER = f"https://us-central1-{PROJECT}.cloudfunctions.net/telegram_worker/telegram/work"


_session = None


class JobError(Exception):
    pass


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
        raise JobError("El registro está cambiando. Vuelve a consultarlo en unos segundos.")

    def write(self, identifier, data, generation):
        self.bucket.blob(f"jobs/{identifier}.json").upload_from_string(json.dumps(data),
            content_type="application/json", if_generation_match=generation)

    def admit(self, identifier, owner_uid=''):
        # Storage generation preconditions keep the ten-slot limit atomic across instances.
        queue_key='vacancy-queue' + ('-' + hashlib.sha256(owner_uid.encode()).hexdigest() if owner_uid else '')
        for _ in range(5):
            queue, generation = self.read(queue_key)
            pending = []
            for item in (queue or {}).get("pending", []):
                job, _ = self.read(item["id"])
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
                usage = admission_policy.reserve(queue or {}, identifier, time.time())
            except admission_policy.QuotaExceeded as error:
                raise AdmissionLimit(error.period, error.retry_after) from None
            except ValueError:
                raise JobError('La política de admisión no está disponible.') from None
            if usage is None:
                return True
            pending.append({"id": identifier, "created_at": time.time()})
            try:
                self.write(queue_key, {"pending": pending, "usage": usage}, generation)
                return True
            except PreconditionFailed:
                continue
        raise JobError("La cola está ocupada; vuelve a enviar la vacante en unos segundos.")

    def put_pdf(self, identifier, content):
        self.bucket.blob(f"temporary/{identifier}.pdf").upload_from_string(content, content_type="application/pdf")

    def pdf(self, identifier):
        return self.bucket.blob(f"temporary/{identifier}.pdf").download_as_bytes()

    def remove_pdf(self, identifier):
        try:
            self.bucket.blob(f"temporary/{identifier}.pdf").delete()
        except NotFound:
            pass

    def put_artifact(self, identifier, content, mime):
        self.bucket.blob(f"temporary/{identifier}.artifact").upload_from_string(content, content_type=mime)

    def artifact(self, identifier):
        blob = self.bucket.blob(f"temporary/{identifier}.artifact")
        blob.reload()
        return blob.download_as_bytes(if_generation_match=blob.generation), blob.content_type


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
    response = _session.post(f"https://cloudtasks.googleapis.com/v2/{QUEUE}/tasks", json=body, timeout=25)
    if response.status_code != 409 and not response.ok:
        raise JobError("No se pudo poner la vacante en la cola de generación.")
