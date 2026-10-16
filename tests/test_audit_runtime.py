"""Synthetic regressions for audit H03, H06 and H12. No network or real users."""
import base64
import copy
import io
import json
import re
import threading
import unittest
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import patch
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
