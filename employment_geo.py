"""Geographic policy. Pure functions: no network, accounts or model calls."""
import math
import re
from datetime import datetime, timezone


class PolicyError(ValueError):
    pass


def number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f'{name}: introduce un número.')
    if not math.isfinite(value) or not low <= value <= high:
        raise PolicyError(f'{name}: valor fuera de rango.')
    return value


def text(value, limit=160):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise PolicyError('Texto inválido.')
    return value.strip()


def country(value):
    value = text(value, 2).upper()
    if not re.fullmatch('[A-Z]{2}', value):
        raise PolicyError('Indica el código de país de dos letras (por ejemplo DO).')
    return value


def location(payload):
    if not isinstance(payload, dict):
        raise PolicyError('Ubicación inválida.')
    allowed = {'country', 'region', 'city', 'reference', 'lat', 'lng', 'accuracy_m',
               'radius_m', 'allowed_countries', 'allow_remote', 'allow_travel'}
    if set(payload) - allowed:
        raise PolicyError('Campos de ubicación desconocidos.')
    countries = payload.get('allowed_countries', [])
    if not isinstance(countries, list) or not 0 <= len(countries) <= 20:
        raise PolicyError('Selecciona los países permitidos.')
    home = country(payload['country']) if payload.get('country') else ''
    countries = sorted(set(country(c) for c in countries))
    if home and home not in countries:
        raise PolicyError('El país de residencia debe estar permitido.')
    for key in ('allow_remote', 'allow_travel'):
        if type(payload.get(key)) is not bool:
            raise PolicyError('Preferencia inválida.')
    # Four decimals ~11 m. Add 16 m to uncertainty for coordinate quantization.
    accuracy = math.ceil(number(payload.get('accuracy_m'), 0, 100000, 'Precisión')) + 16
    result = {key: text(payload.get(key, '')) for key in ('region', 'city', 'reference')}
    result.update(country=home, allowed_countries=countries,
        lat=round(number(payload.get('lat'), -90, 90, 'Latitud'), 4),
        lng=round(number(payload.get('lng'), -180, 180, 'Longitud'), 4),
        accuracy_m=accuracy, radius_m=number(payload.get('radius_m'), 500, 100000, 'Radio'),
        allow_remote=payload['allow_remote'], allow_travel=payload['allow_travel'])
    return result


def distance_m(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2 - lat1
    dlng = math.radians(b['lng'] - a['lng'])
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2)**2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def evaluate(preferences, offer, now=None):
    now = now or datetime.now(timezone.utc)
    result = {'eligible': False, 'distance_m': None, 'uncertainty_m': None}

    def blocked(reason):
        return {**result, 'reason': reason}

    if not preferences:
        return blocked('ubicacion_no_confirmada')
    if offer.get('source_country') and offer['source_country'] not in preferences['allowed_countries']:
        return blocked('pais_no_autorizado')
    expiry = offer.get('expires_at')
    if expiry:
        try:
            expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
            if expiry.tzinfo is None or expiry <= now:
                return blocked('oferta_vencida')
        except (ValueError, TypeError, AttributeError):
            return blocked('fecha_ambigua')
    if offer.get('suspicious') is not False:
        return blocked('oferta_no_validada')
    if type(offer.get('requires_travel')) is not bool:
        return blocked('desplazamiento_desconocido')
    if offer['requires_travel'] and not preferences['allow_travel']:
        return blocked('desplazamiento_no_autorizado')
    if offer.get('mode') == 'remote':
        if not preferences.get('country'):
            return blocked('pais_remoto_no_verificado')
        countries = offer.get('remote_countries')
        if not isinstance(countries,list) or not countries and offer.get('remote_worldwide') is not True:
            return blocked('pais_remoto_no_verificado')
        if countries and preferences['country'] not in countries:
            return blocked('pais_no_autorizado')
        if not preferences['allow_remote']:
            return blocked('remoto_no_autorizado')
        offsets=offer.get('timezone_restrictions',[])
        if offsets is None:
            return blocked('horario_remoto_no_verificado')
        if offsets:
            # Dominican Republic is UTC-4 year-round. Other countries with restrictions need review.
            if preferences['country']!='DO' or -4 not in offsets and '-4' not in offsets and 'UTC-4' not in offsets:
                return blocked('horario_remoto_no_autorizado')
        return {**result, 'eligible': True, 'reason': 'remoto_permitido'}
    if offer.get('mode') not in ('onsite', 'hybrid'):
        return blocked('modalidad_ambigua')
    point = offer.get('location')
    if not isinstance(point, dict) or point.get('verified') is not True:
        return blocked('ubicacion_no_verificable')
    if point.get('country') not in preferences['allowed_countries']:
        return blocked('pais_no_autorizado')
    try:
        number(point.get('lat'), -90, 90, 'Latitud')
        number(point.get('lng'), -180, 180, 'Longitud')
        number(point.get('accuracy_m'), 0, 100000, 'Precisión')
    except PolicyError:
        return blocked('ubicacion_ambigua')
    dist = distance_m(preferences, point)
    uncertainty = preferences['accuracy_m'] + point['accuracy_m']
    result.update(distance_m=round(dist), uncertainty_m=math.ceil(uncertainty))
    if dist - uncertainty > preferences['radius_m']:
        return blocked('fuera_del_radio')
    if dist + uncertainty > preferences['radius_m']:
        return blocked('limite_geografico_ambiguo')
    return {**result, 'eligible': True, 'reason': 'dentro_del_radio'}


def compatibility(profile, offer):
    """Conservative, explainable evidence coverage, not a hiring probability."""
    skills = {item.get('label',item.get('name')).casefold() for item in profile.get('skills', [])
              if isinstance(item, dict) and isinstance(item.get('label',item.get('name')), str)}
    required = offer.get('required_skills', [])
    if not required or not all(isinstance(s, str) for s in required):
        return {'score': None, 'reason': 'requisitos_no_estructurados'}
    required = list(dict.fromkeys(s.casefold() for s in required))
    met = [s for s in required if s in skills]
    missing = [s for s in required if s not in skills]
    return {'score': round(100 * len(met) / len(required)), 'met': met, 'missing': missing,
            'method': 'Cobertura de habilidades documentadas; no evalúa aún experiencia, formación o idiomas.'}
