from pdf_fixture import PDF
import job_runtime
import io
import json
import os
import time
import unittest
from unittest.mock import MagicMock,patch
import app
import telegram_bot as bot
from test_telegram import MemoryStore,CONFIG,message

class TelegramProgressTests(unittest.TestCase):
    def core(self):
        core=MagicMock(AppError=app.AppError,VacancySelectionRequired=app.VacancySelectionRequired,MAX_FILE_BYTES=1000,VERTEX_MODEL='test')
        core.load_drive_bank.return_value={'pending':0}
        core.extract_vacancy.return_value=('SECRET-ADVERT',[])
        core.analyze_with_model.return_value={'vacancy':{'position':'Chef'}}
        core.make_draft.return_value={'position':'Chef','candidate':{'name':'Alice'}}
        core.make_pdf.return_value=io.BytesIO(PDF)
        return core

    def test_new_user_pdf_without_references_or_photo_is_delivered(self):
        import user_accounts
        from pathlib import Path
        store=MemoryStore();store.write('1',{'state':'queued','message':message(message_id=7)},0)
        core=self.core()
        profile=user_accounts.blank_profile({'name':'Usuario nuevo','email':'nuevo@example.com'})
        draft={'candidate':profile['candidate'],'position':'Camarero','summary':'Atencion al cliente',
               'skills':[],'education':[],'courses':[],'experiences':[], 'references':[], 'projects':[]}
        core.make_draft.return_value=draft
        core.make_pdf.side_effect=app.make_pdf
        with patch.object(app,'current_photo_path',return_value=Path('tmp/absent-new-user-photo')),patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'vacancy_payload',return_value={}),patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/id/view'),patch.object(bot,'telegram',return_value={'message_id':50}) as send:
            bot.process_job(core,CONFIG,'1',store)
        self.assertEqual(store.read('1')[0]['state'],'done')
        document=next(call for call in send.call_args_list if call.args[1]=='sendDocument')
        self.assertTrue(document.kwargs['files']['document'][1].startswith(b'%PDF'))

    def test_unexpected_failure_records_stage_and_safe_reference(self):
        store=MemoryStore();store.write('1',{'state':'queued','message':message()},0)
        core=self.core();core.make_pdf.side_effect=ValueError('private content')
        with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'vacancy_payload',return_value={}),patch.object(bot,'telegram',return_value={'message_id':50}):
            bot.process_job(core,CONFIG,'1',store)
        failed=store.read('1')[0]
        self.assertEqual(failed['failed_stage'],'building')
        self.assertEqual(failed['error_type'],'ValueError')
        self.assertNotIn('private content',failed['progress_text'])
        self.assertIn('Referencia: 1',failed['progress_text'])

    def test_receipt_is_sent_before_enqueue_and_duplicates_share_one_notice(self):
        store=MemoryStore();events=[]
        def send(config,method,data,files=None): events.append(method);return {'message_id':50}
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_MULTI_ACCOUNT':'0'}),patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(bot,'telegram',side_effect=send),patch.object(job_runtime, 'enqueue',side_effect=lambda *a,**k:events.append('enqueue')):
            client=app.app.test_client()
            for _ in range(2):client.post('/telegram/webhook',json={'update_id':1,'message':message(message_id=7)},headers={'X-Telegram-Bot-Api-Secret-Token':'secret-test'})
        self.assertEqual(events,['sendMessage','enqueue','enqueue'])
        self.assertEqual(store.read('1')[0]['progress_message_id'],50)

    def test_selection_has_persistent_confirmation_and_removes_choice_buttons_before_queue(self):
        store=MemoryStore();store.write('1',{'state':'awaiting_selection','positions':['Chef','Camarero'],'owner_id':123,'progress_message_id':50},0)
        events=[];calls=[]
        def send(config,method,data,files=None): events.append(method);calls.append(data);return {}
        query={'id':'q','from':{'id':123},'message':{'chat':{'id':123,'type':'private'}},'data':'position:1:1'}
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_MULTI_ACCOUNT':'0'}),patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(bot,'telegram',side_effect=send),patch.object(job_runtime, 'enqueue',side_effect=lambda *a,**k:events.append('enqueue')):
            app.app.test_client().post('/telegram/webhook',json={'update_id':2,'callback_query':query},headers={'X-Telegram-Bot-Api-Secret-Token':'secret-test'})
        self.assertEqual(events,['answerCallbackQuery','editMessageText','enqueue'])
        self.assertIn('Camarero',calls[1]['text'])
        self.assertEqual(json.loads(calls[1]['reply_markup']),{'inline_keyboard':[]})

    def test_callback_notice_failure_does_not_block_selected_job_enqueue(self):
        store=MemoryStore();store.write('1',{'state':'awaiting_selection','positions':['Chef','Camarero'],'owner_id':123,'progress_message_id':50},0)
        def send(config,method,data,files=None):
            if method=='answerCallbackQuery':raise bot.TelegramError('Transient callback error')
            return {}
        query={'id':'q','from':{'id':123},'message':{'chat':{'id':123,'type':'private'}},'data':'position:1:1'}
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1','CV_MULTI_ACCOUNT':'0'}),patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(bot,'telegram',side_effect=send),patch.object(job_runtime, 'enqueue') as queue:
            response=app.app.test_client().post('/telegram/webhook',json={'update_id':2,'callback_query':query},headers={'X-Telegram-Bot-Api-Secret-Token':'secret-test'})
        self.assertEqual(response.status_code,200);queue.assert_called_once()
        self.assertEqual(store.read('1')[0]['selected_position'],'Camarero')

    def test_real_stages_edit_one_message_and_success_follows_document_confirmation(self):
        store=MemoryStore();store.write('1',{'state':'queued','message':message(message_id=7),'source_message_id':7},0)
        calls=[]
        def send(config,method,data,files=None):calls.append((method,data));return {'message_id':50}
        with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'vacancy_payload',return_value={}),patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/id/view'),patch.object(bot,'telegram',side_effect=send):
            bot.process_job(self.core(),CONFIG,'1',store)
        self.assertEqual(sum(method=='sendMessage' for method,data in calls),2)
        for method,data in calls:
            if method=='editMessageText':self.assertEqual(data['message_id'],50)
        self.assertEqual(calls[-3][0],'sendDocument')
        self.assertIn('no indica un correo',calls[-2][1]['text'])
        self.assertIn('PDF disponible',calls[-1][1]['text'])
        self.assertIn('resultado del correo se informa por separado',calls[-1][1]['text'])
        self.assertEqual(store.read('1')[0]['progress_stage'],'done')

    def test_selected_vacancy_reuses_encrypted_extraction_without_downloading_again(self):
        store=MemoryStore();store.write('1',{'state':'queued','message':message(text='Anuncio')},0)
        core=self.core();core.analyze_with_model.side_effect=app.VacancySelectionRequired(['Chef','Camarero'])
        with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'vacancy_payload',return_value={}) as download,patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/id/view'),patch.object(bot,'telegram',return_value={'message_id':50}):
            bot.process_job(core,CONFIG,'1',store)
            job,generation=store.read('1')
            self.assertTrue(job['cached_input']);self.assertNotIn('SECRET-ADVERT',str(job))
            job.update(state='queued',selected_position='Camarero');store.write('1',job,generation)
            core.analyze_with_model.side_effect=None
            bot.process_job(core,CONFIG,'1',store)
        self.assertEqual(download.call_count,1);self.assertEqual(core.extract_vacancy.call_count,1)
        self.assertEqual(core.analyze_with_model.call_count,2)
        self.assertIsNone(store.read('1')[0]['cached_input'])

    def test_visual_errors_do_not_cancel_cv_or_repeat_slow_edits(self):
        store=MemoryStore();store.write('1',{'state':'queued','message':message()},0)
        edits=[]
        def send(config,method,data,files=None):
            if method=='editMessageText':edits.append(data);raise bot.TelegramError('Offline')
            return {'message_id':50}
        with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'vacancy_payload',return_value={}),patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/id/view'),patch.object(bot,'telegram',side_effect=send):
            bot.process_job(self.core(),CONFIG,'1',store)
        self.assertEqual(store.read('1')[0]['state'],'done')
        self.assertEqual(len(edits),2)

    def test_failed_delivery_never_displays_completed(self):
        store=MemoryStore();store.write('1',{'state':'queued','message':message()},0)
        def send(config,method,data,files=None):
            if method=='sendDocument':raise bot.TelegramError('Unconfirmed')
            return {'message_id':50}
        with patch.object(bot,'drive_token',return_value='token'),patch.object(bot,'vacancy_payload',return_value={}),patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/id/view'),patch.object(bot,'telegram',side_effect=send):
            bot.process_job(self.core(),CONFIG,'1',store)
        self.assertEqual(store.read('1')[0]['state'],'delivery_started')
        self.assertEqual(store.read('1')[0]['progress_stage'],'uncertain')

    def test_status_excludes_other_accounts_and_cached_token_avoids_refresh(self):
        store=MemoryStore();store.write('vacancy-queue',{'pending':[{'id':'1'},{'id':'2'}]},0)
        store.write('1',{'owner_id':123,'progress_text':'Analizando tu anuncio'},0)
        store.write('2',{'owner_id':456,'progress_text':'PRIVATE-OTHER-USER'},0)
        self.assertIn('Analizando',bot.status_summary(CONFIG,store))
        self.assertNotIn('PRIVATE-OTHER-USER',bot.status_summary(CONFIG,store))
        with patch.object(bot.requests,'post') as request:
            self.assertEqual(bot.drive_token({**CONFIG,'_access_token':'cached','_access_until':time.time()+100}),'cached')
        request.assert_not_called()
