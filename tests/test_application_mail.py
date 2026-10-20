import hashlib
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch, MagicMock
import pymupdf as fitz
import application_mail as mail
import telegram_bot as bot
import app
from pdf_fixture import PDF
from test_telegram import CONFIG, MemoryStore

ATTEMPT = '12345678-1234-1234-1234-123456789012'
SCOPES = 'https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.send'


class CompositionTests(unittest.TestCase):
    def compose(self, **changes):
        data = dict(sender='alice@gmail.com', recipient='jobs@example.com', position='Técnico de almacén',
                    name='María Pérez', attempt=ATTEMPT, content=PDF, filename='Maria_Perez_Tecnico.pdf')
        data.update(changes)
        return mail.compose(**data)

    def test_mime_headers_plain_html_hash_and_exact_bytes(self):
        message, digest = self.compose(text='Saludos:\n\nExperiencia <real> & verificable.')
        parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
        self.assertEqual(parsed['From'].addresses[0].addr_spec, 'alice@gmail.com')
        self.assertEqual(parsed['From'].addresses[0].display_name, 'María Pérez')
        self.assertEqual(parsed['Subject'], 'Postulación a Técnico de almacén — María Pérez')
        self.assertIsNotNone(parsed['Date'].datetime)
        self.assertEqual(parsed['Message-ID'], '<' + ATTEMPT + '@cvalamedida.web.app>')
        self.assertIn('<real>', parsed.get_body(('plain',)).get_content())
        self.assertIn('&lt;real&gt; &amp;', parsed.get_body(('html',)).get_content())
        attachment = list(parsed.iter_attachments())[0]
        self.assertEqual(attachment.get_content_type(), 'application/pdf')
        self.assertEqual(attachment.get_payload(decode=True), PDF)
        self.assertEqual(digest, hashlib.sha256(PDF).hexdigest())

    def test_stable_logical_id_and_custom_reviewed_subject(self):
        first, _ = self.compose(subject='Mi postulación revisada')
        second, _ = self.compose()
        self.assertEqual(first['Message-ID'], second['Message-ID'])
        self.assertEqual(first['Subject'], 'Mi postulación revisada')

    def test_long_spanish_name_survives_serialization(self):
        name = 'María José ' * 25
        msg, _ = self.compose(name=name)
        parsed = BytesParser(policy=policy.default).parsebytes(msg.as_bytes())
        self.assertEqual(parsed['From'].addresses[0].display_name, name.strip())

    def test_every_header_blocks_injection(self):
        for field in ('sender', 'recipient', 'position', 'name', 'filename', 'subject'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.compose(**{field: 'Persona\r\nBcc: evil@example.com'})

    def test_invalid_recipient_and_attempt(self):
        for recipient in ('a@example.com,b@example.com', 'Name <a@example.com>', 'invalid', 'a@example.com;'):
            with self.subTest(recipient=recipient), self.assertRaises(ValueError):
                self.compose(recipient=recipient)
        with self.assertRaises(ValueError):
            self.compose(attempt='evil@example.com')

    def test_invalid_and_oversized_pdf(self):
        for content in (b'%PDF-fake', b'not a PDF', b'%PDF-' + b'x' * mail.MAX_PDF):
            with self.subTest(size=len(content)), self.assertRaises(ValueError):
                mail.validate_pdf(content)

    def test_blank_encrypted_and_active_pdf(self):
        with fitz.open() as doc:
            doc.new_page()
            with self.assertRaises(ValueError): mail.validate_pdf(doc.tobytes())
            doc[0].insert_text((72,72), 'Private CV')
            protected = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='test')
            with self.assertRaises(ValueError): mail.validate_pdf(protected)
            action = doc.get_new_xref()
            doc.update_object(action, r'<< /S /JavaScript /JS (app.alert\(1\)) >>')
            doc.xref_set_key(doc.pdf_catalog(), 'OpenAction', f'{action} 0 R')
            with self.assertRaises(ValueError): mail.validate_pdf(doc.tobytes())

    def test_invalid_message(self):
        for value in ('', ' ' * 5, 'x' * 5001, 23):
            with self.subTest(value_type=type(value)), self.assertRaises(ValueError): self.compose(text=value)

    def test_neutral_text_invents_no_company_or_experience(self):
        text = mail.default_text('Mensajero', 'María', 'contact@example.com')
        self.assertNotIn('Asunto:', text)
        self.assertNotIn('experiencia', text)
        self.assertIn('contact@example.com', text)


