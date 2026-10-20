import job_runtime
import copy
import json
import os
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse, parse_qs
import app
import user_accounts as users
import telegram_bot as bot
import background_jobs as jobs
import web_notifications as push
from test_telegram import MemoryStore
from test_background_jobs import ID, job
from test_drive_bank import MemoryBank, memory

ALICE = {'uid':'alice-uid', 'email':'alice@example.com', 'name':'Alice'}
BOB = {'uid':'bob-uid', 'email':'bob@example.com', 'name':'Bob'}

class Drive:
    def __init__(self): self.files = {}; self.created = 0
    def create(self, name, parent, mime, email=ALICE['email']):
        self.created += 1
        record = {'id':str(self.created), 'name':name, 'parents':[parent], 'mimeType':mime, 'owners':[{'emailAddress':email}]}
        self.files[record['id']] = record
        return record
    def api(self, core, token, method, path, payload=None):
        if method == 'POST':
            return self.create(payload['name'], payload['parents'][0], payload['mimeType'])
        if path.startswith('files/'):
            return self.files[path.split('/')[1].split('?')[0]]
        query = parse_qs(urlparse('https://drive/' + path).query)['q'][0]
        parent = query.split("'")[1]
        return {'files':[item for item in self.files.values() if parent in item['parents']]}
    def request(self, url, token, body=None, content_type=None):
        if url.endswith('userinfo'): return {'email':ALICE['email'], 'email_verified':True}
        metadata = json.loads(body.split(b'\r\n\r\n')[1].split(b'\r\n--')[0])
        return self.create(metadata['name'], metadata['parents'][0], metadata['mimeType'])

