from pdf_fixture import PDF
import base64
import json
import os
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

import app as cv_app
import job_runtime
from test_telegram import MemoryStore


class GmailSendingTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CV_AUTH_REQUIRED": "0", "CV_ALLOW_REMOTE": "1"})
        env.start()
        self.addCleanup(env.stop)
        durable_store = patch.object(job_runtime, 'JobStore', return_value=MemoryStore())
        durable_store.start()
        self.addCleanup(durable_store.stop)
        self.client = cv_app.app.test_client()
        self.payload = {"application_id": "12345678-1234-1234-1234-123456789012",
                        "recipient": "empleos@example.com", "message": "Hola, adjunto mi CV.", "analysis": {}}
        self.headers = {"X-Gmail-Access-Token": "gmail-test", "X-Drive-Access-Token": "drive-test"}
        self.identity = {"email": cv_app.ARCHIVE_CONFIG["allowed_email"], "email_verified": True}

    def test_pdf_recipient_subject_and_message_are_in_actual_mime(self):
        import io
        with patch.object(cv_app, "gmail_request", side_effect=[self.identity, {"id": "gmail-message-id"}]) as gmail, \
             patch.object(cv_app, "verify_drive_access", return_value={"id": "folder"}), \
             patch.object(cv_app, "drive_request", return_value={"files": []}), \
             patch.object(cv_app, "make_draft", return_value={"position": "Chef de partida", "candidate":{"name":"Alice"}}), \
             patch.object(cv_app, "make_pdf", return_value=io.BytesIO(PDF)), \
             patch.object(cv_app, "archive_generated_resume", return_value="https://drive.google.com/file/d/cv/view"), \
             patch.object(cv_app, "save_application_record") as history:
            result = self.client.post("/api/gmail/send", json=self.payload, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["entry"]["status"], "gmail_accepted")
            self.assertEqual(result.json["entry"]["sender"], self.identity["email"])
            self.assertEqual(result.json["entry"]["rfc_message_id"], self.payload["application_id"] + '@cvalamedida.web.app')
            raw = json.loads(gmail.call_args.args[2])["raw"]
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
            self.assertEqual(message["To"], "empleos@example.com")
            self.assertEqual(message["Subject"], "Postulación a Chef de partida — Alice")
            self.assertIn("Hola, adjunto mi CV.", message.get_body(preferencelist=("plain",)).get_content())
            attachment = list(message.iter_attachments())[0]
            self.assertEqual(attachment.get_content_type(), "application/pdf")
            self.assertEqual(attachment.get_payload(decode=True), PDF)
            self.assertTrue(attachment.get_filename().startswith('Alice_'))
            self.assertEqual(history.call_count, 2)

    def test_repeated_success_does_not_send_twice(self):
        prior = {"status": "gmail_accepted", "gmail_message_id": "existing"}
        with patch.object(cv_app, "gmail_request", return_value=self.identity) as gmail, \
             patch.object(cv_app, "verify_drive_access", return_value={"id": "folder"}), \
             patch.object(cv_app, "drive_request", return_value={"files": [{"description": json.dumps(prior)}]}), \
             patch.object(cv_app, "make_pdf") as pdf:
            result = self.client.post("/api/gmail/send", json=self.payload, headers=self.headers)
            self.assertTrue(result.json["already_sent"])
            self.assertEqual(gmail.call_count, 1)
            pdf.assert_not_called()

    def test_uncertain_previous_attempt_is_not_resent(self):
        with patch.object(cv_app, "gmail_request", return_value=self.identity) as gmail, \
             patch.object(cv_app, "verify_drive_access", return_value={"id": "folder"}), \
             patch.object(cv_app, "drive_request", return_value={"files": [{"description": '{"status":"send_unknown"}'}]}):
            self.assertEqual(self.client.post("/api/gmail/send", json=self.payload, headers=self.headers).status_code, 409)
            self.assertEqual(gmail.call_count, 1)

    def test_unauthorized_sender_and_header_injection_are_rejected(self):
        with patch.object(cv_app, "gmail_request", return_value={"email": "other@example.com", "email_verified": True}) as gmail:
            self.assertEqual(self.client.post("/api/gmail/send", json=self.payload, headers=self.headers).status_code, 403)
            result = self.client.post("/api/gmail/send", json={**self.payload, "recipient": "a@example.com\r\nBcc: evil@example.com"}, headers=self.headers)
            self.assertEqual(result.status_code, 400)
            self.assertEqual(gmail.call_count, 1)

    def test_history_failure_after_acceptance_is_warning_not_send_failure(self):
        import io
        with patch.object(cv_app, "gmail_request", side_effect=[self.identity, {"id": "gmail-message-id"}]) as gmail, \
             patch.object(cv_app, "verify_drive_access", return_value={"id": "folder"}), \
             patch.object(cv_app, "drive_request", return_value={"files": []}), \
             patch.object(cv_app, "make_draft", return_value={"position": "Chef", "candidate":{"name":"Alice"}}), \
             patch.object(cv_app, "make_pdf", return_value=io.BytesIO(PDF)), \
             patch.object(cv_app, "archive_generated_resume", return_value="https://drive.google.com/file/d/cv/view"), \
             patch.object(cv_app, "save_application_record", side_effect=[None, cv_app.AppError("Drive no disponible", 502)]):
            result = self.client.post("/api/gmail/send", json=self.payload, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["entry"]["status"], "gmail_accepted")
            self.assertIn("No vuelvas a enviarlo", result.json["warning"])
            self.assertEqual(gmail.call_count, 2)


if __name__ == "__main__":
    unittest.main()
