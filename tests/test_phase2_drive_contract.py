"""Offline regression matrix; every provider transport is replaced."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
import app
import onboarding
import user_accounts

URL = 'https://www.googleapis.com/drive/v3/files'
PRIVATE = 'PRIVATE TOKEN CV MESSAGE'

class DriveContractTests(unittest.TestCase):
    def test_all_methods_share_classification_without_provider_content(self):
        cases = [(401,None,'google_authorization_expired'),
                 (403,None,'drive_access_undetermined'), (404,None,'drive_access_undetermined'),
                 (403,'insufficientPermissions','google_permissions_missing'),
                 (403,'insufficientFilePermissions','drive_folder_permission'),
                 (403,'storageQuotaExceeded','drive_storage_full'),
                 (403,'accessNotConfigured','google_api_disabled'),
                 (403,'authError','google_authorization_expired'),
                 (429,None,'google_rate_limit'),(503,None,'google_request_failed')]
        for status, reason, expected in cases:
            for method in ('GET','POST','PATCH','upload'):
                with self.subTest(status=status,reason=reason,method=method):
                    body=json.dumps({'error':{'message':PRIVATE,'errors':[{'reason':reason}]}}).encode()
                    response=SimpleNamespace(ok=False,status_code=status,content=body)
                    with patch('urllib.request.urlopen',side_effect=HTTPError(URL,status,PRIVATE,{},io.BytesIO(body))), \
                         patch.object(user_accounts.requests,'request',return_value=response), \
                         patch.object(user_accounts.requests,'patch',return_value=response), \
                         patch.object(user_accounts,'existing',return_value={'id':'fixture'}):
                        with self.assertRaises(app.AppError) as caught:
                            if method=='PATCH': onboarding.put(app,'TOKEN','folder','file','text/plain',b'CV')
                            elif method=='upload': app.drive_request(URL,'TOKEN',b'CV')
                            else: user_accounts.api(app,'TOKEN',method,'files',{})
                    error=caught.exception
                    self.assertEqual(getattr(error,'code',None),expected)
                    self.assertEqual(error.status_code,429 if status==429 else 401 if status==401 or reason=='authError' else 403 if status in (403,404) else 502)
                    with app.app.test_request_context('/api/account/setup'):
                        result,_=app.handle_app_error(error)
                        data=result.get_json()
                    for key in ('code','stage','operationId','correlationId','retryable','safeNextAction','externalOutcome','buildId'):
                        self.assertIn(key,data)
                    self.assertIn('error',data)  # Existing clients keep their original field.
                    self.assertNotIn(PRIVATE,json.dumps(data))
                    self.assertEqual(data['stage'],'drive-prepare' if method=='POST' else 'drive-upload' if method in ('PATCH','upload') else 'drive-access-check')

    def test_malformed_provider_bodies_do_not_invent_permission_revocation(self):
        for body in (b'',b'<html>PRIVATE TOKEN CV MESSAGE</html>',b'[]',b'{"error":"private"}'):
            with self.subTest(body=body), patch('urllib.request.urlopen',side_effect=HTTPError(URL,504,PRIVATE,{},io.BytesIO(body))):
                with self.assertRaises(app.AppError) as caught: app.drive_request(URL,'TOKEN')
                self.assertEqual(caught.exception.code,'google_request_failed')
                self.assertNotIn(PRIVATE,str(caught.exception))

    def test_account_write_codes_have_conservative_contract(self):
        import error_contract
        for code in ('job_account_maintenance','account_write_busy','account_write_lease_lost','account_write_outcome_unknown','admin_delete_failed'):
            result=error_contract.details(code)
            self.assertEqual(result['code'],code)
            self.assertEqual(result['retryable'],code=='account_write_busy')
            if code=='account_write_outcome_unknown':
                self.assertEqual(result['externalOutcome'],'unknown')
                self.assertEqual(result['safeNextAction'],'review_outcome')

    def test_error_info_and_malformed_reasons_are_safe(self):
        from drive_error_details import classify
        self.assertEqual(classify(URL,403,b'{"error":{"details":[{"reason":"SERVICE_DISABLED","metadata":{"private":"TOKEN"}}]}}')[0],'google_api_disabled')
        self.assertEqual(classify(URL,403,b'{"error":{"errors":[{"reason":{"private":"TOKEN"}}]}}')[0],'drive_access_undetermined')

    def test_bank_adapter_uses_same_safe_translation(self):
        from drive_bank import DriveBank, BankError
        bank=DriveBank({})
        bank._session=SimpleNamespace(request=lambda *a,**k:SimpleNamespace(status_code=401,ok=False,content=b'PRIVATE'))
        with self.assertRaises(BankError) as caught: bank.request('GET',URL)
        self.assertEqual(caught.exception.code,'google_authorization_expired')
        self.assertEqual(caught.exception.status_code,401)