class AccountsTests(unittest.TestCase):
    def test_new_account_creates_own_folders_and_empty_profile_idempotently(self):
        store = MemoryStore(); drive = Drive()
        with patch.object(users, 'api', side_effect=drive.api), patch.object(app, 'drive_request', side_effect=drive.request):
            record = users.prepare(app, ALICE, 'alice-token', store=store)
            before = drive.created
            again = users.prepare(app, ALICE, 'alice-token', store=store)
        self.assertEqual(record, again)
        self.assertEqual(drive.created, before)
        self.assertEqual(set(record['sections']), set(users.SECTIONS))
        self.assertNotEqual(record['bank']['folder_id'], record['archive_id'])
        self.assertTrue(record['bank']['photo_optional'])
        self.assertEqual(users.blank_profile(ALICE)['experiences'], [])
        self.assertEqual(users.blank_profile(ALICE)['candidate']['email'], ALICE['email'])

    def test_existing_folders_reused_including_case_differences(self):
        store = MemoryStore(); drive = Drive()
        bank = drive.create('Banco de datos','root','application/vnd.google-apps.folder')
        archive = drive.create('CV Generados','root','application/vnd.google-apps.folder')
        section = drive.create('Informacion laboral',bank['id'],'application/vnd.google-apps.folder')
        with patch.object(users, 'api', side_effect=drive.api), patch.object(app, 'drive_request', side_effect=drive.request):
            record = users.prepare(app, ALICE, 'alice-token', store=store)
        self.assertEqual(record['bank']['folder_id'], bank['id'])
        self.assertEqual(record['archive_id'], archive['id'])
        self.assertEqual(record['sections']['Informacion Laboral'], section['id'])

    def test_other_accounts_token_and_shared_folder_cannot_be_used(self):
        with patch.object(app,'drive_request', return_value={'email':BOB['email'],'email_verified':True}):
            with self.assertRaises(app.AppError): users.prepare(app,ALICE,'bob-token',store=MemoryStore())
        drive=Drive(); foreign=drive.create('Banco de Datos','root','application/vnd.google-apps.folder',BOB['email'])
        with patch.object(users,'api',side_effect=drive.api):
            with self.assertRaises(app.AppError): users.folder(app,'alice-token',ALICE,'Banco de Datos',selected=foreign['id'])

    def test_manual_selection_uses_only_selected_owned_folders(self):
        drive=Drive(); bank=drive.create('Mi banco','root','application/vnd.google-apps.folder')
        archive=drive.create('Mis CV','root','application/vnd.google-apps.folder')
        with patch.object(users,'api',side_effect=drive.api),patch.object(app,'drive_request',side_effect=drive.request):
            record=users.prepare(app,ALICE,'alice-token',{'bank_id':bank['id'],'archive_id':archive['id']},MemoryStore())
        self.assertEqual(record['bank']['folder_id'],bank['id']); self.assertEqual(record['archive_id'],archive['id'])

    def test_scope_isolates_profiles_indexes_photo_and_restores_on_error(self):
        original={key:getattr(app,key) for key in users.GLOBALS}
        store=MemoryStore()
        for identity in (ALICE,BOB):
            with self.assertRaises(RuntimeError):
                with users.scope(app,identity,store=store):
                    self.assertEqual(app.MASTER_PROFILE['candidate']['name'],identity['name'])
                    self.assertEqual(app.MASTER_PROFILE['experiences'],[])
                    self.assertEqual(app.EXPERIENCE_BY_ID,{})
                    self.assertNotEqual(app.current_photo_path(),app.ROOT / original['MASTER_PROFILE']['candidate']['photo'])
                    app.validate_profile(app.MASTER_PROFILE)
                    raise RuntimeError('interruption')
            for key,value in original.items(): self.assertIs(getattr(app,key),value)
        self.assertIsNone(users.CURRENT.get())

    def test_account_without_photo_loads_empty_bank_without_previous_identity(self):
        files,contents=memory(); del files['photo']; del files['certificate']
        contents['base']=json.dumps(users.blank_profile(ALICE)).encode()
        bank=MemoryBank(files,contents); bank.config={**bank.config,'photo_optional':True}
        profile,status,photo=bank.load(process=True)
        self.assertEqual(profile['candidate']['name'],'Alice'); self.assertEqual(status['pending'],0)
        self.assertEqual(photo,b''); self.assertEqual(profile['experiences'],[])

    def test_any_verified_account_can_login_but_unverified_and_missing_uid_fail(self):
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_ALLOWED_EMAILS':'owner@example.com'}):
            for claims in ({**ALICE,'email_verified':True,'auth_time':__import__('session_policy').REAUTHENTICATE_AFTER}, {**ALICE,'email_verified':False}, {'email':ALICE['email'],'email_verified':True}):
                with app.app.test_request_context('/api/account',headers={'Authorization':'Bearer token'}),patch('firebase_admin.auth.verify_id_token',return_value=claims):
                    if claims.get('uid') and claims['email_verified']: app.verify_google_identity()
                    else:
                        with self.assertRaises(app.AppError): app.verify_google_identity()

    def test_private_job_status_result_and_artifact_are_owner_only(self):
        store=MemoryStore(); job(store,owner_uid=ALICE['uid'],state='done',result={'private':'alice'})
        def verify(): app.g.google_identity=BOB
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime, 'JobStore',return_value=store):
            client=app.app.test_client()
            self.assertEqual(client.post('/api/background/jobs/'+ID,json={}).status_code,404)
            self.assertEqual(client.get('/api/background/jobs/'+ID+'/file').status_code,404)
            self.assertEqual(client.post('/api/analyze/jobs/'+ID,json={}).status_code,404)
            with patch.object(job_runtime, 'configuration',return_value={'bot_token':'test','bot_username':'TestBot','drive_connected':True,'drive_refresh_token':'original-private'}):
                telegram=client.get('/api/telegram/status')
                self.assertEqual(telegram.status_code,200)
                self.assertFalse(telegram.json['drive_connected'])
                self.assertFalse(telegram.json['linked'])
                self.assertEqual(telegram.json['bot_url'],'')

    def test_notifications_go_only_to_job_owner(self):
        store=MemoryStore()
        for identity in (ALICE,BOB):
            push.subscribe(store,{'endpoint':'https://fcm.googleapis.com/'+identity['uid'],'keys':{'p256dh':'x'*40,'auth':'x'*24}},identity['uid'])
        with patch('pywebpush.webpush') as send:
            push.notify(store,ID,{'state':'done','progress':100,'owner_uid':ALICE['uid']})
        self.assertEqual(send.call_count,1)
        self.assertIn(ALICE['uid'],send.call_args.kwargs['subscription_info']['endpoint'])

    def test_job_recovery_does_not_require_unexpired_drive_token(self):
        store=MemoryStore(); job(store,owner_uid=ALICE['uid'],state='done',progress=100,result={'ok':True})
        store.write(users.account_key(ALICE['uid']), {'bank':{'folder_id':'alice-bank'},'archive_id':'alice-cv'},0)
        def verify(): app.g.google_identity=ALICE
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime,'JobStore',return_value=store),patch.object(users,'assert_drive_identity',side_effect=app.AppError('Drive venció.',401)) as drive:
            client=app.app.test_client()
            response=client.post('/api/background/jobs/'+ID,json={},headers={'X-Drive-Access-Token':'expired-fixture'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['progress'],100)
            drive.assert_not_called()

    def test_failed_drive_identity_restores_context_and_stops_worker_below_100(self):
        store=MemoryStore()
        store.write(users.account_key(ALICE['uid']), {'bank':{'folder_id':'alice-bank'},'archive_id':'alice-cv'},0)
        original={key:getattr(app,key) for key in users.GLOBALS}
        job(store,owner_uid=ALICE['uid'],owner_email=ALICE['email'],owner_name=ALICE['name'])
        with patch.object(users,'assert_drive_identity',side_effect=app.AppError('Conecta nuevamente Drive.',401)),patch.object(push,'notify'):
            with self.assertRaises(app.AppError):
                with users.scope(app,ALICE,{'X-Drive-Access-Token':'expired'},store): pass
            jobs.process_job(app,ID,store)
        failed=store.read(ID)[0]
        self.assertEqual(failed['state'],'failed'); self.assertLess(failed['progress'],100)
        self.assertNotIn('credentials',failed)
        for key,value in original.items(): self.assertIs(getattr(app,key),value)
        self.assertIsNone(users.CURRENT.get())

    def test_empty_new_account_api_never_returns_original_profile(self):
        store=MemoryStore()
        def verify(): app.g.google_identity=BOB
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime, 'JobStore',return_value=store):
            response=app.app.test_client().get('/api/profile')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['candidate']['name'],'Bob')
            self.assertEqual(response.json['experiences'],[])
            self.assertEqual(response.json['references'],[])

    def test_background_worker_uses_persisted_owner_and_credentials(self):
        store=MemoryStore()
        job(store,owner_uid=ALICE['uid'],owner_email=ALICE['email'],owner_name=ALICE['name'])
        def analyze(*args):
            self.assertEqual(app.MASTER_PROFILE['candidate']['name'],ALICE['name'])
            self.assertEqual(users.owner(),ALICE['uid'])
            return {'vacancy':{'position':'Camarero'}}
        with patch.object(app,'bank_enabled',return_value=False),patch.object(app,'require_model',return_value='test'),patch.object(app,'analyze_with_model',side_effect=analyze),patch.object(push,'notify'):
            jobs.process_job(app,ID,store)
        self.assertEqual(store.read(ID)[0]['state'],'done')
        self.assertEqual(store.read(ID)[0]['progress'],100)
        self.assertIsNone(users.CURRENT.get())
