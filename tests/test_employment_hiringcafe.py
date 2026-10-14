import unittest
from test_employment import MemoryStore,POINT
from employment_hiringcafe import HiringCafe
from employment_service import Employment
from employment_geo import PolicyError
class HiringTests(unittest.TestCase):
 def setUp(self):
  self.store=MemoryStore();self.calls=[]
  self.job={'id':'fixture','title':'Sales','company':'Fixture','location':'Santo Domingo, Nacional, Dominican Republic','workplaceType':'Onsite','technologies':None,'applyUrl':'https://hiringcafe.com/job/fixture','requirementsSummary':'Verified source requirements'}
  def call(name,args):
   self.calls.append((name,args));return {'jobs':[self.job]} if name=='search_hiringcafe_jobs' else {'job':{**self.job,'description':'Complete source requirements'}}
  self.provider=HiringCafe(lambda:self.store,call)
 def test_cache_and_no_coordinates(self):
  offers=self.provider.search('Sales',POINT);self.provider.search('Sales',POINT)
  self.assertEqual(len(self.calls),1);self.assertNotIn('lat',self.calls[0][1]);self.assertIsNone(offers[0]['location']);self.assertEqual(offers[0]['source_country'],'DO')
 def test_unknown_country_not_assumed(self):
  self.job['location']='Somewhere';self.assertIsNone(self.provider.search('Sales',POINT)[0]['source_country'])
 def test_detail_is_cached(self):
  self.assertEqual(self.provider.detail('fixture')['description'],'Complete source requirements');self.provider.detail('fixture');self.assertEqual(len(self.calls),1)
 def test_budget(self):
  from datetime import datetime,timezone
  self.store.write('employment-provider-budget',{'date':datetime.now(timezone.utc).date().isoformat(),'count':100},0)
  with self.assertRaises(PolicyError):self.provider.search('Sales',POINT)
 def test_office_requires_confirmation_and_is_private(self):
  registry=type('Registry',(),{'for_source':lambda _,name:self.provider})()
  geocoder=type('Geocoder',(),{'search':lambda *a:[{'country':'DO','lat':POINT['lat'],'lng':POINT['lng'],'accuracy_m':50}]})()
  service=Employment(lambda:self.store,registry,geocoder=geocoder);service.save_location('alice',POINT)
  job=service.search('alice','Sales',{},'nearby')['unverified'][0]
  service.offer_places('alice',job['id'],'Public workplace')
  with self.assertRaises(PolicyError):service.confirm_offer_place('alice',job['id'],0,False)
  with self.assertRaises(PolicyError):service.confirm_offer_place('bob',job['id'],0,True)
  result=service.confirm_offer_place('alice',job['id'],0,True);self.assertTrue(result['geography']['eligible'])
  self.assertEqual(service.offer_detail('alice',job['id'])['description'],'Complete source requirements')

 def test_registry_blocks_unlicensed_republication(self):
  from employment_hiringcafe import Sources
  with self.assertRaises(PolicyError):Sources(lambda:self.store).for_source('nearby')
