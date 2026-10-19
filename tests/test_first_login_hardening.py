"""Failed generations, simultaneous devices and recoverable setup; no live providers."""
import os
import io
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock
from types import SimpleNamespace
from flask import g, request
import app
import admission_policy
import background_jobs
import job_runtime
import user_accounts as users
import web_notifications
from test_period_admission import Store
from test_user_accounts import ALICE, Drive
from test_telegram import MemoryStore, CONFIG, message
import telegram_bot


class FailedGenerationTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        def verify():
            uid = request.headers.get('X-Fixture-User', 'alice')
            g.google_identity = {'uid': uid, 'email': uid + '@example.invalid', 'name': uid}
        for fixture in (
            patch.dict(os.environ, {'CV_AUTH_REQUIRED':'1', 'CV_MULTI_ACCOUNT':'1', 'CV_ALLOW_REMOTE':'1',
                                    'CV_BANK_PROVIDER':'local', 'CV_DAILY_JOB_LIMIT':'3', 'CV_MONTHLY_JOB_LIMIT':'30'}),
            patch.object(app, 'verify_google_identity', side_effect=verify),
            patch.object(app, 'bank_enabled', return_value=False),
            patch.object(job_runtime, 'JobStore', return_value=self.store),
        ):
            fixture.start(); self.addCleanup(fixture.stop)

    def usage(self, uid='alice'):
        queue, _ = self.store.read(admission_policy.queue_key(uid))
        return admission_policy.usage_summary(queue, time.time(), {'daily':3, 'monthly':30})

    def test_repeated_invalid_cv_requests_do_not_consume_or_exhaust_slots(self):
        client = app.app.test_client()
        for _ in range(15):
            self.assertEqual(client.post('/api/draft', json={}).status_code, 400)
        self.assertEqual(self.usage()['daily'], 0)
        self.assertEqual(self.usage()['monthly'], 0)
        with patch.object(app, 'make_draft', return_value={'position':'Test'}):
            self.assertEqual(client.post('/api/draft', json={'analysis':{}}).status_code, 200)
        self.assertEqual(self.usage()['daily'], 1)

    def test_successful_cv_still_consumes_one_and_respects_limit(self):
        client = app.app.test_client()
        with patch.object(app, 'make_draft', return_value={'position':'Test'}):
            for _ in range(3):
                self.assertEqual(client.post('/api/draft', json={'analysis':{}}).status_code, 200)
            self.assertEqual(client.post('/api/draft', json={'analysis':{}}).status_code, 429)
        self.assertEqual(self.usage()['daily'], 3)

    def test_worker_failure_refunds_once_even_when_delivered_again(self):
        identifier = 'web-12345678-1234-1234-1234-123456789012'
        self.store.admit(identifier, 'alice')
        self.store.write(identifier, {'owner_uid':'alice', 'owner_email':'alice@example.invalid',
            'operation':'draft', 'path':'/api/draft', 'payload':{}, 'state':'queued', 'created_at':time.time()}, 0)
        with patch.object(web_notifications, 'unprotect', return_value={}), patch.object(web_notifications, 'notify'):
            background_jobs.process_job(app, identifier, self.store)
            background_jobs.process_job(app, identifier, self.store)
        self.assertEqual(self.store.read(identifier)[0]['state'], 'failed')
        self.assertEqual(self.usage()['daily'], 0)

    def test_concurrent_refunds_do_not_reduce_another_completed_cv(self):
        self.store.admit('completed', 'alice'); self.store.done('completed')
        self.store.admit('failed', 'alice')
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _:job_runtime.refund_usage(self.store, 'failed', 'alice'), range(36)))
        self.assertEqual(self.usage()['daily'], 1)
        self.assertEqual(self.usage()['monthly'], 1)

    def test_refund_previous_day_does_not_reduce_today(self):
        yesterday = time.time() - 86400
        with patch.object(job_runtime.time, 'time', return_value=yesterday):
            self.store.admit('yesterday', 'alice'); self.store.done('yesterday')
        self.store.admit('today', 'alice')
        job_runtime.refund_usage(self.store, 'yesterday', 'alice')
        self.assertEqual(self.usage()['daily'], 1)
        self.assertEqual(self.usage()['monthly'], 1)

    def test_failed_account_does_not_refund_other_account(self):
        self.store.admit('same-id', 'alice')
        self.store.admit('same-id', 'bob')
        job_runtime.refund_usage(self.store, 'same-id', 'alice')
        self.assertEqual(self.usage('alice')['daily'], 0)
        self.assertEqual(self.usage('bob')['daily'], 1)

    def test_job_creation_storage_failure_does_not_leave_quota_or_slots(self):
        original = self.store.write
        def fail_job_only(key, data, generation):
            if key.startswith('direct-'):
                raise job_runtime.JobError('Synthetic storage outage')
            return original(key, data, generation)
        with patch.object(self.store, 'write', side_effect=fail_job_only):
            for _ in range(12):
                self.assertEqual(app.app.test_client().post('/api/draft', json={}).status_code, 503)
        self.assertEqual(self.usage()['daily'], 0)
        self.assertEqual(self.store.read(admission_policy.queue_key('alice'))[0]['pending'], [])

    def test_expired_direct_reservation_is_recovered_without_refunding_success(self):
        yesterday = time.time() - 700
        with patch.object(job_runtime.time, 'time', return_value=yesterday):
            self.store.admit('direct-crashed', 'alice')
        self.store.write('direct-crashed', {'state':'processing', 'lease_until':yesterday+600}, 0)
        self.store.admit('next', 'alice')
        self.assertEqual(self.usage()['daily'], 1)

    def test_failed_credential_protection_does_not_reserve_a_cv(self):
        payload = {'request_id':'12345678-1234-1234-1234-123456789012', 'path':'/api/draft', 'payload':{}}
        with patch.object(web_notifications, 'protect', side_effect=app.AppError('Synthetic failure', 503)):
            self.assertEqual(app.app.test_client().post('/api/background/jobs', json=payload).status_code, 503)
        self.assertEqual(self.usage()['daily'], 0)

    def test_capacity_probe_never_consumes_quota(self):
        for _ in range(10):
            self.assertTrue(self.store.admit('probe', 'alice', probe=True))
        self.assertIsNone(self.store.read(admission_policy.queue_key('alice'))[0])

    def test_concurrent_success_and_failure_bill_only_completed_cvs(self):
        def make_draft(analysis):
            if analysis is None:
                raise app.AppError('Synthetic invalid input', 400)
            return {'position':'Test'}
        def submit(index):
            payload = {} if index % 2 else {'analysis':{}}
            with app.app.test_client() as client:
                return client.post('/api/draft', json=payload).status_code
        with patch.object(app, 'make_draft', side_effect=make_draft), ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(submit, range(40)))
        completed = statuses.count(200)
        self.assertGreater(completed, 0)
        self.assertLessEqual(completed, 3)
        self.assertEqual(self.usage()['daily'], completed)
        self.assertEqual(self.usage()['monthly'], completed)

    def test_refund_across_month_boundary_keeps_new_month_consumption(self):
        from datetime import datetime, timezone
        before = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc).timestamp()
        after = datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc).timestamp()
        with patch.object(job_runtime.time, 'time', return_value=before):
            self.store.admit('old-month', 'alice'); self.store.done('old-month')
        with patch.object(job_runtime.time, 'time', return_value=after):
            self.store.admit('new-month', 'alice')
        job_runtime.refund_usage(self.store, 'old-month', 'alice')
        queue, _ = self.store.read(admission_policy.queue_key('alice'))
        self.assertEqual(queue['usage']['daily'], 1)
        self.assertEqual(queue['usage']['monthly'], 1)

    def test_expired_permissions_before_worker_generation_refund_the_reservation(self):
        identifier = 'web-12345678-1234-1234-1234-123456789012'
        self.store.admit(identifier, 'alice')
        self.store.write(identifier, {'owner_uid':'alice', 'owner_email':'alice@example.invalid',
            'operation':'draft', 'state':'queued', 'created_at':time.time()}, 0)
        with patch.object(users, 'scope', side_effect=app.AppError('Grant expired', 401)), \
             patch.object(web_notifications, 'unprotect', return_value={}), patch.object(web_notifications, 'notify'):
            background_jobs.process_job(app, identifier, self.store)
        self.assertEqual(self.store.read(identifier)[0]['state'], 'failed')
        self.assertEqual(self.usage()['daily'], 0)


