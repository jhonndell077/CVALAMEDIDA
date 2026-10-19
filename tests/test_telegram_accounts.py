import job_runtime
import io
import os
import time
import unittest
from unittest.mock import patch, MagicMock
import app
import telegram_bot as bot
import telegram_accounts as accounts
import user_accounts as users
from test_telegram import MemoryStore, CONFIG
from test_user_accounts import ALICE, BOB

CONFIG={**CONFIG,'bot_username':'TestBot','client_id':'client','client_secret':'secret'}
def message(telegram_id,text='Chef'):
    return {'message_id':7,'chat':{'id':telegram_id,'type':'private'},'from':{'id':telegram_id,'first_name':'Usuario','username':'usuario'},'text':text}
def link(store,identity,telegram_id):
    token=accounts.create_link(app,identity,store)
    accounts.stage_link(app,token,message(telegram_id),store)
    return accounts.confirm_link(app,identity,store)

class TelegramAccountsTests(unittest.TestCase):
    def test_authenticated_link_api_shows_only_own_pending_chat_and_rejects_foreign_origin(self):
        store=MemoryStore();identity=ALICE
        def verify(): app.g.google_identity=identity
        headers={'Origin':bot.ORIGIN,'X-Requested-With':'XmlHttpRequest'}
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(job_runtime, 'configuration',return_value=CONFIG):
            client=app.app.test_client()
            self.assertEqual(client.post('/api/telegram/link',json={},headers={**headers,'Origin':'https://other.example'}).status_code,403)
            created=client.post('/api/telegram/link',json={},headers=headers)
            self.assertEqual(created.status_code,200)
            token=created.json['bot_url'].split('start=')[1]
            accounts.stage_link(app,token,message(321),store)
            self.assertEqual(client.get('/api/telegram/status').json['pending']['telegram_id'],321)
            identity=BOB
            self.assertIsNone(client.get('/api/telegram/status').json['pending'])
            self.assertEqual(client.post('/api/telegram/link/confirm',json={},headers=headers).status_code,409)
            identity=ALICE
            self.assertEqual(client.post('/api/telegram/link/confirm',json={},headers=headers).status_code,200)
            self.assertTrue(client.get('/api/telegram/status').json['linked'])
            self.assertEqual(client.post('/api/telegram/disconnect',json={},headers=headers).status_code,200)
            self.assertFalse(client.get('/api/telegram/status').json['linked'])
    def test_oauth_api_saves_only_current_users_encrypted_refresh_not_shared_secret(self):
        store=MemoryStore()
        def verify(): app.g.google_identity=ALICE
        token=MagicMock(ok=True)
        token.json.return_value={'access_token':'alice-access','refresh_token':'alice-new-refresh',
                                 'scope':'openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly'}
        user=MagicMock(ok=True);user.json.return_value={'email':ALICE['email'],'email_verified':True}
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'save_configuration') as shared,patch.object(bot.requests,'post',return_value=token),patch.object(bot.requests,'get',return_value=user):
            response=app.app.test_client().post('/api/telegram/drive/authorize',json={'code':'code'},headers={'Origin':bot.ORIGIN,'X-Requested-With':'XmlHttpRequest'})
        self.assertEqual(response.status_code,200);shared.assert_not_called()
        self.assertEqual(response.json.get('scope'),token.json.return_value['scope'])
        self.assertEqual(response.json.get('expires_in'),3600)
        self.assertEqual(response.headers.get('Cache-Control'),'no-store')
        self.assertEqual(accounts.runtime(app,CONFIG,ALICE,store)['drive_refresh_token'],'alice-new-refresh')
        self.assertNotIn('drive_refresh_token',accounts.runtime(app,CONFIG,BOB,store))
        self.assertNotIn('alice-new-refresh',str(store.jobs))

    def test_saved_drive_session_remains_usable_without_optional_gmail_grant(self):
        store=MemoryStore();accounts.save_oauth(store,ALICE['uid'],'saved-refresh',True)
        def verify(): app.g.google_identity=ALICE
        scopes='https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly'
        token=MagicMock(ok=True);token.json.return_value={'access_token':'renewed-drive-only','scope':scopes}
        identity=MagicMock(ok=True);identity.json.return_value={'email':ALICE['email'],'email_verified':True}
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime,'JobStore',return_value=store),patch.object(job_runtime,'configuration',return_value=CONFIG),patch.object(bot.requests,'post',return_value=token),patch.object(bot.requests,'get',return_value=identity):
            result=app.app.test_client().post('/api/telegram/drive/session',json={},headers={'Origin':bot.ORIGIN,'X-Requested-With':'XmlHttpRequest'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json.get('scope'),scopes)
        self.assertNotIn('gmail.send',result.json.get('scope',''))

    def test_browser_session_renews_saved_grant_without_authorization_code(self):
        store=MemoryStore();accounts.save_oauth(store,ALICE['uid'],'saved-refresh',True)
        def verify(): app.g.google_identity=ALICE
        token=MagicMock(ok=True);token.json.return_value={'access_token':'renewed','expires_in':3600,
            'scope':'https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.send'}
        identity=MagicMock(ok=True);identity.json.return_value={'email':ALICE['email'],'email_verified':True}
        headers={'Origin':bot.ORIGIN,'X-Requested-With':'XmlHttpRequest'}
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}),patch.object(app,'verify_google_identity',side_effect=verify),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(bot.requests,'post',return_value=token) as renewal,patch.object(bot.requests,'get',return_value=identity):
            client=app.app.test_client()
            result=client.post('/api/telegram/drive/session',json={},headers=headers)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['access_token'],'renewed')
            self.assertEqual(result.headers['Cache-Control'],'no-store')
            self.assertEqual(renewal.call_args.kwargs['data']['grant_type'],'refresh_token')
            self.assertNotIn('refresh_token',result.json)
            self.assertEqual(client.post('/api/telegram/drive/session',json={},headers={**headers,'Origin':'https://other.example'}).status_code,403)
            token.ok=False;token.json.return_value={'error':'invalid_grant'}
            self.assertEqual(client.post('/api/telegram/drive/session',json={},headers=headers).status_code,409)

    def test_busy_linked_worker_keeps_processing_job_for_retry(self):
        store=MemoryStore();linked=link(store,ALICE,321)
        store.write('1',{'state':'processing','lease_until':time.time()+100,'owner_uid':ALICE['uid'],'owner_id':321,'binding_id':linked['binding_id']},0)
        with self.assertRaises(bot.TelegramError): bot.process_job(app,CONFIG,'1',store)
        self.assertEqual(store.read('1')[0]['state'],'processing')
    def test_pair_needs_authenticated_web_confirmation_and_is_one_time(self):
        store=MemoryStore();token=accounts.create_link(app,ALICE,store)
        accounts.stage_link(app,token,message(321),store)
        self.assertIsNone(accounts.binding(store,321))
        with self.assertRaises(app.AppError): accounts.confirm_link(app,BOB,store)
        confirmed=accounts.confirm_link(app,ALICE,store)
        self.assertEqual(accounts.binding(store,321)['uid'],ALICE['uid'])
        self.assertEqual(confirmed['telegram_username'],'usuario')
        with self.assertRaises(app.AppError): accounts.stage_link(app,token,message(321),store)
        with self.assertRaises(app.AppError): accounts.confirm_link(app,ALICE,store)

    def test_expired_replaced_and_claimed_links_cannot_bind_another_chat(self):
        store=MemoryStore();old=accounts.create_link(app,ALICE,store)
        token=accounts.create_link(app,ALICE,store)
        with self.assertRaises(app.AppError): accounts.stage_link(app,old,message(321),store)
        accounts.stage_link(app,token,message(321),store)
        with self.assertRaises(app.AppError): accounts.stage_link(app,token,message(654),store)
        with patch.object(accounts.time,'time',return_value=time.time()+601):
            self.assertIsNone(accounts.pending_link(store,ALICE['uid']))
            with self.assertRaises(app.AppError): accounts.confirm_link(app,ALICE,store)

    def test_chat_cannot_link_to_two_google_accounts_and_disconnect_revokes_both(self):
        store=MemoryStore();link(store,ALICE,321)
        other=accounts.create_link(app,BOB,store)
        with self.assertRaises(app.AppError): accounts.stage_link(app,other,message(321),store)
        accounts.save_oauth(store,ALICE['uid'],'alice-refresh',True)
        accounts.disconnect(store,ALICE['uid'])
        self.assertIsNone(accounts.binding(store,321))
        self.assertFalse(accounts.runtime(app,CONFIG,ALICE,store)['drive_connected'])
        accounts.stage_link(app,other,message(321),store)
        accounts.confirm_link(app,BOB,store)
        self.assertEqual(accounts.binding(store,321)['uid'],BOB['uid'])

    def test_refresh_tokens_are_encrypted_per_owner_and_never_fall_back_to_original(self):
        store=MemoryStore();link(store,ALICE,321);link(store,BOB,654)
        accounts.save_oauth(store,ALICE['uid'],'alice-private',True)
        accounts.save_oauth(store,BOB['uid'],'bob-private',True)
        self.assertNotIn('alice-private',str(store.jobs))
        self.assertEqual(accounts.runtime(app,CONFIG,ALICE,store)['drive_refresh_token'],'alice-private')
        self.assertEqual(accounts.runtime(app,CONFIG,BOB,store)['drive_refresh_token'],'bob-private')
        stranger={**BOB,'uid':'stranger'}
        self.assertNotIn('drive_refresh_token',accounts.runtime(app,CONFIG,stranger,store))

    def test_existing_original_owner_migrates_without_reauthorizing_and_stays_revoked(self):
        store=MemoryStore();identity={**ALICE,'email':app.ORIGINAL_OWNER_EMAIL}
        accounts.legacy(app,CONFIG,identity,store)
        self.assertEqual(accounts.account_binding(store,identity['uid'])['telegram_id'],123)
        self.assertTrue(accounts.runtime(app,CONFIG,identity,store)['drive_connected'])
        accounts.disconnect(store,identity['uid'])
        accounts.legacy(app,CONFIG,identity,store)
        self.assertIsNone(accounts.account_binding(store,identity['uid']))
        self.assertFalse(accounts.runtime(app,CONFIG,identity,store)['drive_connected'])

    def test_conflict_offers_disconnect_and_chat_can_relink_without_old_login(self):
        store=MemoryStore(); old=link(store,ALICE,321)
        accounts.save_oauth(store,ALICE['uid'],'old-refresh',True)
        token=accounts.create_link(app,BOB,store)
        result,queued,sent=self.webhook(store,{'update_id':90,'message':message(321,'/start '+token)})
        button=sent[0].args[2]['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'],'Desvincular');self.assertFalse(queued)
        callback={'id':'unlink-q','from':{'id':321},'message':message(321),'data':button['callback_data']}
        result,queued,sent=self.webhook(store,{'update_id':91,'callback_query':callback})
        self.assertIsNone(accounts.binding(store,321))
        self.assertFalse(accounts.runtime(app,CONFIG,ALICE,store)['drive_connected'])
        self.assertIn('Desvinculado de '+ALICE['email'],sent[-1].args[2]['text'])
        accounts.stage_link(app,token,message(321),store);accounts.confirm_link(app,BOB,store)
        self.webhook(store,{'update_id':92,'callback_query':callback})
        self.assertEqual(accounts.binding(store,321)['uid'],BOB['uid'])

    def test_disconnect_button_only_for_linked_private_sender(self):
        store=MemoryStore(); linked=link(store,ALICE,321)
        result,queued,sent=self.webhook(store,{'update_id':95,'message':message(321,'/start')})
        self.assertIn(ALICE['email'],sent[0].args[2]['text'])
        callback={'id':'foreign','from':{'id':654},'message':message(654),'data':accounts.disconnect_callback(linked)}
        self.webhook(store,{'update_id':96,'callback_query':callback})
        self.assertEqual(accounts.binding(store,321)['uid'],ALICE['uid'])
        result,queued,sent=self.webhook(store,{'update_id':97,'message':message(654,'/start')})
        self.assertNotIn('reply_markup',sent[0].args[2])

    def webhook(self,store,update):
        with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1','CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}),patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(job_runtime, 'enqueue') as queue,patch.object(bot,'telegram') as sent:
            response=app.app.test_client().post('/telegram/webhook',json=update,headers={'X-Telegram-Bot-Api-Secret-Token':'secret-test'})
            return response,queue.call_args_list,sent.call_args_list

    def test_signed_start_completes_link_and_groups_are_ignored(self):
        store=MemoryStore();token=accounts.create_link(app,ALICE,store)
        result,queued,sent=self.webhook(store,{'update_id':1,'message':message(321,'/start '+token)})
        self.assertEqual(result.status_code,200); self.assertFalse(queued)
        self.assertEqual(accounts.binding(store,321)['uid'], ALICE['uid']);self.assertTrue(sent)
        grouped=message(654,'/start '+token);grouped['chat']['type']='group'
        result,queued,sent=self.webhook(store,{'update_id':2,'message':grouped})
        self.assertFalse(queued);self.assertFalse(sent)

    def test_unlinked_chat_never_queues_private_owner_work(self):
        store=MemoryStore()
        result,queued,sent=self.webhook(store,{'update_id':1,'message':message(321)})
        self.assertEqual(result.status_code,200);self.assertFalse(queued)
        self.assertEqual(sent[0].args[2]['chat_id'],321)
        self.assertIsNone(store.read('1')[0])

    def test_two_chats_queue_jobs_with_their_own_owners_and_reject_foreign_callbacks(self):
        store=MemoryStore();a=link(store,ALICE,321);b=link(store,BOB,654)
        self.webhook(store,{'update_id':1,'message':message(321)})
        self.webhook(store,{'update_id':2,'message':message(654)})
        self.assertEqual(store.read('1')[0]['owner_uid'],ALICE['uid'])
        self.assertEqual(store.read('2')[0]['owner_uid'],BOB['uid'])
        prior,version=store.read('1');prior.update(state='done',contacts={'emails':['job@example.com']})
        store.write('1',prior,version)
        callback={'id':'q','from':{'id':654},'message':{'chat':{'id':654,'type':'private'}},'data':'gmail:1:0'}
        result,queued,sent=self.webhook(store,{'update_id':3,'callback_query':callback})
        self.assertFalse(queued);self.assertIsNone(store.read('3')[0])

    def test_worker_uses_linked_identity_and_delivers_only_to_its_chat(self):
        store=MemoryStore();a=link(store,ALICE,321)
        accounts.save_oauth(store,ALICE['uid'],'alice-refresh',True)
        store.write('1',{'state':'queued','message':message(321), 'owner_uid':ALICE['uid'],'owner_id':321,'binding_id':a['binding_id']},0)
        original=app.MASTER_PROFILE
        def analyze(*args):
            self.assertEqual(users.owner(),ALICE['uid'])
            self.assertEqual(app.MASTER_PROFILE['candidate']['name'],'Alice')
            self.assertEqual(app.MASTER_PROFILE['experiences'],[])
            return {}
        with patch.object(bot,'drive_token',return_value='alice-access'),patch.object(app,'load_drive_bank',return_value={'pending':0}),patch.object(app,'extract_vacancy',return_value=('Chef',[])),patch.object(app,'analyze_with_model',side_effect=analyze),patch.object(app,'make_draft',return_value={'position':'Chef','candidate':{'name':'Alice'}}),patch.object(app,'make_pdf',return_value=io.BytesIO(b'pdf')),patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/alice/view'),patch.object(bot,'telegram',return_value={'message_id':55}) as sent:
            bot.process_job(app,CONFIG,'1',store)
        self.assertEqual(store.read('1')[0]['state'],'done')
        for call in sent.call_args_list:self.assertEqual(call.args[2]['chat_id'],321)
        self.assertIs(app.MASTER_PROFILE,original)

    def test_revoked_or_rebound_chat_cannot_receive_old_pending_job(self):
        store=MemoryStore();a=link(store,ALICE,321)
        store.write('1',{'state':'queued','message':message(321),'owner_uid':ALICE['uid'],'owner_id':321,'binding_id':a['binding_id']},0)
        accounts.disconnect(store,ALICE['uid']);link(store,BOB,321)
        with patch.object(bot,'telegram') as sent,patch.object(bot,'drive_token') as token:
            bot.process_job(app,CONFIG,'1',store)
        self.assertEqual(store.read('1')[0]['state'],'failed'); sent.assert_not_called();token.assert_not_called()
