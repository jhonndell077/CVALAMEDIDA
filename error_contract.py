"""Additive public error metadata. Never copy provider bodies or arbitrary IDs."""
import json
from pathlib import Path
from uuid import uuid4
from flask import g, has_request_context, request
import distributed_diagnostics as traces

POLICY = {
    'session_reauthentication_required': (False, 'reauthenticate', 'not_started'),
    'job_account_maintenance': (False, 'contact_admin', 'not_started'),
    'account_write_busy': (True, 'retry', 'not_started'),
    'account_write_lease_lost': (False, 'synchronize', 'unknown'),
    'account_write_outcome_unknown': (False, 'review_outcome', 'unknown'),
    'admin_delete_failed': (False, 'contact_admin', 'unknown'),
    'google_authorization_expired': (False, 'reauthorize', 'rejected'),
    'job_authorization_expired': (False, 'reauthorize', 'rejected'),
    'google_permissions_missing': (False, 'reauthorize', 'rejected'),
    'drive_folder_permission': (False, 'select_folders', 'rejected'),
    'drive_access_undetermined': (False, 'check_access', 'rejected'),
    'drive_storage_full': (False, 'free_storage', 'rejected'),
    'google_api_disabled': (False, 'contact_admin', 'rejected'),
    'google_rate_limit': (True, 'retry', 'rejected'),
    'google_daily_limit': (False, 'contact_admin', 'rejected'),
    'google_request_failed': (False, 'review_outcome', 'unknown'),
    'google_identity_check_failed': (False, 'check_access', 'rejected'),
    'bank_review_required': (False, 'review_bank', 'not_started'),
    'bank_sync_pending': (True, 'synchronize', 'not_started'),
    'external_outcome_unknown': (False, 'review_outcome', 'unknown'),
    'job_dispatch_unavailable': (True, 'retry_same_operation', 'unknown'),
    'job_service_unavailable': (True, 'retry', 'not_started'),
    'period_quota_exceeded': (False, 'wait_period', 'not_started'),
}
STAGES = {'request','drive-access-check','drive-prepare','drive-upload','bank-sync',
          'authorization','admission','worker','administration','delivery'}

def build_id():
    try:
        value = json.loads((Path(__file__).parent / 'static/version.json').read_text())['buildId']
        import re
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',value): return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'unknown'

def request_stage():
    path = request.path if has_request_context() else ''
    if path == '/api/account/setup': return 'drive-prepare'
    if path in {'/api/drive/check','/api/connections/verify'}: return 'drive-access-check'
    if path.startswith('/api/admin/'): return 'administration'
    return 'request'

def details(code=None, *, stage=None, source=None):
    source = source or {}
    code = code if isinstance(code,str) and code in POLICY else 'request_failed'
    retryable, action, outcome = POLICY.get(code,(False,'review_error','unknown'))
    captured = traces.capture()
    operation = source.get('diagnostics_operation') or captured.get('diagnostics_operation')
    correlation = source.get('diagnostics_correlation') or captured.get('diagnostics_correlation')
    if has_request_context():
        fallback = getattr(g,'public_error_ids',None)
        if fallback is None:
            fallback = (uuid4().hex,uuid4().hex)
            g.public_error_ids = fallback
    else: fallback = (uuid4().hex,uuid4().hex)
    return dict(code=code,stage=stage if isinstance(stage,str) and stage in STAGES else request_stage(),
        operationId=operation if traces.valid(operation) else fallback[0],
        correlationId=correlation if traces.valid(correlation) else fallback[1],
        retryable=retryable,safeNextAction=action,externalOutcome=outcome,buildId=build_id())

def from_error(error, *, stage=None, source=None):
    return details(getattr(error,'code',None) or getattr(error,'public_code',None),
        stage=getattr(error,'stage',None) or stage,source=source)

def register(app):
    @app.after_request
    def public_error_metadata(response):
        if response.status_code < 400 or not response.is_json: return response
        payload = response.get_json(silent=True)
        if not isinstance(payload,dict): return response
        meta = details(payload.get('code'),stage=payload.get('stage'))
        # Preserve server-generated metadata already bound by the error handler.
        for field,value in meta.items(): payload.setdefault(field,value)
        response.set_data(app.json.dumps(payload))
        response.headers['X-Correlation-ID'] = payload['correlationId']
        if payload['code']=='account_write_busy': response.headers['Retry-After']='1'
        return response
