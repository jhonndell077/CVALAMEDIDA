import json
import os
import unittest
from unittest.mock import patch

import app as cv_app


class ApplicationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"CV_AUTH_REQUIRED": "0", "CV_ALLOW_REMOTE": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = cv_app.app.test_client()
        self.entry = {"position": "Chef de partida", "recipient": "empleos@example.com", "channel": "gmail",
                      "status": "prepared", "cv_url": "https://drive.google.com/file/d/test-file/view"}

    def test_cannot_read_history_without_valid_drive_access(self):
        with patch.object(cv_app, "verify_drive_access", side_effect=cv_app.AppError("No autorizado", 403)), \
             patch.object(cv_app, "drive_request") as drive:
            self.assertEqual(self.client.get("/api/applications").status_code, 403)
            drive.assert_not_called()

    def test_upload_stays_in_configured_folder_and_does_not_claim_sent(self):
        with patch.object(cv_app, "verify_drive_access", return_value={"id": "authorized-folder"}), \
             patch.object(cv_app, "drive_request", return_value={"id": "history-file", "parents": ["authorized-folder"]}) as drive:
            response = self.client.post("/api/applications", json=self.entry)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["entry"]["status"], "prepared")
            self.assertIn(b'"parents": ["authorized-folder"]', drive.call_args.args[2])
            self.assertIn(b'"cvDispatch": "1"', drive.call_args.args[2])

    def test_rejects_injected_recipient_and_unverified_sent_status(self):
        with patch.object(cv_app, "verify_drive_access", return_value={"id": "authorized-folder"}), \
             patch.object(cv_app, "drive_request") as drive:
            for changes in [{"recipient": "person@example.com\r\nBcc: other@example.com"}, {"status": "sent"}]:
                response = self.client.post("/api/applications", json={**self.entry, **changes})
                self.assertEqual(response.status_code, 400)
            drive.assert_not_called()

    def test_latest_confirmation_replaces_prepared_event(self):
        prepared = {**self.entry, "application_id": "same-application"}
        confirmed = {**prepared, "status": "confirmed_by_user"}
        with patch.object(cv_app, "verify_drive_access", return_value={"id": "authorized-folder"}), \
             patch.object(cv_app, "drive_request", return_value={"files": [
                 {"description": json.dumps(confirmed)}, {"description": json.dumps(prepared)},
                 {"description": "corrupted record"},
             ]}):
            response = self.client.get("/api/applications")
            self.assertEqual(response.json["entries"], [confirmed])

    def test_whatsapp_click_is_saved_automatically_and_reloaded(self):
        entry = {**self.entry, "recipient":"18095550100", "channel":"whatsapp", "status":"whatsapp_opened"}
        with patch.object(cv_app, "verify_drive_access", return_value={"id":"authorized-folder"}), patch.object(cv_app, "drive_request", return_value={"id":"history-file", "parents":["authorized-folder"]}) as drive:
            response = self.client.post('/api/applications', json=entry)
            self.assertEqual(response.status_code, 200)
            record = response.json['entry']
            self.assertEqual(record['status'], 'whatsapp_opened')
            self.assertTrue(record['date'])
            drive.return_value = {'files':[{'description':json.dumps(record)}]}
            self.assertEqual(self.client.get('/api/applications').json['entries'], [record])
            self.assertEqual(self.client.post('/api/applications',json={**record,'channel':'gmail','recipient':'empleos@example.com'}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
