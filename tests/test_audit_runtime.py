"""Synthetic regressions for audit H03, H06 and H12. No network or real users."""
import base64
import copy
import io
import json
import re
import threading
import time
import unittest
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from uuid import uuid4

from flask import Flask, jsonify, request
from google.api_core.exceptions import PreconditionFailed
import background_jobs
import job_runtime
import resume_routes
import user_accounts
import web_notifications


class AppError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


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


def fixture():
    core = SimpleNamespace(
        app=Flask('audit-runtime'), request=request, jsonify=jsonify, AppError=AppError,
        re=re, urllib=SimpleNamespace(parse=urllib.parse), json=json, uuid4=uuid4,
        EmailMessage=EmailMessage, base64=base64, datetime=datetime, timezone=timezone,
        account_state=SimpleNamespace(ARCHIVE_CONFIG={'allowed_email': 'fixture@example.invalid'}),
        verify_drive_access=lambda token: {'id': 'fixture-folder'},
        drive_request=lambda *args: {'files': []},
        make_draft=lambda data: {'position': 'Puesto ficticio', 'candidate': {'name': 'Persona ficticia'}},
        make_pdf=lambda data: io.BytesIO(b'%PDF-synthetic'),
        archive_generated_resume=lambda *args: 'https://drive.google.com/file/d/fixture/view',
        save_application_record=lambda *args: None,
    )
    @core.app.errorhandler(AppError)
    def error(exc):
        return jsonify(error=str(exc)), exc.status_code
    resume_routes.register_routes(core)
    return core


PAYLOAD = {'application_id': '12345678-1234-1234-1234-123456789012',
           'recipient': 'recipient@example.invalid', 'message': 'Prueba local', 'analysis': {}}
HEADERS = {'X-Gmail-Access-Token': 'synthetic', 'X-Drive-Access-Token': 'synthetic'}


class AuditGmailTests(unittest.TestCase):
    def test_completed_direct_dispatch_is_reused_by_background_worker(self):
        core, store = fixture(), Store()
        sent = []
        def gmail(url, *args):
            if url.endswith('userinfo'):
                return {'email': 'fixture@example.invalid', 'email_verified': True}
            sent.append(url)
            return {'id': 'synthetic-message'}
        core.gmail_request = gmail
        core.bank_enabled = lambda: False
        identifier = 'web-' + str(uuid4())
        with patch.object(job_runtime, 'JobStore', return_value=store), \
             patch.object(web_notifications, 'unprotect', return_value=HEADERS), \
             patch.object(web_notifications, 'notify'):
            self.assertEqual(core.app.test_client().post('/api/gmail/send', json=PAYLOAD, headers=HEADERS).status_code, 200)
            store.write(identifier, {'path': '/api/gmail/send', 'operation': 'gmail', 'state': 'queued',
                                    'payload': PAYLOAD, 'created_at': time.time()}, 0)
            background_jobs.process_job(core, identifier, store)
        self.assertEqual(store.read(identifier)[0]['state'], 'done')
        self.assertTrue(store.read(identifier)[0]['result']['already_sent'])
        self.assertEqual(len(sent), 1)

    def test_simultaneous_identical_requests_archive_and_send_once(self):
        core, store = fixture(), Store()
        barrier = threading.Barrier(2)
        sent, archived = [], []
        def gmail(url, *args):
            if url.endswith('userinfo'):
                barrier.wait(timeout=5)
                return {'email': 'fixture@example.invalid', 'email_verified': True}
            sent.append(url)
            return {'id': 'synthetic-message'}
        core.gmail_request = gmail
        def archive(*args):
            archived.append(args)
            return 'https://drive.google.com/file/d/fixture/view'
        core.archive_generated_resume = archive
        def submit(_):
            with core.app.test_client() as client:
                return client.post('/api/gmail/send', json=PAYLOAD, headers=HEADERS).status_code
        with patch.object(job_runtime, 'JobStore', return_value=store):
            with ThreadPoolExecutor(max_workers=2) as executor:
                statuses = list(executor.map(submit, range(2)))
        self.assertIn(200, statuses)
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(archived), 1)

    def test_same_application_id_cannot_change_recipient_or_message(self):
        core, store = fixture(), Store()
        sent = []
        def gmail(url, *args):
            if url.endswith('userinfo'):
                return {'email': 'fixture@example.invalid', 'email_verified': True}
            sent.append(url)
            return {'id': 'synthetic-message'}
        core.gmail_request = gmail
        with patch.object(job_runtime, 'JobStore', return_value=store):
            client = core.app.test_client()
            self.assertEqual(client.post('/api/gmail/send', json=PAYLOAD, headers=HEADERS).status_code, 200)
            result = client.post('/api/gmail/send', json={**PAYLOAD, 'recipient': 'other@example.invalid'}, headers=HEADERS)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(len(sent), 1)

    def test_unknown_gmail_result_cannot_be_resent_from_direct_route(self):
        core, store = fixture(), Store()
        sent = []
        def gmail(url, *args):
            if url.endswith('userinfo'):
                return {'email': 'fixture@example.invalid', 'email_verified': True}
            sent.append(url)
            raise AppError('Simulated lost response', 502)
        core.gmail_request = gmail
        with patch.object(job_runtime, 'JobStore', return_value=store):
            client = core.app.test_client()
            self.assertEqual(client.post('/api/gmail/send', json=PAYLOAD, headers=HEADERS).status_code, 502)
            second = client.post('/api/gmail/send', json=PAYLOAD, headers=HEADERS)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(len(sent), 1)


