"""Local fake-only tests for owner usage inspection and quota configuration."""
import copy
import types
import unittest
from unittest.mock import patch

import flask
from google.api_core.exceptions import PreconditionFailed
import admin_usage
import admission_policy


class Store:
    def __init__(self):
        self.data = {}
        self.writes = []
    def read(self, key):
        return copy.deepcopy(self.data.get(key, (None, 0)))
    def write(self, key, value, generation):
        if self.read(key)[1] != generation:
            raise PreconditionFailed('fixture')
        self.data[key] = (copy.deepcopy(value), generation+1)
        self.writes.append(key)


class AdminUsageTests(unittest.TestCase):
    headers = {'Origin': 'https://cvalamedida.web.app', 'X-Requested-With': 'XmlHttpRequest', 'X-Fixture-Admin': 'yes'}
    def setUp(self):
        app = flask.Flask(__name__)
        class AppError(Exception):
            def __init__(self, message, status):
                self.status_code = status
                self.message = message
        core = types.SimpleNamespace(app=app, g=flask.g, request=flask.request, jsonify=flask.jsonify,
                                     ORIGINAL_OWNER_EMAIL='admin@example.test', AppError=AppError)
        @app.before_request
        def identity():
            if flask.request.headers.get('X-Fixture-Admin') == 'yes':
                flask.g.google_identity = {'uid': 'admin', 'email': 'admin@example.test'}
        @app.errorhandler(AppError)
        def failed(error):
            return flask.jsonify(error=error.message), error.status_code
        admin_usage.register_routes(core)
        self.client = app.test_client()
        self.store = Store()
        self.fixture = patch.object(admin_usage.job_runtime, 'JobStore', return_value=self.store)
        self.fixture.start()
        self.addCleanup(self.fixture.stop)
        self.user = types.SimpleNamespace(uid='alice', email='alice@example.test', display_name='Alice', disabled=False,
                                          password_hash='must-never-return', custom_claims={'private': 'never-return'})
        self.users = patch.object(admin_usage.auth, 'list_users', return_value=types.SimpleNamespace(users=[self.user], next_page_token='next-fixture'))
        self.list_users = self.users.start()
        self.addCleanup(self.users.stop)
        self.account = patch.object(admin_usage.auth, 'get_user', return_value=self.user)
        self.get_user = self.account.start()
        self.addCleanup(self.account.stop)

    def put(self, **data):
        return self.client.put('/api/admin/usage/limits', json=data, headers=self.headers)

    def test_admin_only_list_and_write(self):
        self.assertEqual(self.client.get('/api/admin/usage').status_code, 403)
        self.assertEqual(self.client.put('/api/admin/usage/limits', json={}).status_code, 403)
        self.list_users.assert_not_called()
        self.assertEqual(self.store.writes, [])

    def test_paginated_safe_account_fields_and_headers(self):
        response = self.client.get('/api/admin/usage?pageSize=5&pageToken=fixture', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.list_users.assert_called_once_with(page_token='fixture', max_results=5)
        payload = response.json
        self.assertEqual(payload['accounts'][0]['usage']['daily'], 0)
        self.assertEqual(payload['accounts'][0]['overrideGeneration'], '0')
        self.assertEqual(payload['nextPageToken'], 'next-fixture')
        self.assertIn('+00:00', payload['resets']['daily'])
        self.assertNotIn('never-return', response.text)
        self.assertIn('private', response.headers['Cache-Control'])
        self.assertEqual(self.store.writes, [])

    def test_write_global_and_account_then_inherit_preserves_queue(self):
        self.store.write(admission_policy.queue_key('alice'), {'usage': {'monthly': 3}}, 0)
        self.assertEqual(self.put(scope='global', generation='0', daily=8, monthly=30).status_code, 200)
        self.assertEqual(self.put(scope='account', uid='alice', generation='0', daily=2, monthly=10).status_code, 200)
        self.assertEqual(admission_policy.effective_limits(self.store, 'alice'), {'daily': 2, 'monthly': 10})
        result = self.put(scope='account', uid='alice', generation='1', inherit=True)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(admission_policy.effective_limits(self.store, 'alice'), {'daily': 8, 'monthly': 30})
        self.assertEqual(self.store.read(admission_policy.queue_key('alice'))[0], {'usage': {'monthly': 3}})

    def test_stale_generation_conflict(self):
        self.put(scope='global', generation='0', daily=3, monthly=10)
        self.assertEqual(self.put(scope='global', generation='0', daily=9, monthly=10).status_code, 409)
        self.assertEqual(admission_policy.effective_limits(self.store)['daily'], 3)

    def test_strict_limits_and_generation_validation(self):
        for daily in (True, -1, 10001, '2', 2.5, None):
            self.assertEqual(self.put(scope='global', generation='0', daily=daily, monthly=10).status_code, 400)
        for generation in (0, '-1', 'x', True, None):
            self.assertEqual(self.put(scope='global', generation=generation, daily=2, monthly=10).status_code, 400)
        self.assertEqual(self.put(scope='global', generation='0', inherit=True).status_code, 400)
        self.assertEqual(self.store.writes, [])

    def test_cross_origin_cannot_write(self):
        result = self.client.put('/api/admin/usage/limits', json={'scope': 'global', 'generation': '0', 'daily': 1, 'monthly': 2},
                                 headers={**self.headers, 'Origin': 'https://attacker.example'})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.store.writes, [])

    def test_bad_pagination_rejected_before_provider(self):
        for query in ('pageSize=51', 'pageSize=0', 'pageSize=abc', 'pageToken='):
            self.assertEqual(self.client.get('/api/admin/usage?'+query, headers=self.headers).status_code, 400)
        self.list_users.assert_not_called()

    def test_provider_failure_sanitized_no_false_zero(self):
        self.list_users.side_effect = RuntimeError('private-provider-token')
        response = self.client.get('/api/admin/usage', headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-provider-token', response.text)
        self.assertNotIn('accounts', response.json)

    def test_current_utc_usage_and_remaining(self):
        from datetime import datetime, timezone
        now = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp()
        self.store.write(admission_policy.queue_key('alice'), {'usage': {'day': '2026-12-31', 'month': '2026-12', 'daily': 3, 'monthly': 12}}, 0)
        with patch.object(admin_usage.time, 'time', return_value=now):
            response = self.client.get('/api/admin/usage', headers=self.headers)
        self.assertEqual(response.json['accounts'][0]['usage']['daily'], 3)
        self.assertEqual(response.json['resets']['monthly'], '2027-01-01T00:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
