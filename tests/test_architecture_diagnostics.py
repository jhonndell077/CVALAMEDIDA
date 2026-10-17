import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import flask
import architecture_diagnostics as diagnostics


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        app = flask.Flask(__name__)
        self.core = types.SimpleNamespace(app=app, g=flask.g, request=flask.request,
                                          jsonify=flask.jsonify, ORIGINAL_OWNER_EMAIL='owner@example.test')
        class AppError(Exception):
            def __init__(self, message, status=400):
                self.status_code = status
        self.core.AppError = AppError
        @app.errorhandler(AppError)
        def error(exc):
            return flask.jsonify(error='denied'), exc.status_code
        @app.before_request
        def identity():
            if flask.request.headers.get('X-Fixture-Owner') == 'yes':
                flask.g.google_identity = {'uid': 'fixture', 'email': 'owner@example.test'}
        @app.post('/api/export/<format_name>')
        def export(format_name):
            return flask.jsonify(ok=True), 403 if format_name == 'fail' else 200
        diagnostics.register_routes(self.core)
        self.client = app.test_client()

    def snapshot(self):
        return self.client.get('/api/admin/architecture', headers={'X-Fixture-Owner': 'yes'})

    def test_admin_denied_and_read_is_side_effect_free(self):
        self.assertEqual(self.client.get('/api/admin/architecture').status_code, 403)
        response = self.snapshot()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['events'], [])
        self.assertIn('private', response.headers['Cache-Control'])
        self.assertEqual(len(response.json['nodes']), len(diagnostics.IDS))

    def test_server_correlation_and_http_only_evidence(self):
        response = self.client.post('/api/export/pdf?token=never-retain', json={'cv': 'private-cv'}, headers={'X-Correlation-ID': 'attacker-value', 'Authorization': 'secret-value'})
        self.assertNotEqual(response.headers['X-Correlation-ID'], 'attacker-value')
        event = self.snapshot().json['events'][0]
        self.assertEqual(event['correlationId'], response.headers['X-Correlation-ID'])
        self.assertEqual(event['service'], 'api')
        self.assertEqual(event['stage'], 'http-backend')
        self.assertEqual(event['endpoint'], '/api/export/<format_name>')
        serialized = str(event)
        for secret in ('never-retain', 'private-cv', 'secret-value', 'attacker-value'):
            self.assertNotIn(secret, serialized)

    def test_confirmed_http_error_does_not_blame_drive(self):
        self.client.post('/api/export/fail')
        event = self.snapshot().json['events'][0]
        self.assertEqual((event['result'], event['code'], event['service']), ('error', 403, 'api'))

    def test_retention_and_bounded_concurrent_writes(self):
        now = [1000]
        store = diagnostics.EventStore(clock=lambda: now[0])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: store.append({'id': index}), range(diagnostics.MAX_EVENTS * 2)))
        self.assertEqual(len(store.snapshot()), diagnostics.MAX_EVENTS)
        now[0] += diagnostics.RETENTION_SECONDS + 1
        self.assertEqual(store.snapshot(), [])

    def test_telemetry_failure_does_not_break_operation_or_read(self):
        store = self.core.app.extensions['architecture_diagnostics']
        with patch.object(store, 'append', side_effect=RuntimeError('fixture')):
            self.assertEqual(self.client.post('/api/export/pdf').status_code, 200)
        with patch.object(store, 'snapshot', side_effect=RuntimeError('fixture')):
            self.assertEqual(self.snapshot().json['events'], [])

    def test_stage_rejects_untrusted_labels_and_recovers(self):
        with self.core.app.test_request_context('/api/export/pdf'):
            flask.g.architecture_observation = {'id': 'server-fixture'}
            diagnostics.record_stage(self.core, component='pdf', service='drive-api', endpoint='/api/export/<format_name>', stage='secret-value', result='error')
        self.assertEqual(self.snapshot().json['events'], [])
        self.client.post('/api/export/pdf')
        self.assertEqual(len(self.snapshot().json['events']), 1)

    def test_real_stage_evidence_and_original_error_preserved(self):
        class ProviderError(Exception):
            code = 403
        with self.core.app.test_request_context('/api/export/pdf'):
            flask.g.architecture_observation = {'id': 'server-fixture', 'endpoint': '/api/export/<format_name>'}
            with diagnostics.stage(self.core, 'pdf', 'pdf-generator', 'pdf-generated'):
                pass
            with self.assertRaises(ProviderError):
                with diagnostics.stage(self.core, 'drive', 'drive-api', 'drive-upload'):
                    raise ProviderError('private provider response')
        events = self.snapshot().json['events']
        self.assertEqual(events[0]['result'], 'success')
        self.assertEqual((events[1]['service'], events[1]['code']), ('drive-api', 403))
        self.assertNotIn('private provider response', str(events))
        with diagnostics.stage(self.core, 'pdf', 'pdf-generator', 'pdf-generated'):
            pass


if __name__ == '__main__':
    unittest.main()
