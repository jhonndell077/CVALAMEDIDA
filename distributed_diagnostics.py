"""Non-sensitive trace continuity for authenticated durable operations."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import re
import time
from uuid import uuid4
from flask import g, has_request_context, request

_event_batch = ContextVar("cv_diagnostic_batch", default=None)


def valid(value):
    return isinstance(value, str) and bool(re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", value))


def capture():
    if not has_request_context():
        return {}
    context = getattr(g, 'architecture_observation', None) or {}
    operation, correlation = context.get('operationId', context.get('id')), context.get('id')
    if not valid(operation) or not valid(correlation):
        return {}
    return {'diagnostics_operation': operation, 'diagnostics_correlation': correlation}


def telegram_trace(identifier):
    # update_id is globally unique per bot; never retain a chat/user identifier.
    value = hashlib.sha256(('cv-telegram-update:' + str(identifier)).encode()).hexdigest()
    return {'diagnostics_operation': value, 'diagnostics_correlation': uuid4().hex}


def adopt(job):
    """Attach verified operation identity to the current request observation."""
    if not has_request_context():
        return
    operation, correlation = job.get('diagnostics_operation'), job.get('diagnostics_correlation')
    context = getattr(g, 'architecture_observation', None)
    if context and valid(operation) and valid(correlation):
        context.update(id=correlation, operationId=operation)


@contextmanager
def restore(job):
    """Caller must authenticate worker and validate job ownership first."""
    if not has_request_context():
        yield
        return
    previous = getattr(g, 'architecture_observation', None)
    operation, correlation = job.get('diagnostics_operation'), job.get('diagnostics_correlation')
    batch = _event_batch.get()
    if batch is None:
        batch = previous.setdefault('events', []) if previous is not None else []
    marker = _event_batch.set(batch)
    if valid(operation) and valid(correlation):
        endpoint = (previous or {}).get('endpoint') or (request.url_rule.rule if request.url_rule else '/telegram/work')
        g.architecture_observation = {'id': correlation, 'operationId': operation,
            'start': time.monotonic(), 'endpoint': endpoint, 'events': batch}
    try:
        yield
    finally:
        g.architecture_observation = previous
        _event_batch.reset(marker)
