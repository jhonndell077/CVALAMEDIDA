import copy
import time
import unittest
from unittest.mock import patch
from google.api_core.exceptions import PreconditionFailed
import app
import admission_policy
import job_runtime
import web_notifications
from test_period_admission import Store
import test_first_login_hardening as login_fixtures


class DispatchRecoveryTests(unittest.TestCase):
    setUp = login_fixtures.FailedGenerationTests.setUp
    usage = login_fixtures.FailedGenerationTests.usage

    def test_durable_dispatch_failure_explicit_retry_reuses_job_and_single_reservation(self):
        payload = dict(request_id='12345678-1234-1234-1234-123456789012', path='/api/draft', payload={})
        client = app.app.test_client()
        with patch.object(web_notifications, 'protect', return_value=None), \
             patch.object(job_runtime, 'configuration', return_value={}), \
             patch.object(job_runtime, 'enqueue', side_effect=[RuntimeError('private-provider-details'), None]) as enqueue:
            failed = client.post('/api/background/jobs', json=payload)
            self.assertEqual(failed.status_code, 503)
            self.assertEqual(failed.json['code'], 'job_dispatch_unavailable')
            self.assertEqual(failed.json['job_id'], 'web-' + payload['request_id'])
            self.assertNotIn('private-provider', failed.text)
            retry = client.post('/api/background/jobs', json=payload)
            self.assertEqual(retry.status_code, 202)
            self.assertEqual(retry.json['job_id'], failed.json['job_id'])
            self.assertEqual(enqueue.call_args_list[0], enqueue.call_args_list[1])
        self.assertEqual(self.usage()['daily'], 1)

    def test_maintenance_is_precise_and_never_removed_by_retry(self):
        key = admission_policy.queue_key('alice')
        queue = dict(pending=[], maintenance={'action': 'delete_user'})
        self.store.write(key, queue, 0)
        response = app.app.test_client().post('/api/background/jobs', json=dict(
            request_id='12345678-1234-1234-1234-123456789012', path='/api/bank/sync', payload={}))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['code'], 'job_account_maintenance')
        self.assertNotIn('job_id', response.json)
        self.assertEqual(self.store.read(key)[0], queue)

    def test_safe_google_reason_reaches_client_without_other_exception_attributes(self):
        error = app.AppError('Vuelve a conectar tu cuenta.', 401)
        error.code = 'google_authorization_expired'
        error.token = 'private'
        with app.app.test_request_context():
            response, status = app.handle_app_error(error)
        self.assertEqual(status, 401)
        self.assertEqual({key: response.json[key] for key in ('error', 'code')},
                         {'error': str(error), 'code': error.code})
        self.assertEqual(response.json['safeNextAction'], 'reauthorize')
        self.assertNotIn('private', response.get_data(as_text=True))
        self.assertNotIn('token', response.json)

    def test_session_state_real_middleware_requires_verified_identity_and_never_drive_scope(self):
        with patch.object(app, 'verify_google_identity', side_effect=app.AppError('Denied', 401)), \
             patch.object(app.user_accounts, 'scope') as scope:
            response = app.app.test_client().get('/api/session/state')
            self.assertEqual(response.status_code, 401)
            scope.assert_not_called()


class ExpiredQueueRecoveryTests(unittest.TestCase):
    def store_with_job(self, **changes):
        store = Store()
        identifier = 'web-12345678-1234-1234-1234-123456789012'
        with patch.object(job_runtime.time, 'time', return_value=time.time() - 4000):
            store.admit(identifier, 'alice')
        store.write(identifier, dict(owner_uid='alice', operation='draft', state='queued',
            created_at=time.time()-4000, payload={'text':'preserved'}, credentials='fixture', **changes), 0)
        return store, identifier

    def test_undispatched_expired_queue_recovers_without_deleting_user_data(self):
        store, identifier = self.store_with_job()
        self.assertTrue(store.admit('new-sync', 'alice', charge=False))
        expired = store.read(identifier)[0]
        self.assertEqual(expired['state'], 'failed')
        self.assertEqual(expired['payload'], {'text':'preserved'})
        self.assertNotIn('credentials', expired)
        queue = store.read(admission_policy.queue_key('alice'))[0]
        self.assertEqual(queue['usage']['daily'], 0)
        self.assertNotIn(identifier, [item['id'] for item in queue['pending']])

    def test_active_and_uncertain_jobs_are_never_expired_or_refunded(self):
        for changes in ({'external_started':True}, {'lease_until':time.time()+60}, {'owner_uid':'bob'}):
            store, identifier = self.store_with_job()
            job, generation = store.read(identifier)
            store.write(identifier, {**job, **changes}, generation)
            before = copy.deepcopy(store.read(identifier)[0])
            store.admit('new-sync', 'alice', charge=False)
            self.assertEqual(store.read(identifier)[0], before)
            self.assertEqual(store.read(admission_policy.queue_key('alice'))[0]['usage']['daily'], 1)

    def test_worker_winning_cas_retains_reservation(self):
        store, identifier = self.store_with_job()
        write = store.write
        def racing(key, data, generation):
            if key == identifier and data.get('state') == 'failed':
                raise PreconditionFailed('fixture-worker-wins')
            return write(key, data, generation)
        with patch.object(store, 'write', side_effect=racing):
            store.admit('new-sync', 'alice', charge=False)
        queue = store.read(admission_policy.queue_key('alice'))[0]
        self.assertIn(identifier, [item['id'] for item in queue['pending']])
        self.assertEqual(queue['usage']['daily'], 1)

    def test_ten_expired_undispatched_jobs_do_not_block_account_forever(self):
        store = Store()
        for i in range(10):
            identifier = f'expired-{i}'
            store.write(identifier, dict(owner_uid='alice', state='queued', created_at=time.time()-4000), 0)
        store.write(admission_policy.queue_key('alice'), dict(pending=[
            dict(id=f'expired-{i}', created_at=time.time()-4000) for i in range(10)]), 0)
        self.assertTrue(store.admit('new-sync', 'alice', charge=False))
        self.assertEqual(len(store.read(admission_policy.queue_key('alice'))[0]['pending']), 1)
