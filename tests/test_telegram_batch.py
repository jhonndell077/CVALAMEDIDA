from pdf_fixture import PDF
import job_runtime
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import app
import telegram_bot as bot
from test_telegram import MemoryStore, CONFIG, message


class TelegramBatchTests(unittest.TestCase):
    @patch.dict(os.environ, {'CV_DAILY_JOB_LIMIT': '100', 'CV_MONTHLY_JOB_LIMIT': '1000'})
    def test_ten_pending_messages_limit_duplicates_and_freed_slot(self):
        store = MemoryStore()
        with patch.object(job_runtime, 'configuration', return_value=CONFIG), patch.object(job_runtime, 'JobStore', return_value=store), patch.object(bot,'telegram'), patch.object(job_runtime, 'enqueue') as enqueue, patch.object(bot, 'say') as say, patch.dict(os.environ, {'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}):
            client = app.app.test_client()
            headers = {'X-Telegram-Bot-Api-Secret-Token':'secret-test'}
            for number in range(1, 11):
                response = client.post('/telegram/webhook', json={'update_id':number,'message':message(message_id=100+number,text='Vacante '+str(number))},headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(store.read(str(number))[0]['source_message_id'],100+number)
            self.assertEqual(enqueue.call_count,10)
            client.post('/telegram/webhook',json={'update_id':11,'message':message(message_id=111)},headers=headers)
            self.assertEqual(store.read('11')[0]['state'],'rejected')
            self.assertEqual(enqueue.call_count,10)
            self.assertEqual(say.call_args.args[2],111)
            client.post('/telegram/webhook',json={'update_id':11,'message':message(message_id=111)},headers=headers)
            self.assertEqual(say.call_count,1)
            job, generation = store.read('1')
            store.write('1',{**job,'state':'done'},generation)
            client.post('/telegram/webhook',json={'update_id':12,'message':message(message_id=112)},headers=headers)
            self.assertEqual(enqueue.call_count,11)
            self.assertEqual(store.read('12')[0]['state'],'queued')

    def test_each_pdf_replies_to_its_own_vacancy_and_keeps_its_buttons(self):
        store = MemoryStore()
        core = MagicMock(AppError=app.AppError, MAX_FILE_BYTES=1000, VERTEX_MODEL='model')
        core.load_drive_bank.return_value={'pending':0}
        core.extract_vacancy.side_effect=lambda payload:(payload['text'],[])
        core.analyze_with_model.side_effect=lambda model,text,images:{'vacancy':{'position':text,'application_emails':['jobs@example.com']}}
        core.make_draft.side_effect=lambda analysis:{'position':analysis['vacancy']['position']}
        core.make_pdf.side_effect=lambda draft:io.BytesIO(PDF)
        for number in range(1,11):
            store.write(str(number), {'state':'queued','message':message(message_id=number+100,text='Vacante '+str(number)),'source_message_id':number+100},0)
        delivered = []
        def send(config,method,data,files=None):
            if method=='sendDocument': delivered.append((data, files['document'][1]))
            return {'message_id':200+len(delivered)}
        with patch.object(bot,'drive_token',return_value='token'), patch.object(bot,'say'), patch.object(bot,'vacancy_payload',side_effect=lambda msg,*args:msg), patch.object(bot,'archive_pdf',side_effect=lambda core,config,key,*args:'https://drive.google.com/file/d/cv-'+key+'/view'), patch.object(bot,'telegram',side_effect=send), patch.object(bot,'process_application') as dispatch:
            for number in reversed(range(1,11)):
                bot.process_job(core,CONFIG,str(number),store)
                bot.process_job(core,CONFIG,str(number),store)
        self.assertEqual(len(delivered),10)
        self.assertEqual(dispatch.call_count,10)
        self.assertEqual({call.args[2]["source_job"] for call in dispatch.call_args_list}, {str(n) for n in range(1,11)})
        for data, content in delivered:
            original = json.loads(data['reply_parameters'])['message_id']
            number = original-100
            self.assertEqual(content,PDF)
            buttons = json.loads(data['reply_markup'])['inline_keyboard']
            self.assertTrue(any(button.get('callback_data','').startswith('gmail:') for row in buttons for button in row))
