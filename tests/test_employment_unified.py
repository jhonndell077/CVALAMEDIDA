"""Offline source fixtures; never query portals or Firebase in tests."""
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from employment_unified import (UnifiedDominicanJobs, fetch_public, parse_tuempleord,
                                parse_rdtrabaja, parse_tuvacanterd, portal_url, LIMIT)
from employment_service import Employment, canonical
from employment_geo import PolicyError
from test_employment import MemoryStore

CHIRIPAS = b'''<rss><channel><item><title>Cajero en Empresa</title>
<link>https://chiripas.com/empleo/cajero/1</link><description>Caja.</description>
<pubDate>Mon, 12 Oct 2026 09:00:00 -0400</pubDate></item></channel></rss>'''
TUEMPLEO = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:job="https://tuempleord.do"><channel>
<item><title>Cajero</title><link>https://tuempleord.do/empleo/cajero/</link><description>Resumen</description>
<content:encoded>&lt;p&gt;REQUISITOS FICTICIOS&lt;/p&gt;&lt;script&gt;no visible&lt;/script&gt;</content:encoded>
<pubDate>Tue, 13 Oct 2026 09:00:00 -0400</pubDate><job:location>Santiago</job:location></item></channel></rss>'''
RD = json.dumps({'data': [{'puesto': {'id': 10, 'titulo': 'Cajero', 'descripcion': 'Atencion.',
                         'requisitosGenerales': 'Experiencia.', 'pais': None,
                         'fechaPublicacion': '2026-10-14T08:00:00', 'fechaVencimiento': '2099-01-01'}}],
                 'pageCount': 2}).encode()
VACANTE = b'''<html><input value="DO" id="current_country_code">
<a class="card jobcardStyle1" href="https://tuvacanterd.com/empleo/cajero">
<span class="tw-text-lg">Cajero</span><span class="tw-card-title">Empleos RD</span>
<span class="tw-location">Santo Domingo</span></a></html>'''
FIXTURES = {'chiripas': CHIRIPAS, 'tuempleord': TUEMPLEO, 'rdtrabaja': RD, 'tuvacanterd': VACANTE}


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.calls = []
        def fetch(source, query):
            self.calls.append((source, query)); return FIXTURES[source]
        self.provider = UnifiedDominicanJobs(lambda: self.store, fetch)
        self.service = Employment(lambda: self.store, self.provider)

    def test_one_search_merges_four_sources_and_exposes_all_six(self):
        result = self.service.search('fixture', 'Cajero', {}, 'rd')
        self.assertEqual(len(result['offers']), 4)
        self.assertEqual(result['offers'][0]['source_key'], 'rdtrabaja')
        self.assertEqual({job['source_country'] for job in result['offers']}, {'DO'})
        self.assertEqual(len(result['sources']), 6)
        self.assertEqual([item['status'] for item in result['sources']][-2:], ['external', 'external'])
        self.assertFalse(result['partial'])
        self.assertEqual({key for key, query in self.calls}, set(FIXTURES))

    def test_cache_is_per_source_and_query(self):
        self.provider.search('Cajero'); self.provider.search('cajero')
        self.assertEqual(len(self.calls), 4)
        self.provider.search('Chef'); self.assertEqual(len(self.calls), 8)
        self.assertTrue(all(query == 'Chef' for _, query in self.calls[4:]))

    def test_source_failure_does_not_discard_others_and_is_not_empty_success(self):
        fetch = self.provider.fetch
        def fail_one(source, query):
            if source == 'chiripas': raise PolicyError('No disponible')
            return fetch(source, query)
        self.provider.fetch = fail_one
        result = self.service.search('fixture', '', {}, 'rd', True)
        self.assertEqual(len(result['offers']), 3); self.assertTrue(result['partial'])
        self.assertEqual(result['sources'][0]['status'], 'unavailable')
        self.provider.fetch = lambda *_: (_ for _ in ()).throw(PolicyError('No disponible'))
        self.store.items.clear()
        failed = self.service.search('fixture', '', {}, 'rd', True)
        self.assertEqual(failed['offers'], [])
        self.assertTrue(all(item['status'] == 'unavailable' for item in failed['sources'][:4]))

    def test_rd_jobs_with_same_title_keep_distinct_ids(self):
        data = json.loads(RD); second = dict(data['data'][0]['puesto'], id=11)
        data['data'].append({'puesto': second})
        self.provider.fetch = lambda source, query: json.dumps(data).encode() if source == 'rdtrabaja' else FIXTURES[source]
        result = self.service.search('fixture', 'Cajero', {}, 'rd')
        jobs = [job for job in result['offers'] if job['source_key'] == 'rdtrabaja']
        self.assertEqual(len(jobs), 2); self.assertNotEqual(jobs[0]['id'], jobs[1]['id'])
        self.assertEqual(jobs[0]['url'], jobs[1]['url'])
        self.assertEqual(next(item['count'] for item in result['sources'] if item['key'] == 'rdtrabaja'), 2)

    def test_rss_rejects_entities_foreign_links_and_script_content(self):
        jobs = parse_tuempleord(TUEMPLEO)
        self.assertIn('REQUISITOS FICTICIOS', jobs[0]['description'])
        self.assertNotIn('no visible', jobs[0]['description'])
        for url in (b'https://evil.invalid/empleo/a', b'https://user:pass@tuempleord.do/empleo/a', b'https://tuempleord.do:443/empleo/a'):
            self.assertEqual(parse_tuempleord(TUEMPLEO.replace(b'https://tuempleord.do/empleo/cajero/', url)), [])
        for raw in (b'<!DOCTYPE rss><rss/>', b'<html/>', b'invalid'):
            with self.assertRaises(PolicyError): parse_tuempleord(raw)

    def test_official_api_excludes_expired_and_foreign_positions(self):
        data = json.loads(RD); job = data['data'][0]['puesto']; job['fechaVencimiento'] = '2020-01-01'
        self.assertEqual(parse_rdtrabaja(json.dumps(data).encode())[0], [])
        job['fechaVencimiento'] = '2099-01-01'; job['pais'] = 'US'
        self.assertEqual(parse_rdtrabaja(json.dumps(data).encode())[0], [])
        jobs, more = parse_rdtrabaja(RD, datetime(2026,10,14,tzinfo=timezone.utc))
        self.assertTrue(more); self.assertEqual(jobs[0]['published_at'], '2026-10-14T12:00:00+00:00')
        self.assertTrue(jobs[0]['source_link_home'])

    def test_tuvacante_summaries_do_not_invent_dates_or_requirements(self):
        job = parse_tuvacanterd(VACANTE)[0]
        self.assertEqual(job['title'], 'Cajero'); self.assertIsNone(job['published_at'])
        self.assertFalse(job['description_verified']); self.assertEqual(job['company'], '')
        for raw in (VACANTE.replace(b'value="DO"', b'value="US"'), b'<html/>'):
            with self.assertRaises(PolicyError): parse_tuvacanterd(raw)

    def test_external_links_preserve_query_and_rd_scope(self):
        url = urlsplit(portal_url('aldaba', 'Cajero & administrador'))
        self.assertEqual(parse_qs(url.query)['q'], ['Cajero & administrador'])
        self.assertEqual(parse_qs(url.query)['pais'], ['República Dominicana'])
        self.assertIn('trabajo-de-tecnico-electrico', portal_url('computrabajo', 'Técnico eléctrico'))
        self.assertEqual(portal_url('rdtrabaja', 'Cajero'), 'https://rdtrabaja.mt.gob.do/')

    def test_legacy_rd_links_are_normalized_without_rewriting_other_portals(self):
        self.assertEqual(canonical('https://rdtrabaja.mt.gob.do/empleo/buscar-empleo?titulo=PISCINERO'),
                         'https://rdtrabaja.mt.gob.do/')
        self.assertEqual(canonical('https://tuempleord.do/empleo/cajero/'), 'https://tuempleord.do/empleo/cajero/')

    def test_http_requests_are_bounded_and_do_not_follow_redirects(self):
        response = Mock(status_code=302)
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        with patch('employment_unified.requests.get', return_value=response) as get:
            with self.assertRaises(PolicyError): fetch_public('rdtrabaja', 'Cajero')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(get.call_args.kwargs['params']['pageSize'], LIMIT)
        response.status_code = 200; response.iter_content.return_value = [b'x' * 2000001]
        with patch('employment_unified.requests.get', return_value=response):
            with self.assertRaises(PolicyError): fetch_public('tuempleord', '')


if __name__ == '__main__': unittest.main()
