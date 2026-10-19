import hashlib
import types
import unittest
from unittest.mock import Mock, patch
from flask import Flask, g, request, jsonify
import functional_session as session


class FunctionalSessionTests(unittest.TestCase):
    def setUp(self):
        self.uid = 'fixture-alice'
        self.events = [self.event(str(i)) for i in range(5)]
        app = Flask(__name__)
        class Error(Exception):
            def __init__(self, message, status=400): self.status = status
        def verify():
            if not self.uid: raise Error('denied', 401)
            g.google_identity = {'uid': self.uid}
        core = types.SimpleNamespace(app=app, g=g, request=request, jsonify=jsonify,
            AppError=Error, verify_google_identity=verify)
        @app.errorhandler(Error)
        def error(exc): return jsonify(error='fixture'), exc.status
        self.shared = Mock()
        self.shared.snapshot.side_effect = lambda: list(self.events)
        app.extensions['architecture_shared_diagnostics'] = self.shared
        session.register_routes(core)
        self.app = app

    def event(self, operation, uid='fixture-alice', result='error', at='2026-10-19T10:00:00Z'):
        return dict(accountKey=hashlib.sha256(uid.encode()).hexdigest(),
            operationId=operation, component='bank', service='api', endpoint='/api/background/jobs',
            stage='request', confirmed=True, result=result, at=at, code=503,
            token='must-never-be-returned')

    def test_seventy_independent_clients_share_revision_and_five_incidents(self):
        responses = [self.app.test_client().get('/api/session/state') for _ in range(70)]
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual({r.json['errorCount'] for r in responses}, {5})
        self.assertEqual(len({r.json['revision'] for r in responses}), 1)
        self.assertNotIn('must-never', responses[0].text)
        self.assertNotIn('fixture-alice', responses[0].text)
        self.assertEqual(responses[0].headers['Cache-Control'], 'no-store, private')

    def test_account_isolation_and_client_cannot_select_another_account(self):
        self.uid = 'fixture-bob'
        client = self.app.test_client()
        self.assertEqual(client.get('/api/session/state').json['errorCount'], 0)
        self.assertEqual(client.get('/api/session/state?uid=fixture-alice').status_code, 400)
        self.uid = None
        self.assertEqual(client.get('/api/session/state').status_code, 401)

    def test_only_confirmed_matching_operation_recovery_resolves_incident(self):
        self.events += [self.event('unrelated', result='success'),
            {**self.event('0', result='success', at='2026-10-19T10:01:00Z'), 'confirmed': False}]
        client = self.app.test_client()
        self.assertEqual(client.get('/api/session/state').json['errorCount'], 5)
        self.events.append(self.event('0', result='success', at='2026-10-19T10:02:00Z'))
        self.assertEqual(client.get('/api/session/state').json['errorCount'], 4)

    def test_unavailable_shared_state_is_unknown_and_never_instance_fallback(self):
        self.shared.snapshot.side_effect = RuntimeError('private')
        result = self.app.test_client().get('/api/session/state').json
        self.assertFalse(result['available'])
        self.assertIsNone(result['errorCount'])
        self.assertNotIn('private', str(result))
        self.app.extensions['architecture_shared_diagnostics'] = None
        with patch('diagnostic_store.cloud_runtime', return_value=True):
            self.assertFalse(self.app.test_client().get('/api/session/state').json['available'])

    def test_empty_events_do_not_certify_health(self):
        self.events = []
        result = self.app.test_client().get('/api/session/state').json
        self.assertEqual(result['errorCount'], 0)
        self.assertEqual(result['health'], 'not-inferred')
        self.assertEqual(result['retentionSeconds'], 3600)