class TelegramQuotaOutcomeTests(unittest.TestCase):
    def run_job(self, failure):
        store = MemoryStore()
        store.admit('1')
        store.write('1', {'state':'queued', 'message':message(), 'created_at':time.time()}, 0)
        core = SimpleNamespace(AppError=app.AppError, MAX_FILE_BYTES=1000, VERTEX_MODEL='synthetic',
            VacancySelectionRequired=app.VacancySelectionRequired, app=SimpleNamespace(logger=Mock()),
            load_drive_bank=Mock(return_value={'pending':0}), extract_vacancy=Mock(return_value=('Test', [])),
            analyze_with_model=Mock(return_value={}), make_draft=Mock(return_value={'position':'Test'}),
            make_pdf=Mock(return_value=io.BytesIO(b'pdf')))
        if failure == 'analysis':
            core.analyze_with_model.side_effect = app.AppError('Synthetic model failure', 503)
        def archive(*args):
            if failure == 'archive': raise app.AppError('Synthetic archive failure', 503)
            return 'https://drive.google.com/file/d/synthetic/view'
        def telegram(config, method, data, **kwargs):
            if failure == 'delivery' and method == 'sendDocument':
                raise job_runtime.JobError('Synthetic lost confirmation')
            return {'message_id':42}
        with patch.object(telegram_bot, 'drive_token', return_value='synthetic'), \
             patch.object(telegram_bot, 'vacancy_payload', return_value={}), patch.object(telegram_bot, 'progress'), \
             patch.object(telegram_bot, 'say'), patch.object(telegram_bot, 'archive_pdf', side_effect=archive), \
             patch.object(telegram_bot, 'telegram', side_effect=telegram), patch.object(telegram_bot, 'auto_send_application'):
            telegram_bot.process_job(core, CONFIG, '1', store)
            telegram_bot.process_job(core, CONFIG, '1', store)
        queue, _ = store.read(admission_policy.queue_key())
        return store.read('1')[0], queue['usage']['daily']

    def test_model_failure_refunds_telegram_generation(self):
        job, count = self.run_job('analysis')
        self.assertEqual(job['state'], 'failed'); self.assertEqual(count, 0)

    def test_unsaved_pdf_failure_does_not_charge_the_user(self):
        job, count = self.run_job('archive')
        self.assertTrue(job['pdf_ready']); self.assertEqual(count, 0)

    def test_lost_delivery_confirmation_keeps_the_single_recoverable_cv_charge(self):
        job, count = self.run_job('delivery')
        self.assertEqual(job['state'], 'delivery_started')
        self.assertTrue(job['drive_url']); self.assertEqual(count, 1)