class PartialGrantTests(unittest.TestCase):
    def test_minimal_and_legacy_full_drive_still_require_gmail(self):
        mail.require_scopes(SCOPES, True)
        mail.require_scopes('https://www.googleapis.com/auth/drive ' + mail.GMAIL_SEND, True)
        for scopes in ('https://www.googleapis.com/auth/drive', SCOPES.replace(mail.GMAIL_SEND, ''), mail.GMAIL_SEND):
            with self.subTest(scopes=scopes), self.assertRaises(ValueError): mail.require_scopes(scopes, True)

    def test_refresh_success_revocation_and_partial_grant(self):
        response = MagicMock(ok=True)
        response.json.return_value = dict(access_token='test', scope=SCOPES)
        config = dict(CONFIG, client_id='test', client_secret='test')
        with patch.object(bot.requests, 'post', return_value=response):
            self.assertEqual(bot.drive_token(config), 'test')
            response.json.return_value = dict(access_token='test', scope=SCOPES.replace(mail.GMAIL_SEND, ''))
            self.assertEqual(bot.drive_token(config), 'test')
            with self.assertRaises(bot.TelegramError): bot.drive_token(config, require_gmail=True)
            response.ok = False
            response.json.return_value = {'error': 'invalid_grant'}
            with self.assertRaises(bot.TelegramError): bot.drive_token(config)

    def test_multiple_recipients_require_selection(self):
        store = MemoryStore()
        store.write('job', {'contacts': {'emails': ['one@example.com', 'two@example.com']}, 'candidate_contact':'candidate@example.com'}, 0)
        with patch.object(bot, 'process_application') as send, patch.object(bot, 'say') as say:
            bot.auto_send_application(app, CONFIG, 'job', store)
            send.assert_not_called()
            self.assertIn('varios correos', say.call_args.args[1])
        buttons = bot.application_buttons('10', store.read('job')[0])['inline_keyboard']
        choices = [button for row in buttons for button in row if button.get('callback_data', '').startswith('gmail:')]
        self.assertEqual([button['callback_data'] for button in choices], ['gmail:10:0','gmail:10:1'])

    def test_contacts_normalize_before_deduplication_and_exclude_candidate(self):
        analysis = {'vacancy': {'application_emails': ['JOBS@example.com', 'jobs@example.com', 'me@example.com']}}
        self.assertEqual(bot.application_contacts(analysis, 'ME@example.com')['emails'], ['jobs@example.com'])


class RateTests(unittest.TestCase):
    def test_same_attempt_is_idempotent_and_accounts_are_independent(self):
        store = MemoryStore()
        mail.reserve_rate(store, 'alice', 'jobs@example.com', ATTEMPT)
        mail.reserve_rate(store, 'alice', 'jobs@example.com', ATTEMPT)
        mail.reserve_rate(store, 'bob', 'jobs@example.com', ATTEMPT)
        with self.assertRaises(ValueError): mail.reserve_rate(store, 'alice', 'other@example.com', 'new')

    def test_recipient_cooldown_and_daily_ceiling(self):
        store = MemoryStore()
        with patch.object(mail.time, 'time', return_value=100000):
            mail.reserve_rate(store, 'alice', 'jobs@example.com', 'first')
        with patch.object(mail.time, 'time', return_value=100040):
            with self.assertRaises(ValueError): mail.reserve_rate(store, 'alice', 'jobs@example.com', 'second')
            mail.reserve_rate(store, 'alice', 'other@example.com', 'second')
        with patch.object(mail.time, 'time', return_value=100400):
            mail.reserve_rate(store, 'alice', 'jobs@example.com', 'third')
        daily = MemoryStore()
        for index in range(20):
            with patch.object(mail.time, 'time', return_value=200000 + index * 31):
                mail.reserve_rate(daily, 'alice', f'jobs{index}@example.com', str(index))
        with patch.object(mail.time, 'time', return_value=201000), self.assertRaises(ValueError):
            mail.reserve_rate(daily, 'alice', 'last@example.com', 'over-limit')


