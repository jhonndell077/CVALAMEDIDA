import os
import unittest
from unittest.mock import patch
import app
import session_policy as policy


class SessionPolicyTests(unittest.TestCase):
    def test_old_sessions_for_every_account_fail_even_after_token_refresh(self):
        for uid in ('fixture-a', 'fixture-b', 'fixture-admin'):
            identity=dict(uid=uid,email=uid+'@example.test',email_verified=True,
                          auth_time=policy.REAUTHENTICATE_AFTER-1,iat=policy.REAUTHENTICATE_AFTER+600)
            with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1'}),patch('firebase_admin.auth.verify_id_token',return_value=identity), \
                 patch.object(app.user_accounts,'scope') as scope:
                with app.app.test_request_context('/api/account',headers={'Authorization':'Bearer fixture'}):
                    with self.assertRaises(app.AppError) as caught: app.verify_google_identity()
                self.assertEqual(caught.exception.status_code,401)
                self.assertEqual(caught.exception.code,'session_reauthentication_required')
                scope.assert_not_called()

    def test_new_sign_in_is_allowed_for_all_accounts(self):
        for authenticated_at in (policy.REAUTHENTICATE_AFTER,policy.REAUTHENTICATE_AFTER+1):
            identity=dict(uid='fixture',email='fixture@example.test',email_verified=True,auth_time=authenticated_at)
            with patch.dict(os.environ,{'CV_MULTI_ACCOUNT':'1'}),patch('firebase_admin.auth.verify_id_token',return_value=identity):
                with app.app.test_request_context('/api/account',headers={'Authorization':'Bearer fixture'}):
                    app.verify_google_identity()
                    self.assertEqual(app.g.google_identity['uid'],'fixture')

    def test_missing_or_invalid_authentication_time_cannot_bypass_cutoff(self):
        for value in (None,False,'9999999999',float('nan'),float('inf')):
            self.assertTrue(policy.requires_reauthentication({'auth_time':value}))

    def test_public_health_and_error_expose_only_safe_policy_metadata(self):
        with patch.object(app,'ai_provider',return_value='vertex'):
            response=app.app.test_client().get('/api/health')
        self.assertEqual(response.json['reauthenticate_after'],policy.REAUTHENTICATE_AFTER)
        import error_contract
        error=error_contract.details('session_reauthentication_required')
        self.assertEqual(error['externalOutcome'],'not_started')
        self.assertEqual(error['safeNextAction'],'reauthenticate')
        self.assertFalse(error['retryable'])
