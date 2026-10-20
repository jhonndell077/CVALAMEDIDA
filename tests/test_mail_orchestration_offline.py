"""Unit-execute actual route/worker definitions with injected boundaries.
No Flask, OAuth server, GCS, or delivery is exercised; this is NOT E2E.
"""
import ast
import base64
import copy
import hashlib
import io
import json
import re
import socket
import sys
import time
import unittest
import urllib
import urllib.parse
import uuid
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import application_mail
from test_application_mail import pdf_bytes
ROOT = Path(__file__).resolve().parents[1]

class AppError(Exception):
    def __init__(self, text, status_code=400): super().__init__(text); self.status_code=status_code
class Conflict(Exception): pass
class Store:
    def __init__(self): self.values={}
    def read(self, key): return copy.deepcopy(self.values.get(key, (None, 0)))
    def write(self, key, value, version):
        if self.read(key)[1] != version: raise Conflict()
        self.values[key] = (copy.deepcopy(value), version+1)


def definitions(file, names, context):
    tree = ast.parse((ROOT/file).read_text())
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT/file), 'exec'), context)
    return context

class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(); self.pdf=pdf_bytes('CV de Ana verificado')
        self.grant=patch.object(application_mail, 'verify_grant'); self.grant.start(); self.addCleanup(self.grant.stop)
        net=patch.object(socket.socket, 'connect', side_effect=AssertionError('NETWORK_DISABLED')); net.start(); self.addCleanup(net.stop)
        self.runtime=SimpleNamespace(PROJECT='test', JobError=AppError, JobStore=lambda:self.store)
        self.core=Mock(AppError=AppError)
        self.core.ARCHIVE_CONFIG={'allowed_email':'alice@gmail.com'}
        self.core.account_state=SimpleNamespace(ARCHIVE_CONFIG=self.core.ARCHIVE_CONFIG)
        self.core.verify_drive_access.return_value={'id':'alice-folder'}
        self.core.drive_request.return_value={'files':[], 'parents':['alice-folder'], 'mimeType':'application/pdf'}
        self.core.gmail_request.side_effect=[{'email':'alice@gmail.com','email_verified':True},{'id':'accepted'}]
        self.core.make_draft.return_value={'position':'Chef','candidate':{'name':'Ana'}}
        self.core.make_pdf.return_value=io.BytesIO(self.pdf)
        self.core.archive_generated_resume.return_value='https://drive.google.com/file/d/alicepdf/view'
        self.core.re=re; self.core.json=json; self.core.datetime=datetime; self.core.timezone=timezone
        self.core.uuid4=uuid.uuid4; self.core.urllib=urllib
        self.core.jsonify.side_effect=lambda *a,**kw: a[0] if a else kw
        self.core.app.post.side_effect=lambda *a,**kw: lambda fn:fn
        self.core.app.route.side_effect=lambda *a,**kw: lambda fn:fn
        self.core.app.get.side_effect=lambda *a,**kw: lambda fn:fn
        self.core.request.headers={'X-Gmail-Access-Token':'alice-gmail','X-Drive-Access-Token':'alice-drive'}
        self.payload={'application_id':'12345678-1234-1234-1234-123456789012','recipient':'jobs@example.com','message':'Saludos, adjunto CV.','analysis':{}}
        self.core.request.get_json.return_value=self.payload
        ctx={'Any':object,'hashlib':hashlib,'time':time,'job_runtime':self.runtime,
             'user_accounts':SimpleNamespace(owner=lambda:'alice-uid'), 'application_mail':application_mail,
             'PreconditionFailed':Conflict, 'requests':Mock()}
        definitions('resume_routes.py', {'_dispatch_key','_reserve_dispatch','_save_dispatch','register_routes'},ctx)
        ctx['register_routes'](self.core)
        self.web=self.core.send_gmail_application
        requests=Mock(); requests.get.return_value.ok=True; requests.get.return_value.iter_content.return_value=[self.pdf]
        self.bot=definitions('telegram_bot.py',{'process_application','auto_send_application'}, {
            'application_mail':application_mail,'runtime':self.runtime,'drive_token':lambda c:'alice-token',
            'requests':requests,'re':re,'uuid5':uuid.uuid5,'NAMESPACE_URL':uuid.NAMESPACE_URL,
            'datetime':datetime,'timezone':timezone,'json':json,'say':Mock()})
        self.config={'owner_id':1,'owner_uid':'alice-uid','binding_id':'binding-a','owner_name':'Ana'}
        self.source={'state':'done','owner_id':1,'owner_uid':'alice-uid','binding_id':'binding-a',
            'contacts':{'emails':['jobs@example.com']},'position':'Chef','candidate_name':'Ana',
            'filename':'Ana_Chef.pdf','drive_url':'https://drive.google.com/file/d/alicepdf/view',
            'pdf_sha256':hashlib.sha256(self.pdf).hexdigest()}
        self.store.write('1',self.source,0)

    def run_bot(self): return self.bot['process_application'](self.core,self.config,{'source_job':'1','recipient_index':0},self.store)
    def test_web_attaches_exact_archived_pdf_and_prevents_repeat(self):
        result=self.web(); self.assertEqual(result['entry']['status'],'gmail_accepted')
        message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(self.core.gmail_request.call_args.args[2])['raw']))
        self.assertEqual(next(message.iter_attachments()).get_payload(decode=True),self.pdf)
        self.assertEqual(self.core.archive_generated_resume.call_args.args[2], self.pdf)
        self.core.gmail_request.side_effect=None;self.core.gmail_request.return_value={'email':'alice@gmail.com','email_verified':True}
        self.assertTrue(self.web()['already_sent']); self.assertEqual(self.core.make_pdf.call_count,1)
    def test_web_rate_rejection_is_not_started_and_can_retry(self):
        with patch.object(application_mail, 'reserve_rate', side_effect=ValueError('rate')):
            with self.assertRaises(AppError) as error: self.web()
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(self.core.gmail_request.call_count, 1)
        self.core.gmail_request.side_effect=[{'email':'alice@gmail.com','email_verified':True},{'id':'accepted'}]
        self.core.make_pdf.return_value=io.BytesIO(self.pdf)
        self.assertEqual(self.web()['entry']['status'], 'gmail_accepted')

    def test_bot_notification_failure_does_not_reverse_acceptance(self):
        self.bot['say'].side_effect=RuntimeError('Telegram unavailable')
        self.run_bot()
        self.assertEqual(self.store.read('1')[0]['email_status'], 'gmail_accepted')

    def test_web_wrong_identity_blocks_send(self):
        self.core.gmail_request.side_effect=[{'email':'admin@gmail.com','email_verified':True}]
        with self.assertRaises(AppError): self.web()
        self.core.make_pdf.assert_not_called()
    def test_web_scope_failure_blocks_pdf_and_send(self):
        with patch.object(application_mail,'verify_grant',side_effect=ValueError('partial grant')):
            with self.assertRaises(AppError):self.web()
        self.core.make_pdf.assert_not_called()
    def test_web_lost_response_blocks_retry(self):
        self.core.gmail_request.side_effect=[{'email':'alice@gmail.com','email_verified':True}, AppError('timeout',502)]
        with self.assertRaises(AppError):self.web()
        self.core.gmail_request.side_effect=None;self.core.gmail_request.return_value={'email':'alice@gmail.com','email_verified':True}
        with self.assertRaises(AppError) as err:self.web()
        self.assertEqual(err.exception.status_code,409)
        self.assertEqual(self.core.make_pdf.call_count,1)
    def test_web_acceptance_survives_history_failure(self):
        self.core.save_application_record.side_effect=[None, AppError('history unavailable',502)]
        result=self.web();self.assertEqual(result['entry']['status'],'gmail_accepted');self.assertTrue(result['warning'])
    def test_bot_hash_and_owner_are_enforced(self):
        for change in ({'owner_uid':'other'},{'binding_id':'other'},{'pdf_sha256':'changed'}):
            source={**self.source,**change};_,v=self.store.read('1');self.store.write('1',source,v)
            self.core.gmail_request.side_effect=[{'email':'alice@gmail.com','email_verified':True},{'id':'accepted'}]
            with self.subTest(change=change),self.assertRaises(AppError):self.run_bot()
            self.assertFalse(any('messages/send' in str(c) for c in self.core.gmail_request.call_args_list))
            self.core.gmail_request.reset_mock()
    def test_bot_actual_pdf_and_duplicate_callback(self):
        self.run_bot();self.run_bot()
        self.assertEqual(self.core.gmail_request.call_count,2)
        message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(self.core.gmail_request.call_args.args[2])['raw']))
        self.assertEqual(next(message.iter_attachments()).get_payload(decode=True),self.pdf)
        self.assertEqual(self.store.read('1')[0]['email_status'],'gmail_accepted')
    def test_bot_multiple_recipients_never_auto_sends(self):
        source={**self.source,'contacts':{'emails':['a@example.com','b@example.com']}};_,v=self.store.read('1');self.store.write('1',source,v)
        self.bot['auto_send_application'](self.core,self.config,'1',self.store)
        self.core.gmail_request.assert_not_called()
    def test_bot_missing_id_or_provider_failure_never_retries(self):
        for outcome in ({},AppError('forbidden',403),AppError('quota',429),AppError('unavailable',503)):
            self.store.values.clear(); self.store.write('1', self.source, 0)
            self.core.gmail_request.reset_mock()
            self.core.gmail_request.side_effect=[{'email':'alice@gmail.com','email_verified':True}, outcome]
            with self.subTest(outcome=str(outcome)),self.assertRaises(AppError):self.run_bot()
            self.run_bot();self.assertEqual(self.core.gmail_request.call_count,2)
    def test_bot_post_acceptance_history_failure_is_warning(self):
        self.core.save_application_record.side_effect=[None, AppError('history',502)]
        self.run_bot();self.assertEqual(self.store.read('1')[0]['email_status'],'gmail_accepted')
        self.assertIn('no está verificada', self.bot['say'].call_args.args[1])

if __name__=='__main__':unittest.main(verbosity=2)
