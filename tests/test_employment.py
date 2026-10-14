"""Controlled fixtures only. No Firebase credentials, requests or applications."""
import copy
import json
import math
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, g

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import employment_geo as geo
from employment_service import Employment, register_routes, key


POINT = {'country': 'DO', 'region': 'Santo Domingo', 'city': 'Santo Domingo Este',
         'reference': '', 'lat': 18.4885, 'lng': -69.8571, 'accuracy_m': 30,
         'radius_m': 10000, 'allowed_countries': ['DO'], 'allow_remote': False,
         'allow_travel': False}
NEAR = {'title': 'VACANTE FICTICIA DE PRUEBA', 'company': 'Empresa simulada',
        'description': 'Formulario controlado sin envío.', 'source': 'fixture',
        'url': 'https://example.invalid/jobs/near', 'mode': 'onsite',
        'suspicious': False, 'requires_travel': False, 'required_skills': ['Python'],
        'location': {'lat':18.489, 'lng':-69.856, 'country':'DO', 'accuracy_m':50, 'verified':True}}
FAR = {**NEAR, 'url': 'https://example.invalid/jobs/punta-cana',
       'location': {'lat':18.5601, 'lng':-68.3725, 'country':'DO', 'accuracy_m':100, 'verified':True}}


class MemoryStore:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()

    def read(self, identifier):
        with self.lock:
            data, generation = self.items.get(identifier, (None, 0))
            return copy.deepcopy(data), generation

    def write(self, identifier, data, generation):
        with self.lock:
            if self.items.get(identifier, (None, 0))[1] != generation:
                raise RuntimeError('CAS conflict')
            self.items[identifier] = copy.deepcopy(data), generation + 1


class Provider:
    def search(self, query, point):
        return [{**item,'source_country':'DO'} for item in [NEAR, {**NEAR, 'url':NEAR['url']+'?utm_source=test'}, FAR]]


