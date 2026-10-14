from __future__ import annotations

import os

os.environ.setdefault("CV_AI_PROVIDER", "vertex")
os.environ.setdefault("CV_BANK_PROVIDER", "drive")
os.environ.setdefault("CV_AUTH_REQUIRED", "1")
os.environ.setdefault("CV_ALLOW_REMOTE", "1")
os.environ.setdefault("CV_MULTI_ACCOUNT", "1")
os.environ.setdefault("CV_EMPLOYMENT_ENABLED", "1")
os.environ.setdefault("CV_ALLOWED_EMAILS", "jhonndell077@gmail.com")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "cv-a-la-medida-jhonn")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

import firebase_admin
from firebase_functions import https_fn, options

from app import app as flask_app

try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


@https_fn.on_request(
    region="us-central1",
    timeout_sec=300,
    memory=options.MemoryOption.MB_512,
    max_instances=1,
    concurrency=1,
    service_account="cv-runtime@cv-a-la-medida-jhonn.iam.gserviceaccount.com",
)
def api(req: https_fn.Request) -> https_fn.Response:
    with flask_app.request_context(req.environ):
        response = flask_app.full_dispatch_request()
    response.headers["Cache-Control"] = "no-store"
    return response


@https_fn.on_request(
    region="us-central1",
    timeout_sec=300,
    memory=options.MemoryOption.MB_512,
    max_instances=1,
    concurrency=1,
    service_account="cv-runtime@cv-a-la-medida-jhonn.iam.gserviceaccount.com",
)
def telegram_worker(req: https_fn.Request) -> https_fn.Response:
    # Telegram acknowledges new messages quickly while this separate service works.
    if req.path != "/telegram/work":
        return https_fn.Response("Not found", status=404)
    with flask_app.request_context(req.environ):
        return flask_app.full_dispatch_request()
