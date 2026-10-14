import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from employment_live import Himalayas,Nominatim,timestamp
from employment_service import Employment
from employment_geo import PolicyError
from test_employment import MemoryStore,POINT


class LiveTests(unittest.TestCase):
    def setUp(self): self.store=MemoryStore()
    def test_remote_restrictions_salary_dates_and_cache(self):
        calls=[]
        job={'title':'Customer support','companyName':'Fixture','description':'<p>Only stated facts.</p>',
             'applicationLink':'https://himalayas.app/companies/fixture/jobs/support',
             'locationRestrictions':[],'timezoneRestrictions':[],
             'pubDate':1790348745,'expiryDate':1795532745,'minSalary':40000,'salaryPeriod':'annual','currency':'USD'}
        def fetch(url,params): calls.append(params); return {'jobs':[job]}
        provider=Himalayas(lambda:self.store,fetch)
        first=provider.search('support',POINT); second=provider.search('support',POINT)
        self.assertEqual(first,second); self.assertEqual(len(calls),1)
        self.assertNotIn('lat',calls[0]); self.assertTrue(first[0]['remote_worldwide'])
        self.assertEqual(first[0]['salary']['period'],'year'); self.assertIn('+00:00',first[0]['expires_at'])

    def test_missing_country_is_never_inferred_worldwide(self):
        job={'title':'Support','companyName':'Fixture','applicationLink':'https://himalayas.app/jobs/support'}
        provider=Himalayas(lambda:self.store,lambda *a:{'jobs':[job]})
        self.assertFalse(provider.search('support',POINT)[0]['remote_worldwide'])

    def test_geocode_bounds_country_and_aggregate_rate(self):
        data={'lat':'18.4885','lon':'-69.8571','boundingbox':['18.488','18.489','-69.858','-69.857'],
              'display_name':'Punto público ficticio','address':{'country_code':'do','city':'Fixture'}}
        geocoder=Nominatim(lambda:self.store,lambda *a:[data])
        first=geocoder.search('DO','Fixture'); self.assertEqual(first[0]['country'],'DO')
        self.assertGreater(first[0]['accuracy_m'],20)
        with self.assertRaises(PolicyError): geocoder.search('DO','Other')

    def test_supervised_review_does_not_enable_automatic_or_claim_submission(self):
        offer={'title':'Support','description':'No sensitive facts','company':'Fixture','source':'fixture',
               'url':'https://example.invalid/job','mode':'remote','suspicious':False,'requires_travel':None,
               'remote_countries':[],'remote_worldwide':True,'timezone_restrictions':[]}
        service=Employment(lambda:self.store,type('Provider',(),{'search':lambda *a:[offer]})())
        service.save_location('alice',{**POINT,'allow_remote':True})
        result=service.search('alice','Support',{'skills':[]}); found=result['unverified'][0]
        self.assertTrue(found['geography']['location_eligible'])
        with self.assertRaises(PolicyError): service.prepare('alice',found['id'])
        pending=service.prepare('alice',found['id'],True)
        with self.assertRaises(PolicyError): service.open_official('alice',pending['id'],False)
        opened=service.open_official('alice',pending['id'],True)
        self.assertEqual(opened['status'],'REQUIERE INTERVENCIÓN'); self.assertFalse(opened['simulation'])

    def test_changed_scope_blocks_opening(self):
        from test_employment import Provider
        service=Employment(lambda:self.store,Provider()); service.save_location('alice',POINT)
        found=service.search('alice','Python',{})['offers'][0]; pending=service.prepare('alice',found['id'])
        service.save_location('alice',{**POINT,'radius_m':500})
        with self.assertRaises(PolicyError): service.open_official('alice',pending['id'],True)

    def test_bad_timestamp_is_unknown(self):
        self.assertIsNone(timestamp('not a date')); self.assertIsNone(timestamp(True))
