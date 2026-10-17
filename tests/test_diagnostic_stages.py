"""Real instrumentation boundaries, with providers replaced by local fixtures."""
import sys
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from flask import Flask, g, request, jsonify
import architecture_diagnostics as diagnostics
from diagnostic_stages import observe, observe_drive, provider_response


class StageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.core = types.SimpleNamespace(app=self.app, g=g, request=request, jsonify=jsonify)
        diagnostics.register_routes(self.core)

    def test_pdf_success_drive_403_and_backend_share_correlation(self):
        @observe('pdf', 'pdf-generator', 'pdf-generated')
        def pdf():
            return b'private-cv-fixture'

        @observe_drive
        def drive(url, token, data=None, content_type=None):
            try:
                raise HTTPError(url, 403, 'private-provider-text', {}, None)
            except HTTPError as error:
                raise RuntimeError('translated private text') from error

        @self.app.post('/api/export/<format_name>')
        def export(format_name):
            self.assertEqual(pdf(), b'private-cv-fixture')
            try:
                drive('https://www.googleapis.com/upload/drive/v3/files', 'private-token')
            except RuntimeError:
                return jsonify(error='fixture'), 403
            self.fail('Original provider failure must remain a failure')

        with patch.dict(sys.modules, {'app': self.core}):
            response = self.app.test_client().post('/api/export/pdf')
        events = self.app.extensions['architecture_diagnostics'].snapshot()
        self.assertEqual([(e['service'], e['stage'], e['result']) for e in events], [
            ('pdf-generator', 'pdf-generated', 'success'),
            ('drive-api', 'drive-upload', 'error'), ('api', 'http-backend', 'error')])
        self.assertEqual(events[1]['code'], 403)
        self.assertEqual({e['correlationId'] for e in events}, {response.headers['X-Correlation-ID']})
        self.assertNotIn('private', str(events))

    def test_missing_provider_response_is_warning_not_provider_error(self):
        @observe_drive
        def offline(*args):
            raise TimeoutError('private-network-text')

        @self.app.post('/api/export/<format_name>')
        def export(format_name):
            with self.assertRaises(TimeoutError):
                offline('https://www.googleapis.com/drive/v3/files', 'private-token')
            return jsonify(ok=True)

        with patch.dict(sys.modules, {'app': self.core}):
            self.app.test_client().post('/api/export/pdf')
        event = self.app.extensions['architecture_diagnostics'].snapshot()[0]
        self.assertEqual((event['result'], event['code']), ('warning', None))

    def test_no_provider_call_produces_only_http_stage(self):
        @self.app.get('/api/bank/status')
        def cached():
            return jsonify(pending=0)

        self.app.test_client().get('/api/bank/status')
        events = self.app.extensions['architecture_diagnostics'].snapshot()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['service'], 'api')

    def test_provider_response_and_telemetry_failure_preserve_result(self):
        @self.app.post('/api/bank/sync')
        def sync():
            provider_response(types.SimpleNamespace(ok=False, status_code=412), 0,
                              stage='drive-upload')
            return jsonify(pending=1), 409

        with patch.dict(sys.modules, {'app': self.core}):
            result = self.app.test_client().post('/api/bank/sync')
        self.assertEqual(result.status_code, 409)
        events = self.app.extensions['architecture_diagnostics'].snapshot()
        self.assertEqual(events[0]['code'], 412)
        with patch.object(self.app.extensions['architecture_diagnostics'], 'append', side_effect=RuntimeError()):
            self.assertEqual(self.app.test_client().post('/api/bank/sync').status_code, 409)
