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
        with patch.object(core, 'ORIGINAL_OWNER_EMAIL', 'owner@example.test'), patch.object(core, 'verify_google_identity', side_effect=identity), patch.object(core.user_accounts, 'scope') as scope, patch('connection_probes.inspect',return_value=[]):
            response=core.app.test_client().get('/api/admin/connections')
            self.assertEqual(response.status_code,200)
            self.assertEqual([x['id'] for x in response.json['checks']],['api','google','gmail'])
            self.assertIn('no-store',response.headers['Cache-Control'])
            scope.assert_not_called()

    def test_missing_owner_configuration_fails_closed(self):
        def identity(): core.g.google_identity={'uid':'owner','email':'owner@example.test'}
        with patch.object(core,'ORIGINAL_OWNER_EMAIL',''),patch.object(core,'verify_google_identity',side_effect=identity):
            self.assertEqual(core.app.test_client().get('/api/admin/connections').status_code,403)

    def test_mutating_checks_require_same_origin_and_never_accept_provider_ack_as_delivery(self):
        def identity():core.g.google_identity={'uid':'owner','email':'owner@example.test'}
        headers={'Origin':'https://cvalamedida.web.app','X-Requested-With':'XmlHttpRequest'}
        with patch.object(core,'ORIGINAL_OWNER_EMAIL','owner@example.test'),patch.object(core,'verify_google_identity',side_effect=identity),patch('connection_probes.send_push_probe',return_value='accepted') as send:
            client=core.app.test_client()
            self.assertEqual(client.post('/api/admin/connections/push/test',json={}).status_code,403)
            self.assertEqual(client.post('/api/admin/connections/push/test',headers=headers).status_code,400)
            self.assertEqual(send.call_count,0)
            result=client.post('/api/admin/connections/push/test',headers=headers,json={'endpoint':'fixture','nonce':'fixture'})
            self.assertEqual(result.json['check']['state'],'unknown')

    def test_gmail_check_returns_no_oauth_token(self):
        def identity():core.g.google_identity={'uid':'owner','email':'owner@example.test'}
        headers={'Origin':'https://cvalamedida.web.app','X-Requested-With':'XmlHttpRequest','X-Drive-Access-Token':'private-fixture'}
        with patch.object(core,'ORIGINAL_OWNER_EMAIL','owner@example.test'),patch.object(core,'verify_google_identity',side_effect=identity),patch('connection_probes.gmail',return_value='scope verified'),patch('connection_probes.drive',return_value='metadata verified'):
            result=core.app.test_client().post('/api/admin/connections/google',headers=headers)
            self.assertEqual(result.json['check']['state'],'ok')
            self.assertNotIn('private-fixture',result.get_data(as_text=True))

    def test_push_confirmation_needs_matching_recent_probe(self):
        def identity():core.g.google_identity={'uid':'owner','email':'owner@example.test'}
        headers={'Origin':'https://cvalamedida.web.app','X-Requested-With':'XmlHttpRequest'}
        import connection_probes
        with patch.object(core,'ORIGINAL_OWNER_EMAIL','owner@example.test'),patch.object(core,'verify_google_identity',side_effect=identity),patch('connection_probes.confirm_push_probe',side_effect=connection_probes.ProbeFailure('safe')):
            self.assertEqual(core.app.test_client().post('/api/admin/connections/push/confirm',headers=headers,json={'nonce':'wrong'}).status_code,409)
