import job_runtime
import base64
import time
import unittest
from unittest.mock import patch
from flask import jsonify, Response
import app
import background_jobs as jobs
import telegram_bot as bot
import web_notifications as push
from test_telegram import MemoryStore, CONFIG

ID = 'web-12345678-1234-1234-1234-123456789012'


class Store(MemoryStore):
    def __init__(self):
        super().__init__()
        self.artifacts = {}
        self.progress = []

    def write(self, key, data, generation):
        super().write(key, data, generation)
        if key == ID and 'progress' in data:
            self.progress.append(data['progress'])

    def put_artifact(self, key, data, mime):
        self.artifacts[key] = data, mime

    def artifact(self, key):
        return self.artifacts[key]


def job(store, path='/api/analyze', **values):
    record = {'operation': jobs.PATHS[path], 'path': path, 'state': 'queued',
              'payload': {'text': 'Vacante de camarero'}, 'created_at': time.time(), 'progress': 1, **values}
    store.write(ID, record, 0)


class BackgroundJobTests(unittest.TestCase):
    def test_bank_sync_persists_removals_even_when_no_new_files_are_pending(self):
        store = Store(); job(store, '/api/bank/sync')
        with patch.object(app, 'bank_enabled', return_value=True), patch.object(app, 'load_drive_bank', return_value={'pending': 0, 'documents': []}) as load, patch.object(push, 'notify'):
            jobs.process_job(app, ID, store)
            load.assert_any_call(process=True)
        saved = store.read(ID)[0]
        self.assertEqual(saved['state'], 'done')
        self.assertEqual(saved['result']['documents'], [])
        self.assertEqual(saved['progress'], 100)

    def test_authenticated_submission_poll_hides_payload_and_credentials(self):
        store = Store()
        with patch.object(job_runtime, 'JobStore', return_value=store), patch.object(job_runtime, 'configuration', return_value=CONFIG), patch.object(job_runtime, 'enqueue'), patch.dict('os.environ', {'CV_AUTH_REQUIRED': '1', 'CV_ALLOW_REMOTE': '1'}):
            client = app.app.test_client()
            payload = {'path': '/api/draft', 'payload': {'analysis': {'secret': 'private'}}, 'request_id': ID[4:]}
            self.assertEqual(client.post('/api/background/jobs', json=payload).status_code, 401)
            with patch.object(app, 'verify_google_identity'):
                headers = {'X-Drive-Access-Token': 'private-token'}
                self.assertEqual(client.post('/api/background/jobs', json=payload, headers=headers).status_code, 202)
                self.assertEqual(client.post('/api/background/jobs', json=payload, headers=headers).status_code, 202)
                status = client.post('/api/background/jobs/' + ID, json={}).json
                self.assertEqual(status['progress'], 1)
                self.assertNotIn('payload', status)
                self.assertNotIn('credentials', status)
                self.assertNotIn('private-token', str(store.read(ID)[0]))
                self.assertEqual(client.post('/api/background/jobs', json={**payload, 'path': '/api/notifications/config'}).status_code, 400)

    def test_analysis_survives_page_closure_and_completion_is_idempotent(self):
        store = Store(); job(store)
        with patch.object(app, 'bank_enabled', return_value=False), patch.object(app, 'require_model', return_value='test'), patch.object(app, 'analyze_with_model', return_value={'vacancy': {'position': 'Camarero'}}) as analyze, patch.object(push, 'notify') as notify:
            jobs.process_job(app, ID, store)  # No client is polling or connected.
            jobs.process_job(app, ID, store)
            analyze.assert_called_once(); notify.assert_called_once()
        result = store.read(ID)[0]
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['progress'], 100)
        self.assertNotIn('payload', result)
        self.assertEqual(store.progress, sorted(store.progress))
        self.assertIn(55, store.progress)

    def test_bank_continuation_keeps_analysis_payload_until_all_files_complete(self):
        store = Store(); job(store)
        with patch.object(app, 'bank_enabled', return_value=True), patch.object(app, 'load_drive_bank', side_effect=[{'pending': 3}, {'pending': 2}, {'pending': 2}, {'pending': 1}, {'pending': 1}, {'pending': 0}]), patch.object(job_runtime, 'configuration', return_value=CONFIG), patch.object(job_runtime, 'enqueue') as enqueue, patch.object(app, 'require_model', return_value='test'), patch.object(app, 'analyze_with_model', return_value={'vacancy': {'position': 'Camarero'}}) as analyze:
            for _ in range(2):
                jobs.process_job(app, ID, store)
                current = store.read(ID)[0]
                self.assertEqual(current['state'], 'queued')
                self.assertIn('payload', current)
                analyze.assert_not_called()
            jobs.process_job(app, ID, store)
            self.assertEqual(enqueue.call_count, 2)
            analyze.assert_called_once()
            self.assertEqual(store.read(ID)[0]['progress'], 100)

    def test_stalled_bank_fails_after_three_attempts_without_analyzing(self):
        store = Store(); job(store)
        with patch.object(app, 'bank_enabled', return_value=True), patch.object(app, 'load_drive_bank', return_value={'pending': 1}), patch.object(job_runtime, 'configuration', return_value=CONFIG), patch.object(job_runtime, 'enqueue'), patch.object(app, 'analyze_with_model') as analyze:
            for _ in range(3): jobs.process_job(app, ID, store)
            self.assertEqual(store.read(ID)[0]['state'], 'failed')
            self.assertLess(store.read(ID)[0]['progress'], 100)
            analyze.assert_not_called()

    def test_lease_prevents_parallel_execution(self):
        store = Store(); job(store, lease_until=time.time() + 300)
        with self.assertRaises(bot.TelegramError): jobs.process_job(app, ID, store)

    def test_uncertain_external_operation_is_not_repeated(self):
        store = Store(); job(store, '/api/gmail/send', external_started=True)
        with patch.dict(app.app.view_functions, {'send_gmail_application': lambda: self.fail('Repeated email')}):
            jobs.process_job(app, ID, store)
        self.assertEqual(store.read(ID)[0]['state'], 'failed')

    def test_encrypted_credentials_removed_after_result_and_artifact_recoverable(self):
        store = Store()
        encrypted = push.protect(store, {'X-Drive-Access-Token': 'private-token'}, ID)
        job(store, '/api/export/pdf', credentials=encrypted)
        def export(format_name):
            self.assertEqual(app.request.headers['X-Drive-Access-Token'], 'private-token')
            return Response(b'pdf-content', mimetype='application/pdf', headers={
                'Content-Disposition': 'attachment; filename="CV.pdf"', 'X-CV-Drive-URL': 'https://drive.google.com/file/d/test/view'})
        with patch.object(app, 'bank_enabled', return_value=False), patch.dict(app.app.view_functions, {'export_resume': export}):
            jobs.process_job(app, ID, store)
        saved = store.read(ID)[0]
        self.assertEqual(saved['state'], 'done')
        self.assertNotIn('credentials', saved)
        self.assertEqual(store.artifact(ID)[0], b'pdf-content')
        self.assertEqual(saved['result']['fileName'], 'CV.pdf')

    def test_push_keys_parse_and_encrypted_headers_are_bound_to_job(self):
        from py_vapid import Vapid
        store = Store(); keys = push.configuration(store)
        Vapid.from_string(keys['private_key'])
        encrypted = push.protect(store, {'X-Gmail-Access-Token': 'private-token'}, ID)
        self.assertEqual(push.unprotect(store, encrypted, ID)['X-Gmail-Access-Token'], 'private-token')
        with self.assertRaises(Exception): push.unprotect(store, encrypted, ID + 'x')

    def test_push_rejects_private_network_and_notifies_only_registered_devices(self):
        store = Store()
        subscription = {'endpoint': 'https://fcm.googleapis.com/test', 'keys': {'p256dh': 'a' * 87, 'auth': 'b' * 22}}
        self.assertTrue(push.valid_subscription(subscription))
        self.assertFalse(push.valid_subscription({**subscription, 'endpoint': 'https://127.0.0.1/secrets'}))
        push.subscribe(store, subscription)
        with patch('pywebpush.webpush') as send:
            push.notify(store, ID, {'state': 'done'})
            self.assertIn(ID, send.call_args.kwargs['data'])
            self.assertNotIn('private', send.call_args.kwargs['data'])

    def test_failed_notification_does_not_lose_completed_job(self):
        store = Store(); job(store, '/api/draft')
        with patch.object(app, 'bank_enabled', return_value=False), patch.dict(app.app.view_functions, {'draft': lambda: jsonify(draft={'position': 'Camarero'})}), patch.object(push, 'notify', side_effect=RuntimeError('Offline push provider')):
            jobs.process_job(app, ID, store)
        self.assertEqual(store.read(ID)[0]['state'], 'done')


if __name__ == '__main__': unittest.main()
