"""Per-account limits: CAS races, retries, rollover and Telegram callback parity."""
import copy
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace
from flask import Flask

from google.api_core.exceptions import PreconditionFailed
import job_runtime
import telegram_bot


class Store:
    admit = job_runtime.JobStore.admit

    def __init__(self):
        self.jobs = {}
        self.lock = threading.RLock()

    def read(self, key):
        with self.lock:
            return copy.deepcopy(self.jobs.get(key, (None, 0)))

    def write(self, key, data, generation):
        with self.lock:
            if self.read(key)[1] != generation:
                raise PreconditionFailed('fixture conflict')
            self.jobs[key] = (copy.deepcopy(data), generation + 1)

    def done(self, key):
        _, generation = self.read(key)
        self.write(key, {'state': 'done'}, generation)


class PeriodAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.policy = patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': '3', 'CV_MONTHLY_JOB_LIMIT': '5'})
        self.policy.start()
        self.addCleanup(self.policy.stop)
        self.now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc).timestamp()
        self.clock = patch('job_runtime.time.time', return_value=self.now)
        self.clock_value = self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_completed_work_still_counts_and_duplicate_does_not(self):
        store = Store()
        for identifier in ('web-one', 'direct-two', '123'):
            self.assertTrue(store.admit(identifier, 'alice'))
            store.done(identifier)
        self.assertTrue(store.admit('web-one', 'alice'))
        with self.assertRaises(job_runtime.AdmissionLimit) as error:
            store.admit('fourth', 'alice')
        self.assertEqual(error.exception.period, 'day')
        self.assertGreater(error.exception.retry_after, 0)
        self.assertTrue(store.admit('fourth', 'bob'))

    def test_daily_rollover_keeps_monthly_total_and_month_rollover_resets(self):
        store = Store()
        for index in range(3):
            key = str(index)
            store.admit(key, 'alice'); store.done(key)
        self.clock_value.return_value = self.now + 86400
        for key in ('3', '4'):
            store.admit(key, 'alice'); store.done(key)
        with self.assertRaises(job_runtime.AdmissionLimit) as error:
            store.admit('5', 'alice')
        self.assertEqual(error.exception.period, 'month')
        self.clock_value.return_value = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
        self.assertTrue(store.admit('6', 'alice'))

    def test_zero_limit_blocks_new_work_but_not_existing_pending(self):
        store = Store()
        store.admit('existing', 'alice')
        with patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': '0'}):
            self.assertTrue(store.admit('existing', 'alice'))
            with self.assertRaises(job_runtime.AdmissionLimit):
                store.admit('new', 'alice')

    def test_invalid_configuration_fails_closed(self):
        for value in ('invalid', '-1', '1.5', '100000000'):
            with self.subTest(value=value), patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': value}):
                with self.assertRaises(job_runtime.JobError):
                    Store().admit('new', 'alice')

    def test_concurrent_new_jobs_cannot_exceed_daily_limit(self):
        store = Store()
        def submit(index):
            try:
                return store.admit(str(index), 'alice')
            except job_runtime.JobError:
                return False
        with ThreadPoolExecutor(max_workers=10) as pool:
            accepted = list(pool.map(submit, range(10)))
        self.assertEqual(sum(accepted), 3)

    def test_queue_full_does_not_consume_period_allowance(self):
        store = Store()
        with patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': '11', 'CV_MONTHLY_JOB_LIMIT': '20'}):
            for index in range(10):
                store.admit(str(index), 'alice')
            self.assertFalse(store.admit('rejected', 'alice'))
            store.done('0')
            self.assertTrue(store.admit('eleventh', 'alice'))
            store.done('1')
            with self.assertRaises(job_runtime.AdmissionLimit):
                store.admit('twelfth', 'alice')

    def test_active_delivery_still_occupies_pending_slot(self):
        store = Store()
        with patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': '20', 'CV_MONTHLY_JOB_LIMIT': '20'}):
            for index in range(10):
                store.admit(str(index), 'alice')
                store.write(str(index), {'state': 'delivery_started', 'lease_until': self.now + 300}, 0)
            self.assertFalse(store.admit('eleventh', 'alice'))

    def test_ten_simultaneous_accounts_share_no_slots_or_period_usage(self):
        store = Store()
        def session(index):
            uid = 'pilot-' + str(index)
            first = [store.admit(f'{uid}-{step}', uid) for step in range(3)]
            try:
                store.admit(uid + '-over-limit', uid)
            except job_runtime.AdmissionLimit:
                return all(first)
            return False
        with ThreadPoolExecutor(max_workers=10) as pool:
            self.assertTrue(all(pool.map(session, range(10))))

    def test_december_monthly_reset_handles_year_boundary(self):
        store = Store()
        self.clock_value.return_value = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp()
        with patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': '5', 'CV_MONTHLY_JOB_LIMIT': '0'}):
            with self.assertRaises(job_runtime.AdmissionLimit) as error:
                store.admit('new', 'alice')
        self.assertEqual(error.exception.retry_after, 60)


class TelegramAdmissionTests(unittest.TestCase):
    def test_gmail_callback_cannot_bypass_full_queue(self):
        app = Flask('telegram-admission')
        telegram_bot.register_routes(app, SimpleNamespace())
        store = Store()
        store.write('10', {'state': 'done', 'owner_id': 123}, 0)
        config = {'owner_id': 123, 'bot_token': 'synthetic', 'webhook_secret': 'synthetic'}
        update = {'update_id': 20, 'callback_query': {'id': 'fixture-callback', 'data': 'gmail:10:0',
            'from': {'id': 123}, 'message': {'chat': {'id': 123, 'type': 'private'}}}}
        with patch.dict(os.environ, {'CV_MULTI_ACCOUNT': '0'}), \
             patch.object(job_runtime, 'configuration', return_value=config), \
             patch.object(job_runtime, 'JobStore', return_value=store), \
             patch.object(Store, 'admit', return_value=False) as admission, \
             patch.object(job_runtime, 'enqueue') as enqueue, \
             patch.object(telegram_bot, 'telegram'):
            response = app.test_client().post('/telegram/webhook', json=update,
                headers={'X-Telegram-Bot-Api-Secret-Token': 'synthetic'})
        self.assertEqual(response.status_code, 200)
        admission.assert_called_once()
        enqueue.assert_not_called()
        self.assertIsNone(store.read('20')[0])

    def test_http_quota_response_includes_retry_after_and_machine_code(self):
        import app as core
        with core.app.test_request_context('/'):
            response = core.handle_admission_limit(job_runtime.AdmissionLimit('month', 600))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '600')
        self.assertEqual(response.json['code'], 'period_quota_exceeded')
        self.assertEqual(response.json['period'], 'month')


if __name__ == '__main__':
    unittest.main()
