import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import app
from drive_error_details import classify

class DriveErrorDetailsTests(unittest.TestCase):
    def test_confirmed_reasons_and_no_private_text(self):
        for reason, expected in [('storageQuotaExceeded','drive_storage_full'),('insufficientPermissions','google_permissions_missing'),('insufficientFilePermissions','drive_folder_permission'),('accessNotConfigured','google_api_disabled'),('userRateLimitExceeded','google_rate_limit')]:
            result=classify('https://www.googleapis.com/drive/v3/files',403,json.dumps({'error':{'message':'PRIVATE EMAIL TOKEN','errors':[{'reason':reason}]}}))
            self.assertEqual(result[0],expected)
            self.assertNotIn('PRIVATE',str(result))
    def test_unknown_403_does_not_claim_full_storage_or_folder_failure(self):
        code,message=classify('https://www.googleapis.com/oauth2/v3/userinfo',403,b'invalid')
        self.assertEqual(code,'google_identity_check_failed')
        self.assertIn('identidad',message)
        self.assertNotIn('espacio disponible',message)
        self.assertEqual(classify('https://www.googleapis.com/drive/v3/files',403,b'{}')[0],'drive_access_undetermined')
    def test_real_wrapper_preserves_safe_code_and_http_status(self):
        error=HTTPError('https://www.googleapis.com/drive/v3/files',403,'private',{},io.BytesIO(b'{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}'))
        with patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaises(app.AppError) as caught:
                app.drive_request(error.url,'private-token')
        self.assertEqual(caught.exception.code,'drive_storage_full')
        self.assertEqual(caught.exception.status_code,403)
        self.assertNotIn('private',str(caught.exception))
