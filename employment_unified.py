"""Bounded public RD feeds and listings; restricted portals remain explicit links."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit

import requests
from employment_geo import PolicyError
from employment_providers import PlainText
from employment_rd import DominicanJobs, normalized, read_feed

LIMIT = 50
TTL = 900
MAX_BYTES = 2000000
RD_ZONE = timezone(timedelta(hours=-4))
SOURCES = {
    'chiripas': ('Chiripas', 'https://chiripas.com/'),
    'tuempleord': ('TuEmpleoRD', 'https://tuempleord.do/busca-tu-trabajo/'),
    'rdtrabaja': ('RD Trabaja', 'https://rdtrabaja.mt.gob.do/empleo/buscar-empleo'),
    'tuvacanterd': ('TuVacanteRD', 'https://tuvacanterd.com/ultimas-vacantes'),
    'aldaba': ('Aldaba', 'https://www.aldaba.com/index.php?bbdd=246&lang=es'),
    'computrabajo': ('Computrabajo RD', 'https://do.computrabajo.com/ofertas-de-trabajo?by=publicationtime'),
}
LIVE = ('chiripas', 'tuempleord', 'rdtrabaja', 'tuvacanterd')


def portal_url(source, query=''):
    base = SOURCES[source][1]
    if not query: return base
    if source == 'aldaba':
        return 'https://www.aldaba.com/buscar.php?' + urlencode({'q': query, 'pais': 'República Dominicana'})
    if source == 'computrabajo':
        slug = re.sub(r'[^a-z0-9]+', '-', normalized(query)).strip('-')
        return 'https://do.computrabajo.com/trabajo-de-' + slug + '?by=publicationtime' if slug else base
    params = {'tuempleord': 'search_keywords', 'rdtrabaja': 'titulo',
              'tuvacanterd': 'keyword'}
    return base + '?' + urlencode({params[source]: query}) if source in params else base


def text(value, limit=40000):
    parser = PlainText(); parser.feed(value if isinstance(value, str) else '')
    return re.sub(r'[ \t]+', ' ', ''.join(parser.parts)).strip()[:limit]


def safe_link(url, host, prefix='/'):
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname == host and not parts.username
                and not parts.password and not parts.port and parts.path.startswith(prefix))
    except (TypeError, ValueError): return False


def iso_date(value):
    if not isinstance(value, str): return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # The official RD API exposes local timestamps without an offset.
        if date.tzinfo is None: date = date.replace(tzinfo=RD_ZONE)
        return date.astimezone(timezone.utc).isoformat()
    except ValueError: return None


def offer(source, url, title, description, **extra):
    return {'source_key': source, 'source': SOURCES[source][0], 'source_country': 'DO',
            'url': url, 'source_job_id': hashlib.sha256(url.encode()).hexdigest()[:32],
            'title': text(title, 160), 'description': text(description), 'company': '',
            'published_at': None, 'mode': 'unknown', 'location': None,
            'location_text': 'República Dominicana · consulta la ciudad en la fuente',
            'requires_travel': None, 'required_skills': [], 'suspicious': False,
            'sensitive_questions': None, 'captcha': None, 'mfa': None, **extra}


def parse_tuempleord(raw):
    if len(raw) > MAX_BYTES or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise PolicyError('RSS inválido.')
    try: root = ET.fromstring(raw)
    except ET.ParseError as error: raise PolicyError('RSS inválido.') from error
    if root.tag != 'rss': raise PolicyError('RSS inválido.')
    from email.utils import parsedate_to_datetime
    jobs = []
    for item in root.findall('.//item'):
        fields = {child.tag.split('}')[-1]: child.text or '' for child in item}
        url = fields.get('link', '').strip()
        if not safe_link(url, 'tuempleord.do', '/empleo/'): continue
        description = fields.get('encoded') or fields.get('description', '')
        title = fields.get('title', '')
        if not text(title) or not text(description): continue
        date = None
        try:
            parsed = parsedate_to_datetime(fields.get('pubDate', ''))
            if parsed.tzinfo: date = parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError): pass
        jobs.append(offer('tuempleord', url, title, description, published_at=date,
                          location_text=text(fields.get('location', ''), 200) or 'República Dominicana'))
    return jobs


def parse_rdtrabaja(raw, now=None):
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise PolicyError('Respuesta de RD Trabaja inválida.')
    jobs = []; now = now or datetime.now(timezone.utc)
    for row in data['data'][:LIMIT]:
        job = row.get('puesto') if isinstance(row, dict) else None
        if not isinstance(job, dict) or type(job.get('id')) is not int: continue
        if job.get('pais') not in (None, '', 'DO', 'República Dominicana'): continue
        title = text(job.get('titulo'), 160)
        description = '\n\n'.join(filter(None, (text(job.get('descripcion')), text(job.get('requisitosGenerales')))))
        if not title or not description: continue
        expiry = iso_date(job.get('fechaVencimiento'))
        if expiry and datetime.fromisoformat(expiry) < now: continue
        # The portal has inline job details, not individual vacancy permalinks.
        url = portal_url('rdtrabaja', title)
        jobs.append(offer('rdtrabaja', url, title, description,
                          source_job_id=str(job['id']), published_at=iso_date(job.get('fechaPublicacion')),
                          expires_at=expiry, source_link_search=True))
    return jobs, data.get('pageCount', 1) > 1


class VacancyCards(HTMLParser):
    """Read only brief index facts, without fetching or copying full job pages."""
    def __init__(self):
        super().__init__(); self.jobs = []; self.current = None
        self.capture = None; self.buffer = []; self.country = None; self.blocked = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); classes = attrs.get('class', '').split()
        if tag in ('script', 'style'): self.blocked += 1
        if tag == 'input' and attrs.get('id') == 'current_country_code': self.country = attrs.get('value')
        if tag == 'a' and 'jobcardStyle1' in classes:
            url = attrs.get('href', '')
            if safe_link(url, 'tuvacanterd.com', '/empleo/'):
                self.current = {'url': url, 'title': '', 'company': '', 'location': ''}
        if self.current and tag == 'span':
            if 'tw-text-lg' in classes: self.capture = 'title'
            elif 'tw-card-title' in classes: self.capture = 'company'
            elif 'tw-location' in classes: self.capture = 'location'
            else: self.capture = None
            self.buffer = []

    def handle_data(self, data):
        if self.current and self.capture and not self.blocked: self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.blocked: self.blocked -= 1
        if tag == 'span' and self.current and self.capture:
            self.current[self.capture] = text(''.join(self.buffer), 200); self.capture = None
        if tag == 'a' and self.current:
            if self.current['title']: self.jobs.append(self.current)
            self.current = None; self.capture = None


def parse_tuvacanterd(raw):
    parser = VacancyCards(); parser.feed(raw.decode('utf-8'))
    if parser.country != 'DO': raise PolicyError('El listado no confirma República Dominicana.')
    if not parser.jobs:
        raise PolicyError('No se pudo leer el listado de TuVacanteRD; consulta el portal.')
    return [offer('tuvacanterd', job['url'], job['title'],
                  'Consulta los requisitos completos en TuVacanteRD y añádelos para adaptar tu CV.',
                  company='' if job['company'] == 'Empleos RD' else job['company'],
                  location_text=job['location'] or 'República Dominicana', description_verified=False)
            for job in parser.jobs[:LIMIT]]


def fetch_public(source, query):
    url, params = {
        'chiripas': ('https://chiripas.com/rss/all/', None),
        'tuempleord': ('https://tuempleord.do/', {'feed': 'job_feed', 'posts_per_page': LIMIT,
                                               'search_keywords': query}),
        'rdtrabaja': ('https://empleateya.mt.gob.do/api/puestos',
                      {'filters': json.dumps({'titulo': query}) if query else '{}', 'pageIndex': 1, 'pageSize': LIMIT}),
        'tuvacanterd': ('https://tuvacanterd.com/ultimas-vacantes', {'keyword': query}),
    }[source]
    started = time.monotonic()
    with requests.get(url, params=params, headers={'User-Agent': 'CVaLaMedida/1.0 (+https://cvalamedida.web.app)'},
                      timeout=(4, 12), allow_redirects=False, stream=True) as response:
        if response.status_code != 200: raise PolicyError('Fuente no disponible.')
        chunks = []; size = 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() - started > 22: raise PolicyError('Fuente fuera de los límites de consulta.')
            chunks.append(chunk)
        return b''.join(chunks)


class SearchBatch(list):
    def __init__(self, jobs, sources):
        super().__init__(jobs); self.sources = sources


class UnifiedDominicanJobs(DominicanJobs):
    def __init__(self, store_factory, fetch=fetch_public):
        self.store_factory = store_factory; self.fetch = fetch

    def _source(self, source, query):
        store = self.store_factory()
        key = 'employment-unified-v1-' + source + '-' + hashlib.sha256(query.casefold().encode()).hexdigest()[:24]
        cached, generation = store.read(key)
        if cached and time.time() - cached.get('at', 0) < TTL: return cached['jobs'], cached['more']
        raw = self.fetch(source, query)
        more = False
        if source == 'chiripas': jobs = [{**job, 'source_key': source, 'source': 'Chiripas'} for job in read_feed(raw)]
        elif source == 'tuempleord': jobs = parse_tuempleord(raw)
        elif source == 'rdtrabaja': jobs, more = parse_rdtrabaja(raw)
        else: jobs = parse_tuvacanterd(raw)
        terms = normalized(query).split()
        jobs = [job for job in jobs if all(term in normalized(job['title'] + ' ' + job['company']) for term in terms)]
        jobs.sort(key=lambda job: job.get('published_at') or '', reverse=True)
        more = more or len(jobs) >= LIMIT
        jobs = jobs[:LIMIT]
        try: store.write(key, {'at': time.time(), 'jobs': jobs, 'more': more}, generation)
        except RuntimeError: pass  # A competing refresh can win the cache write without discarding these results.
        return jobs, more

    def search(self, query, location=None):
        jobs = []; statuses = []
        with ThreadPoolExecutor(max_workers=len(LIVE)) as pool:
            tasks = {source: pool.submit(self._source, source, query) for source in LIVE}
            for source, future in tasks.items():
                item = {'key': source, 'name': SOURCES[source][0], 'url': portal_url(source, query)}
                try:
                    found, more = future.result(); jobs.extend(found)
                    item.update(status='ok', count=len(found), has_more=more,
                                message='Resumen de vacantes; requisitos completos en el portal.' if source == 'tuvacanterd' else '')
                except (PolicyError, requests.RequestException, ValueError, TypeError, KeyError):
                    item.update(status='unavailable', count=0, message='No disponible en esta consulta. Puedes consultar el portal.')
                statuses.append(item)
        for source in ('aldaba', 'computrabajo'):
            statuses.append({'key': source, 'name': SOURCES[source][0], 'url': portal_url(source, query),
                             'status': 'external', 'count': 0,
                             'message': 'Consulta directa: el portal restringe la reutilización automática de sus ofertas.'})
        unique = {(job['source_key'], job['source_job_id']): job for job in jobs}
        return SearchBatch(sorted(unique.values(), key=lambda job: job.get('published_at') or '', reverse=True)[:200], statuses)
