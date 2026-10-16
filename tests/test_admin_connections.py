import unittest
from unittest.mock import patch
import app as core


class AdminConnectionsTests(unittest.TestCase):
    def test_missing_identity_is_denied_before_storage(self):
        with patch.object(core, 'ORIGINAL_OWNER_EMAIL', 'owner@example.test'), patch.object(core, 'verify_google_identity', side_effect=core.AppError('session',401)), patch.object(core.user_accounts, 'scope') as scope:
            response = core.app.test_client().get('/api/admin/connections')
            self.assertEqual(response.status_code, 401)
            scope.assert_not_called()

    def test_other_user_is_denied_before_account_scope(self):
        def identity(): core.g.google_identity={'uid':'other','email':'other@example.test'}
        with patch.object(core, 'ORIGINAL_OWNER_EMAIL', 'owner@example.test'), patch.object(core, 'verify_google_identity', side_effect=identity), patch.object(core.user_accounts, 'scope') as scope:
            response=core.app.test_client().get('/api/admin/connections')
            self.assertEqual(response.status_code,403)
            scope.assert_not_called()

    def test_owner_can_read_without_drive_and_no_external_health_claim(self):
        def identity(): core.g.google_identity={'uid':'owner','email':'OWNER@example.test'}
        with patch.object(core, 'ORIGINAL_OWNER_EMAIL', 'owner@example.test'), patch.object(core, 'verify_google_identity', side_effect=identity), patch.object(core.user_accounts, 'scope') as scope:
            response=core.app.test_client().get('/api/admin/connections')
            self.assertEqual(response.status_code,200)
            self.assertEqual([x['id'] for x in response.json['checks']],['api'])
            self.assertIn('no-store',response.headers['Cache-Control'])
            scope.assert_not_called()

    def test_missing_owner_configuration_fails_closed(self):
        def identity(): core.g.google_identity={'uid':'owner','email':'owner@example.test'}
        with patch.object(core,'ORIGINAL_OWNER_EMAIL',''),patch.object(core,'verify_google_identity',side_effect=identity):
            self.assertEqual(core.app.test_client().get('/api/admin/connections').status_code,403)