class OwnershipTests(unittest.TestCase):
    def test_shared_bank_and_archive_block_before_loading_or_uploading(self):
        import user_accounts
        identity = {'uid':'alice', 'email':'alice@gmail.com', 'drive_token':'test'}
        marker = user_accounts.CURRENT.set(identity)
        self.addCleanup(user_accounts.CURRENT.reset, marker)
        foreign = {'id':'folder','mimeType':'application/vnd.google-apps.folder',
                   'owners':[{'emailAddress':'admin@gmail.com'}], 'capabilities':{'canAddChildren':True}}
        bank = MagicMock()
        with patch.object(app,'BANK_CLIENT',bank), patch.object(app,'BANK_CONFIG',{'folder_id':'folder'}), patch.object(app,'drive_request',return_value=foreign):
            with self.assertRaises(app.AppError): app.load_drive_bank()
            bank.load.assert_not_called()
        with patch.object(app,'ARCHIVE_CONFIG',{'folder_id':'folder','allowed_email':identity['email']}), patch.object(app,'drive_request',side_effect=[{**identity,'email_verified':True},foreign]):
            with self.assertRaises(app.AppError): app.verify_drive_access('test')

    def test_legacy_authenticated_bank_uses_the_personal_token(self):
        import user_accounts
        identity={'uid':'legacy','email':'legacy@gmail.com'}
        store=MemoryStore()
        store.write(user_accounts.account_key('legacy'),{'legacy':True,'bank':{'folder_id':'bank'},'archive_id':'archive'},0)
        with patch('drive_bank.DriveBank') as factory, patch.object(app,'drive_request',return_value={**identity,'email_verified':True}):
            with user_accounts.scope(app,identity,{'X-Drive-Access-Token':'personal'},store):
                session=factory.call_args.kwargs['session']
                self.assertEqual(session.headers['Authorization'],'Bearer personal')
            with user_accounts.scope(app,identity,store=store):
                self.assertIsNone(app.BANK_CLIENT)


