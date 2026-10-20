"""Account actions use fake storage and mocked Firebase; no provider side effects."""
import types
import unittest
from unittest.mock import patch
import flask
import admin_user_actions as actions
import admission_policy
import telegram_accounts
from tests.test_admin_usage import Store


class ActionTests(unittest.TestCase):
    headers = {'Origin': 'https://cvalamedida.web.app', 'X-Requested-With': 'XmlHttpRequest', 'X-Fixture-Admin': 'admin'}
    def setUp(self):
        app = flask.Flask(__name__)
        class AppError(Exception):
            def __init__(self, message, status):
                self.message, self.status_code = message, status
        core = types.SimpleNamespace(app=app, g=flask.g, request=flask.request, jsonify=flask.jsonify,
                                     ORIGINAL_OWNER_EMAIL='admin@example.test', AppError=AppError)
        @app.before_request
        def identity():
            if flask.request.headers.get('X-Fixture-Admin'):
                flask.g.google_identity = {'uid': flask.request.headers['X-Fixture-Admin'], 'email': 'admin@example.test'}
        @app.errorhandler(AppError)
        def failure(error):
            return flask.jsonify(error=error.message), error.status_code
        actions.register_routes(core)
        self.client = app.test_client()
        self.store = Store()
        self.user = types.SimpleNamespace(uid='alice', email='alice@example.test')
        for name, obj, method, options in (
            ('storage', actions.job_runtime, 'JobStore', {'return_value': self.store}),
            ('get_user', actions.auth, 'get_user', {'return_value': self.user}),
            ('revoke', actions.auth, 'revoke_refresh_tokens', {}),
            ('delete', actions.auth, 'delete_user', {})):
            fixture = patch.object(obj, method, **options)
            setattr(self, name, fixture.start())
            self.addCleanup(fixture.stop)

    def preview(self, action='reset'):
        return self.client.post('/api/admin/users/action/preview', json={'uid':'alice','action': action}, headers=self.headers)

    def execute(self, plan, **changes):
        body = {key:plan[key] for key in ('uid','action','planId')}
        body['confirmation'] = 'alice'
        body.update(changes)
        return self.client.post('/api/admin/users/action/execute', json=body, headers=self.headers)

    def test_preview_changes_only_plan_no_auth_or_queue_mutation(self):
        result = self.preview()
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json['blocked'])
        self.assertTrue(self.store.writes[0].startswith('admin-user-action-'))
        self.delete.assert_not_called()
        self.revoke.assert_not_called()

    def test_reset_preserves_pending_receipts_and_other_queue_metadata(self):
        key = admission_policy.queue_key('alice')
        self.store.write(key, {'pending': [{'id':'job'}], 'usage': {'daily':10,'monthly':40,'receipts':{'receipt':123}}, 'other':True}, 0)
        self.store.write('job', {'state':'processing'}, 0)
        plan = self.preview().json
        self.assertEqual(self.execute(plan).status_code, 200)
        queue = self.store.read(key)[0]
        self.assertEqual(queue['usage']['daily'], 0)
        self.assertEqual(queue['usage']['monthly'], 0)
        self.assertEqual(queue['usage']['receipts'], {'receipt':123})
        self.assertEqual(queue['pending'], [{'id':'job'}])
        self.assertTrue(queue['other'])
        self.assertEqual(self.execute(plan).status_code, 409)

    def test_wrong_confirmation_tampering_and_admin_binding_rejected(self):
        plan = self.preview().json
        self.assertEqual(self.execute(plan, confirmation='wrong').status_code, 400)
        self.assertEqual(self.execute(plan, planId=plan['planId'][:-1]+('0' if plan['planId'][-1]!='0' else '1')).status_code, 403)
        self.headers = {**self.headers, 'X-Fixture-Admin':'another-admin'}
        self.assertEqual(self.execute(plan).status_code, 403)

    def test_expiration_and_generation_change_require_new_preview(self):
        plan = self.preview().json
        with patch.object(actions.time,'time',return_value=plan['expiresAt']+1):
            self.assertEqual(self.execute(plan).status_code, 409)
        self.store.write(admission_policy.queue_key('alice'), {'pending':[]}, 0)
        self.assertEqual(self.execute(plan).status_code, 409)

    def test_auth_deletion_is_explicitly_separate_from_data_deletion(self):
        plan = self.preview('delete_user').json
        self.assertFalse(plan['blocked'])
        self.assertIn('exclusivamente', plan['summary']['scope'])
        response = self.execute(plan)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['dataDeleted'])
        self.revoke.assert_called_once_with('alice')
        self.delete.assert_called_once_with('alice')
        self.assertTrue(self.store.read(telegram_accounts.key('account','alice'))[0]['revoked'])
        self.assertTrue(self.store.read(telegram_accounts.key('oauth','alice'))[0]['revoked'])
        self.assertEqual(self.store.read(admission_policy.queue_key('alice'))[0]['maintenance']['action'], 'delete_user')

    def test_admin_account_cannot_be_deleted(self):
        self.user.email = 'admin@example.test'
        plan = self.preview('delete_user').json
        self.assertTrue(plan['blocked'])
        self.assertEqual(self.execute(plan).status_code,409)
        self.delete.assert_not_called()

    def test_active_job_blocks_auth_deletion_but_not_quota_reset(self):
        self.store.write(admission_policy.queue_key('alice'), {'pending':[{'id':'active'}]}, 0)
        self.store.write('active', {'state':'processing'}, 0)
        self.assertTrue(self.preview('delete_user').json['blocked'])
        self.assertFalse(self.preview('reset').json['blocked'])
        self.delete.assert_not_called()

    def test_data_delete_blocked_without_ownership_inventory(self):
        plan = self.preview('delete_data').json
        self.assertTrue(plan['blocked'])
        self.assertEqual(self.execute(plan).status_code,409)
        self.delete.assert_not_called()

    def test_auth_failure_is_partial_and_does_not_report_success(self):
        plan = self.preview('delete_user').json
        self.delete.side_effect = RuntimeError('private-token-provider')
        response = self.execute(plan)
        self.assertEqual(response.status_code,503)
        self.assertIn('parciales',response.json['error'])
        self.assertNotIn('private-token-provider',response.text)
        self.assertEqual(self.execute(plan).status_code,409)

    def failed_before_delete(self):
        plan = self.preview('delete_user').json
        self.revoke.side_effect = RuntimeError('fixture-provider-error')
        response = self.execute(plan)
        self.revoke.side_effect = None
        self.assertEqual(response.status_code, 503)
        return plan

    def test_failed_deletion_is_tracked_and_recovery_preserves_data_and_consumption(self):
        key = admission_policy.queue_key('alice')
        usage = {'daily': 2, 'monthly': 7, 'receipts': {'kept': 123}}
        self.store.write(key, {'pending': [], 'usage': usage, 'other': True}, 0)
        plan = self.failed_before_delete()
        queue = self.store.read(key)[0]
        self.assertEqual(queue['maintenance']['state'], 'failed')
        self.assertEqual(queue['maintenance']['planId'], plan['planId'].split('.')[0])
        original, _ = self.store.read(actions._key(queue['maintenance']['planId']))
        self.assertEqual(original['state'], 'failed')
        self.assertFalse(original['deleteAttempted'])
        recover = self.preview('recover_access').json
        self.assertFalse(recover['blocked'])
        self.assertEqual(self.execute(recover).status_code, 200)
        after = self.store.read(key)[0]
        self.assertNotIn('maintenance', after)
        self.assertEqual(after['usage'], usage)
        self.assertEqual(after['pending'], [])
        self.assertTrue(after['other'])
        self.delete.assert_not_called()
        self.assertTrue(self.store.read(telegram_accounts.key('oauth','alice'))[0]['revoked'])
        self.assertEqual(self.execute(recover).status_code, 200)
        self.assertTrue(actions.job_runtime.JobStore.admit(self.store, 'sync-after-recovery', 'alice', charge=False))

    def test_legacy_executing_completed_and_unknown_fences_are_not_auto_removed(self):
        key = admission_policy.queue_key('alice')
        for fence in ({'action':'delete_user','at':1}, {'action':'delete_user','state':'executing'},
                      {'action':'delete_user','state':'completed'}, {'action':'unknown','state':'failed'}):
            _, version = self.store.read(key)
            self.store.write(key, {'pending':[], 'maintenance':fence}, version)
            plan = self.preview('recover_access').json
            self.assertTrue(plan['blocked'])
            self.assertEqual(self.execute(plan).status_code, 409)
            self.assertEqual(self.store.read(key)[0]['maintenance'], fence)

    def test_unknown_external_delete_result_is_not_reported_as_recoverable(self):
        plan = self.preview('delete_user').json
        self.delete.side_effect = RuntimeError('fixture-lost-delete-confirmation')
        self.assertEqual(self.execute(plan).status_code, 503)
        recovery = self.preview('recover_access').json
        self.assertTrue(recovery['blocked'])
        self.assertIn('resultado externo', ' '.join(recovery['reasons']))

    def test_disabled_missing_or_busy_account_cannot_be_recovered(self):
        self.failed_before_delete()
        self.user.disabled = True
        self.assertTrue(self.preview('recover_access').json['blocked'])
        self.user.disabled = False
        key = admission_policy.queue_key('alice')
        queue, version = self.store.read(key)
        self.store.write(key, {**queue, 'pending':[{'id':'active'}]}, version)
        self.assertTrue(self.preview('recover_access').json['blocked'])
        self.get_user.side_effect = actions.auth.UserNotFoundError('fixture-missing')
        self.assertEqual(self.preview('recover_access').status_code, 404)

    def test_recovery_revalidates_queue_and_original_plan_after_preview(self):
        self.failed_before_delete()
        plan = self.preview('recover_access').json
        key = admission_policy.queue_key('alice')
        queue, version = self.store.read(key)
        self.store.write(key, {**queue, 'changed': True}, version)
        self.assertEqual(self.execute(plan).status_code, 409)
        plan = self.preview('recover_access').json
        original_key = actions._key(queue['maintenance']['planId'])
        original, version = self.store.read(original_key)
        self.store.write(original_key, {**original,'state':'executing'}, version)
        self.assertEqual(self.execute(plan).status_code, 409)
        self.assertIn('maintenance', self.store.read(key)[0])

    def test_recovery_of_one_account_does_not_change_another_account(self):
        self.failed_before_delete()
        key = admission_policy.queue_key('bob')
        other = {'maintenance':{'action':'delete_user'},'usage':{'daily':5},'pending':[]}
        self.store.write(key, other, 0)
        self.assertEqual(self.execute(self.preview('recover_access').json).status_code, 200)
        self.assertEqual(self.store.read(key)[0], other)

    def test_seventy_independent_accounts_recover_failed_actions_without_resetting_consumption(self):
        self.get_user.side_effect = lambda uid: types.SimpleNamespace(uid=uid, email=uid+'@example.test', disabled=False)
        for index in range(70):
            uid = 'fixture-' + str(index)
            key = admission_policy.queue_key(uid)
            usage = {'daily':index % 3, 'monthly':index, 'receipts':{'kept':index}}
            self.store.write(key, {'pending':[], 'usage':usage}, 0)
            self.revoke.side_effect = RuntimeError('fixture-only')
            deletion = self.client.post('/api/admin/users/action/preview', json={'uid':uid,'action':'delete_user'}, headers=self.headers).json
            self.assertEqual(self.execute(deletion, confirmation=uid).status_code, 503)
            self.revoke.side_effect = None
            recovery = self.client.post('/api/admin/users/action/preview', json={'uid':uid,'action':'recover_access'}, headers=self.headers).json
            self.assertFalse(recovery['blocked'])
            self.assertEqual(self.execute(recovery, confirmation=uid).status_code, 200)
            self.assertEqual(self.store.read(key)[0]['usage'], usage)
            self.assertTrue(actions.job_runtime.JobStore.admit(self.store, 'sync-'+uid, uid, charge=False))
        self.delete.assert_not_called()

    def test_unauthorized_and_cross_origin_never_act(self):
        self.assertEqual(self.client.post('/api/admin/users/action/preview',json={'uid':'alice','action':'reset'}).status_code,403)
        self.headers = {**self.headers,'Origin':'https://attacker.example'}
        self.assertEqual(self.preview().status_code,403)
        self.get_user.assert_not_called()
        self.assertEqual(self.store.writes,[])


if __name__ == '__main__':
    unittest.main()
