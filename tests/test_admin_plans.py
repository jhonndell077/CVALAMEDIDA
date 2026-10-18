"""Manual plan assignment uses one CAS document and never calls billing services."""
import types
import unittest
from unittest.mock import patch
import flask
import admin_plans
import admin_usage
import admission_policy
from tests.test_admin_usage import Store


class AdminPlanTests(unittest.TestCase):
    headers = {'Origin':'https://cvalamedida.web.app','X-Requested-With':'XmlHttpRequest','X-Fixture-Admin':'yes'}
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
                flask.g.google_identity = {'uid':'admin','email':'admin@example.test'}
        @app.errorhandler(AppError)
        def failure(error):
            return flask.jsonify(error=error.message), error.status_code
        admin_plans.register_routes(core)
        admin_usage.register_routes(core)
        self.client = app.test_client()
        self.store = Store()
        self.user = types.SimpleNamespace(uid='alice',email='alice@example.test',display_name='Alice',disabled=False)
        for name, obj, method, options in (
            ('storage', admin_plans.job_runtime, 'JobStore', {'return_value':self.store}),
            ('get_user', admin_plans.auth, 'get_user', {'return_value':self.user}),
            ('list_users', admin_plans.auth, 'list_users', {'return_value':types.SimpleNamespace(users=[self.user],next_page_token=None)})):
            fixture = patch.object(obj,method,**options)
            setattr(self,name,fixture.start())
            self.addCleanup(fixture.stop)

    def assign(self, **changes):
        data = dict(uid='alice',name='plus',priceMinor=10000,currency='DOP',daily=20,monthly=200,generation='0')
        data.update(changes)
        return self.client.put('/api/admin/users/plan',json=data,headers=self.headers)

    def usage(self):
        return self.client.get('/api/admin/usage',headers=self.headers)

    def test_plan_assignment_is_atomic_with_effective_limits(self):
        response = self.assign()
        self.assertEqual(response.status_code,200)
        document, generation = self.store.read(admission_policy.policy_key('alice'))
        self.assertEqual(generation,1)
        self.assertEqual(document['plan']['collection'],'manual')
        self.assertEqual(document['plan']['paymentStatus'],'unverified')
        self.assertEqual(admission_policy.effective_limits(self.store,'alice'),{'daily':20,'monthly':200})
        self.assertEqual(self.store.writes,[admission_policy.policy_key('alice')])
        account = self.usage().json['accounts'][0]
        self.assertEqual(account['plan']['priceMinor'],10000)
        self.assertEqual(account['overrideGeneration'],'1')

    def test_no_default_assignment_and_paid_prices_not_invented(self):
        payload = self.usage().json
        self.assertIsNone(payload['accounts'][0]['plan'])
        catalog = {item['id']:item for item in payload['planCatalog']}
        self.assertEqual(catalog['basic']['priceMinor'],0)
        self.assertIsNone(catalog['plus']['priceMinor'])
        self.assertIsNone(catalog['pro']['priceMinor'])
        self.assertEqual(self.store.writes,[])

    def test_quota_edit_preserves_plan_and_marks_custom_limits(self):
        self.assign()
        response = self.client.put('/api/admin/usage/limits',json={'scope':'account','uid':'alice','daily':25,'monthly':250,'generation':'1'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        plan = self.usage().json['accounts'][0]['plan']
        self.assertEqual(plan['name'],'plus')
        self.assertEqual(plan['priceMinor'],10000)
        self.assertTrue(plan['customLimits'])

    def test_inherit_clears_assignment_with_limits(self):
        self.assign()
        response = self.client.put('/api/admin/usage/limits',json={'scope':'account','uid':'alice','inherit':True,'generation':'1'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(self.usage().json['accounts'][0]['plan'])
        self.assertEqual(self.store.read(admission_policy.policy_key('alice'))[0],{'inherit':True})

    def test_plan_and_limit_edits_share_conflict_generation(self):
        self.assign()
        self.assertEqual(self.assign(name='pro',daily=50,monthly=500).status_code,409)
        response = self.client.put('/api/admin/usage/limits',json={'scope':'account','uid':'alice','daily':1,'monthly':2,'generation':'0'},headers=self.headers)
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.usage().json['accounts'][0]['plan']['name'],'plus')

    def test_strict_configuration_does_not_enable_payment(self):
        for changes in ({'priceMinor':True},{'priceMinor':-1},{'priceMinor':100000001},{'priceMinor':1.1},
                        {'currency':'EUR'},{'currency':'USD'},{'name':'unknown'},{'daily':True},{'monthly':-1},
                        {'generation':0},{'name':'basic','priceMinor':100},{'priceMinor':0},{'paymentStatus':'paid'}):
            self.assertEqual(self.assign(**changes).status_code,400)
        self.assertEqual(self.store.writes,[])

    def test_paid_zero_rejected_and_basic_zero_uses_global_limits(self):
        for name in ('plus', 'pro', 'custom'):
            self.assertEqual(self.assign(name=name, priceMinor=0).status_code, 400)
        self.store.write(admission_policy.policy_key(), {'daily': 7, 'monthly': 33}, 0)
        response = self.assign(name='basic', priceMinor=0, daily=999, monthly=999)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['limits'], {'daily': 7, 'monthly': 33})
        self.assertNotIn('customLimits', response.json['plan'])

    def test_owner_and_origin_guards(self):
        self.headers = {**self.headers,'Origin':'https://attacker.example'}
        self.assertEqual(self.assign().status_code,403)
        self.headers = {}
        self.assertEqual(self.assign().status_code,403)
        self.get_user.assert_not_called()
        self.assertEqual(self.store.writes,[])

    def test_unknown_user_or_storage_error_never_claims_assigned(self):
        self.get_user.side_effect = admin_plans.auth.UserNotFoundError('fixture')
        self.assertEqual(self.assign().status_code,404)
        self.get_user.side_effect = None
        with patch.object(self.store,'write',side_effect=RuntimeError('private-provider-text')):
            response = self.assign()
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private-provider-text',response.text)
        self.assertEqual(self.store.writes,[])

    def test_corrupt_payment_metadata_fails_closed(self):
        self.assign()
        document, generation = self.store.read(admission_policy.policy_key('alice'))
        document['plan']['collection']='automatic'
        self.store.write(admission_policy.policy_key('alice'),document,generation)
        with self.assertRaises(ValueError):
            admission_policy.effective_limits(self.store,'alice')
        self.assertEqual(self.usage().status_code,503)

    def test_customized_plan_limits_are_marked_and_price_cents_retained(self):
        response = self.assign(daily=22, priceMinor=29)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['plan']['customLimits'])
        self.assertEqual(response.json['plan']['priceMinor'], 29)


if __name__ == '__main__':
    unittest.main()
