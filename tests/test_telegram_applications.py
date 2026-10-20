from test_application_mail import pdf_bytes
import application_mail
import job_runtime
import base64, json, unittest, os
from email import policy
from email.parser import BytesParser
from unittest.mock import patch, MagicMock
import app
import telegram_bot as bot
from test_telegram import MemoryStore, CONFIG

class TelegramApplicationsTests(unittest.TestCase):
    def setUp(self):
        grant = patch.object(application_mail, 'verify_grant')
        grant.start(); self.addCleanup(grant.stop)

    def source(self):
        store=MemoryStore()
        store.write('10',{'state':'done','owner_id':123,'contacts':{'emails':['jobs@example.com'],'whatsapp':['18095551234']},
                          'position':'Chef','filename':'CV_Chef.pdf','drive_url':'https://drive.google.com/file/d/file123/view'},0)
        return store
    def core(self):
        core=MagicMock(ARCHIVE_CONFIG={'allowed_email':'owner@example.com'},AppError=app.AppError)
        core.verify_drive_access.return_value={'id':'folder'}
        core.drive_request.return_value={'parents':['folder'],'mimeType':'application/pdf'}
        core.gmail_request.side_effect=[{'email':'owner@example.com','email_verified':True},{'id':'sent1'}]
        return core
    def test_contacts_buttons_and_no_fabricated_contact(self):
        contacts=bot.application_contacts({'vacancy':{'application_emails':['jobs@example.com','bad\n@example.com'],'application_whatsapp':['809-555-1234']}})
        self.assertEqual(contacts,{'emails':['jobs@example.com'],'whatsapp':['18095551234']})
        buttons=bot.application_buttons('10',{'contacts':contacts,'position':'Chef'})['inline_keyboard']
        self.assertIn('https://wa.me/18095551234?',buttons[1][0]['url'])
        self.assertEqual(len(bot.application_buttons('10',{'position':'Chef'})['inline_keyboard']),1)
    def test_automatic_dispatch_uses_existing_pdf_and_never_repeats(self):
        core=self.core(); store=self.source(); response=MagicMock(ok=True)
        response.iter_content.return_value=[pdf_bytes()]
        with patch.object(bot,'drive_token',return_value='test'), patch.object(bot.requests,'get',return_value=response), patch.object(bot,'say'):
            bot.auto_send_application(core,CONFIG,'10',store)
            bot.auto_send_application(core,CONFIG,'10',store)
        self.assertEqual(core.gmail_request.call_count,2)
        self.assertEqual(store.read('10')[0]['gmail_dispatches']['jobs@example.com'],'confirmado por Gmail')

    def test_automatic_dispatch_without_email_explains_and_does_not_send(self):
        core=self.core(); store=self.source(); job,version=store.read('10')
        job['contacts']['emails']=[]; store.write('10',job,version)
        with patch.object(bot,'say') as say:
            bot.auto_send_application(core,CONFIG,'10',store)
        core.gmail_request.assert_not_called()
        self.assertIn('no indica un correo',say.call_args.args[1])

    def test_job_delivers_pdf_then_sends_automatically(self):
        from test_telegram import message
        core=self.core(); store=MemoryStore()
        store.write('10',{'state':'queued','message':message(message_id=7),'pdf_ready':True,
                         'position':'Chef','filename':'CV.pdf','drive_url':'https://drive.google.com/file/d/file123/view',
                         'owner_id':123,'contacts':{'emails':['jobs@example.com']}},0)
        store.put_pdf('10',pdf_bytes()); events=[]
        def deliver(config,method,data,**kwargs):
            if method=='sendDocument': events.append('pdf')
            return {'message_id':50}
        def dispatch(core,config,action,store):
            self.assertEqual(store.read('10')[0]['state'],'done')
            events.append('gmail')
        with patch.object(bot,'telegram',side_effect=deliver), patch.object(bot,'process_application',side_effect=dispatch):
            bot._process_job(core,CONFIG,'10',store)
        self.assertEqual(events,['pdf','gmail'])
        self.assertEqual(store.read('10')[0]['state'],'done')

    def test_private_callback_rejects_foreign_owner_and_group(self):
        query={'id':'q','from':{'id':123},'message':{'chat':{'type':'private','id':123}},'data':'gmail:10:0'}
        self.assertIsNotNone(bot.private_callback({'update_id':11,'callback_query':query},CONFIG))
        query['from']['id']=456
        self.assertIsNone(bot.private_callback({'update_id':11,'callback_query':query},CONFIG))
        query['from']['id']=123;query['message']['chat']['type']='group'
        self.assertIsNone(bot.private_callback({'update_id':11,'callback_query':query},CONFIG))
    def test_actual_pdf_mime_history_and_repeated_click(self):
        core=self.core();store=self.source();response=MagicMock(ok=True)
        response.iter_content.return_value=[pdf_bytes()]
        with patch.object(bot,'drive_token',return_value='test'),patch.object(bot.requests,'get',return_value=response),patch.object(bot,'say'):
            bot.process_application(core,CONFIG,{'source_job':'10','recipient_index':0},store)
            bot.process_application(core,CONFIG,{'source_job':'10','recipient_index':0},store)
        self.assertEqual(core.gmail_request.call_count,2)
        payload=json.loads(core.gmail_request.call_args.args[2])
        mail=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload['raw']))
        self.assertEqual(mail['To'],'jobs@example.com');self.assertEqual(mail['Subject'],'Postulación a Chef — owner@example.com')
        self.assertTrue(list(mail.iter_attachments())[0].get_payload(decode=True).startswith(b'%PDF-'))
        self.assertEqual(core.save_application_record.call_args.args[0]['status'],'gmail_accepted')
        self.assertEqual(store.read('10')[0]['gmail_dispatches']['jobs@example.com'],'confirmado por Gmail')
    def test_unknown_send_never_repeated(self):
        core=self.core();store=self.source();response=MagicMock(ok=True)
        response.iter_content.return_value=[pdf_bytes()]
        core.gmail_request.side_effect=[{'email':'owner@example.com','email_verified':True},app.AppError('unknown',502)]
        with patch.object(bot,'drive_token',return_value='test'),patch.object(bot.requests,'get',return_value=response),patch.object(bot,'say'):
            with self.assertRaises(app.AppError):bot.process_application(core,CONFIG,{'source_job':'10','recipient_index':0},store)
            bot.process_application(core,CONFIG,{'source_job':'10','recipient_index':0},store)
        self.assertEqual(core.gmail_request.call_count,2)
        self.assertEqual(core.save_application_record.call_args.args[0]['status'],'send_unknown')
    def test_foreign_source_or_index_cannot_send(self):
        core=self.core();store=self.source()
        with self.assertRaises(bot.TelegramError):bot.process_application(core,CONFIG,{'source_job':'10','recipient_index':1},store)
        with self.assertRaises(bot.TelegramError):bot.process_application(core,{**CONFIG,'owner_id':456},{'source_job':'10','recipient_index':0},store)
        core.gmail_request.assert_not_called()
    def test_callback_creates_queued_action_without_sending_email(self):
        store=self.source();query={'id':'q','from':{'id':123},'message':{'chat':{'id':123,'type':'private'}},'data':'gmail:10:0'}
        with patch.object(job_runtime, 'configuration',return_value=CONFIG),patch.object(job_runtime, 'JobStore',return_value=store),patch.object(job_runtime, 'enqueue') as queue,patch.object(bot,'telegram'),patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}):
            response=app.app.test_client().post('/telegram/webhook',json={'update_id':11,'callback_query':query},headers={'X-Telegram-Bot-Api-Secret-Token':'secret-test'})
        self.assertEqual(response.status_code,200);self.assertEqual(store.read('11')[0]['action']['source_job'],'10');queue.assert_called_once()

