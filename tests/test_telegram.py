import job_runtime
import copy,io,os,unittest
from unittest.mock import patch,MagicMock
import app
import telegram_bot as bot

CONFIG={'owner_id':123,'bot_token':'test-token','webhook_secret':'secret-test','drive_refresh_token':'refresh-test','drive_connected':True}
def message(**values):
 return {'chat':{'id':123,'type':'private'},'from':{'id':123,'is_bot':False},'text':'Vacante de prueba',**values}
class MemoryStore:
 admit=bot.JobStore.admit
 def __init__(self):self.jobs={};self.pdfs={}
 def read(self,key):
  if key not in self.jobs:return None,0
  data,version=self.jobs[key];return copy.deepcopy(data),version
 def write(self,key,data,generation):
  if self.read(key)[1]!=generation:raise bot.PreconditionFailed('conflict')
  self.jobs[key]=(copy.deepcopy(data),generation+1)
 def put_pdf(self,key,data):self.pdfs[key]=data
 def pdf(self,key):return self.pdfs[key]
 def remove_pdf(self,key):self.pdfs.pop(key,None)

class TelegramTests(unittest.TestCase):
 def test_private_owner_only(self):
  self.assertIsNotNone(bot.allowed_message({'update_id':1,'message':message()},CONFIG))
  for bad in [message(chat={'id':123,'type':'group'}),message(chat={'id':456,'type':'private'}),message(**{'from':{'id':456}}),message(**{'from':{'id':123,'is_bot':True}})]:
   self.assertIsNone(bot.allowed_message({'update_id':1,'message':bad},CONFIG))
 def test_routes_reject_unsigned_calls_and_public_status(self):
  with patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}):
   client=app.app.test_client()
   self.assertEqual(client.post('/telegram/webhook',json={'update_id':1,'message':message()}).status_code,403)
   self.assertEqual(client.post('/telegram/work',json={'update_id':'1'}).status_code,403)
   self.assertEqual(client.get('/api/telegram/status').status_code,401)
 def test_duplicate_webhook_enqueues_without_duplicating_job_and_groups_ignored(self):
  store=MemoryStore()
  with patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(bot,'telegram'),patch.object(job_runtime, 'enqueue') as queue,patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}):
   client=app.app.test_client(); headers={'X-Telegram-Bot-Api-Secret-Token':'secret-test'}
   for _ in range(2):self.assertEqual(client.post('/telegram/webhook',json={'update_id':1,'message':message()},headers=headers).status_code,200)
   self.assertEqual(len([key for key in store.jobs if key.isdigit()]),1)
   store.jobs['1']=({'state':'done'},2)
   client.post('/telegram/webhook',json={'update_id':1,'message':message()},headers=headers)
   self.assertEqual(queue.call_count,2)
   client.post('/telegram/webhook',json={'update_id':2,'message':message(chat={'id':-1,'type':'group'})},headers=headers)
   self.assertEqual(len([key for key in store.jobs if key.isdigit()]),1)
 def test_oversized_file_rejected_before_download(self):
  with patch.object(bot,'telegram') as api:
   with self.assertRaises(bot.TelegramError):bot.vacancy_payload(message(document={'file_name':'x.pdf','file_size':11000000}),CONFIG,10000000)
   api.assert_not_called()
 def test_download_limit_and_image_caption(self):
  response=MagicMock(ok=True);response.iter_content.return_value=[b'abc']
  with patch.object(bot,'telegram',return_value={'file_path':'photos/abc.jpg'}),patch.object(bot.requests,'get',return_value=response):
   payload=bot.vacancy_payload(message(text='',caption='Chef',photo=[{'file_id':'x','width':10,'height':10}]),CONFIG,10)
   self.assertEqual(payload['text'],'Chef'); self.assertEqual(payload['file_name'],'vacante.jpg')
   response.iter_content.return_value=[b'12345678901']
   with self.assertRaises(bot.TelegramError):bot.vacancy_payload(message(photo=[{'file_id':'x'}]),CONFIG,10)
 def process_fixture(self,send_failure=False):
  store=MemoryStore();store.write('1',{'state':'queued','message':message()},0)
  core=MagicMock(); core.MAX_FILE_BYTES=1000;core.VERTEX_MODEL='model';core.AppError=app.AppError
  core.load_drive_bank.return_value={'pending':0};core.extract_vacancy.return_value=('vacante',[])
  core.make_draft.return_value={'position':'Chef'};core.make_pdf.return_value=io.BytesIO(b'pdf')
  calls=[]
  def send(config,method,data,files=None):
   calls.append(method)
   if send_failure:raise bot.TelegramError('Network unknown')
   return {'message_id':42}
  with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'say'),patch.object(bot,'vacancy_payload',return_value={}),patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/id/view') as archive,patch.object(bot,'telegram',side_effect=send):
   bot.process_job(core,CONFIG,'1',store);bot.process_job(core,CONFIG,'1',store)
   self.assertEqual(archive.call_count,1);self.assertEqual(core.analyze_with_model.call_count,1);self.assertEqual([method for method in calls if method=='sendDocument'],['sendDocument'])
  return store
 def test_worker_generates_archives_sends_and_deduplicates(self):
  store=self.process_fixture();self.assertEqual(store.read('1')[0]['state'],'done');self.assertIsNone(store.read('1')[0]['message']);self.assertNotIn('1',store.pdfs)
 def test_uncertain_delivery_is_not_resent(self):
  store=self.process_fixture(True);self.assertEqual(store.read('1')[0]['state'],'delivery_started')
 def test_pending_bank_syncs_and_resumes_without_web_app(self):
  store=MemoryStore();store.write('1',{'state':'queued','message':message()},0)
  core=MagicMock(AppError=app.AppError);core.load_drive_bank.side_effect=[{'pending':2},{'pending':1}]
  with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'say'),patch.object(bot,'telegram'),patch.object(job_runtime, 'enqueue') as enqueue:
   bot.process_job(core,CONFIG,'1',store)
  core.analyze_with_model.assert_not_called();self.assertEqual(store.read('1')[0]['state'],'queued')
  core.load_drive_bank.assert_any_call(process=True)
  enqueue.assert_called_once_with('1',CONFIG,task_identifier='1-bank-1')
 def test_popup_exchange_rejects_foreign_origin(self):
  with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'0'}):
   self.assertEqual(app.app.test_client().post('/api/telegram/drive/authorize',json={'code':'a'},headers={'Origin':'https://evil.example','X-Requested-With':'XmlHttpRequest'}).status_code,403)
 def test_popup_exchange_rejects_other_google_account_without_saving_tokens(self):
  tokens=MagicMock(ok=True);tokens.json.return_value={'access_token':'access','refresh_token':'new-refresh','scope':'openid email https://www.googleapis.com/auth/drive.file'}
  identity=MagicMock(ok=True);identity.json.return_value={'email':'other@example.com','email_verified':True}
  config={**CONFIG,'client_id':'client','client_secret':'secret'}
  with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'0'}),patch.object(job_runtime, 'configuration',return_value=config),patch.object(bot.requests,'post',return_value=tokens),patch.object(bot.requests,'get',return_value=identity),patch.object(job_runtime, 'save_configuration') as save:
   response=app.app.test_client().post('/api/telegram/drive/authorize',json={'code':'authorization-code'},headers={'Origin':bot.ORIGIN,'X-Requested-With':'XmlHttpRequest'})
   self.assertEqual(response.status_code,403);save.assert_not_called()
