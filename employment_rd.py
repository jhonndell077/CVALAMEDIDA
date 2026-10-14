"""Dominican jobs from Chiripas' expressly redistributable RSS, linked to the source."""
import hashlib
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import requests
from employment_geo import PolicyError
from employment_providers import PlainText

FEED = 'https://chiripas.com/rss/all/'
PERMISSION = 'https://chiripas.com/rss'


def fetch_feed():
    with requests.get(FEED, headers={'User-Agent': 'CVaLaMedida/1.0 (+https://cvalamedida.web.app)'},
                      timeout=(4, 18), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise PolicyError('Chiripas no está disponible. Reintenta en unos minutos.')
        chunks = []; size = 0
        for chunk in response.iter_content(16384):
            size += len(chunk)
            if size > 2000000: raise PolicyError('La fuente superó el tamaño permitido.')
            chunks.append(chunk)
        return b''.join(chunks)


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold()) if not unicodedata.combining(c))


def read_feed(raw):
    if not isinstance(raw, bytes) or len(raw) > 2000000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise PolicyError('La fuente de vacantes no contiene un RSS válido.')
    try: root = ET.fromstring(raw)
    except ET.ParseError as error: raise PolicyError('No se pudo leer la fuente de vacantes.') from error
    if root.tag.split('}')[-1] not in ('RDF', 'rss'):
        raise PolicyError('La fuente de vacantes no contiene un RSS válido.')
    offers = []; seen = set()
    for item in root.iter():
        if item.tag.split('}')[-1] != 'item': continue
        fields = {child.tag.split('}')[-1]: child.text or '' for child in item}
        url = fields.get('link', '').strip()
        try:
            parts = urlsplit(url)
            safe = parts.scheme == 'https' and parts.hostname == 'chiripas.com' and not parts.username and not parts.password and not parts.port and parts.path.startswith('/empleo/')
        except ValueError: safe = False
        if not safe or url in seen:
            continue
        title = re.sub(r'^\[[^\]]+\]\s*', '', fields.get('title', '')).strip()
        title, separator, company = title.rpartition(' en ') if ' en ' in title else (title, '', '')
        parser = PlainText(); parser.feed(fields.get('description', ''))
        description = ''.join(parser.parts).strip()[:40000]
        if not title or not description: continue
        published = None
        try:
            date = parsedate_to_datetime(fields.get('date') or fields.get('pubDate', ''))
            if date.tzinfo: published = date.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError): pass
        seen.add(url)
        offers.append({'title': title[:160], 'company': company[:160], 'description': description,
                       'source': 'Chiripas RD', 'source_country': 'DO', 'url': url,
                       'source_job_id': hashlib.sha256(url.encode()).hexdigest()[:32],
                       'published_at': published, 'mode': 'unknown', 'location': None,
                       'location_text': 'República Dominicana · consulta la ciudad en la oferta',
                       'requires_travel': None, 'required_skills': [], 'suspicious': False,
                       'sensitive_questions': None, 'captcha': None, 'mfa': None})
    return sorted(offers, key=lambda job: job['published_at'] or '', reverse=True)[:200]


class DominicanJobs:
    def __init__(self, store_factory, fetch=fetch_feed):
        self.store_factory = store_factory; self.fetch = fetch

    def search(self, query, location=None):
        store = self.store_factory(); key = 'employment-rd-feed-v1'
        cached, generation = store.read(key)
        if cached and time.time() - cached.get('at', 0) < 300: offers = cached['offers']
        else:
            offers = read_feed(self.fetch())
            store.write(key, {'at': time.time(), 'offers': offers}, generation)
        terms = normalized(query).split()
        return [offer for offer in offers if all(term in normalized(offer['title'] + ' ' + offer['company']) for term in terms)]
