import job_runtime
import os
import unittest
from unittest.mock import patch
import app
import analysis_jobs as jobs
import telegram_bot as bot
from test_telegram import MemoryStore, CONFIG

class AnalysisJobTests(unittest.TestCase):
    def test_submit_poll_and_worker_are_idempotent_and_authenticated(self):
        store = MemoryStore()
        with patch.object(job_runtime, 'JobStore', return_value=store), patch.object(job_runtime, 'configuration', return_value=CONFIG), patch.object(job_runtime, 'enqueue') as enqueue, patch.dict(os.environ, {'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}):
            client = app.app.test_client()
            self.assertEqual(client.post('/api/analyze/jobs',json={'text':'Chef'}).status_code,401)
            with patch.object(app,'verify_google_identity'):
                payload={'text':'Chef','request_id':'12345678-1234-1234-1234-123456789012'}
                identifier=client.post('/api/analyze/jobs',json=payload).json['job_id']
                self.assertEqual(client.post('/api/analyze/jobs',json=payload).json['job_id'],identifier)
                self.assertEqual(len(store.jobs),1)
                self.assertEqual(client.post('/api/analyze/jobs/'+identifier,json={}).json,{'state':'queued'})
                self.assertNotIn('payload',client.post('/api/analyze/jobs/'+identifier,json={}).json)
            worker_payload={'update_id':identifier,'kind':'web_analysis'}
            self.assertEqual(client.post('/telegram/work',json=worker_payload).status_code,403)
            with patch.object(app,'load_drive_bank',return_value={'pending':0}), patch.object(app,'require_model',return_value='test'), patch.object(app,'analyze_with_model',return_value={'vacancy':{'position':'Chef'}}) as analyze:
                headers={'X-CV-Telegram-Worker':bot.task_secret(CONFIG)}
                for _ in range(2):
                    self.assertEqual(client.post('/telegram/work',json=worker_payload,headers=headers).status_code,200)
                analyze.assert_called_once()
            completed=store.read(identifier)[0]
            self.assertEqual(completed['state'],'done')
            self.assertNotIn('payload',completed)
            enqueue.assert_called_with(identifier,CONFIG,kind='web_analysis')

    def test_selection_and_timeout_are_durable_results(self):
        for error, expected in [(app.VacancySelectionRequired(['Chef','Cocinero']),'done'),(app.AppError('Tiempo agotado',503),'failed')]:
            store=MemoryStore(); store.write('web-test',{'state':'queued','payload':{'text':'Chef'}},0)
            with patch.object(app,'load_drive_bank',return_value={'pending':0}),patch.object(app,'require_model',return_value='test'),patch.object(app,'analyze_with_model',side_effect=error):
                jobs.process_job(app,'web-test',store)
            job=store.read('web-test')[0]
            self.assertEqual(job['state'],expected)
            self.assertNotIn('payload',job)
            if expected=='done':self.assertTrue(job['result']['selection_required'])
            else:self.assertEqual(job['error'],'Tiempo agotado')
