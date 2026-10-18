import types
import unittest
from unittest.mock import patch
from flask import Flask, g, request, jsonify
import client_diagnostics as browser
import architecture_diagnostics as diagnostics


class BrowserDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        browser._windows.clear()
        app = Flask(__name__)
        class Error(Exception):
            def __init__(self, text, status=400): self.status = status
        self.authenticated = True
        def verify():
            if not self.authenticated: raise Error('denied', 401)
            g.google_identity = {'uid': 'fixture-only'}
        self.core = types.SimpleNamespace(app=app, g=g, request=request, jsonify=jsonify,
                                         AppError=Error, verify_google_identity=verify)
        @app.errorhandler(Error)
        def error(exc): return jsonify(error='fixture'), exc.status
        diagnostics.register_routes(self.core)
        browser.register_routes(self.core)
        self.client = app.test_client()
        self.headers = {'Origin': 'https://cvalamedida.web.app'}
        self.payload = dict(service='drive-api', stage='oauth-authorization', result='error', code='access_denied')

    def test_reports_are_unconfirmed_and_do_not_store_extra_content(self):
        response = self.client.post('/api/diagnostics/client', json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['confirmed'])
        event = self.core.app.extensions['architecture_diagnostics'].snapshot()[0]
        self.assertEqual((event['result'], event['confirmed'], event['code']), ('warning', False, 'access_denied'))
        self.assertNotIn('fixture-only', str(event))
        self.assertEqual(self.client.post('/api/diagnostics/client', json={**self.payload, 'token': 'private'}, headers=self.headers).status_code, 400)

    def test_telegram_pending_and_error_remain_unconfirmed_with_safe_component(self):
        response = self.client.post('/api/diagnostics/client', json={**self.payload,
            'component':'telegram', 'result':'pending', 'code':'authorization_pending'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/api/diagnostics/client', json={**self.payload,
            'component':'telegram', 'code':'origin_mismatch'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        signals = [e for e in self.core.app.extensions['architecture_diagnostics'].snapshot() if e['stage']=='oauth-authorization']
        self.assertEqual([e['component'] for e in signals], ['telegram','telegram'])
        self.assertTrue(all(e['result']=='warning' and e['confirmed'] is False for e in signals))
        self.assertEqual(signals[-1]['code'], 'origin_mismatch')
        self.assertEqual(self.client.post('/api/diagnostics/client', json={**self.payload,
            'component':'not-allowed'}, headers=self.headers).status_code, 400)

    def test_requires_session_origin_and_bounded_codes(self):
        self.authenticated = False
        self.assertEqual(self.client.post('/api/diagnostics/client', json=self.payload, headers=self.headers).status_code, 401)
        self.authenticated = True
        self.assertEqual(self.client.post('/api/diagnostics/client', json=self.payload, headers={'Origin': 'https://attacker.invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/diagnostics/client', json={**self.payload, 'code': 'private text'}, headers=self.headers).status_code, 400)

    def test_rate_limit_and_telemetry_failure_do_not_expose_details(self):
        with patch.object(self.core.app.extensions['architecture_diagnostics'], 'append', side_effect=RuntimeError('private')):
            self.assertEqual(self.client.post('/api/diagnostics/client', json=self.payload, headers=self.headers).status_code, 200)
        for _ in range(11):
            self.assertEqual(self.client.post('/api/diagnostics/client', json=self.payload, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/api/diagnostics/client', json=self.payload, headers=self.headers).status_code, 429)


    def test_browser_network_failure_is_unconfirmed_and_cannot_spoof_account(self):
        payload=dict(component='bank',service='api',stage='browser-request',result='error',code='network_error')
        response=self.client.post('/api/diagnostics/client',json=payload,headers=self.headers)
        self.assertEqual(response.status_code,200)
        event=next(e for e in self.core.app.extensions['architecture_diagnostics'].snapshot() if e['stage']=='browser-request')
        self.assertFalse(event['confirmed'])
        self.assertEqual(event['code'],'network_error')
        self.assertEqual(self.client.post('/api/diagnostics/client',json={**payload,'accountKey':'a'*64},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/diagnostics/client',json={**payload,'code':{}},headers=self.headers).status_code,400)
