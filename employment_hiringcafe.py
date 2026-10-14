"""Public, interactive MCP search. Fixed read-only tools, no authentication or apply calls."""
import hashlib
import json
import time
from datetime import datetime, timezone
import requests
from employment_geo import PolicyError
from employment_live import USER_AGENT, timestamp

COUNTRY_NAMES={'DO':'Dominican Republic','US':'United States','CA':'Canada','GB':'United Kingdom',
    'ES':'Spain','MX':'Mexico','CO':'Colombia','AR':'Argentina','CL':'Chile','PE':'Peru',
    'BR':'Brazil','DE':'Germany','FR':'France','IT':'Italy','NL':'Netherlands','AU':'Australia',
    'NZ':'New Zealand','IN':'India','JP':'Japan','ZA':'South Africa','CR':'Costa Rica','PA':'Panama'}


def mcp_call(name,arguments):
    if name not in ('search_hiringcafe_jobs','get_hiringcafe_job_details'):
        raise PolicyError('Operación de fuente no permitida.')
    with requests.post('https://hiringcafe.com/api/chatgpt/mcp',headers={
        'Content-Type':'application/json','Accept':'application/json, text/event-stream','User-Agent':USER_AGENT},
        json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments}},
        timeout=(4,20),allow_redirects=False,stream=True) as response:
        if response.status_code!=200: raise PolicyError('HiringCafe no está disponible; reintenta más tarde.')
        chunks=[]; total=0
        for chunk in response.iter_content(16384):
            total+=len(chunk)
            if total>2000000: raise PolicyError('La respuesta superó el límite de tamaño.')
            chunks.append(chunk)
        data=json.loads(b''.join(chunks))
    result=data.get('result',{})
    if data.get('error') or result.get('isError'): raise PolicyError('La fuente no pudo completar la búsqueda.')
    content=result.get('structuredContent')
    if not isinstance(content,dict): raise PolicyError('La fuente no devolvió datos estructurados verificables.')
    return content


class HiringCafe:
    def __init__(self,store_factory,call=mcp_call): self.store_factory=store_factory; self.call=call
    def search(self,query,location):
        country=COUNTRY_NAMES.get(location['country'])
        if not country: raise PolicyError('País no configurado para esta fuente. Puedes usar la búsqueda remota.')
        arguments={'search':query,'location':location['city']+', '+country,
            'workplace_types':['Onsite','Hybrid'],
            # Overfetch around the municipality; only our confirmed point determines the final radius.
            'radius_miles':max(50,location['radius_m']/1609.344+20), 'posted_within_days':30,'limit':10}
        store=self.store_factory()
        identifier='employment-hiringcafe-'+hashlib.sha256(json.dumps(arguments,sort_keys=True).encode()).hexdigest()
        cached,generation=store.read(identifier)
        if cached and time.time()-cached.get('at',0)<3600: data=cached['data']
        else:
            budget,version=store.read('employment-provider-budget'); today=datetime.now(timezone.utc).date().isoformat()
            count=budget.get('count',0) if budget and budget.get('date')==today else 0
            if count>=100: raise PolicyError('Límite diario de consultas alcanzado.')
            store.write('employment-provider-budget',{'date':today,'count':count+1},version)
            data=self.call('search_hiringcafe_jobs',arguments)
            if not isinstance(data.get('jobs'),list): raise PolicyError('Respuesta de búsqueda inválida.')
            store.write(identifier,{'at':time.time(),'data':data},generation)
        offers=[]
        reverse={value.casefold():code for code,value in COUNTRY_NAMES.items()}
        for job in data['jobs'][:10]:
            if not isinstance(job,dict): continue
            url=job.get('applyUrl','')
            if not isinstance(url,str) or not url.startswith('https://hiringcafe.com/job/'): continue
            place=job.get('location',''); country_code=reverse.get(place.split(',')[-1].strip().casefold()) if isinstance(place,str) else None
            summary=job.get('requirementsSummary') or ''
            if not isinstance(summary,str): summary=''
            if not all(isinstance(job.get(key),str) and job[key].strip() for key in ('title','company','id')): continue
            responsibilities=job.get('responsibilities') or []
            if not isinstance(responsibilities,list): responsibilities=[]
            text='\n'.join([summary,*[s for s in responsibilities if isinstance(s,str)]])[:40000]
            offers.append({'title':str(job.get('title',''))[:160],'company':str(job.get('company',''))[:160],
                'description':text,'source':'HiringCafe','url':url,'source_job_id':str(job.get('id','')),
                'source_country':country_code,'location_text':place,
                'mode':{'Onsite':'onsite','Hybrid':'hybrid'}.get(job.get('workplaceType'),'unknown'),
                'location':None,'requires_travel':None,'suspicious':False,
                'required_skills':[s for s in (job.get('technologies') or []) if isinstance(s,str)],
                'salary':None,'published_at':timestamp(job.get('datePosted')),'expires_at':None,
                'sensitive_questions':None,'captcha':None,'mfa':None})
        return offers

    def detail(self,identifier):
        if not isinstance(identifier,str) or not 1<=len(identifier)<=100: raise PolicyError('Identificador inválido.')
        store=self.store_factory(); key='employment-detail-'+hashlib.sha256(identifier.encode()).hexdigest()
        cached,generation=store.read(key)
        if cached and time.time()-cached.get('at',0)<3600: return cached['job']
        budget,version=store.read('employment-provider-budget'); today=datetime.now(timezone.utc).date().isoformat()
        count=budget.get('count',0) if budget and budget.get('date')==today else 0
        if count>=100: raise PolicyError('Límite diario de consultas alcanzado.')
        store.write('employment-provider-budget',{'date':today,'count':count+1},version)
        data=self.call('get_hiringcafe_job_details',{'job_id':identifier})
        job=data.get('job')
        if not isinstance(job,dict): raise PolicyError('No se pudo verificar el detalle.')
        store.write(key,{'at':time.time(),'job':job},generation)
        return job


class Sources:
    def __init__(self,store_factory):
        from employment_unified import UnifiedDominicanJobs
        self.sources={'rd':UnifiedDominicanJobs(store_factory)}
    def for_source(self,name):
        if name=='nearby': raise PolicyError('HiringCafe requiere permiso de redistribucion del proveedor. Consulta su portal original.')
        if name not in self.sources: raise PolicyError('Fuente no permitida.')
        return self.sources[name]
    def search(self,query,location): return self.sources['rd'].search(query,location)
