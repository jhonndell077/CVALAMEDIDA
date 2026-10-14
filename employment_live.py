"""Explicitly selected public services. No portal credentials or submissions."""
import hashlib
import json
import math
import time
from datetime import datetime, timezone
import requests
from employment_geo import PolicyError, distance_m
from employment_providers import PlainText

USER_AGENT = 'CVaLaMedida/1.0 (+https://cvalamedida.web.app)'


def public_json(url, params):
    with requests.get(url, params=params, headers={'User-Agent': USER_AGENT},
                      timeout=(4,18), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise PolicyError('La fuente externa no está disponible. Reintenta más tarde.')
        chunks=[]; length=0
        for chunk in response.iter_content(16384):
            length += len(chunk)
            if length > 2000000: raise PolicyError('La respuesta externa superó el tamaño permitido.')
            chunks.append(chunk)
        return json.loads(b''.join(chunks))


def timestamp(value):
    try:
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            return datetime.fromtimestamp(value / 1000 if value > 1e12 else value,timezone.utc).isoformat()
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        return date.isoformat() if date.tzinfo else None
    except (ValueError,TypeError,AttributeError,OverflowError): return None


class Himalayas:
    def __init__(self,store_factory,fetch=public_json): self.store_factory=store_factory; self.fetch=fetch
    def search(self,query,location):
        # Identical public searches are cached across users for 24 h. No coordinates leave the server.
        params={'q':query,'country':location['country'],'page':1}
        identifier='employment-public-'+hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
        store=self.store_factory(); cached,generation=store.read(identifier)
        if cached and time.time()-cached.get('at',0)<86400: data=cached['data']
        else:
            budget,version=store.read('employment-provider-budget'); today=datetime.now(timezone.utc).date().isoformat()
            count=budget.get('count',0) if budget and budget.get('date')==today else 0
            if count>=100: raise PolicyError('La fuente alcanzó el límite diario de consultas. Reintenta mañana.')
            store.write('employment-provider-budget',{'date':today,'count':count+1},version)
            data=self.fetch('https://himalayas.app/jobs/api/search',params)
            if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):
                raise PolicyError('La fuente devolvió una respuesta inválida.')
            store.write(identifier,{'at':time.time(),'data':data},generation)
        offers=[]
        for job in data['jobs'][:20]:
            if not isinstance(job,dict): continue
            if not isinstance(job.get('title'),str) or not isinstance(job.get('companyName',''),str): continue
            if not isinstance(job.get('description') or job.get('excerpt') or '',str): continue
            restrictions=job.get('locationRestrictions')
            countries=[]
            if isinstance(restrictions,list):
                for item in restrictions:
                    code=item.get('alpha2') if isinstance(item,dict) else item
                    if isinstance(code,str) and len(code)==2: countries.append(code.upper())
            parser=PlainText(); parser.feed(job.get('description') or job.get('excerpt') or '')
            url=job.get('applicationLink','')
            if not isinstance(url,str) or not url.startswith('https://himalayas.app/'): continue
            salary=None
            if isinstance(job.get('minSalary'),(int,float)) and not isinstance(job['minSalary'],bool):
                period={'monthly':'month','annual':'year','hourly':'hour','weekly':'week'}.get(job.get('salaryPeriod'))
                salary={'minimum':job['minSalary'],'maximum':job.get('maxSalary'),'currency':job.get('currency'),'period':period}
            offsets=job.get('timezoneRestrictions')
            offers.append({'title':job.get('title','')[:160],'company':job.get('companyName','')[:160],
                'description':''.join(parser.parts).strip()[:40000],'source':'Himalayas','url':url,
                'mode':'remote','location':None,'remote_countries':countries,
                'remote_worldwide':isinstance(restrictions,list) and not restrictions,
                'timezone_restrictions':offsets if isinstance(offsets,list) else None,
                'requires_travel':None,'suspicious':False,'required_skills':[],
                'salary':salary,'employment_type':job.get('employmentType'),
                'published_at':timestamp(job.get('pubDate')),'expires_at':timestamp(job.get('expiryDate')),
                'sensitive_questions':None,'captcha':None,'mfa':None})
        return offers


class Nominatim:
    def __init__(self,store_factory,fetch=public_json): self.store_factory=store_factory; self.fetch=fetch

    def _request(self,path,params):
        # Shared Storage CAS reservation enforces the public service's aggregate 1 req/s limit.
        store=self.store_factory(); gate,generation=store.read('employment-geocode-rate')
        now=time.time()
        if gate and now-gate.get('at',0)<1.1:
            raise PolicyError('Espera dos segundos antes de localizar otra dirección.')
        today=datetime.now(timezone.utc).date().isoformat()
        count=gate.get('count',0) if gate and gate.get('date')==today else 0
        if count>=100: raise PolicyError('El proveedor de mapas alcanzó el límite diario de consultas.')
        store.write('employment-geocode-rate',{'at':now,'date':today,'count':count+1},generation)
        return self.fetch('https://nominatim.openstreetmap.org/'+path,params)

    def _normalize(self,item):
        address=item.get('address') or {}
        code=(address.get('country_code') or '').upper()
        if len(code)!=2: return None
        try:
            lat=float(item['lat']); lng=float(item['lon'])
            bounds=[float(x) for x in item['boundingbox']]
            accuracy=math.ceil(max(distance_m({'lat':lat,'lng':lng},{'lat':a,'lng':b})
                for a in bounds[:2] for b in bounds[2:]))
        except (KeyError,ValueError,TypeError): return None
        return {'label':str(item.get('display_name',''))[:500],'lat':round(lat,4),'lng':round(lng,4),
            'accuracy_m':max(20,min(100000,accuracy)), 'country':code,
            'region':str(address.get('state') or address.get('province') or '')[:160],
            'city':str(address.get('city') or address.get('town') or address.get('municipality') or address.get('village') or '')[:160]}

    def search(self,country,address):
        data=self._request('search',{'q':address,'countrycodes':country.lower(),'format':'jsonv2',
                                     'addressdetails':1,'limit':5})
        if not isinstance(data,list): raise PolicyError('Respuesta de mapa inválida.')
        return [result for item in data if isinstance(item,dict)
                and (result:=self._normalize(item)) and result['country']==country]

    def reverse(self,lat,lng):
        # Used only after the separate user action disclosing coordinates to this provider.
        data=self._request('reverse',{'lat':round(lat,4),'lon':round(lng,4),'format':'jsonv2','addressdetails':1})
        result=self._normalize(data) if isinstance(data,dict) else None
        return [result] if result else []


def live_service(store_factory):
    from employment_service import Employment
    from employment_hiringcafe import Sources
    return Employment(store_factory,Sources(store_factory),Nominatim(store_factory))
