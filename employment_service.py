"""Isolated extension using existing private JobStore and verified Firebase identity.

Disabled unless explicitly configured. This iteration cannot send applications.
Providers are injected server-side; no arbitrary URLs or client-supplied vacancies.
"""
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from flask import g
import employment_geo as geo


def key(uid):
    return 'employment-' + hashlib.sha256(uid.encode()).hexdigest()


def canonical(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise geo.PolicyError('La oferta no tiene un enlace HTTPS válido.')
    query = [(k, v) for k, v in parse_qsl(parts.query)
             if not k.startswith('utm_') and k not in ('ref', 'trackingId')]
    return urlunsplit(('https', parts.netloc.lower(), parts.path, urlencode(sorted(query)), ''))


class Employment:
    def __init__(self, store_factory, provider=None, geocoder=None):
        self.store_factory = store_factory
        self.provider = provider
        self.geocoder = geocoder

    def read(self, uid):
        state, generation = self.store_factory().read(key(uid))
        return state or {'location': None, 'revision': 0, 'offers': {}, 'applications': {},
                         'authorization': None}, generation

    def mutate(self, uid, operation):
        # Existing JobStore uses Storage if_generation_match: no lost updates.
        state, generation = self.read(uid)
        result = operation(state)
        self.store_factory().write(key(uid), state, generation)
        return result

    def save_location(self, uid, payload):
        point = geo.location(payload)
        def save(state):
            state['location'] = point
            state['revision'] += 1
            state['authorization'] = None  # Any change requires fresh consent.
            for item in state['applications'].values():
                if item['status'] in ('PREPARADA', 'PENDIENTE DE APROBACIÓN'):
                    item['status'] = 'CANCELADA'
                    item['result'] = 'Ubicación modificada: prepara una candidatura nueva.'
            return {'location': point, 'revision': state['revision']}
        return self.mutate(uid, save)

    def delete_location(self, uid):
        def delete(state):
            state['location'] = None
            state['authorization'] = None
            state['revision'] += 1
            state['offers'] = {}
            for item in state['applications'].values():
                if item['status'] in ('PREPARADA','PENDIENTE DE APROBACIÓN'):
                    item['status']='CANCELADA'
                    item['result']='Ubicación eliminada: revisa y prepara una nueva candidatura.'
            state['geocode_cache']={}
            state['offer_places']={}
            return {'deleted': True}
        return self.mutate(uid, delete)

    def search(self, uid, query, profile, source='remote', latest=False):
        query = geo.text(query, 120)
        if type(latest) is not bool: raise geo.PolicyError('Búsqueda inválida.')
        if source=='rd' and not latest and not query: raise geo.PolicyError('Escribe el nombre de una vacante o pulsa Ver últimas publicadas.')
        if latest: query=''
        state, _ = self.read(uid)
        if not state['location'] and source!='rd':
            raise geo.PolicyError('Confirma tu ubicación antes de buscar.')
        if self.provider is None:
            raise geo.PolicyError('No hay una fuente de vacantes autorizada configurada.')
        today = datetime.now(timezone.utc).date().isoformat()
        revision = state['revision']
        def reserve(current):
            if current['revision'] != revision:
                raise geo.PolicyError('La ubicación cambió. Repite la búsqueda.')
            count = current.get('search_count',0) if current.get('search_date') == today else 0
            if count >= 30:
                raise geo.PolicyError('Límite diario de 30 búsquedas alcanzado.')
            current.update(search_date=today,search_count=count+1)
        self.mutate(uid,reserve)  # Failed calls consume a slot; repeated timeouts cannot bypass the cap.
        # Provider owns terms compliance, timeouts, provenance, coordinates and filters.
        provider=self.provider.for_source(source) if hasattr(self.provider,'for_source') else self.provider
        offers = provider.search(query, state['location'])
        if not isinstance(offers, list) or len(offers) > 200:
            raise geo.PolicyError('El proveedor superó el límite de resultados.')
        seen, accepted, excluded, unknown = set(), [], [], []
        records = {}
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            try:
                url = canonical(offer.get('url', ''))
                identifier = hashlib.sha256(url.encode()).hexdigest()[:32]
                if identifier in seen:
                    continue
                if not offer.get('source') or not offer.get('title') or not offer.get('description'):
                    continue
                seen.add(identifier)
                offer = {**offer, 'id': identifier, 'url': url}
                if source=='rd':
                    if offer.get('source_country')!='DO':continue
                    records[identifier]=offer
                    accepted.append({**offer,'geography':{'eligible':False,'reason':'distancia_no_verificada','distance_m':None,'uncertainty_m':None},'compatibility':geo.compatibility(profile,offer)})
                    continue
                previous=state['offers'].get(identifier,{})
                if (previous.get('location') and previous['location'].get('verification')=='user_confirmed_place'
                    and previous.get('location_text')==offer.get('location_text')
                    and previous.get('source_country')==offer.get('source_country')
                    and previous.get('company')==offer.get('company') and previous.get('mode')==offer.get('mode')):
                    offer['location']=previous['location']
                policy = geo.evaluate(state['location'], offer)
                if offer.get('requires_travel') is None:
                    geographic=geo.evaluate(state['location'],{**offer,'requires_travel':False})
                    if geographic['eligible']:
                        policy={**geographic,'eligible':False,'location_eligible':True,'reason':'desplazamiento_desconocido'}
                    else: policy=geographic
                item = {**offer, 'geography': policy, 'compatibility': geo.compatibility(profile, offer)}
                records[identifier] = offer
                if policy['eligible']:
                    accepted.append(item)
                elif policy['reason'] in ('ubicacion_no_verificable', 'ubicacion_ambigua',
                                          'limite_geografico_ambiguo', 'pais_remoto_no_verificado',
                                          'desplazamiento_desconocido', 'modalidad_ambigua'):
                    unknown.append(item)
                else:
                    excluded.append(item)
            except (geo.PolicyError, ValueError, TypeError):
                continue
        revision = state['revision']
        def save(current):
            if current['revision'] != revision:
                raise geo.PolicyError('La ubicación cambió durante la búsqueda. Busca de nuevo.')
            pinned={item['offer_id'] for item in current['applications'].values() if item['status']!='CANCELADA'}
            retained={identifier:offer for identifier,offer in current['offers'].items() if identifier in pinned}
            current['offers'] = {**retained,**records}
            return {'offers': accepted, 'excluded': excluded, 'unverified': unknown, 'national':source=='rd','latest':latest}
        return self.mutate(uid, save)

    def prepare(self, uid, offer_id, reviewed_no_travel=False):
        def create(state):
            offer = state['offers'].get(offer_id)
            if not offer:
                raise geo.PolicyError('La vacante no pertenece a esta búsqueda.')
            reviewed=offer.get('requires_travel') is None and reviewed_no_travel is True
            policy = geo.evaluate(state['location'],{**offer,'requires_travel':False} if reviewed else offer)
            if not policy['eligible']:
                raise geo.PolicyError(policy['reason'])
            for item in state['applications'].values():
                if item['offer_id'] == offer_id and item['status'] != 'CANCELADA':
                    return item
            if len(state['applications']) >= 100:
                raise geo.PolicyError('Límite de 100 candidaturas de simulación. Elimina el historial para continuar.')
            item = {'id': str(uuid4()), 'offer_id': offer_id, 'status': 'PENDIENTE DE APROBACIÓN',
                    'position':offer.get('title',''),'company':offer.get('company',''),
                    'location_revision': state['revision'], 'simulation': False,
                    'travel_reviewed':reviewed,
                    'created_at': datetime.now(timezone.utc).isoformat()}
            state['applications'][item['id']] = item
            return item
        return self.mutate(uid, create)

    def open_official(self,uid,application_id,confirmed):
        if confirmed is not True: raise geo.PolicyError('Revisa y autoriza antes de abrir la postulación.')
        def approve(state):
            item=state['applications'].get(application_id)
            if not item or item['status']!='PENDIENTE DE APROBACIÓN': raise geo.PolicyError('Candidatura no disponible.')
            if state['revision']!=item['location_revision']: raise geo.PolicyError('La ubicación cambió.')
            offer=state['offers'].get(item['offer_id'],{})
            checked={**offer,'requires_travel':False} if item.get('travel_reviewed') and offer.get('requires_travel') is None else offer
            policy=geo.evaluate(state['location'],checked)
            if not policy['eligible']: raise geo.PolicyError(policy['reason'])
            url=canonical(offer.get('url',''))
            item.update(status='REQUIERE INTERVENCIÓN',simulation=False,
                result='Completa el formulario en el portal oficial. El envío todavía no está confirmado.',url=url)
            return item
        return self.mutate(uid,approve)

    def approve_simulation(self, uid, application_id, confirmed):
        if confirmed is not True:
            raise geo.PolicyError('Se requiere confirmación explícita.')
        def approve(state):
            item = state['applications'].get(application_id)
            if not item:
                raise geo.PolicyError('Candidatura no encontrada.')
            if item['status'] != 'PENDIENTE DE APROBACIÓN':
                raise geo.PolicyError('La candidatura no está pendiente.')
            if state['revision'] != item['location_revision']:
                raise geo.PolicyError('La ubicación cambió: prepara una candidatura nueva.')
            policy = geo.evaluate(state['location'], state['offers'].get(item['offer_id'], {}))
            if not policy['eligible']:
                raise geo.PolicyError(policy['reason'])
            # Never report ENVIADA CONFIRMADA: no destination was contacted.
            item['status'] = 'PREPARADA'
            item['simulation'] = True
            item['result'] = 'SIMULACIÓN VALIDADA. No se realizó ningún envío.'
            return item
        return self.mutate(uid, approve)

    def cancel(self, uid, application_id):
        def cancel(state):
            item = state['applications'].get(application_id)
            if not item:
                raise geo.PolicyError('Candidatura no encontrada.')
            item['status'] = 'CANCELADA'
            return item
        return self.mutate(uid, cancel)

    def offer_places(self,uid,offer_id,place):
        state,_=self.read(uid); offer=state['offers'].get(offer_id)
        if not offer or offer.get('source')!='HiringCafe': raise geo.PolicyError('Vacante no disponible.')
        country=offer.get('source_country')
        if not state['location'] or country not in state['location']['allowed_countries']:
            raise geo.PolicyError('País no autorizado o sin verificar.')
        place=geo.text(place,250)
        if len(place)<3: raise geo.PolicyError('Indica el centro de trabajo público que aparece en la oferta.')
        if not self.geocoder: raise geo.PolicyError('No hay proveedor de mapa.')
        if len(state.get('offer_places',{}))>=20 and offer_id not in state.get('offer_places',{}):
            raise geo.PolicyError('Límite de ubicaciones de ofertas alcanzado.')
        results=self.geocoder.search(country,place)
        def save(current):
            if offer_id not in current['offers']: raise geo.PolicyError('La búsqueda cambió.')
            current.setdefault('offer_places',{})[offer_id]=results
        self.mutate(uid,save)
        return {'results':results}

    def offer_detail(self,uid,offer_id):
        state,_=self.read(uid); offer=state['offers'].get(offer_id)
        if not offer: raise geo.PolicyError('La vacante no pertenece a tu búsqueda.')
        if offer.get('source')!='HiringCafe': return offer
        if offer.get('details_loaded'): return offer
        provider=self.provider.for_source('nearby')
        job=provider.detail(offer.get('source_job_id'))
        description=job.get('description')
        if not isinstance(description,str) or not description.strip():
            raise geo.PolicyError('La fuente no proporciona descripción completa. Revisa el portal original.')
        def save(current):
            cached=current['offers'].get(offer_id)
            if not cached: raise geo.PolicyError('La búsqueda cambió.')
            cached['description']=description[:40000]; cached['details_loaded']=True
            return cached
        return self.mutate(uid,save)

    def confirm_offer_place(self,uid,offer_id,index,confirmed):
        if confirmed is not True or type(index) is not int: raise geo.PolicyError('Confirma el centro de trabajo correcto.')
        def save(state):
            offer=state['offers'].get(offer_id)
            results=state.get('offer_places',{}).get(offer_id,[])
            if not offer or not 0<=index<len(results) or not state['location']: raise geo.PolicyError('Resultado no disponible.')
            point=results[index]
            if point['country']!=offer.get('source_country') or point['country'] not in state['location']['allowed_countries']:
                raise geo.PolicyError('El país no corresponde con la oferta.')
            offer['location']={'lat':point['lat'],'lng':point['lng'],'country':point['country'],
                'accuracy_m':point['accuracy_m']+16,'verified':True,'verification':'user_confirmed_place'}
            policy=geo.evaluate(state['location'],{**offer,'requires_travel':False})
            return {'geography':policy,'location':offer['location']}
        return self.mutate(uid,save)

    def revoke(self, uid):
        def revoke(state):
            state['authorization'] = None
            return {'revoked': True}
        return self.mutate(uid, revoke)

    def authorize_simulation(self, uid, payload):
        """Explicit, expiring scope; only valid for controlled automatic simulations."""
        expected = {'confirmed', 'titles', 'countries', 'modes', 'sources', 'excluded_companies',
                    'minimum_score', 'minimum_salary', 'currency', 'daily_limit',
                    'start_hour', 'end_hour', 'expires_at', 'use_cover_letter'}
        if not isinstance(payload, dict) or set(payload) != expected or payload['confirmed'] is not True:
            raise geo.PolicyError('Revisa y confirma todo el alcance de la autorización.')
        scope = {}
        for name in ('titles','countries','modes','sources','excluded_companies'):
            values = payload[name]
            if not isinstance(values, list) or len(values) > 20 or (name != 'excluded_companies' and not values):
                raise geo.PolicyError('El alcance necesita listas explícitas y limitadas.')
            scope[name] = [geo.text(value,120) for value in values]
            if any(not value for value in scope[name]): raise geo.PolicyError('Alcance vacío.')
        scope['countries'] = [geo.country(value) for value in scope['countries']]
        if set(scope['modes']) - {'onsite','hybrid','remote'}:
            raise geo.PolicyError('Modalidades inválidas.')
        for name, low, high in [('minimum_score',0,100),('minimum_salary',0,100000000),
                                ('daily_limit',1,10),('start_hour',0,23),('end_hour',1,24)]:
            scope[name] = geo.number(payload[name],low,high,name)
        if any(type(scope[name]) is not int for name in ('daily_limit','start_hour','end_hour')):
            raise geo.PolicyError('Los límites y horarios deben ser enteros.')
        if scope['start_hour'] >= scope['end_hour']:
            raise geo.PolicyError('Selecciona un horario diurno sin cruzar medianoche.')
        scope['currency'] = geo.text(payload['currency'],3).upper()
        if not re.fullmatch('[A-Z]{3}',scope['currency']):
            raise geo.PolicyError('Indica la moneda salarial.')
        if type(payload['use_cover_letter']) is not bool:
            raise geo.PolicyError('Preferencia de carta inválida.')
        scope['use_cover_letter'] = payload['use_cover_letter']
        try:
            expiry = datetime.fromisoformat(payload['expires_at'].replace('Z','+00:00'))
            now = datetime.now(timezone.utc)
            if expiry.tzinfo is None or not now < expiry <= now + timedelta(days=30):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise geo.PolicyError('La autorización debe caducar en un máximo de 30 días.') from None
        scope['expires_at'] = expiry.isoformat()
        def save(state):
            if not state['location'] or not set(scope['countries']) <= set(state['location']['allowed_countries']):
                raise geo.PolicyError('El alcance debe estar dentro de los países de tu ubicación confirmada.')
            scope.update(id=str(uuid4()), location_revision=state['revision'], simulation=True)
            state['authorization'] = scope
            return scope
        return self.mutate(uid,save)

    def auto_simulation(self, uid, offer_id, profile, now=None):
        now = now or datetime.now(timezone.utc)
        def validate(state):
            scope = state['authorization']
            if not scope or scope['location_revision'] != state['revision'] or datetime.fromisoformat(scope['expires_at']) <= now:
                raise geo.PolicyError('Autorización revocada o vencida.')
            local = now.astimezone(timezone(timedelta(hours=-4)))  # America/Santo_Domingo
            if not scope['start_hour'] <= local.hour < scope['end_hour']:
                raise geo.PolicyError('Fuera del horario autorizado (Santo Domingo).')
            offer = state['offers'].get(offer_id)
            if not offer or not geo.evaluate(state['location'],offer,now)['eligible']:
                raise geo.PolicyError('La ubicación o vacante no está autorizada.')
            if (offer.get('location') or {}).get('verification')=='user_confirmed_place':
                raise geo.PolicyError('La ubicación fue confirmada manualmente y requiere postulación supervisada.')
            if (offer['title'].casefold() not in [s.casefold() for s in scope['titles']] or
                offer['mode'] not in scope['modes'] or offer['source'] not in scope['sources'] or
                offer.get('company','').casefold() in [s.casefold() for s in scope['excluded_companies']]):
                raise geo.PolicyError('La oferta está fuera del alcance.')
            offer_country = (offer.get('location') or {}).get('country')
            if offer['mode'] == 'remote': offer_country = state['location']['country']
            if offer_country not in scope['countries']:
                raise geo.PolicyError('País fuera de la autorización automática.')
            salary = offer.get('salary')
            if (not isinstance(salary,dict) or salary.get('currency') != scope['currency'] or
                salary.get('period') != 'month'):
                raise geo.PolicyError('Salario mensual o moneda sin verificar.')
            salary_min = geo.number(salary.get('minimum'),0,100000000,'Salario')
            if salary_min < scope['minimum_salary']:
                raise geo.PolicyError('Salario inferior al autorizado.')
            score = geo.compatibility(profile,offer).get('score')
            if score is None or score < scope['minimum_score']:
                raise geo.PolicyError('Compatibilidad insuficiente o sin verificar.')
            if offer.get('sensitive_questions') is not False or offer.get('captcha') is not False or offer.get('mfa') is not False:
                raise geo.PolicyError('Se requiere intervención humana para revisar el formulario.')
            if scope['use_cover_letter']:
                raise geo.PolicyError('Carta pendiente de generación y validación; intervención requerida.')
            applications = state['applications']
            if any(item['offer_id'] == offer_id and item['status'] != 'CANCELADA' for item in applications.values()):
                raise geo.PolicyError('Candidatura duplicada.')
            if len(applications) >= 100: raise geo.PolicyError('Historial de simulaciones lleno.')
            today = local.date().isoformat()
            if sum(item.get('automatic_date') == today for item in applications.values()) >= scope['daily_limit']:
                raise geo.PolicyError('Límite diario alcanzado.')
            item = {'id':str(uuid4()),'offer_id':offer_id,'status':'PREPARADA',
                'simulation':True,'automatic_date':today,'authorization_id':scope['id'],
                'location_revision':state['revision'],'created_at':now.isoformat(),
                'result':'SIMULACIÓN AUTOMÁTICA VALIDADA. No se realizó envío.'}
            applications[item['id']] = item
            return item
        return self.mutate(uid,validate)


def register_routes(core, service=None):
    # Lazy factory: import/registration never loads ADC or touches the cloud.
    def existing_store():
        import job_runtime
        return job_runtime.JobStore()
    if service is None:
        from employment_live import live_service
        service=live_service(existing_store)

    def identity():
        if os.environ.get('CV_EMPLOYMENT_ENABLED') != '1':
            raise core.AppError('Empleo Inteligente todavía no está habilitado.', 503)
        identity = getattr(g, 'google_identity', None)
        # Even local auth-disabled mode must never expose employment accounts.
        if not identity or not identity.get('uid'):
            raise core.AppError('Inicia sesión para usar Empleo Inteligente.', 401)
        return identity['uid']

    def run(operation):
        uid = identity()
        try:
            return core.jsonify(operation(uid))
        except geo.PolicyError as error:
            raise core.AppError(str(error), 400) from error
        except core.AppError:
            raise
        except Exception as error:
            # Do not leak SDK errors, coordinates, identifiers or credentials.
            raise core.AppError('No se pudo completar la operación. Recarga antes de reintentar.', 503) from error

    def verified_profile(required=False):
        if getattr(core,'bank_enabled',lambda:False)():
            if not required and getattr(core.account_state,'BANK_CLIENT',None) is None:
                return core.account_state.MASTER_PROFILE
            status = core.load_drive_bank()
            if status.get('pending'):
                raise geo.PolicyError('Sincroniza el banco antes de evaluar compatibilidad.')
        return core.account_state.MASTER_PROFILE

    @core.app.get('/api/employment/location')
    def get_location():
        return run(lambda uid: {'location': service.read(uid)[0]['location']})

    @core.app.put('/api/employment/location')
    def put_location():
        return run(lambda uid: service.save_location(uid, core.request.get_json(silent=True)))

    @core.app.delete('/api/employment/location')
    def delete_location():
        return run(service.delete_location)

    @core.app.post('/api/employment/reverse-geocode')
    def reverse_geocode():
        def operation(uid):
            payload = core.request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) != {'lat', 'lng'}:
                raise geo.PolicyError('Coordenadas inválidas.')
            lat = round(geo.number(payload['lat'], -90, 90, 'Latitud'), 4)
            lng = round(geo.number(payload['lng'], -180, 180, 'Longitud'), 4)
            if service.geocoder is None or not hasattr(service.geocoder, 'reverse'):
                raise geo.PolicyError('No se pudo identificar el país. Reintenta más tarde.')
            cache_key = hashlib.sha256(f'reverse:{lat}:{lng}'.encode()).hexdigest()
            state, _ = service.read(uid)
            cached = state.get('geocode_cache', {}).get(cache_key)
            if cached:
                return {'results': cached}
            if len(state.get('geocode_cache', {})) >= 20:
                raise geo.PolicyError('Límite de localizaciones alcanzado. Elimina la ubicación guardada para limpiar la caché.')
            results = service.geocoder.reverse(lat, lng)
            if not results:
                raise geo.PolicyError('No se pudo identificar el país de este punto. Reintenta o corrige el marcador.')
            def save(current):
                current.setdefault('geocode_cache', {})[cache_key] = results
            service.mutate(uid, save)
            return {'results': results}
        return run(operation)

    @core.app.post('/api/employment/geocode')
    def geocode():
        def operation(uid):
            payload = core.request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) != {'country', 'address'}:
                raise geo.PolicyError('Dirección inválida.')
            c = geo.country(payload['country'])
            address = geo.text(payload['address'], 300)
            if len(address) < 3:
                raise geo.PolicyError('Escribe una dirección completa.')
            if service.geocoder is None:
                raise geo.PolicyError('Geocodificación pendiente de configurar. Corrige las coordenadas manualmente.')
            # No URL from client; reviewed adapter must implement timeout/cache/rate limit.
            cache_key=hashlib.sha256((c+address.casefold()).encode()).hexdigest()
            state,_=service.read(uid)
            cached=state.get('geocode_cache',{}).get(cache_key)
            if cached: return {'results':cached}
            if len(state.get('geocode_cache',{}))>=20:
                raise geo.PolicyError('Límite de localizaciones alcanzado. Elimina la ubicación guardada para limpiar la caché.')
            results=service.geocoder.search(c,address)
            def save(current): current.setdefault('geocode_cache',{})[cache_key]=results
            service.mutate(uid,save)
            return {'results':results}
        return run(operation)

    @core.app.post('/api/employment/search')
    def search():
        def operation(uid):
            payload = core.request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload)-{'query','source','latest'} or 'query' not in payload:
                raise geo.PolicyError('Búsqueda inválida.')
            source=payload.get('source','rd')
            if source != 'rd': raise geo.PolicyError('Selecciona una fuente de empleos de República Dominicana.')
            return service.search(uid,payload['query'],{},source,payload.get('latest',False))
        return run(operation)

    @core.app.post('/api/employment/offers/<offer_id>/places')
    def offer_places(offer_id):
        def operation(uid):
            payload=core.request.get_json(silent=True)
            if not isinstance(payload,dict) or set(payload)!={'place'}: raise geo.PolicyError('Lugar inválido.')
            return service.offer_places(uid,offer_id,payload['place'])
        return run(operation)

    @core.app.get('/api/employment/offers/<offer_id>/details')
    def offer_detail(offer_id):
        return run(lambda uid:service.offer_detail(uid,offer_id))

    @core.app.post('/api/employment/offers/<offer_id>/location')
    def confirm_offer_place(offer_id):
        def operation(uid):
            payload=core.request.get_json(silent=True)
            if not isinstance(payload,dict) or set(payload)!={'index','confirmed'}: raise geo.PolicyError('Confirmación inválida.')
            return service.confirm_offer_place(uid,offer_id,payload['index'],payload['confirmed'])
        return run(operation)

    @core.app.post('/api/employment/applications')
    def prepare():
        def operation(uid):
            payload = core.request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload)-{'offer_id','reviewed_no_travel'} or not isinstance(payload.get('offer_id'), str):
                raise geo.PolicyError('Selección inválida.')
            return service.prepare(uid,payload['offer_id'],payload.get('reviewed_no_travel') is True)
        return run(operation)

    @core.app.get('/api/employment/applications')
    def applications():
        return run(lambda uid: {'applications': list(service.read(uid)[0]['applications'].values())})

    @core.app.post('/api/employment/applications/<application_id>/simulate')
    def simulate(application_id):
        def operation(uid):
            payload = core.request.get_json(silent=True)
            if not isinstance(payload,dict) or set(payload) != {'confirmed'}:
                raise geo.PolicyError('Confirmación inválida.')
            return service.approve_simulation(uid,application_id,payload['confirmed'])
        return run(operation)

    @core.app.post('/api/employment/applications/<application_id>/open-official')
    def open_official(application_id):
        def operation(uid):
            payload=core.request.get_json(silent=True)
            if not isinstance(payload,dict) or set(payload)!={'confirmed'}: raise geo.PolicyError('Confirmación inválida.')
            return service.open_official(uid,application_id,payload['confirmed'])
        return run(operation)

    @core.app.post('/api/employment/applications/<application_id>/cancel')
    def cancel(application_id):
        return run(lambda uid: service.cancel(uid, application_id))

    @core.app.delete('/api/employment/authorization')
    def revoke():
        return run(service.revoke)

    @core.app.put('/api/employment/authorization')
    def authorize():
        return run(lambda uid: service.authorize_simulation(uid,core.request.get_json(silent=True)))

    @core.app.get('/api/employment/authorization')
    def authorization_status():
        return run(lambda uid: {'authorization': service.read(uid)[0]['authorization']})

    @core.app.post('/api/employment/automatic-simulation')
    def automatic():
        def operation(uid):
            payload = core.request.get_json(silent=True)
            if not isinstance(payload,dict) or set(payload) != {'offer_id'} or not isinstance(payload['offer_id'],str):
                raise geo.PolicyError('Selección inválida.')
            return service.auto_simulation(uid,payload['offer_id'],verified_profile(required=True))
        return run(operation)

    return service
