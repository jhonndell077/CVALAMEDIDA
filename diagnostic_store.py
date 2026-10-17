"""Bounded, sanitized architecture evidence in the existing private job bucket.

No bucket/IAM/lifecycle changes. Expiry is enforced on reads; expired physical
records are replaced on the next successful write, not by a background service.
"""
import json
import math
import os
import re
import time
from datetime import datetime

from google.api_core.exceptions import NotFound, PreconditionFailed

MAX_EVENTS = 400
RETENTION_SECONDS = 3600
OBJECT_NAME = 'diagnostics/architecture-v1.json'
TIMEOUT = 0.7
MAX_BYTES = 512000
STAGES = frozenset({'http-backend', 'pdf-generated', 'drive-upload', 'drive-readback', 'drive-request', 'telegram-request', 'bank-sync', 'identity-verified', 'oauth-authorization', 'browser-signin', 'task-dispatched', 'vertex-response', 'gmail-request', 'storage-read', 'storage-write'})
CLIENT_CODES = frozenset({'access_denied', 'popup_closed', 'popup_failed_to_open', 'oauth_error'})
IDENTIFIER = re.compile(r'^[a-f0-9]{32}$')
OPERATION = re.compile(r'^(?:[a-f0-9]{32}|[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$')


class DiagnosticStore:
    def __init__(self, ids, endpoints, bucket=None, clock=time.time):
        self.ids, self.endpoints = frozenset(ids), frozenset(endpoints)
        self.bucket, self.clock = bucket, clock

    def _bucket(self):
        if self.bucket is None:
            from google.cloud import storage
            from job_runtime import PROJECT, BUCKET
            self.bucket = storage.Client(project=PROJECT).bucket(BUCKET)
        return self.bucket

    def sanitize(self, events):
        clean = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            if any(not isinstance(event.get(key), str) or not IDENTIFIER.fullmatch(event[key]) for key in ('id', 'correlationId')):
                continue
            if not isinstance(event.get('operationId'), str) or not OPERATION.fullmatch(event['operationId']):
                continue
            if event.get('component') not in self.ids or event.get('service') not in self.ids or event.get('endpoint') not in self.endpoints:
                continue
            if event.get('stage') not in STAGES or event.get('result') not in {'success', 'error', 'warning'}:
                continue
            try:
                timestamp = datetime.fromisoformat(event['at']).timestamp()
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
            if not self.clock() - RETENTION_SECONDS <= timestamp <= self.clock() + 60:
                continue
            duration = event.get('durationMs')
            duration = round(duration, 2) if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and 0 <= duration <= 86400000 else None
            code = event.get('code')
            client_code = code if isinstance(code, str) and code in CLIENT_CODES and event.get('stage') in {'oauth-authorization', 'browser-signin'} and event.get('confirmed') is False else None
            code = code if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599 else client_code
            clean[event['id']] = dict(id=event['id'], correlationId=event['correlationId'], operationId=event['operationId'],
                component=event['component'], service=event['service'], endpoint=event['endpoint'],
                at=event['at'], durationMs=duration, result=event['result'], code=code,
                stage=event['stage'], confirmed=event.get('confirmed') is True, dependencies=[])
        return sorted(clean.values(), key=lambda item: (item['at'], item['id']))[-MAX_EVENTS:]

    def _read(self):
        blob = self._bucket().blob(OBJECT_NAME)
        try:
            blob.reload(timeout=TIMEOUT, retry=None)
        except NotFound:
            return [], 0
        if blob.size is not None and blob.size > MAX_BYTES:
            raise ValueError('diagnostics snapshot too large')
        raw = blob.download_as_text(if_generation_match=blob.generation, timeout=TIMEOUT, retry=None)
        if len(raw.encode('utf-8')) > MAX_BYTES:
            raise ValueError('diagnostics snapshot too large')
        payload = json.loads(raw)
        events = payload.get('events', [])
        if not isinstance(events, list):
            raise ValueError('invalid diagnostics snapshot')
        return self.sanitize(events), blob.generation

    def snapshot(self):
        # Read-only admin request; no provider probes or mutation on inspection.
        events, _ = self._read()
        return events

    def append_batch(self, events):
        additions = self.sanitize(events)
        if not additions:
            return
        deadline = time.monotonic() + 2.5
        for attempt in range(3):
            try:
                existing, generation = self._read()
                merged = self.sanitize(existing + additions)
                self._bucket().blob(OBJECT_NAME).upload_from_string(
                    json.dumps({'version': 1, 'events': merged}, separators=(',', ':')),
                    content_type='application/json', if_generation_match=generation,
                    timeout=TIMEOUT, retry=None)
                return
            except (PreconditionFailed, NotFound):
                if attempt == 2 or time.monotonic() >= deadline:
                    raise


def cloud_runtime():
    """Never use cloud storage during local tests/dev by default."""
    return bool(os.environ.get('K_SERVICE') or os.environ.get('FUNCTION_TARGET'))
