import unittest
from employment_rd import DominicanJobs, read_feed
from employment_service import Employment
from employment_hiringcafe import Sources
from employment_geo import PolicyError
from test_employment import MemoryStore

FEED = b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><description>Empleos en RD</description></channel>
<item><title>[Tiempo Completo] Cajero en Empresa Uno</title><link>https://chiripas.com/empleo/cajero/1</link><description>Atencion de caja.</description><dc:date>Mon, 12 Oct 2026 09:00:00 -0400</dc:date></item>
<item><title>Camarero en Empresa Dos</title><link>https://chiripas.com/empleo/camarero/2</link><description>Servicio al cliente.</description><dc:date>Tue, 13 Oct 2026 09:00:00 -0400</dc:date></item>
<item><title>Chef en Empresa Tres</title><link>https://chiripas.com/empleo/chef/3</link><description>Cocina.</description></item>
</rdf:RDF>'''


class DominicanEmploymentTests(unittest.TestCase):
    def setUp(self):
        self.store=MemoryStore();self.calls=[]
        def fetch():self.calls.append(True);return FEED
        self.provider=DominicanJobs(lambda:self.store,fetch)
        self.service=Employment(lambda:self.store,self.provider)

    def test_title_search_without_gps_or_profile(self):
        result=self.service.search('fixture','Cajero',{},'rd')
        self.assertTrue(result['national'])
        self.assertEqual([job['title'] for job in result['offers']],['Cajero'])
        self.assertIsNone(self.service.read('fixture')[0]['location'])
        self.assertFalse(result['offers'][0]['geography']['eligible'])

    def test_latest_ignores_text_and_sorts_all_available_jobs(self):
        result=self.service.search('fixture','Cajero',{},'rd',True)
        self.assertEqual([job['title'] for job in result['offers']],['Camarero','Cajero','Chef'])
        self.assertIsNone(result['offers'][-1]['published_at'])
        self.assertEqual(len(self.provider.search('cajero')),1)
        self.assertEqual(len(self.calls),1)

    def test_empty_named_search_and_invalid_latest_rejected(self):
        for query,latest in [('',False),('cajero','yes')]:
            with self.assertRaises(PolicyError):self.service.search('fixture',query,{},'rd',latest)
        self.assertEqual(self.calls,[])

    def test_only_rd_provider_can_be_selected(self):
        registry=Sources(lambda:self.store)
        self.assertIsInstance(registry.for_source('rd'),DominicanJobs)
        for source in ('remote','nearby','arbitrary'):
            with self.assertRaises(PolicyError):registry.for_source(source)

    def test_source_links_markup_and_dates_are_validated(self):
        for bad in [b'https://evil.invalid/',b'https://chiripas.com:bad/',b'https://user:pass@chiripas.com/']:
            raw=FEED.replace(b'https://chiripas.com/empleo/cajero/1',bad)
            self.assertEqual(len(read_feed(raw)),2)
        with self.assertRaises(PolicyError):read_feed(b'<!DOCTYPE rss [<!ENTITY x "y">]><rss/>')
        with self.assertRaises(PolicyError):read_feed(b'<html/>')

    def test_feed_failure_never_becomes_empty_success(self):
        self.provider.fetch=lambda: (_ for _ in ()).throw(PolicyError('Fuente no disponible'))
        with self.assertRaises(PolicyError):self.service.search('fixture','',{},'rd',True)
