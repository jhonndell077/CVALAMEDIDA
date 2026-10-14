"""New-account journey uses real bank-form extraction and document generators."""
import io,unittest
from pathlib import Path
from unittest.mock import patch
import app,onboarding,user_accounts as users
from drive_bank import extract_facts,merge_profile
from test_user_accounts import Drive,ALICE
from test_telegram import MemoryStore

class NewUserJourneyTests(unittest.TestCase):
    def test_setup_form_bank_and_cv_without_photo_or_employment(self):
        store=MemoryStore();drive=Drive()
        with patch.object(users,'api',side_effect=drive.api),patch.object(app,'drive_request',side_effect=drive.request):
            record=users.prepare(app,ALICE,'test-token',store=store)
        identity=users.CURRENT.set({**ALICE,'record':record,'drive_token':'test-token'})
        try:
            payload={'name':'Alice','education':[{'title':'Bachiller','institution':'Escuela'}], 'skills':['Excel']}
            source=onboarding.collect(app,payload)
            documents={}
            for index,(_,name,mime,raw) in enumerate(source):
                facts=extract_facts(name,mime,raw,'Alice')
                documents[str(index)]={'active':True,'status':'incorporado','name':name,'fingerprint':'v1','facts':facts}
            profile,_=merge_profile(users.blank_profile(ALICE),documents)
            self.assertEqual(profile['candidate']['email'],ALICE['email'])
            self.assertEqual(profile['education'][0]['title'],'Bachiller')
            self.assertEqual(profile['experiences'],[])
            with patch.object(app,'MASTER_PROFILE',profile),patch.object(app,'EXPERIENCE_BY_ID',{}),patch.object(app,'SKILL_BY_ID',{s['id']:s for s in profile['skills']}),patch.object(app,'COURSE_BY_ID',{}),patch.object(app,'current_photo_path',return_value=Path('work/absent-new-user-photo')):
                analysis=app.sanitize_analysis({'vacancy':{'position':'Asistente'},'matching':{}})
                draft=app.make_draft(analysis)
                self.assertEqual(draft['candidate']['email'],ALICE['email'])
                self.assertTrue(app.make_pdf(draft).getvalue().startswith(b'%PDF'))
                self.assertTrue(app.make_docx(draft).getvalue().startswith(b'PK'))
        finally:users.CURRENT.reset(identity)

    def test_word_archive_returns_drive_link_even_when_google_returns_docs_link(self):
        with patch.dict('os.environ',{'CV_ARCHIVE_PROVIDER':'drive'}), patch.object(app,'verify_drive_access',return_value={'id':'cv-folder'}), patch.object(app,'drive_request',side_effect=[{'id':'word-id'},{'id':'word-id','parents':['cv-folder'],'webViewLink':'https://docs.google.com/document/d/word-id/edit'}]):
            with app.app.test_request_context('/',headers={'X-Drive-Access-Token':'test'}):
                self.assertEqual(app.archive_generated_resume('CV.docx','docx',b'PK-test'),'https://drive.google.com/file/d/word-id/view')
