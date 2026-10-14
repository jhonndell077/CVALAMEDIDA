"""Regresiones locales: ningún acceso a servicios o datos personales."""
import unittest
from employment_service import Employment
from employment_live import Himalayas
from test_employment import MemoryStore, POINT, NEAR


class IntegrationTests(unittest.TestCase):
    def test_invalid_duplicate_does_not_hide_valid_offer(self):
        store = MemoryStore()
        class Provider:
            def search(self, *args):
                return [{**NEAR, 'description': ''}, NEAR]
        service = Employment(lambda: store, Provider())
        service.save_location('fixture', POINT)
        result = service.search('fixture', 'chef', {'skills': []})
        self.assertEqual(len(result['offers']), 1)

    def test_malformed_record_does_not_hide_next_record(self):
        store = MemoryStore()
        job = {'title': 'Chef', 'companyName': 'Fixture', 'description': 'Datos',
               'applicationLink': 'https://himalayas.app/jobs/fixture'}
        provider = Himalayas(lambda: store, lambda *args: {'jobs': [{**job, 'title': None}, job]})
        self.assertEqual(len(provider.search('chef', POINT)), 1)
