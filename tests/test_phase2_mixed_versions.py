"""Adjacent API/worker versions, executed offline against an in-memory store.

The historical fixture is git show 6232e11:background_jobs.py (pre Phase 2).
It is code from this repository, never a downloaded dependency.
"""
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch
from flask import Flask
import app
import background_jobs as current
import job_runtime
import web_notifications
from tests.test_background_jobs import Store, job, ID


def previous():
    module = ModuleType('phase2_previous_background_jobs')
    source = Path(__file__).with_name('fixtures') / 'background_jobs_6232e11.txt'
    exec(compile(source.read_text(encoding='utf-8-sig'), str(source), 'exec'), module.__dict__)
    return module


class MixedVersionTests(unittest.TestCase):
    def status(self, module, store):
        isolated = Flask('mixed-version-fixture')
        module.register_routes(isolated, app)
        with patch.object(job_runtime, 'JobStore', return_value=store), \
             patch.object(module.user_accounts, 'require_owner'), \
             patch.object(job_runtime, 'enqueue') as enqueue:
            response = isolated.test_client().post('/api/background/jobs/' + ID, json={})
        self.assertEqual(response.status_code, 200)
        enqueue.assert_not_called()
        return response.json

    def test_old_worker_failure_is_normalized_by_new_api_without_replaying(self):
        old = previous()
        store = Store()
        job(store, '/api/bank/sync')
        with patch.object(app, 'bank_enabled', return_value=True), \
             patch.object(app, 'load_drive_bank', return_value={'pending': 0, 'warnings': [{'message': 'Fixture review'}]}), \
             patch.object(web_notifications, 'notify'):
            old.process_job(app, ID, store)
        saved = store.read(ID)[0]
        self.assertEqual(saved['errorCode'], 'bank_review_required')
        self.assertNotIn('safeNextAction', saved)
        first = self.status(current, store)
        second = self.status(current, store)
        self.assertEqual(first['code'], 'bank_review_required')
        self.assertEqual(first['safeNextAction'], 'review_bank')
        self.assertEqual(first['correlationId'], second['correlationId'])
        self.assertEqual(store.read(ID)[0], saved)

    def test_new_worker_failure_remains_readable_by_old_api_and_client(self):
        store = Store()
        job(store, created_at=0)
        with patch.object(web_notifications, 'notify'):
            current.process_job(app, ID, store)
        self.assertEqual(store.read(ID)[0]['errorCode'], 'job_authorization_expired')
        result = self.status(previous(), store)
        self.assertEqual(result['state'], 'failed')
        self.assertIsInstance(result['error'], str)
        self.assertIn('autorización', result['error'].lower())
        self.assertNotIn('credentials', result)

    def test_completed_old_record_remains_unchanged_and_does_not_restart(self):
        store = Store()
        expected = {'analysis': {'vacancy': {'position': 'Fixture'}}}
        job(store, state='done', progress=100, result=expected)
        for module in (previous(), current):
            result = self.status(module, store)
            self.assertEqual(result['result'], expected)
            self.assertEqual(result['state'], 'done')
