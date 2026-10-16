import unittest
from unittest.mock import patch
import app as core


class AdminConnectionsTests(unittest.TestCase):
    def test_functionality_requires_owner_and_never_probes_services(self):
        client=core.app.test_client()
        with patch.object(core,'verify_google_identity',side_effect=core.AppError('session',401)):
            self.assertEqual(client.get('/api/admin/functionality').status_code,401)
        def other():core.g.google_identity={'uid':'other','email':'other@example.test'}
        with patch.object(core,'ORIGINAL_OWNER_EMAIL','owner@example.test'),patch.object(core,'verify_google_identity',side_effect=other):
            self.assertEqual(client.get('/api/admin/functionality').status_code,403)
        def owner():core.g.google_identity={'uid':'owner','email':'owner@example.test'}
        with patch.object(core,'ORIGINAL_OWNER_EMAIL','owner@example.test'),patch.object(core,'verify_google_identity',side_effect=owner),patch('connection_probes.inspect') as probe,patch.object(core.user_accounts,'scope') as scope:
            response=client.get('/api/admin/functionality')
            self.assertEqual(response.status_code,200)
            self.assertTrue(any(route['path']=='/api/admin/functionality' for route in response.json['routes']))
            self.assertEqual(set(response.json['flags']),{'CV_AUTH_REQUIRED','CV_MULTI_ACCOUNT','CV_EMPLOYMENT_ENABLED'})
            self.assertIn('private',response.headers['Cache-Control']);probe.assert_not_called();scope.assert_not_called()

    def test_background_receipt_needs_capability_but_not_firebase_session(self):
        import connection_probes
        with patch.object(core,'verify_google_identity') as verify,patch('connection_probes.allow_push_receipt',return_value=True),patch('connection_probes.receive_push_proof') as receipt:
            client=core.app.test_client()
            self.assertEqual(client.post('/api/admin/connections/push/receipt',json={'receipt':'fixture','token':'fixture'}).status_code,200)
            verify.assert_not_called();receipt.assert_called_once_with('fixture','fixture')
            receipt.side_effect=connection_probes.ProbeFailure('private-token')
            response=client.post('/api/admin/connections/push/receipt',json={'receipt':'fixture','token':'fixture'})
            self.assertEqual(response.status_code,403);self.assertNotIn('private-token',response.get_data(as_text=True))
            self.assertEqual(client.post('/api/admin/connections/push/receipt',json={}).status_code,400)
        with patch('connection_probes.allow_push_receipt',return_value=False):
            self.assertEqual(core.app.test_client().post('/api/admin/connections/push/receipt',json={'receipt':'fixture','token':'fixture'}).status_code,429)
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
