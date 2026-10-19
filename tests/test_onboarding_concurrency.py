import threading
import unittest
from unittest.mock import patch
from google.api_core.exceptions import PreconditionFailed
import app
import onboarding
import user_accounts as users
from test_telegram import MemoryStore
from test_onboarding import IDENTITY, RECORD


class OnboardingConcurrencyTests(unittest.TestCase):
    def save(self, store):
        identity = users.CURRENT.set({**IDENTITY, 'record': RECORD, 'drive_token': 'fixture'})
        try:
            return onboarding.save(app, {'name': 'Fixture'}, None, store)
        finally:
            users.CURRENT.reset(identity)

    def test_two_devices_serialize_lookup_and_create_without_duplicate(self):
        store = MemoryStore()
        entered = threading.Event()
        release = threading.Event()
        files = []
        outcomes = []

        def upload(*args):
            if not files:
                entered.set()
                self.assertTrue(release.wait(2))
                files.append('one-file')
            return files[0]

        def device():
            try:
                outcomes.append(self.save(store))
            except Exception as error:
                outcomes.append(error)

        with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put', side_effect=upload):
            first = threading.Thread(target=device)
            first.start()
            self.assertTrue(entered.wait(2))
            second = threading.Thread(target=device)
            second.start()
            release.set()
            first.join(3)
            second.join(3)
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(isinstance(result, dict) for result in outcomes), outcomes)
        self.assertEqual(files, ['one-file'])
        self.assertTrue(store.read(onboarding.marker(IDENTITY['uid']))[0]['completed'])

    def test_same_account_setup_lease_blocks_save_but_not_other_account(self):
        store = MemoryStore()
        key = 'setup-' + users.account_key(IDENTITY['uid'])
        store.write(key, {'holder': 'setup', 'expires_at': onboarding.time.time() + 180}, 0)
        with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put') as upload, patch.object(onboarding.time, 'sleep'):
            with self.assertRaises(app.AppError) as caught:
                self.save(store)
            self.assertTrue(caught.exception.setup_busy)
            upload.assert_not_called()
            with onboarding.save_lease(app, store, 'different-user') as renew:
                renew()
        self.assertEqual(store.read(key)[0]['holder'], 'setup')

    def test_failure_releases_lease_preserves_files_and_retry_succeeds(self):
        store = MemoryStore()
        with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put', side_effect=app.AppError('fixture')):
            with self.assertRaises(app.AppError):
                self.save(store)
        self.assertEqual(store.read('setup-' + users.account_key(IDENTITY['uid']))[0]['expires_at'], 0)
        self.assertIsNone(store.read(onboarding.marker(IDENTITY['uid']))[0])
        with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put', return_value='existing-file'):
            self.assertEqual(self.save(store)['saved'], 1)

    def test_completion_cas_conflict_is_success_when_other_request_completed(self):
        store = MemoryStore()
        original = store.write
        key = onboarding.marker(IDENTITY['uid'])
        def racing_write(identifier, data, generation):
            if identifier == key:
                original(key, {'completed': True, 'preserved': 'metadata'}, generation)
                raise PreconditionFailed('fixture race')
            return original(identifier, data, generation)
        with patch.object(store, 'write', side_effect=racing_write):
            onboarding.mark_completed(app, store, IDENTITY['uid'])
        self.assertEqual(store.read(key)[0], {'completed': True, 'preserved': 'metadata'})

    def test_expired_lease_recovered_and_lost_lease_does_not_release_new_holder(self):
        store = MemoryStore()
        key = 'setup-' + users.account_key(IDENTITY['uid'])
        store.write(key, {'holder': 'expired', 'expires_at': 0}, 0)
        with onboarding.save_lease(app, store, IDENTITY['uid']) as renew:
            lease, generation = store.read(key)
            store.write(key, {'holder': 'replacement', 'expires_at': onboarding.time.time() + 180}, generation)
            with self.assertRaises(app.AppError):
                renew()
        self.assertEqual(store.read(key)[0]['holder'], 'replacement')

    def test_folder_change_after_request_scope_rejects_before_any_drive_write(self):
        import copy
        store = MemoryStore()
        changed = copy.deepcopy(RECORD)
        changed['sections']['Informacion personal'] = 'different-folder'
        store.write(users.account_key(IDENTITY['uid']), changed, 0)
        with patch.object(users, 'assert_drive_identity'), patch.object(onboarding, 'put') as upload:
            with self.assertRaises(app.AppError) as caught:
                self.save(store)
        self.assertEqual(caught.exception.status_code, 409)
        upload.assert_not_called()
        self.assertIsNone(store.read(onboarding.marker(IDENTITY['uid']))[0])

    def test_patch_error_preserves_safe_authorization_code_and_provider_reason(self):
        from types import SimpleNamespace
        for status, body, code, expected in [
            (401, b'{"error":{"message":"PRIVATE"}}', 'google_authorization_expired', 401),
            (403, b'{"error":{"errors":[{"reason":"storageQuotaExceeded"}]}}', 'drive_storage_full', 403),
            (404, b'PRIVATE', 'drive_access_undetermined', 403),
            (503, b'PRIVATE', 'google_request_failed', 502),
        ]:
            with self.subTest(status=status), patch.object(users, 'existing', return_value={'id':'fixture-file'}), patch.object(users.requests, 'patch', return_value=SimpleNamespace(ok=False, status_code=status, content=body)):
                with self.assertRaises(app.AppError) as caught:
                    onboarding.put(app, 'fixture-token', 'folder', 'file', 'text/plain', b'fixture')
                self.assertEqual(caught.exception.status_code, expected)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('PRIVATE', str(caught.exception))