class TransportTests(unittest.TestCase):
    def test_bot_rejects_obsolete_or_modified_archived_pdf(self):
        from test_telegram_applications import TelegramApplicationsTests
        helper = TelegramApplicationsTests()
        for digest in (None, '0' * 64):
            core, store = helper.core(), helper.source()
            source, version = store.read('10')
            source['pdf_sha256'] = digest
            store.write('10', source, version)
            response = MagicMock(ok=True)
            response.iter_content.return_value = [PDF]
            with patch.object(bot, 'drive_token', return_value='test'), patch.object(bot.requests, 'get', return_value=response):
                with self.assertRaises(bot.TelegramError):
                    bot.process_application(core, CONFIG, {'source_job':'10','recipient_index':0}, store)
            self.assertLessEqual(core.gmail_request.call_count, 1)

    def test_two_simultaneous_identities_use_their_own_pdf_sender_and_history(self):
        from concurrent.futures import ThreadPoolExecutor
        from test_audit_runtime import fixture, Store, PAYLOAD, HEADERS
        from pdf_fixture import pdf_bytes
        import job_runtime, user_accounts, json, base64
        store = Store()
        def run(uid):
            core = fixture()
            sender = uid + '@gmail.com'
            content = pdf_bytes('CV ' + uid)
            core.account_state.ARCHIVE_CONFIG['allowed_email'] = sender
            core.verify_drive_access = lambda token: {'id':'folder-' + uid} if token == 'drive-' + uid else self.fail('foreign Drive token')
            core.archive_generated_resume = lambda *_: 'https://drive.google.com/file/d/cv-' + uid + '/view'
            core.make_draft = lambda _: {'position':'Puesto', 'candidate':{'name':uid}}
            core.make_pdf = lambda _: __import__('io').BytesIO(content)
            core.gmail_request = MagicMock(side_effect=[{'email':sender,'email_verified':True},{'id':'gmail-' + uid}])
            history = []
            def save(record, token, folder):
                self.assertEqual(token,'drive-' + uid)
                self.assertEqual(folder['id'],'folder-' + uid)
                history.append(dict(record))
            core.save_application_record = save
            marker = user_accounts.CURRENT.set({'uid':uid})
            try:
                response = core.app.test_client().post('/api/gmail/send', json=PAYLOAD,
                    headers={**HEADERS,'X-Gmail-Access-Token':'gmail-' + uid,'X-Drive-Access-Token':'drive-' + uid})
            finally:
                user_accounts.CURRENT.reset(marker)
            self.assertEqual(response.status_code,200)
            raw = json.loads(core.gmail_request.call_args.args[2])['raw']
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
            self.assertEqual(message['From'].addresses[0].addr_spec,sender)
            self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True),content)
            self.assertTrue(all(record['uid']==uid and record['sender']==sender for record in history))
            return response.json['entry']['pdf_sha256']
        with patch.object(job_runtime,'JobStore',return_value=store), ThreadPoolExecutor(max_workers=2) as pool:
            hashes = list(pool.map(run, ('alice','bob')))
        self.assertNotEqual(*hashes)
        self.assertEqual(sum(key.startswith('gmail-dispatch-') for key in store.jobs),2)

    def test_http_errors_missing_id_and_uncertainty_never_resend(self):
        from test_audit_runtime import fixture, Store, PAYLOAD, HEADERS, AppError
        import job_runtime
        for code, expected in ((401,'failed'), (403,'failed'), (422,'failed'), (429,'send_unknown'), (502,'send_unknown'), (503,'send_unknown'), (None,'send_unknown')):
            with self.subTest(code=code):
                core, store = fixture(), Store()
                outcome = AppError('sanitized', code) if code else {}
                core.gmail_request = MagicMock(side_effect=[{'email':'fixture@example.invalid','email_verified':True}, outcome,
                                                           {'email':'fixture@example.invalid','email_verified':True}])
                with patch.object(job_runtime,'JobStore',return_value=store):
                    client = core.app.test_client()
                    result = client.post('/api/gmail/send', json=PAYLOAD, headers=HEADERS)
                    self.assertGreaterEqual(result.status_code, 400)
                    self.assertEqual(client.post('/api/gmail/send', json=PAYLOAD, headers=HEADERS).status_code,409)
                records = [value[0] for key,value in store.jobs.items() if key.startswith('gmail-dispatch-')]
                self.assertEqual(records[0]['state'],expected)
                self.assertEqual(core.gmail_request.call_count,3)

    def test_foreign_and_obsolete_artifacts_never_send(self):
        from test_audit_runtime import fixture, Store, PAYLOAD, HEADERS
        import job_runtime
        artifact_id = 'a' * 32
        for owner in ('another-uid', 'fixture@example.invalid'):
            with self.subTest(owner=owner):
                core, store = fixture(), Store()
                store.write('mail-pdf-' + artifact_id, dict(owner=owner, draft_digest='obsolete', created_at=0), 0)
                core.gmail_request = MagicMock(return_value={'email':'fixture@example.invalid','email_verified':True})
                with patch.object(job_runtime,'JobStore',return_value=store):
                    result=core.app.test_client().post('/api/gmail/send',json={**PAYLOAD,'artifact_id':artifact_id},headers=HEADERS)
                self.assertEqual(result.status_code,409)
                self.assertEqual(core.gmail_request.call_count,1)

    def test_archived_artifact_is_attached_without_regeneration(self):
        import json, time, base64
        from test_audit_runtime import fixture, PAYLOAD, HEADERS
        import job_runtime
        core, store = fixture(), MemoryStore()
        artifact_id = 'b' * 32
        draft = core.make_draft({})
        store.write('mail-pdf-' + artifact_id, dict(owner='fixture@example.invalid',
            draft_digest=hashlib.sha256(json.dumps(draft,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            pdf_sha256=hashlib.sha256(PDF).hexdigest(), cv_url='https://drive.google.com/file/d/archived/view', created_at=time.time()),0)
        store.put_pdf('mail-pdf-' + artifact_id, PDF)
        core.make_pdf = MagicMock(side_effect=AssertionError('must reuse artifact'))
        core.archive_generated_resume = MagicMock(side_effect=AssertionError('must reuse archive'))
        core.gmail_request=MagicMock(side_effect=[{'email':'fixture@example.invalid','email_verified':True},{'id':'accepted'}])
        with patch.object(job_runtime,'JobStore',return_value=store):
            result=core.app.test_client().post('/api/gmail/send',json={**PAYLOAD,'artifact_id':artifact_id},headers=HEADERS)
        self.assertEqual(result.status_code,200)
        raw=json.loads(core.gmail_request.call_args.args[2])['raw']
        message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
        self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True),PDF)
        self.assertEqual(result.json['entry']['cv_url'],'https://drive.google.com/file/d/archived/view')