class GeographyTests(unittest.TestCase):
    def setUp(self):
        self.point = geo.location(POINT)

    def test_gps_without_address_can_be_saved(self):
        point = geo.location({**POINT, 'country': '', 'city': '', 'region': '',
                              'allowed_countries': []})
        self.assertEqual(point['radius_m'], 10000)
        self.assertEqual(point['lat'], POINT['lat'])
        self.assertEqual(point['country'], '')
        self.assertFalse(geo.evaluate(point, NEAR)['eligible'])
        remote = {**NEAR, 'mode': 'remote', 'remote_countries': [], 'remote_worldwide': True}
        self.assertFalse(geo.evaluate({**point, 'allow_remote': True}, remote)['eligible'])

    def test_santo_domingo_este_excludes_punta_cana(self):
        result = geo.evaluate(self.point, FAR)
        self.assertEqual(result['reason'], 'fuera_del_radio')
        self.assertGreater(result['distance_m'], 150000)

    def test_nearby_is_eligible(self):
        self.assertTrue(geo.evaluate(self.point, NEAR)['eligible'])

    def test_coordinate_precision_minimized(self):
        point = geo.location({**POINT, 'lat':18.488512345678})
        self.assertEqual(point['lat'],18.4885)
        self.assertEqual(point['accuracy_m'],46)

    def test_invalid_numbers_and_ranges(self):
        for field, value in [('lat',True),('lat',math.nan),('lat',91),('lng',181),
                             ('radius_m',499),('radius_m',100001),('accuracy_m',-1),('lng','2')]:
            with self.subTest(field=field,value=value), self.assertRaises(geo.PolicyError):
                geo.location({**POINT,field:value})

    def test_radius_limits(self):
        for radius in (500,1000,5000,10000,25000,50000,100000):
            self.assertEqual(geo.location({**POINT,'radius_m':radius})['radius_m'],radius)

    def test_unknown_owner_field_rejected(self):
        with self.assertRaises(geo.PolicyError):
            geo.location({**POINT,'uid':'other'})

    def test_country_outside_scope(self):
        offer = copy.deepcopy(NEAR); offer['location']['country'] = 'US'
        self.assertEqual(geo.evaluate(self.point,offer)['reason'],'pais_no_autorizado')

    def test_unknown_location_classified(self):
        self.assertEqual(geo.evaluate(self.point,{**NEAR,'location':None})['reason'],'ubicacion_no_verificable')

    def test_boundary_uncertainty_blocks(self):
        point = {**self.point,'accuracy_m':10000}
        self.assertEqual(geo.evaluate(point,NEAR)['reason'],'limite_geografico_ambiguo')

    def test_remote_requires_verified_country_and_consent(self):
        offer = {**NEAR,'mode':'remote','location':None,'remote_countries':['DO']}
        self.assertFalse(geo.evaluate(self.point,offer)['eligible'])
        self.assertTrue(geo.evaluate({**self.point,'allow_remote':True},offer)['eligible'])
        self.assertFalse(geo.evaluate({**self.point,'allow_remote':True},{**offer,'remote_countries':['US']})['eligible'])

    def test_unaccepted_travel_blocked(self):
        self.assertEqual(geo.evaluate(self.point,{**NEAR,'requires_travel':True})['reason'],'desplazamiento_no_autorizado')

    def test_unknown_travel_blocked(self):
        self.assertEqual(geo.evaluate(self.point,{**NEAR,'requires_travel':None})['reason'],'desplazamiento_desconocido')

    def test_expired_and_suspicious(self):
        for offer in ({**NEAR,'expires_at':'2020-01-01T00:00:00Z'}, {**NEAR,'suspicious':True}):
            self.assertFalse(geo.evaluate(self.point,offer)['eligible'])

    def test_haversine_dateline(self):
        self.assertLess(geo.distance_m({'lat':0,'lng':179.99},{'lat':0,'lng':-179.99}),2300)

    def test_compatibility_explains_only_evidence(self):
        result = geo.compatibility({'skills':[{'name':'Python'}]}, {**NEAR,'required_skills':['Python','SQL']})
        self.assertEqual(result['score'],50); self.assertEqual(result['missing'],['sql'])
        self.assertIsNone(geo.compatibility({}, {**NEAR,'required_skills':[]})['score'])

    def test_actual_profile_skill_label_is_supported(self):
        self.assertEqual(geo.compatibility({'skills':[{'id':'python','label':'Python'}]},NEAR)['score'],100)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.service = Employment(lambda:self.store,Provider())
        self.service.save_location('alice',POINT)

    def search(self):
        return self.service.search('alice','Python',{'skills':[{'name':'Python'}]})

    def pending(self):
        return self.service.prepare('alice',self.search()['offers'][0]['id'])

    def test_search_deduplicates_and_excludes(self):
        result = self.search()
        self.assertEqual(len(result['offers']),1); self.assertEqual(len(result['excluded']),1)

    def test_isolation_and_hashed_keys(self):
        self.assertIsNone(self.service.read('bob')[0]['location'])
        item = self.pending()
        with self.assertRaises(geo.PolicyError):
            self.service.approve_simulation('bob',item['id'],True)
        self.assertNotIn('alice',key('alice'))

    def test_client_cannot_supply_vacancy_coordinates(self):
        with self.assertRaises(geo.PolicyError): self.service.prepare('alice','fake-offer')

    def test_preparation_is_idempotent(self):
        result = self.search(); offer_id = result['offers'][0]['id']
        self.assertEqual(self.service.prepare('alice',offer_id),self.service.prepare('alice',offer_id))

    def test_no_submission_without_confirmation(self):
        item = self.pending()
        for consent in (False,None,1,'true'):
            with self.assertRaises(geo.PolicyError): self.service.approve_simulation('alice',item['id'],consent)

    def test_simulation_never_claims_sent(self):
        item = self.pending(); result = self.service.approve_simulation('alice',item['id'],True)
        self.assertEqual(result['status'],'PREPARADA'); self.assertTrue(result['simulation'])

    def test_changed_radius_blocks_previous_approval(self):
        item = self.pending(); self.service.save_location('alice',{**POINT,'radius_m':500})
        with self.assertRaises(geo.PolicyError): self.service.approve_simulation('alice',item['id'],True)

    def test_delete_revokes_and_erases_location_metadata(self):
        self.pending(); self.service.delete_location('alice')
        state, _ = self.service.read('alice')
        self.assertIsNone(state['location']); self.assertFalse(state['offers'])
        self.assertEqual(next(iter(state['applications'].values()))['status'],'CANCELADA')

    def test_cancel_blocks_approval(self):
        item = self.pending(); self.service.cancel('alice',item['id'])
        with self.assertRaises(geo.PolicyError): self.service.approve_simulation('alice',item['id'],True)

    def test_no_provider_no_invented_vacancies(self):
        self.service.provider = None
        with self.assertRaises(geo.PolicyError): self.search()

    def test_network_failure_does_not_create_applications(self):
        self.service.provider = SimpleNamespace(search=lambda *args: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaises(TimeoutError): self.search()
        self.assertFalse(self.service.read('alice')[0]['applications'])

    def test_cas_prevents_lost_updates(self):
        state, generation = self.store.read(key('alice'))
        self.service.save_location('alice',{**POINT,'city':'Cambio'})
        with self.assertRaises(RuntimeError): self.store.write(key('alice'),state,generation)

    def test_backend_rechecks_changed_offer(self):
        item = self.pending()
        state,generation = self.service.read('alice')
        state['offers'][item['offer_id']]['location'] = FAR['location']
        self.store.write(key('alice'),state,generation)
        with self.assertRaises(geo.PolicyError): self.service.approve_simulation('alice',item['id'],True)

    def test_search_has_no_daily_quota_even_with_previous_exhausted_counter(self):
        state,generation=self.service.read('alice')
        state.update(search_date=datetime.now(timezone.utc).date().isoformat(),search_count=1000)
        self.store.write(key('alice'),state,generation)
        for _ in range(35): self.search()
        self.assertEqual(self.service.read('alice')[0]['search_count'],1000)

    def test_reprepare_after_location_change(self):
        item=self.pending()
        self.service.save_location('alice',POINT)
        next_item=self.service.prepare('alice',item['offer_id'])
        self.assertNotEqual(item['id'],next_item['id'])


class RouteTests(unittest.TestCase):
    def test_rd_search_and_latest_work_without_confirmed_location(self):
        headers={'X-Test-User':'alice'}
        for payload in ({'query':'Cajero'},{'query':'','latest':True}):
            response=self.client.post('/api/employment/search',json=payload,headers=headers)
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(response.json['national'])
            self.assertEqual(len(response.json['offers']),2)
        self.assertIsNone(self.service.read('alice')[0]['location'])

    def test_public_search_rejects_international_sources_and_requires_session(self):
        self.assertEqual(self.client.post('/api/employment/search',json={'query':'Chef'}).status_code,401)
        for source in ('nearby','remote','unknown'):
            response=self.client.post('/api/employment/search',json={'query':'Chef','source':source},headers={'X-Test-User':'alice'})
            self.assertEqual(response.status_code,400)

    def setUp(self):
        self.flask = Flask(__name__)
        class AppError(Exception):
            def __init__(self,message,status_code=400): self.status_code=status_code; super().__init__(message)
        core = SimpleNamespace(app=self.flask,request=request,jsonify=jsonify,AppError=AppError,
                               account_state=SimpleNamespace(MASTER_PROFILE={'skills':[]}))
        @self.flask.errorhandler(AppError)
        def error_handler(error): return jsonify(error=str(error)),error.status_code
        @self.flask.before_request
        def fixture_identity():
            # Test-only fixture; this header is NEVER read by production code.
            if request.headers.get('X-Test-User'): g.google_identity={'uid':request.headers['X-Test-User']}
        self.store = MemoryStore(); self.service = Employment(lambda:self.store,Provider())
        register_routes(core,self.service)
        self.client = self.flask.test_client()
        self.environment = patch.dict(os.environ,{'CV_EMPLOYMENT_ENABLED':'1'})
        self.environment.start(); self.addCleanup(self.environment.stop)

    def test_requires_identity_even_if_global_auth_disabled(self):
        self.assertEqual(self.client.get('/api/employment/location').status_code,401)

    def test_default_feature_disabled(self):
        with patch.dict(os.environ,{'CV_EMPLOYMENT_ENABLED':'0'}):
            self.assertEqual(self.client.get('/api/employment/location',headers={'X-Test-User':'alice'}).status_code,503)

    def test_save_update_read_delete_and_isolation(self):
        headers = {'X-Test-User':'alice'}
        self.assertEqual(self.client.put('/api/employment/location',json=POINT,headers=headers).status_code,200)
        self.assertIsNone(self.client.get('/api/employment/location',headers={'X-Test-User':'bob'}).json['location'])
        response = self.client.put('/api/employment/location',json={**POINT,'city':'Otra ciudad','country':'US','allowed_countries':['US']},headers=headers)
        self.assertEqual(response.json['location']['country'],'US')
        self.assertEqual(self.client.delete('/api/employment/location',headers=headers).status_code,200)

    def test_unconfigured_geocoder_is_honest(self):
        response = self.client.post('/api/employment/geocode',json={'country':'DO','address':'Referencia ficticia'},headers={'X-Test-User':'alice'})
        self.assertEqual(response.status_code,400)
        self.assertIn('pendiente',response.json['error'])

    def test_schema_and_owner_injection_rejected(self):
        response = self.client.put('/api/employment/location',json={**POINT,'uid':'bob'},headers={'X-Test-User':'alice'})
        self.assertEqual(response.status_code,400)

    def test_store_failure_does_not_leak_exception(self):
        with patch.object(self.store,'read',side_effect=RuntimeError('PRIVATE SECRET VALUE')):
            response = self.client.get('/api/employment/location',headers={'X-Test-User':'alice'})
        self.assertEqual(response.status_code,503); self.assertNotIn('PRIVATE',response.json['error'])

    def test_complete_supervised_routes_with_fixture(self):
        headers={'X-Test-User':'alice'}
        self.client.put('/api/employment/location',json=POINT,headers=headers)
        found=self.client.post('/api/employment/search',json={'query':'Python'},headers=headers)
        self.assertEqual(found.status_code,200)
        prepared=self.client.post('/api/employment/applications',json={'offer_id':found.json['offers'][0]['id']},headers=headers)
        self.assertEqual(prepared.status_code,200); identifier=prepared.json['id']
        denied=self.client.post(f'/api/employment/applications/{identifier}/simulate',json={'confirmed':False},headers=headers)
        self.assertEqual(denied.status_code,400)
        approved=self.client.post(f'/api/employment/applications/{identifier}/simulate',json={'confirmed':True},headers=headers)
        self.assertEqual(approved.json['status'],'PREPARADA')
        history=self.client.get('/api/employment/applications',headers=headers)
        self.assertEqual(len(history.json['applications']),1)
        cancelled=self.client.post(f'/api/employment/applications/{identifier}/cancel',json={},headers=headers)
        self.assertEqual(cancelled.json['status'],'CANCELADA')

    def test_reverse_geocode_authenticated_cached_and_keeps_gps(self):
        calls = []
        def reverse(lat, lng):
            calls.append((lat, lng))
            return [{'country': 'DO', 'city': 'Fixture', 'lat': 18.5, 'lng': -69.8}]
        self.service.geocoder = SimpleNamespace(reverse=reverse)
        path = '/api/employment/reverse-geocode'
        payload = {'lat': 18.488512, 'lng': -69.857123}
        self.assertEqual(self.client.post(path, json=payload).status_code, 401)
        headers = {'X-Test-User': 'alice'}
        for _ in range(2):
            response = self.client.post(path, json=payload, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['results'][0]['country'], 'DO')
        self.assertEqual(calls, [(18.4885, -69.8571)])
        self.assertIsNone(self.service.read('alice')[0]['location'])
        for bad in ({'lat': 91, 'lng': 0}, {'lat': True, 'lng': 0},
                    {'lat': 0, 'lng': 0, 'url': 'https://example.invalid'}):
            self.assertEqual(self.client.post(path, json=bad, headers=headers).status_code, 400)
        self.assertEqual(len(calls), 1)

    def test_reverse_geocode_empty_result_is_recoverable(self):
        self.service.geocoder = SimpleNamespace(reverse=lambda *args: [])
        response = self.client.post('/api/employment/reverse-geocode',
                                    json={'lat': 0, 'lng': 0}, headers={'X-Test-User': 'alice'})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.service.read('alice')[0]['location'])

    def test_geocoding_does_not_save_without_confirmation(self):
        self.service.geocoder=SimpleNamespace(search=lambda c,a:[{'label':'Fixture','lat':18.4885,'lng':-69.8571,'accuracy_m':100}])
        result=self.client.post('/api/employment/geocode',json={'country':'DO','address':'Punto de prueba'},headers={'X-Test-User':'alice'})
        self.assertEqual(result.status_code,200)
        self.assertIsNone(self.service.read('alice')[0]['location'])

    def test_bad_json_does_not_approve_or_crash(self):
        for path in ('search','geocode','applications','automatic-simulation'):
            result=self.client.post('/api/employment/'+path,json=[],headers={'X-Test-User':'alice'})
            self.assertEqual(result.status_code,400)

    def test_revocation_route_is_private(self):
        result=self.client.delete('/api/employment/authorization',headers={'X-Test-User':'alice'})
        self.assertEqual(result.status_code,200); self.assertTrue(result.json['revoked'])
        self.assertIsNone(self.client.get('/api/employment/authorization',headers={'X-Test-User':'bob'}).json['authorization'])


