"""Moved account routes must still receive the running application core."""
import os
import unittest
from unittest.mock import patch
from flask import g
import app
import job_runtime
import onboarding
import user_accounts
from test_telegram import MemoryStore


class AccountRouteContractTests(unittest.TestCase):
    def test_account_setup_and_onboarding_pass_the_application_core(self):
        store = MemoryStore()
        identity = {'uid': 'route-test', 'email': 'route@example.com', 'name': 'Route'}

        def verify():
            g.google_identity = identity

        with patch.dict(os.environ, {'CV_MULTI_ACCOUNT': '1', 'CV_AUTH_REQUIRED': '1', 'CV_ALLOW_REMOTE': '1'}), \
             patch.object(app, 'verify_google_identity', side_effect=verify), \
             patch.object(job_runtime, 'JobStore', return_value=store), \
             patch.object(user_accounts, 'prepare', return_value={}) as prepare, \
             patch.object(onboarding, 'status', return_value={'needed': True}) as status, \
             patch.object(onboarding, 'save', return_value={'saved': []}) as save:
            with app.app.test_client() as client:
                self.assertEqual(client.post('/api/account/setup', json={}).status_code, 200)
                self.assertIs(prepare.call_args.args[0], app)
                self.assertEqual(client.get('/api/account/onboarding').json, {'needed': True})
                status.assert_called_once_with(app, store)
                response = client.post('/api/account/onboarding', data={'data': '{"name":"Route"}'})
                self.assertEqual(response.status_code, 200)
                save.assert_called_once_with(app, {'name': 'Route'}, None, store, reference=None)
