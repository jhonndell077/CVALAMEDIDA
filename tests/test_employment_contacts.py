"""Private contact persistence and authorization, offline fixtures only."""
import unittest
from employment_service import Employment
from employment_geo import PolicyError
from test_employment import MemoryStore, NEAR
import test_employment as fixtures

class ContactsTests(unittest.TestCase):
    def setUp(self):
        self.store=MemoryStore()
        class Provider:
            def search(self,*args):return [{**NEAR,'source_country':'DO'}]
        self.service=Employment(lambda:self.store,Provider())
        self.offer=self.service.search('alice','Chef',{},'rd')['offers'][0]['id']

    def test_save_reload_update_delete_and_account_isolation(self):
        data=self.service.save_offer_contact('alice',self.offer,{'email':'jobs@example.invalid','whatsapp':'809-555-0123'})
        self.assertEqual(data['contact']['whatsapp'],'+18095550123')
        self.assertEqual(Employment(lambda:self.store).offer_contact('alice',self.offer),data)
        with self.assertRaises(PolicyError):self.service.offer_contact('bob',self.offer)
        with self.assertRaises(PolicyError):self.service.save_offer_contact('bob',self.offer,{'email':'x@example.invalid','whatsapp':''})
        self.service.save_offer_contact('alice',self.offer,{'email':'','whatsapp':'+1 829 555 0123'})
        self.assertEqual(self.service.offer_contact('alice',self.offer)['contact']['email'],'')
        self.service.save_offer_contact('alice',self.offer,{'email':'','whatsapp':''})
        self.assertEqual(self.service.offer_contact('alice',self.offer)['contact'],{'email':'','whatsapp':''})

    def test_invalid_contact_input_and_unknown_fields_are_rejected(self):
        for payload in [{'email':'not-email','whatsapp':''},{'email':'x@example.invalid\r\nBcc:other@example.invalid','whatsapp':''},
                        {'email':'','whatsapp':'javascript:alert(1)'},{'email':'','whatsapp':'123'},
                        {'email':'x@example.invalid','whatsapp':'','uid':'bob'},None]:
            with self.subTest(payload=payload), self.assertRaises(PolicyError):self.service.save_offer_contact('alice',self.offer,payload)

class ContactRouteTests(unittest.TestCase):
    setUp = fixtures.RouteTests.setUp
    def test_contact_endpoints_require_identity_and_preserve_owner(self):
        headers={'X-Test-User':'alice'}
        search=self.client.post('/api/employment/search',json={'query':'Chef'},headers=headers)
        offer=search.json['offers'][0]['id'];url=f'/api/employment/offers/{offer}/contact'
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.put(url,json={'email':'x@example.invalid','whatsapp':''}).status_code,401)
        self.assertEqual(self.client.put(url,json={'email':'x@example.invalid','whatsapp':''},headers=headers).status_code,200)
        self.assertEqual(self.client.get(url,headers=headers).json['contact']['email'],'x@example.invalid')
        self.assertEqual(self.client.get(url,headers={'X-Test-User':'bob'}).status_code,400)

if __name__=='__main__':unittest.main()
