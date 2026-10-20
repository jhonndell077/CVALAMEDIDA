from pdf_fixture import PDF
import job_runtime
import copy
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import app
import telegram_bot as bot
from test_app import valid_analysis
from test_telegram import MemoryStore, CONFIG, message

POSITIONS = ['Encargado de contabilidad','Asistente operativo','Auxiliar de cobros','Analista de cobros','Analista contable','Community manager','Diseñador gráfico']

class VacancySelectionTests(unittest.TestCase):
    def raw(self):
        analysis = valid_analysis()
        analysis['vacancy']['advertised_positions'] = POSITIONS
        return analysis

    def test_multiple_roles_require_choice_before_evidence_or_draft(self):
        raw = self.raw()
        raw['vacancy']['position'] = ''
        raw['matching']['selected_experiences'] = []
        raw['matching']['selected_project_ids'] = []
        with self.assertRaises(app.VacancySelectionRequired) as choice:
            app.sanitize_analysis(raw)
        self.assertEqual(choice.exception.positions, POSITIONS)
        with self.assertRaises(app.AppError):
            app.make_draft(self.raw())

    def test_only_selected_advertised_role_names_cv_and_unadvertised_role_rejected(self):
        selected = app.sanitize_analysis(self.raw(), 'Asistente operativo')
        self.assertEqual(app.make_draft(selected)['position'], 'Asistente operativo')
        with self.assertRaises(app.AppError):
            app.sanitize_analysis(self.raw(),'Secretaria administrativa')

    def test_web_route_returns_options_then_accepts_selected_role(self):
        with patch.dict(os.environ, {'CV_AUTH_REQUIRED':'0','CV_BANK_PROVIDER':'local','CV_ALLOW_REMOTE':'0'}), patch.object(app,'require_model',return_value='test'), patch.object(app,'analyze_with_model',side_effect=app.VacancySelectionRequired(POSITIONS)):
            response = app.app.test_client().post('/api/analyze',json={'text':'Anuncio con siete puestos','model':'test'})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json['selection_required'])
            self.assertNotIn('analysis',response.json)
        with patch.dict(os.environ, {'CV_AUTH_REQUIRED':'0','CV_BANK_PROVIDER':'local','CV_ALLOW_REMOTE':'0'}), patch.object(app,'require_model',return_value='test'), patch.object(app,'analyze_with_model',return_value=app.sanitize_analysis(self.raw(),'Analista contable')) as analyze:
            response = app.app.test_client().post('/api/analyze',json={'text':'Anuncio con siete puestos','model':'test','selected_position':'Analista contable'})
            self.assertEqual(response.json['analysis']['vacancy']['position'],'Analista contable')
            self.assertEqual(analyze.call_args.args[-1],'Analista contable')

    def test_bot_waits_resumes_same_job_and_replies_to_original_message(self):
        store = MemoryStore()
        store.admit('10')
        store.write('10',{'state':'queued','message':message(message_id=100,text='Siete oportunidades'),'source_message_id':100},0)
        core = MagicMock(AppError=app.AppError, VacancySelectionRequired=app.VacancySelectionRequired, MAX_FILE_BYTES=1000, VERTEX_MODEL='test')
        core.load_drive_bank.return_value={'pending':0}
        core.extract_vacancy.return_value=('Siete oportunidades',[])
        core.analyze_with_model.side_effect=app.VacancySelectionRequired(POSITIONS)
        with patch.object(bot,'drive_token',return_value='token'), patch.object(bot,'say'), patch.object(bot,'vacancy_payload',return_value={}), patch.object(bot,'telegram',return_value={'message_id':200}) as telegram:
            bot.process_job(core,CONFIG,'10',store)
            self.assertEqual(store.read('10')[0]['state'],'awaiting_selection')
            core.make_draft.assert_not_called()
            prompt = telegram.call_args.args[2]
            initial=next(call for call in telegram.call_args_list if call.args[1]=='sendMessage')
            self.assertEqual(json.loads(initial.args[2]['reply_parameters'])['message_id'],100)
            buttons = json.loads(prompt['reply_markup'])['inline_keyboard']
            self.assertEqual(len(buttons),7)
            self.assertEqual(buttons[1][0]['callback_data'],'position:10:1')
            bot.process_job(core,CONFIG,'10',store)
            self.assertEqual(core.analyze_with_model.call_count,1)
        query = {'id':'query-test','from':{'id':123},'message':{'chat':{'type':'private','id':123}},'data':'position:10:1'}
        with patch.dict(os.environ, {'CV_AUTH_REQUIRED':'1','CV_ALLOW_REMOTE':'1'}), patch.object(job_runtime, 'configuration',return_value=CONFIG), patch.object(job_runtime, 'JobStore',return_value=store), patch.object(job_runtime, 'enqueue') as enqueue, patch.object(bot,'telegram',return_value={}):
            client = app.app.test_client()
            headers = {'X-Telegram-Bot-Api-Secret-Token':'secret-test'}
            for _ in range(2):
                self.assertEqual(client.post('/telegram/webhook',json={'update_id':11,'callback_query':query},headers=headers).status_code,200)
            self.assertEqual(enqueue.call_args.args[0],'10')
            self.assertEqual(enqueue.call_args.kwargs['task_identifier'],'11')
            query['data']='position:10:6'
            client.post('/telegram/webhook',json={'update_id':12,'callback_query':query},headers=headers)
            self.assertEqual(store.read('10')[0]['selected_position'],'Asistente operativo')
            self.assertEqual(enqueue.call_count,2)
        core.analyze_with_model.side_effect=None
        core.analyze_with_model.return_value={'vacancy':{'position':'Asistente operativo'}}
        core.make_draft.return_value={'position':'Asistente operativo'}
        core.make_pdf.return_value=io.BytesIO(PDF)
        with patch.object(bot,'drive_token',return_value='token'), patch.object(bot,'say'), patch.object(bot,'vacancy_payload',return_value={}), patch.object(bot,'archive_pdf',return_value='https://drive.google.com/file/d/cv-selected/view'), patch.object(bot,'telegram',return_value={'message_id':201}) as telegram:
            bot.process_job(core,CONFIG,'10',store)
            self.assertEqual(core.analyze_with_model.call_args.args[-1],'Asistente operativo')
            delivered=next(call for call in telegram.call_args_list if call.args[1]=='sendDocument')
            self.assertEqual(json.loads(delivered.args[2]['reply_parameters'])['message_id'],100)
            self.assertEqual(store.read('10')[0]['state'],'done')
