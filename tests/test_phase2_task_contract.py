import json
import time
import unittest
from unittest.mock import patch
import app
import background_jobs as jobs
import job_runtime
import web_notifications
from tests.test_background_jobs import Store, job, ID

class TaskContractTests(unittest.TestCase):
    def test_status_returns_failure_metadata_and_no_private_fields(self):
        store=Store()
        job(store,state='failed',errorCode='bank_review_required',error='Revisa el banco',
            stage='bank-sync',retryable=False,diagnostics_operation='a'*32,diagnostics_correlation='b'*32,
            credentials={'TOKEN':'PRIVATE'},owner_uid='fixture')
        with patch.object(job_runtime,'JobStore',return_value=store), patch.object(jobs.user_accounts,'require_owner'):
            response=app.app.test_client().post('/api/background/jobs/'+ID,json={})
        self.assertEqual(response.status_code,200)
        data=response.json
        self.assertEqual(data['errorCode'],'bank_review_required')
        self.assertEqual(data['code'],'bank_review_required')
        self.assertEqual(data['correlationId'],'b'*32)
        self.assertEqual(data['operationId'],'a'*32)
        self.assertFalse(data['retryable'])
        self.assertEqual(data['safeNextAction'],'review_bank')
        self.assertNotIn('PRIVATE',json.dumps(data))
        self.assertNotIn('payload',data)

    def test_worker_retains_authorization_category(self):
        store=Store();job(store,created_at=time.time()-4000)
        with patch.object(web_notifications,'notify'):
            jobs.process_job(app,ID,store)
        data=store.read(ID)[0]
        self.assertEqual(data['errorCode'],'job_authorization_expired')
        self.assertEqual(data['stage'],'authorization')
        self.assertFalse(data['retryable'])
        self.assertEqual(data['safeNextAction'],'reauthorize')

    def test_unknown_effect_is_not_retryable_and_has_stable_correlation(self):
        store=Store();job(store,external_started=True,diagnostics_operation='a'*32,diagnostics_correlation='b'*32)
        with patch.object(web_notifications,'notify'): jobs.process_job(app,ID,store)
        data=store.read(ID)[0]
        self.assertEqual(data['externalOutcome'],'unknown')
        self.assertFalse(data['retryable'])
        self.assertEqual(data['safeNextAction'],'review_outcome')
        self.assertEqual(data['correlationId'],'b'*32)

    def test_worker_does_not_persist_arbitrary_exception_text(self):
        store=Store();job(store)
        with patch.object(app,'bank_enabled',return_value=False), patch.object(app,'extract_vacancy',side_effect=app.AppError('PRIVATE TOKEN CV MESSAGE')), patch.object(web_notifications,'notify'):
            jobs.process_job(app,ID,store)
        self.assertNotIn('PRIVATE',json.dumps(store.read(ID)[0]))
