import unittest
from unittest.mock import patch
import app
import user_accounts as users
import job_runtime
import synchronization_checks
from test_telegram import MemoryStore


class InitialSyncTests(unittest.TestCase):
    def test_informational_document_notes_allow_initial_completion(self):
        store=MemoryStore()
        store.write(users.account_key('alice'),{'uid':'alice','initial_sync_completed':False},0)
        response=self.complete(store,{'uid':'alice'},status={'pending':0,'warnings':[{'code':'bank_document_note','severity':'notice'}]})
        self.assertTrue(response['completed'])
        self.assertTrue(store.read(users.account_key('alice'))[0]['initial_sync_completed'])

    def test_public_status_distinguishes_existing_new_and_incomplete_accounts(self):
        self.assertFalse(users.public(None)['initial_sync_completed'])
        self.assertTrue(users.public({'uid': 'existing'})['initial_sync_completed'])
        self.assertFalse(users.public({'uid': 'new', 'initial_sync_completed': False})['initial_sync_completed'])
        self.assertTrue(users.public({'uid': 'new', 'initial_sync_completed': True})['initial_sync_completed'])

    def complete(self, store, identity=None, verification_error=None, status=None, bank_error=None):
        marker = users.CURRENT.set(identity)
        try:
            with app.app.test_request_context('/api/account/initial-sync', method='POST', headers={'X-Drive-Access-Token':'fixture'}):
                with patch.object(synchronization_checks, 'verify', side_effect=verification_error) as verify, patch.object(app, 'load_drive_bank', return_value=status or {'pending':0,'warnings':[]}, side_effect=bank_error) as load, patch.object(job_runtime, 'JobStore', return_value=store):
                    result = app.app.view_functions['complete_initial_sync']()
                    verify.assert_called_once_with(app, app.app.view_functions['google_grant'])
                    load.assert_called_once_with()
                    return result.get_json()
        finally:
            users.CURRENT.reset(marker)

    def test_saves_only_authenticated_account_and_preserves_record(self):
        store = MemoryStore()
        for uid in ('alice', 'bob'):
            store.write(users.account_key(uid), {'uid':uid, 'archive_id':uid+'-archive', 'initial_sync_completed':False}, 0)
        result = self.complete(store, {'uid':'alice'})
        self.assertTrue(result['completed'])
        self.assertTrue(store.read(users.account_key('alice'))[0]['initial_sync_completed'])
        self.assertEqual(store.read(users.account_key('alice'))[0]['archive_id'], 'alice-archive')
        self.assertFalse(store.read(users.account_key('bob'))[0]['initial_sync_completed'])

    def test_no_marker_on_missing_or_mismatched_account(self):
        for identity, record in [(None,None), ({},None), ({'uid':'alice'},None), ({'uid':'alice'},{'uid':'bob'})]:
            store = MemoryStore()
            if record: store.write(users.account_key('alice'), record, 0)
            with self.assertRaises(app.AppError): self.complete(store, identity)
            self.assertFalse((store.read(users.account_key('alice'))[0] or {}).get('initial_sync_completed',False))

    def test_failed_verification_pending_warnings_or_bank_error_never_save_flag(self):
        cases = [dict(verification_error=app.AppError('Permiso rechazado',403)),
                 dict(status={'pending':1,'warnings':[]}),
                 dict(status={'pending':0,'warnings':['Documento sin leer']}),
                 dict(bank_error=app.AppError('Banco inaccesible',503))]
        for settings in cases:
            with self.subTest(settings=settings):
                store = MemoryStore()
                store.write(users.account_key('alice'), {'uid':'alice','initial_sync_completed':False},0)
                original, generation = store.read(users.account_key('alice'))
                with self.assertRaises(app.AppError): self.complete(store, {'uid':'alice'}, **settings)
                self.assertEqual(store.read(users.account_key('alice')), (original,generation))
