"""Observe boundaries without changing outcomes or retaining operation inputs."""
from functools import wraps
from time import monotonic


def observe(component, service, stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            started = monotonic()
            outcome, code = 'success', None
            try:
                return function(*args, **kwargs)
            except Exception as error:
                outcome = 'error'
                code = getattr(error, 'code', None)
                if code is None:
                    code = getattr(getattr(error, '__cause__', None), 'code', None)
                raise
            finally:
                try:
                    from flask import has_request_context, request
                    if has_request_context() and request.url_rule:
                        import app as core
                        from architecture_diagnostics import record_stage
                        record_stage(core, component=component or __import__('architecture_diagnostics').ROUTES.get(request.url_rule.rule, 'telegram'), service=service,
                                     endpoint=request.url_rule.rule, stage=stage,
                                     result=('warning' if service in {'drive-api', 'gmail', 'vertex', 'storage'} and outcome == 'error' and code is None else outcome), code=code,
                                     duration_ms=(monotonic() - started) * 1000)
                except Exception:
                    pass
        return wrapped
    return decorate


def observe_drive(function):
    @wraps(function)
    def wrapped(url, token, data=None, content_type="application/json"):
        stage = 'oauth-authorization' if url.partition('?')[0].endswith('/userinfo') else 'drive-upload' if '/upload/drive/' in url else 'drive-readback'
        return observe('drive', 'drive-api', stage)(function)(url, token, data, content_type)
    return wrapped


def provider_response(response, started, *, component='bank', service='drive-api', stage='drive-request', success=None):
    """Record only an actual provider HTTP response, never cached/local checks."""
    try:
        from flask import has_request_context, request
        if not has_request_context() or not request.url_rule:
            return
        import app as core
        from architecture_diagnostics import record_stage
        record_stage(core, component=component, service=service,
                     endpoint=request.url_rule.rule, stage=stage,
                     result='success' if (response.ok if success is None else success) else 'error',
                     code=response.status_code, duration_ms=(monotonic()-started)*1000)
    except Exception:
        pass