class AutomaticTests(unittest.TestCase):
    search = ServiceTests.search

    def setUp(self):
        ServiceTests.setUp(self)
        self.now = datetime.now(timezone.utc)
        self.scope = {'confirmed':True,'titles':[NEAR['title']],'countries':['DO'],
            'modes':['onsite'],'sources':['fixture'],'excluded_companies':[],
            'minimum_score':50,'minimum_salary':20000,'currency':'DOP','daily_limit':1,
            'start_hour':0,'end_hour':24,'expires_at':(self.now+timedelta(days=1)).isoformat(),
            'use_cover_letter':False}
        result = self.search(); self.offer_id = result['offers'][0]['id']
        state,generation = self.service.read('alice')
        state['offers'][self.offer_id].update(salary={'minimum':25000,'currency':'DOP','period':'month'},
                                             sensitive_questions=False,captcha=False,mfa=False)
        self.store.write(key('alice'),state,generation)
        self.profile = {'skills':[{'name':'Python'}]}

    def auto(self):
        return self.service.auto_simulation('alice',self.offer_id,self.profile,self.now)

    def test_auto_requires_explicit_scope(self):
        with self.assertRaises(geo.PolicyError): self.auto()
        with self.assertRaises(geo.PolicyError): self.service.authorize_simulation('alice',{**self.scope,'confirmed':False})

    def test_auto_validates_scope_and_never_sends(self):
        self.service.authorize_simulation('alice',self.scope)
        self.assertEqual(self.auto()['status'],'PREPARADA')
        with self.assertRaises(geo.PolicyError): self.auto()

    def test_revoked_scope_blocks(self):
        self.service.authorize_simulation('alice',self.scope); self.service.revoke('alice')
        with self.assertRaises(geo.PolicyError): self.auto()

    def test_expired_scope_blocks(self):
        self.service.authorize_simulation('alice',self.scope)
        with self.assertRaises(geo.PolicyError):
            self.service.auto_simulation('alice',self.offer_id,self.profile,self.now+timedelta(days=2))

    def test_location_changes_revoke_scope(self):
        self.service.authorize_simulation('alice',self.scope)
        self.service.save_location('alice',{**POINT,'radius_m':500})
        with self.assertRaises(geo.PolicyError): self.auto()

    def test_daily_limit_includes_cancelled_attempts(self):
        self.service.authorize_simulation('alice',self.scope); first = self.auto()
        self.service.cancel('alice',first['id'])
        with self.assertRaisesRegex(geo.PolicyError,'diario'): self.auto()

    def test_unknown_sensitive_captcha_or_mfa_blocks(self):
        self.service.authorize_simulation('alice',self.scope)
        for flag in ('sensitive_questions','captcha','mfa'):
            state,generation = self.service.read('alice'); state['offers'][self.offer_id][flag]=True
            self.store.write(key('alice'),state,generation)
            with self.assertRaises(geo.PolicyError): self.auto()
            state,generation=self.service.read('alice'); state['offers'][self.offer_id][flag]=False
            self.store.write(key('alice'),state,generation)

    def test_excluded_company_or_title_blocks(self):
        for scope in ({**self.scope,'excluded_companies':['Empresa simulada']},{**self.scope,'titles':['Otro cargo']}):
            self.service.authorize_simulation('alice',scope)
            with self.assertRaises(geo.PolicyError): self.auto()

    def test_salary_score_and_cover_letter_block(self):
        for scope in ({**self.scope,'minimum_salary':30000},{**self.scope,'use_cover_letter':True}):
            self.service.authorize_simulation('alice',scope)
            with self.assertRaises(geo.PolicyError): self.auto()
        self.service.authorize_simulation('alice',self.scope)
        with self.assertRaises(geo.PolicyError): self.service.auto_simulation('alice',self.offer_id,{},self.now)

    def test_outside_hours_blocks(self):
        hour = self.now.astimezone(timezone(timedelta(hours=-4))).hour
        start = (hour+1)%24
        self.service.authorize_simulation('alice',{**self.scope,'start_hour':start,'end_hour':start+1})
        with self.assertRaises(geo.PolicyError): self.auto()


if __name__ == '__main__': unittest.main()
