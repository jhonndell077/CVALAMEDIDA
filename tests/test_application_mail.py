"""Executable offline tests: real PDFs, decoded MIME and mocked Google boundary."""
import base64
import hashlib
import socket
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock, patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
import application_mail as mail


def pdf_bytes(text='CV de prueba: experiencia verificada'):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 70), text)
        return doc.tobytes()


class ApplicationMailTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('NETWORK_DISABLED'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.pdf = pdf_bytes()
        self.args = ['alice@gmail.com', 'jobs@example.com', 'Ana Pérez', 'Atención al cliente',
                     '12345678-1234-1234-1234-123456789012', self.pdf]

    def decoded(self, args=None, **kw):
        payload, details = mail.compose(*(args or self.args), **kw)
        return BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(payload['raw'])), details

    def test_actual_mime_identity_subject_date_and_id(self):
        message, details = self.decoded()
        self.assertEqual(message['From'].addresses[0].addr_spec, 'alice@gmail.com')
        self.assertEqual(message['From'].addresses[0].display_name, 'Ana Pérez')
        self.assertEqual(str(message['To']), 'jobs@example.com')
        self.assertEqual(str(message['Subject']), 'Postulación a Atención al cliente — Ana Pérez')
        self.assertIsNotNone(message['Date'].datetime)
        self.assertEqual(str(message['Message-ID']), '<' + self.args[4] + '@cvalamedida.web.app>')
        self.assertEqual(details['rfc_message_id'], self.args[4] + '@cvalamedida.web.app')

    def test_plain_html_and_pdf_integrity(self):
        message, details = self.decoded(text='Saludos <script>alert(1)</script>\nAna')
        self.assertIn('<script>', message.get_body(('plain',)).get_content())
        html = message.get_body(('html',)).get_content()
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        attachment, = message.iter_attachments()
        self.assertEqual(attachment.get_payload(decode=True), self.pdf)
        self.assertEqual(attachment.get_content_type(), 'application/pdf')
        self.assertEqual(attachment.get_filename(), 'Ana_Perez_Atencion_al_cliente.pdf')
        self.assertEqual(details['pdf_sha256'], hashlib.sha256(self.pdf).hexdigest())

    def test_no_tracking_or_fake_authentication(self):
        message, _ = self.decoded()
        for key in ('Return-Path', 'Authentication-Results', 'DKIM-Signature', 'Reply-To'):
            self.assertIsNone(message[key])
        self.assertNotIn('Asunto:', message.get_body(('plain',)).get_content())
        self.assertNotIn('<img', message.get_body(('html',)).get_content())

    def test_injection_blocked_in_every_header_field(self):
        for index in range(5):
            args = self.args.copy(); args[index] += '\r\nBcc: evil@example.com'
            with self.subTest(field=index), self.assertRaises(ValueError):
                mail.compose(*args)

    def test_recipient_lists_and_duplicates(self):
        self.assertEqual(mail.contacts([' Jobs@example.com ', 'jobs@example.com', 'bad',
                                      'a@example.com,b@example.com']), ['Jobs@example.com'])

    def test_invalid_and_truncated_pdf(self):
        for content in (b'not a PDF', b'%PDF-broken', b'', b'%PDF-1.7'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                mail.validate_pdf(content)

    def test_empty_page_rejected(self):
        with fitz.open() as doc:
            doc.new_page()
            with self.assertRaises(ValueError): mail.validate_pdf(doc.tobytes())

    def test_encrypted_pdf_rejected(self):
        with fitz.open(stream=self.pdf, filetype='pdf') as doc:
            data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='secret')
        with self.assertRaises(ValueError): mail.validate_pdf(data)

    def test_active_pdf_rejected(self):
        with fitz.open(stream=self.pdf, filetype='pdf') as doc:
            doc.xref_set_key(doc.pdf_catalog(), 'OpenAction', '<</S /JavaScript /JS (app.alert(1))>>')
            data = doc.tobytes()
        with self.assertRaises(ValueError): mail.validate_pdf(data)

    def test_pdf_size_limit(self):
        with patch.object(mail, 'MAX_PDF_BYTES', 20), self.assertRaises(ValueError):
            mail.validate_pdf(self.pdf)

    def test_encoded_mime_size_limit(self):
        with patch.object(mail, 'MAX_MIME_BYTES', 100), self.assertRaises(ValueError): self.decoded()

    def test_long_unicode_name_and_stable_message_id(self):
        args = self.args.copy(); args[2] = 'Á' * 190
        first, _ = self.decoded(args); second, _ = self.decoded(args)
        self.assertEqual(first['Message-ID'], second['Message-ID'])
        self.assertLessEqual(len(next(first.iter_attachments()).get_filename()), 164)

    def test_two_concurrent_accounts_have_no_shared_state(self):
        def compose(index):
            args = self.args.copy(); args[0] = f'user{index}@gmail.com'
            args[2] = f'Usuario {index}'; args[5] = pdf_bytes(f'CV del usuario {index}')
            message, details = self.decoded(args)
            return message['From'].addresses[0].addr_spec, details['pdf_sha256']
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(compose, (1, 2)))
        self.assertEqual(a[0], 'user1@gmail.com'); self.assertEqual(b[0], 'user2@gmail.com')
        self.assertNotEqual(a[1], b[1])

    def test_partial_scope_rejected(self):
        for scope in ('', 'https://www.googleapis.com/auth/drive.file', 'https://mail.google.com/'):
            with self.subTest(scope=scope), self.assertRaises(ValueError): mail.require_scope(scope)
        mail.require_scope('openid ' + mail.GMAIL_SCOPE)

    def test_google_errors_fail_closed_and_token_not_in_url(self):
        requests = Mock()
        with patch.dict(sys.modules, {'requests': requests}):
            for status in (401, 403, 429, 500, 503):
                requests.post.return_value = Mock(ok=False, status_code=status)
                with self.subTest(status=status), self.assertRaises(ValueError): mail.verify_grant('private-token')
                self.assertNotIn('private-token', requests.post.call_args.args[0])
            requests.post.side_effect = TimeoutError('secret should never escape')
            with self.assertRaisesRegex(ValueError, 'no se inició'): mail.verify_grant('private-token')

    def test_shared_rate_limits_and_owner_isolation(self):
        class Store:
            def __init__(self): self.values = {}
            def read(self, key): return self.values.get(key, (None, 0))
            def write(self, key, value, version): self.values[key] = (value, version + 1)
        store = Store()
        mail.reserve_rate(store, 'alice', 'jobs@example.com', 'Chef', now=10000)
        with self.assertRaises(ValueError): mail.reserve_rate(store, 'alice', 'jobs@example.com', 'Chef', now=10020)
        with self.assertRaises(ValueError): mail.reserve_rate(store, 'alice', 'other@example.com', 'Chef', now=10005)
        mail.reserve_rate(store, 'bob', 'jobs@example.com', 'Chef', now=10000)
        mail.reserve_rate(store, 'alice', 'jobs@example.com', 'Chef', now=14000)

    def test_rate_cas_conflict_blocks_send(self):
        store = Mock(); store.read.return_value = (None, 0); store.write.side_effect = RuntimeError('conflict')
        with self.assertRaisesRegex(ValueError, 'no se inició'): mail.reserve_rate(store, 'alice', 'jobs@example.com', 'Chef')

    def test_google_scope_verified(self):
        requests = Mock(); requests.post.return_value = Mock(ok=True)
        requests.post.return_value.json.return_value = {'scope': mail.GMAIL_SCOPE}
        with patch.dict(sys.modules, {'requests': requests}): mail.verify_grant('private-token')


if __name__ == '__main__': unittest.main(verbosity=2)
