"""Real application middleware must deny usage access before any storage call."""
import unittest
from unittest.mock import patch

import app as core


class UsagePolicyTests(unittest.TestCase):
    def test_unsigned_and_non_admin_requests_never_reach_storage(self):
        client = core.app.test_client()
        def other():
            core.g.google_identity = {'uid': 'other', 'email': 'other@example.test'}
        for method, path in [('get', '/api/admin/usage'), ('put', '/api/admin/usage/limits')]:
            with self.subTest(method=method), patch('job_runtime.JobStore') as store, patch.object(core.user_accounts, 'scope') as scope:
                with patch.object(core, 'verify_google_identity', side_effect=core.AppError('session', 401)):
                    self.assertEqual(getattr(client, method)(path).status_code, 401)
                with patch.object(core, 'ORIGINAL_OWNER_EMAIL', 'owner@example.test'), patch.object(core, 'verify_google_identity', side_effect=other):
                    self.assertEqual(getattr(client, method)(path).status_code, 403)
                store.assert_not_called()
                scope.assert_not_called()
