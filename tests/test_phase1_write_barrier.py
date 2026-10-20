"""Business regressions for a single account-wide write fence, no network."""
import unittest
import os
from unittest.mock import patch
import app
import admission_policy
import onboarding
import user_accounts as users
from test_period_admission import Store
from test_onboarding import IDENTITY, RECORD
from test_user_accounts import ALICE, Drive


class MaintenanceBusinessTests(unittest.TestCase):
    def test_active_maintenance_prevents_onboarding_before_any_drive_write(self):
        store = Store()
        store.write(admission_policy.queue_key(IDENTITY['uid']), {'maintenance': {'action':'delete_user','state':'executing'}}, 0)
        token = users.CURRENT.set({**IDENTITY, 'record':RECORD, 'drive_token':'fixture'})
        try:
            with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put', return_value='file') as upload:
                with self.assertRaises(Exception) as failure:
                    onboarding.save(app, {'name':'Fixture'}, None, store)
                self.assertEqual(getattr(failure.exception, 'code', None), 'job_account_maintenance')
                upload.assert_not_called()
        finally:
            users.CURRENT.reset(token)

    def test_maintenance_prevents_prepare_before_creating_any_folder(self):
        store, drive = Store(), Drive()
        store.write(admission_policy.queue_key(ALICE['uid']), {'maintenance': {'action':'delete_user'}}, 0)
        with patch.object(users, 'assert_drive_identity'), patch.object(users, 'api', side_effect=drive.api), patch.object(app, 'drive_request', side_effect=drive.request):
            with self.assertRaises(Exception) as failure:
                users.prepare(app, ALICE, 'fixture', store=store)
        self.assertEqual(getattr(failure.exception, 'code', None), 'job_account_maintenance')
        self.assertEqual(drive.created, 0)

    def test_new_fence_between_files_stops_next_write_and_completion_marker(self):
        store = Store()
        token = users.CURRENT.set({**IDENTITY,'record':RECORD,'drive_token':'fixture'})
        def first_file(*args):
            key = admission_policy.queue_key(IDENTITY['uid'])
            store.write(key, {'maintenance':{'action':'delete_user','state':'executing'}}, 0)
            return 'first-file-kept'
        try:
            with patch.object(users,'assert_drive_identity'), patch.object(onboarding,'put',side_effect=first_file) as upload:
                with self.assertRaises(app.AppError) as failure:
                    onboarding.save(app, {'name':'Fixture','skills':['Fixture skill']}, None, store)
            self.assertEqual(failure.exception.code,'job_account_maintenance')
            self.assertEqual(upload.call_count,1)
            self.assertIsNone(store.read(onboarding.marker(IDENTITY['uid']))[0])
        finally:
            users.CURRENT.reset(token)

    def test_http_mutations_missing_from_old_paths_are_fenced_before_handler(self):
        from flask import g
        store = Store()
        store.write(admission_policy.queue_key('alice'), {'maintenance':{'action':'delete_user'}}, 0)
        def verify(): g.google_identity = {'uid':'alice','email':'alice@example.invalid','name':'Alice'}
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'1','CV_MULTI_ACCOUNT':'1','CV_ALLOW_REMOTE':'1','CV_BANK_PROVIDER':'local'}), patch.object(app,'verify_google_identity',side_effect=verify), patch.object(app.job_runtime,'JobStore',return_value=store), patch.object(app,'load_drive_bank') as bank:
            for method,path in [('POST','/api/account/onboarding/dismiss'),('POST','/api/account/initial-sync'),('POST','/api/profile/delete'),('PUT','/api/profile')]:
                response = app.app.test_client().open(path,method=method,json={})
                self.assertEqual(response.status_code,409)
                self.assertEqual(response.json['code'],'job_account_maintenance')
            bank.assert_not_called()

    def test_application_boundary_preserves_only_safe_barrier_codes(self):
        with app.app.test_request_context():
            failure = app.AppError('Sincroniza antes de reintentar.',409)
            failure.code = 'account_write_lease_lost'
            failure.private = 'NEVER EXPOSE'
            response, status = app.handle_app_error(failure)
            self.assertEqual(status,409)
            self.assertEqual(response.json['code'],'account_write_lease_lost')
            self.assertNotIn('NEVER EXPOSE',response.get_data(as_text=True))
