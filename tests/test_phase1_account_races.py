import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import app
import onboarding
import user_accounts as users
import tests.test_admin_user_actions as fixtures
from test_onboarding import RECORD
from test_user_accounts import Drive
import account_writes


class DeletionRaces(unittest.TestCase):
    headers = fixtures.ActionTests.headers
    setUp = fixtures.ActionTests.setUp
    preview = fixtures.ActionTests.preview
    execute = fixtures.ActionTests.execute

    def test_delete_cannot_pass_a_save_already_in_flight(self):
        plan = self.preview('delete_user').json
        entered, release = threading.Event(), threading.Event()
        def upload(*args):
            entered.set()
            self.assertTrue(release.wait(4))
            return 'one-file'
        def save():
            marker = users.CURRENT.set({'uid':'alice','record':RECORD,'email':'alice@example.test','drive_token':'fixture'})
            try:
                return onboarding.save(app, {'name':'Fixture'}, None, self.store)
            finally:
                users.CURRENT.reset(marker)
        with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put', side_effect=upload), ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(save)
            self.assertTrue(entered.wait(2))
            try:
                self.assertEqual(self.execute(plan).status_code, 409)
                self.delete.assert_not_called()
            finally:
                release.set()
            self.assertEqual(writing.result(4)['saved'], 1)

    def test_delete_cannot_pass_prepare_while_a_folder_is_being_created(self):
        plan = self.preview('delete_user').json
        drive, entered, release = Drive(), threading.Event(), threading.Event()
        identity = {'uid':'alice','email':'alice@example.com','name':'Alice'}
        def provider(core, token, method, path, payload=None):
            if method == 'POST':
                entered.set()
                self.assertTrue(release.wait(4))
            return drive.api(core, token, method, path, payload)
        with patch.object(users, 'assert_drive_identity'), patch.object(users, 'api', side_effect=provider), patch.object(app, 'drive_request', side_effect=drive.request), ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(users.prepare, app, identity, 'fixture', None, self.store)
            self.assertTrue(entered.wait(2))
            try:
                self.assertEqual(self.execute(plan).status_code, 409)
                self.delete.assert_not_called()
            finally:
                release.set()
            self.assertIn('bank', writing.result(4))

    def test_prepare_and_save_refuse_while_delete_owns_the_account(self):
        plan = self.preview('delete_user').json
        entered, release = threading.Event(), threading.Event()
        def revoke(uid):
            entered.set()
            self.assertTrue(release.wait(4))
        with patch.object(self.revoke,'side_effect',revoke), ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(self.execute,plan)
            self.assertTrue(entered.wait(2))
            marker = users.CURRENT.set({'uid':'alice','record':RECORD,'email':'alice@example.test','drive_token':'fixture'})
            try:
                with patch.object(users,'assert_drive_identity'), patch.object(onboarding,'put') as upload, patch.object(users,'api') as folders:
                    for write in (lambda:onboarding.save(app,{'name':'Fixture'},None,self.store),lambda:users.prepare(app,users.CURRENT.get(),'fixture',store=self.store)):
                        with self.assertRaises(app.AppError) as failure: write()
                        self.assertEqual(failure.exception.code,'job_account_maintenance')
                    upload.assert_not_called();folders.assert_not_called()
            finally:
                users.CURRENT.reset(marker)
                release.set()
            self.assertEqual(deleting.result(4).status_code,200)
