"""Account attribution is backend-only; legacy events stay unattributed."""
import hashlib
import types
import unittest
from unittest.mock import patch
import flask
import architecture_diagnostics as diagnostics
from diagnostic_store import DiagnosticStore
from tests.test_diagnostic_store import Bucket, event


def key(uid):
    return hashlib.sha256(uid.encode()).hexdigest()


class ScopedDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        app=flask.Flask(__name__)
        class AppError(Exception):
            def __init__(self,message,status=400):
                self.status_code=status
        self.core=types.SimpleNamespace(app=app,g=flask.g,request=flask.request,jsonify=flask.jsonify,
                                       ORIGINAL_OWNER_EMAIL='admin@example.test',AppError=AppError)
        @app.before_request
        def verified_fixture():
            uid=flask.request.headers.get('X-Fixture-Verified')
            if uid:
                flask.g.google_identity={'uid':uid,'email':'admin@example.test' if uid=='admin' else uid+'@example.test'}
        @app.errorhandler(AppError)
        def failed(error):
            return flask.jsonify(error='denied'),error.status_code
        @app.post('/api/account/setup')
        def setup():
            diagnostics.record_stage(self.core,component='bank',service='drive-api',endpoint='/api/account/setup',
                                     stage='drive-upload',result='error',code='drive_storage_full')
            return flask.jsonify(error='fixture'),403
        @app.post('/telegram/webhook')
        def webhook():
            return flask.jsonify(ok=True)
        diagnostics.register_routes(self.core)
        self.client=app.test_client()

    def get(self, account=None, uid='admin'):
        return self.client.get('/api/admin/architecture'+('?account='+account if account is not None else ''),
                               headers={'X-Fixture-Verified':uid} if uid else {})

    def test_two_accounts_filtered_and_global_selector_summaries(self):
        for uid in ('alice','bob'):
            self.client.post('/api/account/setup',headers={'X-Fixture-Verified':uid})
        global_data=self.get().json
        self.assertEqual(global_data['scope']['totalEvents'],4)
        self.assertEqual(len(global_data['accounts']),2)
        alice=self.get(key('alice')).json
        self.assertEqual(len(alice['events']),2)
        self.assertTrue(all(item['accountKey']==key('alice') for item in alice['events']))
        self.assertEqual(alice['scope']['visibleEvents'],2)
        self.assertEqual(alice['scope']['totalEvents'],4)
        self.assertEqual(len(alice['accounts']),2)
        self.assertEqual(alice['accounts'][0]['errorCount'],2)
        self.assertNotIn('alice@example.test',str(global_data))
        self.assertNotIn("'uid'",str(global_data))

    def test_client_account_uid_headers_and_body_cannot_spoof(self):
        self.client.post('/api/account/setup?account='+key('bob'),json={'uid':'bob','accountKey':key('bob')},
                         headers={'X-Fixture-Verified':'alice','X-Account-Key':key('bob'),'X-CV-Account-UID':'bob'})
        self.assertEqual(len(self.get(key('bob')).json['events']),0)
        self.assertEqual(len(self.get(key('alice')).json['events']),2)

    def test_unattributed_legacy_and_webhook_are_not_assigned_to_reader(self):
        self.client.post('/telegram/webhook',json={'uid':'admin','accountKey':key('admin')})
        self.core.app.extensions['architecture_diagnostics'].append({'id':'legacy','at':'2026-10-17T00:00:00+00:00','result':'error','confirmed':True})
        data=self.get('unattributed').json
        self.assertEqual(data['scope']['mode'],'unattributed')
        self.assertEqual(data['scope']['unattributedEvents'],2)
        self.assertTrue(all(item['accountKey'] is None for item in data['events']))
        self.assertEqual(self.get(key('admin')).json['events'],[])
        self.assertEqual(data['accounts'],[])

    def test_auth_guard_precedes_filter_and_read(self):
        store=self.core.app.extensions['architecture_diagnostics']
        with patch.object(store,'snapshot') as snapshot:
            self.assertEqual(self.get(key('alice'),uid='bob').status_code,403)
            self.assertEqual(self.get('invalid',uid=None).status_code,403)
            snapshot.assert_not_called()
        self.assertEqual(self.get('invalid').status_code,400)

    def test_safe_classified_code_reason_survive_local_and_persistent(self):
        self.client.post('/api/account/setup',headers={'X-Fixture-Verified':'alice'})
        item=self.get().json['events'][0]
        self.assertEqual((item['code'],item['reason']),('drive_storage_full','drive_storage_full'))
        store=DiagnosticStore(diagnostics.IDS,diagnostics.ROUTES,bucket=Bucket())
        store.append_batch([item])
        saved=store.snapshot()[0]
        self.assertEqual(saved['accountKey'],key('alice'))
        self.assertEqual(saved['reason'],'drive_storage_full')
        self.assertEqual(saved['code'],'drive_storage_full')

    def test_safe_reason_and_invalid_attribution_sanitized(self):
        store=DiagnosticStore({'pdf','drive-api'},{'/export'},bucket=Bucket())
        store.append_batch([event(reason='storageQuotaExceeded',accountKey=key('alice')),
                            event(2,reason='secret-provider-text',code='secret-code',accountKey='alice@example.test')])
        saved=store.snapshot()
        self.assertEqual(saved[0]['reason'],'storageQuotaExceeded')
        self.assertEqual(saved[1]['reason'],None)
        self.assertEqual(saved[1]['code'],None)
        self.assertIsNone(saved[1]['accountKey'])
        self.assertNotIn('secret',str(saved))
        self.assertNotIn('alice@example.test',str(saved))

    def test_worker_uses_verified_owner_context_not_telegram_payload(self):
        import user_accounts
        with self.core.app.test_request_context('/telegram/webhook'):
            flask.g.architecture_observation={'id':'a'*32,'operationId':'b'*32}
            marker=user_accounts.CURRENT.set({'uid':'worker-verified-user'})
            try:
                diagnostics.record_stage(self.core,component='telegram',service='drive-api',endpoint='/telegram/webhook',stage='drive-request',result='success')
            finally:
                user_accounts.CURRENT.reset(marker)
        self.assertEqual(len(self.get(key('worker-verified-user')).json['events']),1)

    def test_browser_stage_never_confirmed_provider_evidence(self):
        store=DiagnosticStore({'pdf','drive-api'},{'/export'},bucket=Bucket())
        store.append_batch([event(stage='browser-request',result='warning',confirmed=True,code='network_error')])
        self.assertFalse(store.snapshot()[0]['confirmed'])
        self.assertEqual(store.snapshot()[0]['code'],'network_error')


if __name__=='__main__':
    unittest.main()
