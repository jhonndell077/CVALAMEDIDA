"""Regression checks for overlapping accounts and nested worker scopes."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import g, request
import app
import job_runtime
import user_accounts
from test_telegram import MemoryStore


class AccountContextTests(unittest.TestCase):
    def test_simultaneous_profile_requests_never_share_identity_or_indexes(self):
        barrier = threading.Barrier(2)
        original = app.MASTER_PROFILE

        def verify():
            uid = request.headers['X-Test-User']
            g.google_identity = {'uid': uid, 'email': uid+'@example.com', 'name': uid}

        def load_bank():
            barrier.wait(timeout=5)
            self.assertEqual(app.MASTER_PROFILE['candidate']['name'], user_accounts.owner())
            self.assertEqual(app.EXPERIENCE_BY_ID, {})
            return {'pending': 0}

        def fetch(uid):
            with app.app.test_client() as client:
                response = client.get('/api/profile', headers={'X-Test-User': uid})
                self.assertEqual(response.status_code, 200)
                return response.json['candidate']['name']

        with patch.dict(os.environ, {'CV_MULTI_ACCOUNT': '1', 'CV_AUTH_REQUIRED': '1', 'CV_ALLOW_REMOTE': '1'}), \
             patch.object(app, 'verify_google_identity', side_effect=verify), \
             patch.object(app, 'bank_enabled', return_value=True), \
             patch.object(app, 'load_drive_bank', side_effect=load_bank), \
             patch.object(job_runtime, 'JobStore', return_value=MemoryStore()):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(fetch, uid) for uid in ('alice', 'bob')]
                self.assertEqual([future.result(timeout=10) for future in futures], ['alice', 'bob'])
        self.assertIs(app.MASTER_PROFILE, original)
        self.assertIsNone(user_accounts.CURRENT.get())

    def test_nested_worker_context_restores_outer_account_after_failure(self):
        original = app.MASTER_PROFILE
        store = MemoryStore()
        alice = {'uid': 'alice', 'email': 'alice@example.com', 'name': 'Alice'}
        bob = {'uid': 'bob', 'email': 'bob@example.com', 'name': 'Bob'}
        with user_accounts.scope(app, alice, store=store):
            outer = app.MASTER_PROFILE
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                with user_accounts.scope(app, bob, store=store):
                    self.assertEqual(app.MASTER_PROFILE['candidate']['name'], 'Bob')
                    app.MASTER_PROFILE['skills'] = [{'id': 'bob-skill', 'label': 'Bob skill'}]
                    app.refresh_profile_indexes()
                    self.assertEqual(app.profile_context()['skills'][0]['id'], 'bob-skill')
                    raise RuntimeError('interrupted')
            self.assertIs(app.MASTER_PROFILE, outer)
            self.assertEqual(user_accounts.owner(), 'alice')
            self.assertEqual(app.MASTER_PROFILE['candidate']['name'], 'Alice')
            self.assertEqual(app.profile_context()['skills'], [])
            self.assertEqual(app.SKILL_BY_ID, {})
        self.assertIs(app.MASTER_PROFILE, original)
        self.assertIsNone(user_accounts.CURRENT.get())