class ConcurrentSetupTests(unittest.TestCase):
    def setUp(self):
        self.store, self.drive = Store(), Drive()
        self.identity = patch.object(users, 'assert_drive_identity')
        self.identity.start(); self.addCleanup(self.identity.stop)
        self.upload = patch.object(app, 'drive_request', side_effect=self.drive.request)
        self.upload.start(); self.addCleanup(self.upload.stop)

    def test_two_devices_create_only_one_bank_and_retry_reuses_it(self):
        entered, release = threading.Event(), threading.Event()
        held = False
        lock = threading.Lock()
        def api(*args, **kwargs):
            nonlocal held
            with lock:
                pause = not held
                held = True
            if pause:
                entered.set(); self.assertTrue(release.wait(timeout=5))
            return self.drive.api(*args, **kwargs)
        with patch.object(users, 'api', side_effect=api), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(users.prepare, app, ALICE, 'fixture', None, self.store)
            self.assertTrue(entered.wait(timeout=3))
            try:
                with self.assertRaises(app.AppError) as failure:
                    users.prepare(app, ALICE, 'fixture', store=self.store)
                self.assertEqual(failure.exception.status_code, 409)
            finally:
                release.set()
            original = first.result(timeout=5)
            count = self.drive.created
            retried = users.prepare(app, ALICE, 'fixture', store=self.store)
        self.assertEqual(original, retried)
        self.assertEqual(self.drive.created, count)
        self.assertEqual(sum(item['name']=='Banco de Datos' for item in self.drive.files.values()), 1)
        self.assertEqual(sum(item['name']=='CV Generados' for item in self.drive.files.values()), 1)

    def test_partial_failure_releases_lease_and_reuses_created_folder(self):
        failed = False
        def api(core, token, method, path, payload=None):
            nonlocal failed
            if method == 'POST' and payload['name'] == 'CV Generados' and not failed:
                failed = True
                raise app.AppError('Provider unavailable', 503)
            return self.drive.api(core, token, method, path, payload)
        with patch.object(users, 'api', side_effect=api):
            with self.assertRaises(app.AppError):
                users.prepare(app, ALICE, 'fixture', store=self.store)
            result = users.prepare(app, ALICE, 'fixture', store=self.store)
        self.assertTrue(result['bank']['folder_id'])
        self.assertEqual(sum(item['name']=='Banco de Datos' for item in self.drive.files.values()), 1)

    def test_expired_lease_is_recoverable_and_guard_is_cleared(self):
        key = 'setup-' + users.account_key(ALICE['uid'])
        self.store.write(key, {'holder':'old-instance', 'expires_at':0}, 0)
        with patch.object(users, 'api', side_effect=self.drive.api):
            users.prepare(app, ALICE, 'fixture', store=self.store)
        self.assertIsNone(users.SETUP_GUARD.get())
        self.assertEqual(self.store.read(key)[0]['expires_at'], 0)

    def test_lost_lease_cannot_commit_or_release_another_holder(self):
        key = 'setup-' + users.account_key(ALICE['uid'])
        def api(*args, **kwargs):
            lease, version = self.store.read(key)
            self.store.write(key, {'holder':'other-instance', 'expires_at':time.time()+180}, version)
            return self.drive.api(*args, **kwargs)
        with patch.object(users, 'api', side_effect=api), self.assertRaises(app.AppError):
            users.prepare(app, ALICE, 'fixture', store=self.store)
        self.assertIsNone(self.store.read(users.account_key(ALICE['uid']))[0])
        self.assertEqual(self.store.read(key)[0]['holder'], 'other-instance')
