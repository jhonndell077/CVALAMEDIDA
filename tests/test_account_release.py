"""Authenticated account lifecycle with real drafting/PDF/MIME, isolated providers."""
import base64
import copy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import pymupdf
import app
import job_runtime
import user_accounts
from test_background_jobs import Store


class AccountReleaseTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.identities = {uid:dict(uid=uid,email=uid+'@example.test',name=uid.title()+' Candidate')
                           for uid in ('existing', 'new')}
        self.archives, self.sent, self.history = {}, [], []
        def identity():
            uid = app.request.headers.get('X-Fixture-Uid')
            if not app.request.headers.get('Authorization') or uid not in self.identities:
                raise app.AppError('Inicia sesión.',401)
            app.g.google_identity = self.identities[uid]
        def bank(config, session):
            uid = config['folder_id'].removesuffix('-bank')
            profile = user_accounts.blank_profile(self.identities[uid])
            if uid == 'existing':
                profile['education'] = [dict(id='study-one',title='Bachiller',institution='Centro de pruebas',date='2020')]
            return SimpleNamespace(_session=session,load=lambda **_: (copy.deepcopy(profile),{'pending':0},b''))
        def drive(url, token, *args):
            uid = token.removesuffix('-drive')
            self.assertIn(uid,self.identities)
            if url.endswith('/userinfo'):
                return {**self.identities[uid],'email_verified':True}
            if '/drive/v3/files/' in url:
                self.assertIn('/'+uid+'-',url)
                file_id = url.split('/files/')[1].split('?')[0]
                return dict(id=file_id,mimeType='application/vnd.google-apps.folder',owners=[{'emailAddress':self.identities[uid]['email']}],capabilities={'canAddChildren':True})
            return {'files':[]}
        def archive(filename, kind, content):
            uid = user_accounts.owner()
            self.archives[uid] = content
            return 'https://drive.google.com/file/d/'+uid+'-pdf/view'
        def gmail(url, token, body=None):
            uid = token.removesuffix('-gmail')
            self.assertEqual(uid,user_accounts.owner())
            if body is None:
                return {**self.identities[uid],'email_verified':True}
            from email.parser import BytesParser
            from email import policy
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(json.loads(body)['raw']))
            self.assertEqual(message['From'].addresses[0].addr_spec,self.identities[uid]['email'])
            content = list(message.iter_attachments())[0].get_payload(decode=True)
            self.assertEqual(content,self.archives[uid])
            with pymupdf.open(stream=content,filetype='pdf') as pdf:
                text = ' '.join(''.join(page.get_text() for page in pdf).split())
                self.assertIn(self.identities[uid]['name'],text)
                other = 'new' if uid=='existing' else 'existing'
                self.assertNotIn(self.identities[other]['name'],text)
            self.sent.append(uid)
            return {'id':'gmail-'+uid}
        def history(entry, token, folder):
            self.assertEqual(entry['uid'],user_accounts.owner())
            self.assertEqual(folder['id'],entry['uid']+'-archive')
            self.history.append(copy.deepcopy(entry))
        import os
        patches = [patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_MULTI_ACCOUNT':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'drive','CV_ARCHIVE_PROVIDER':'drive'}),
            patch.object(app,'verify_google_identity',side_effect=identity), patch.object(job_runtime,'JobStore',return_value=self.store),
            patch('drive_bank.DriveBank',side_effect=bank), patch.object(app,'drive_request',side_effect=drive),
            patch.object(app,'archive_generated_resume',side_effect=archive), patch.object(app,'gmail_request',side_effect=gmail),
            patch.object(app,'save_application_record',side_effect=history)]
        for fixture in patches:
            fixture.start();self.addCleanup(fixture.stop)
        self.configure('existing',legacy=True)
        self.client = app.app.test_client()

    def configure(self, uid, legacy=False):
        self.store.write(user_accounts.account_key(uid),{**self.identities[uid], 'legacy':legacy,
            'bank':{'folder_id':uid+'-bank'}, 'archive_id':uid+'-archive','initial_sync_completed':True},0)

    def headers(self, uid):
        return {'Authorization':'Bearer fixture','X-Fixture-Uid':uid,
                'X-Drive-Access-Token':uid+'-drive','X-Gmail-Access-Token':uid+'-gmail'}

    def test_existing_and_new_accounts_draft_export_and_send_exact_personal_pdf(self):
        self.assertTrue(self.client.get('/api/account',headers=self.headers('existing')).json['ready'])
        self.assertFalse(self.client.get('/api/account',headers=self.headers('new')).json['ready'])
        self.configure('new')
        analysis={'vacancy':{'position':'Asistente de oficina','application_emails':['jobs@example.test']},
                  'matching':{'template':'oficina','selected_experiences':[],'selected_skills':[],
                              'selected_course_ids':[],'selected_project_ids':[]}}
        for index, uid in enumerate(('existing','new')):
            with self.subTest(uid=uid):
                headers=self.headers(uid)
                drafted=self.client.post('/api/draft',json={'analysis':analysis},headers=headers)
                self.assertEqual(drafted.status_code,200,drafted.json)
                exported=self.client.post('/api/export/pdf',json={'analysis':analysis},headers=headers)
                self.assertEqual(exported.status_code,200)
                artifact=exported.headers['X-CV-Artifact-ID']
                self.assertEqual(exported.headers['X-CV-PDF-SHA256'],hashlib.sha256(exported.data).hexdigest())
                payload={'application_id':f'12345678-1234-1234-1234-{index:012d}', 'analysis':analysis,
                         'artifact_id':artifact,'recipient':'jobs@example.test','message':'Saludos: adjunto mi CV.'}
                sent=self.client.post('/api/gmail/send',json=payload,headers=headers)
                self.assertEqual(sent.status_code,200,sent.json)
                self.assertEqual(sent.json['entry']['status'],'gmail_accepted')
                self.assertEqual(sent.json['entry']['pdf_sha256'],hashlib.sha256(exported.data).hexdigest())
                self.assertEqual(self.client.post('/api/gmail/send',json=payload,headers=headers).status_code,200)
                self.assertIsNone(user_accounts.CURRENT.get())
        self.assertEqual(self.sent,['existing','new'])
        self.assertEqual(self.client.post('/api/draft',json={'analysis':analysis}).status_code,401)
