import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from employment_providers import GreenhouseProvider
from employment_geo import PolicyError


class Response:
    status_code=200
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def iter_content(self,size):
        yield json.dumps({'jobs':[{'id':1,'title':'Developer Python','content':'<p>Oferta sintética</p><script>ignore me</script>',
            'absolute_url':'https://example.invalid/jobs/1','location':{'name':'Ciudad sin coordenadas'}}]}).encode()


class ProviderTests(unittest.TestCase):
    def test_official_host_timeouts_and_no_private_coordinates(self):
        calls=[]
        def get(url,**kwargs): calls.append((url,kwargs)); return Response()
        provider=GreenhouseProvider(['fixture'],SimpleNamespace(get=get))
        offers=provider.search('Python',{'lat':18.4885,'lng':-69.8571})
        self.assertEqual(len(offers),1)
        self.assertEqual(calls[0][0],'https://boards-api.greenhouse.io/v1/boards/fixture/jobs?content=true')
        self.assertEqual(calls[0][1],{'timeout':(3,10),'allow_redirects':False,'stream':True})
        self.assertIsNone(offers[0]['location']); self.assertIsNone(offers[0]['requires_travel'])
        self.assertNotIn('ignore me',offers[0]['description'])

    def test_no_board_url_injection(self):
        for board in ('https://127.0.0.1','../private','foo?token=private'):
            with self.assertRaises(PolicyError): GreenhouseProvider([board])

    def test_query_filter_does_not_invent_jobs(self):
        provider=GreenhouseProvider(['fixture'],SimpleNamespace(get=lambda *a,**k:Response()))
        self.assertEqual(provider.search('Chef',{}),[])

    def test_response_redirect_is_rejected(self):
        response=Response(); response.status_code=302
        provider=GreenhouseProvider(['fixture'],SimpleNamespace(get=lambda *a,**k:response))
        with self.assertRaises(PolicyError): provider.search('Python',{})


if __name__=='__main__': unittest.main()
