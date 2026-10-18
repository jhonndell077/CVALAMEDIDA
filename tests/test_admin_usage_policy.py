"""Real application middleware must deny usage access before any storage call."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as core


class UsagePolicyTests(unittest.TestCase):
    def test_unsigned_and_non_admin_requests_never_reach_storage(self):
        client = core.app.test_client()
        def other():
            core.g.google_identity = {'uid': 'other', 'email': 'other@example.test'}
        for method, path in [('get', '/api/admin/usage'), ('put', '/api/admin/usage/limits'),
                             ('post', '/api/admin/users/action/preview'),
                             ('post', '/api/admin/users/action/execute'),
                             ('put', '/api/admin/users/plan'),
                             ('put', '/api/admin/plans/catalog')]:
            with self.subTest(method=method), patch('job_runtime.JobStore') as store, patch.object(core.user_accounts, 'scope') as scope:
                with patch.object(core, 'verify_google_identity', side_effect=core.AppError('session', 401)):
                    self.assertEqual(getattr(client, method)(path).status_code, 401)
                with patch.object(core, 'ORIGINAL_OWNER_EMAIL', 'owner@example.test'), patch.object(core, 'verify_google_identity', side_effect=other):
                    self.assertEqual(getattr(client, method)(path).status_code, 403)
                store.assert_not_called()
                scope.assert_not_called()

    def test_own_subscription_requires_identity_but_not_admin_or_drive(self):
        client = core.app.test_client()
        with patch.object(core, 'verify_google_identity', side_effect=core.AppError('session', 401)), patch('job_runtime.JobStore') as store:
            self.assertEqual(client.get('/api/subscription').status_code, 401)
            store.assert_not_called()
        def identity():
            core.g.google_identity = {'uid': 'viewer', 'email': 'viewer@example.test'}
        fake = SimpleNamespace(read=lambda key: (None, 0))
        with patch.object(core, 'verify_google_identity', side_effect=identity), patch('job_runtime.JobStore', return_value=fake), patch.object(core.user_accounts, 'scope') as scope:
            response = client.get('/api/subscription')
            self.assertEqual(response.status_code, 200)
            self.assertIn('private', response.headers['Cache-Control'])
            scope.assert_not_called()
