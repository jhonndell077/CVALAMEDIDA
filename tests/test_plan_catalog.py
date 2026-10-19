"""Catalog and subscriber inspection: fake data only, no payment providers."""
import types
import unittest
from unittest.mock import patch
import flask
import admission_policy
import admin_plans
import admin_usage
import plan_catalog
from tests.test_admin_usage import Store


def entries():
    return [dict(id='plus', label='Plus', daily=20, monthly=200, priceMinor=50000,
                 benefits=['Más operaciones mensuales'], published=True),
            dict(id='pro', label='Pro', daily=50, monthly=500, priceMinor=90000,
                 benefits=['Cupos superiores'], published=False)]


class CatalogTests(unittest.TestCase):
    headers = {'Origin':'https://cvalamedida.web.app','X-Requested-With':'XmlHttpRequest','X-Fixture-User':'admin'}
    def setUp(self):
        app = flask.Flask(__name__)
        class AppError(Exception):
            def __init__(self, message, status):
                self.message, self.status_code = message, status
        core = types.SimpleNamespace(app=app, g=flask.g, request=flask.request, jsonify=flask.jsonify,
                                     ORIGINAL_OWNER_EMAIL='admin@example.test', AppError=AppError)
        @app.before_request
        def identity():
            uid = flask.request.headers.get('X-Fixture-User')
            if uid:
                flask.g.google_identity = {'uid':uid,'email': 'admin@example.test' if uid=='admin' else uid+'@example.test'}
        @app.errorhandler(AppError)
        def failure(error):
            return flask.jsonify(error=error.message), error.status_code
        plan_catalog.register_routes(core)
        admin_usage.register_routes(core)
        admin_plans.register_routes(core)
        self.client = app.test_client()
        self.store = Store()
        self.user = types.SimpleNamespace(uid='alice',email='alice@example.test',display_name='Alice',disabled=False)
        for name,obj,method,options in (
            ('storage',plan_catalog.job_runtime,'JobStore',{'return_value':self.store}),
            ('list_users',admin_usage.auth,'list_users',{'return_value':types.SimpleNamespace(users=[self.user],next_page_token=None)}),
            ('get_user',admin_usage.auth,'get_user',{'return_value':self.user})):
            fixture = patch.object(obj,method,**options)
            setattr(self,name,fixture.start())
            self.addCleanup(fixture.stop)

    def save(self, plans=None, generation='0'):
        return self.client.put('/api/admin/plans/catalog',json={'generation':generation,'plans':entries() if plans is None else plans},headers=self.headers)

    def own(self,uid='alice',query=''):
        return self.client.get('/api/subscription'+query,headers={'X-Fixture-User':uid})

    def test_return_to_inherited_basic_has_a_new_change_version(self):
        first = self.own().json
        key = admission_policy.policy_key('alice')
        self.store.write(key, {'daily':20, 'monthly':200}, 0)
        upgraded = self.own().json
        _, version = self.store.read(key)
        self.store.write(key, {'inherit':True}, version)
        restored = self.own().json
        self.assertEqual(first['limits'], restored['limits'])
        self.assertNotEqual(first['changeVersion'], upgraded['changeVersion'])
        self.assertNotEqual(first['changeVersion'], restored['changeVersion'])

    def test_catalog_cas_and_global_basic_derived(self):
        self.store.write(admission_policy.policy_key(),{'daily':4,'monthly':40},0)
        response = self.save()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['catalogGeneration'],'1')
        basic = response.json['planCatalog'][0]
        self.assertEqual((basic['daily'],basic['monthly'],basic['priceMinor']),(4,40,0))
        self.assertEqual(self.save().status_code,409)
        self.assertEqual(self.store.read(plan_catalog.CATALOG_KEY)[1],1)

    def test_catalog_validation_duplicates_bounds_and_basic_immutable(self):
        variants=[]
        for change in ({'label':'x'*61},{'benefits':['x'*161]},{'benefits':['x']*9},{'daily':True},
                       {'monthly':10001},{'priceMinor':0},{'priceMinor':True},{'published':'yes'},{'label':'bad\ntext'}):
            candidate=entries(); candidate[0].update(change); variants.append(candidate)
        candidate=entries(); candidate[0]['id']='basic';variants.append(candidate)
        candidate=entries(); candidate[1]['id']='plus';variants.append(candidate)
        for variant in variants:
            self.assertEqual(self.save(variant).status_code,400)
        self.assertEqual(self.store.writes,[])

    def test_catalog_get_admin_and_subscription_filter_publication(self):
        self.save()
        response=self.client.get('/api/admin/usage',headers=self.headers)
        self.assertEqual(len(response.json['planCatalog']),3)
        subscriber=self.own().json
        self.assertEqual([item['id'] for item in subscriber['planCatalog']],['basic','plus'])
        self.assertIsNone(subscriber['assignmentVersion'])
        self.assertIsNone(subscriber['plan'])
        self.assertEqual(subscriber['payment']['status'],'unverified')

    def test_subscriber_only_own_usage_and_plan(self):
        self.save()
        plan=dict(name='plus',priceMinor=10000,currency='DOP',interval='month',collection='manual',paymentStatus='unverified')
        self.store.write(admission_policy.policy_key('alice'),{'daily':2,'monthly':9,'plan':plan},0)
        self.store.write(admission_policy.policy_key('bob'),{'daily':99,'monthly':999,'plan':{**plan,'priceMinor':99999}},0)
        response=self.own(query='?uid=bob')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['limits'],{'daily':2,'monthly':9})
        self.assertEqual(response.json['plan']['priceMinor'],10000)
        self.assertTrue(response.json['assignmentVersion'])
        prior_version = response.json['assignmentVersion']
        self.store.write(admission_policy.policy_key('alice'), {'daily':3,'monthly':10,'plan':{**plan,'customLimits':True}}, 1)
        self.assertEqual(self.own().json['assignmentVersion'], prior_version)
        self.assertEqual(response.json['benefits'],['Más operaciones mensuales'])
        self.assertNotIn('bob',response.text)
        self.assertIn('private',response.headers['Cache-Control'])

    def test_old_explicit_basic_inherits_changed_global_everywhere(self):
        basic=dict(name='basic',priceMinor=0,currency='DOP',interval='month',collection='manual',paymentStatus='unverified')
        self.store.write(admission_policy.policy_key('alice'),{'daily':999,'monthly':999,'plan':basic},0)
        self.store.write(admission_policy.policy_key(),{'daily':3,'monthly':11},0)
        self.assertEqual(admission_policy.effective_limits(self.store,'alice'),{'daily':3,'monthly':11})
        self.assertEqual(self.own().json['limits'],{'daily':3,'monthly':11})
        self.assertIsNone(self.own().json['assignmentVersion'])
        admin=self.client.get('/api/admin/usage',headers=self.headers).json
        self.assertEqual(admin['accounts'][0]['limits'],{'daily':3,'monthly':11})
        response=self.client.put('/api/admin/usage/limits',json={'scope':'account','uid':'alice','daily':444,'monthly':555,'generation':'1'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(admission_policy.effective_limits(self.store,'alice'),{'daily':3,'monthly':11})

    def test_no_auth_no_storage_and_non_admin_cannot_write(self):
        self.assertEqual(self.client.get('/api/subscription').status_code,401)
        self.storage.assert_not_called()
        self.headers={**self.headers,'X-Fixture-User':'alice'}
        self.assertEqual(self.save().status_code,403)
        self.assertEqual(self.store.writes,[])

    def test_no_billing_or_assignment_when_catalog_edited(self):
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.store.writes,[plan_catalog.CATALOG_KEY])
        self.get_user.assert_not_called()
        self.assertIsNone(self.store.read(admission_policy.policy_key('alice'))[0])

    def test_corrupt_catalog_returns_unknown_not_fabricated_subscription(self):
        self.store.write(plan_catalog.CATALOG_KEY,{'plans':[{'id':'invalid'}]},0)
        self.assertEqual(self.own().status_code,503)


if __name__=='__main__':
    unittest.main()