class AuditAdmissionTests(unittest.TestCase):
    def test_direct_work_shares_user_limit_and_releases_slot_after_request(self):
        core, store = fixture(), Store()
        marker = user_accounts.CURRENT.set({'uid': 'fixture-uid', 'email': 'fixture@example.invalid'})
        try:
            with patch.object(job_runtime, 'JobStore', return_value=store):
                with core.app.test_request_context('/api/analyze', method='POST'):
                    background_jobs.enforce_request_quota(core)
                    for index in range(9):
                        self.assertTrue(store.admit('queued-' + str(index), 'fixture-uid'))
                    self.assertFalse(store.admit('eleventh', 'fixture-uid'))
                    self.assertTrue(store.admit('other-account', 'another-uid'))
                    background_jobs.release_request_quota()
                    self.assertTrue(store.admit('after-release', 'fixture-uid'))
                # Polling and health never consume an expensive-operation slot.
                with core.app.test_request_context('/api/background/jobs/web-fixture', method='POST'):
                    background_jobs.enforce_request_quota(core)
                    self.assertFalse(hasattr(background_jobs.g, 'cv_request_slot'))
        finally:
            user_accounts.CURRENT.reset(marker)

    def test_crashed_direct_request_releases_capacity_after_server_timeout(self):
        store = Store()
        store.write('direct-crashed', {'state': 'processing', 'lease_until': time.time() - 1}, 0)
        self.assertTrue(store.admit('direct-crashed', 'fixture-uid'))
        for index in range(10):
            self.assertTrue(store.admit('queued-' + str(index), 'fixture-uid'))

    def test_eleventh_job_is_rejected_before_protecting_or_enqueueing(self):
        core, store = fixture(), Store()
        background_jobs.register_routes(core.app, core)
        marker = user_accounts.CURRENT.set({'uid': 'fixture-uid', 'email': 'fixture@example.invalid'})
        try:
            with patch.object(job_runtime, 'JobStore', return_value=store), \
                 patch.object(job_runtime, 'configuration', return_value={}), \
                 patch.object(job_runtime, 'enqueue') as enqueue, \
                 patch.object(web_notifications, 'protect', return_value='synthetic') as protect:
                statuses = [core.app.test_client().post('/api/background/jobs', json={
                    'path': '/api/analyze', 'payload': {'text': 'Vacante sintética'}, 'request_id': str(uuid4())
                }).status_code for _ in range(11)]
            self.assertEqual(statuses, [202] * 10 + [429])
            self.assertEqual(enqueue.call_count, 10)
            self.assertEqual(protect.call_count, 10)
        finally:
            user_accounts.CURRENT.reset(marker)


class AuditHistoryTests(unittest.TestCase):
    def test_drive_cursor_is_returned_and_forwarded_to_next_page(self):
        core = fixture()
        urls = []
        def drive(url, token):
            urls.append(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query))
            return {'files': [], 'nextPageToken': 'opaque-page_2='}
        core.drive_request = drive
        client = core.app.test_client()
        first = client.get('/api/applications')
        self.assertEqual(first.json.get('next_cursor'), 'opaque-page_2=')
        client.get('/api/applications?cursor=opaque-page_2%3D')
        self.assertEqual(urls[-1].get('pageToken'), ['opaque-page_2='])

    def test_cursor_with_control_characters_is_rejected_before_drive_query(self):
        core = fixture()
        with patch.object(core, 'drive_request') as drive:
            response = core.app.test_client().get('/api/applications?cursor=bad%0Avalue')
        self.assertEqual(response.status_code, 400)
        drive.assert_not_called()


class AuditGoogleGrantTests(unittest.TestCase):
    def test_firebase_popup_grant_returns_google_scopes_without_token_in_url(self):
        core = fixture()
        scopes = 'https://www.googleapis.com/auth/drive.file'
        response = MagicMock(ok=True)
        response.json.return_value = {'scope': scopes, 'expires_in': '3210'}
        core.drive_request = lambda *args: {'email': 'fixture@example.invalid', 'email_verified': True}
        with patch('requests.post', return_value=response) as post:
            result = core.app.test_client().post('/api/google/grant', headers=HEADERS)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json, {'scope': scopes, 'expires_in': 3210})
        self.assertEqual(result.headers.get('Cache-Control'), 'no-store')
        self.assertNotIn('synthetic', post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer synthetic')

    def test_google_grant_rejects_foreign_account_before_inspecting_scopes(self):
        core = fixture()
        core.drive_request = lambda *args: {'email': 'foreign@example.invalid', 'email_verified': True}
        with patch('requests.post') as post:
            result = core.app.test_client().post('/api/google/grant', headers=HEADERS)
        self.assertEqual(result.status_code, 403)
        post.assert_not_called()
