"""Official, public Greenhouse board reader; inactive until explicitly injected.

No credentials, cookies, scraping, application endpoints or private coordinates.
Reading a posting never establishes that its location or form is verified.
"""
import json
import re
from html.parser import HTMLParser
import requests
from employment_geo import PolicyError


class PlainText(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.blocked=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.blocked+=1
        if tag in ('p','br','li','div'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style') and self.blocked: self.blocked-=1
    def handle_data(self,data):
        if not self.blocked: self.parts.append(data)


class GreenhouseProvider:
    def __init__(self,boards,session=None):
        if not isinstance(boards,list) or not 1 <= len(boards) <= 5:
            raise PolicyError('Autoriza entre una y cinco bolsas oficiales.')
        if any(not isinstance(board,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',board) for board in boards):
            raise PolicyError('Identificador de bolsa inválido.')
        self.boards=list(dict.fromkeys(boards))
        self.session=session or requests.Session()

    def search(self,query,location):
        offers=[]
        for board in self.boards:
            url=f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true'
            with self.session.get(url,timeout=(3,10),allow_redirects=False,stream=True) as response:
                if response.status_code != 200:
                    raise PolicyError('La bolsa oficial no está disponible; no se usan datos inventados.')
                chunks=[]; size=0
                for chunk in response.iter_content(16384):
                    size+=len(chunk)
                    if size > 2000000: raise PolicyError('La respuesta supera el límite permitido.')
                    chunks.append(chunk)
                data=json.loads(b''.join(chunks))
            jobs=data.get('jobs')
            if not isinstance(jobs,list): raise PolicyError('Respuesta oficial inválida.')
            for job in jobs:
                if not isinstance(job,dict): continue
                title=job.get('title','')
                if not isinstance(title,str) or query.casefold() not in title.casefold(): continue
                parser=PlainText(); parser.feed(job.get('content') or '')
                description=''.join(parser.parts).strip()[:40000]
                offers.append({'title':title[:160],'company':board,'source':f'greenhouse:{board}',
                    'url':job.get('absolute_url',''),'description':description,
                    'location_text':(job.get('location') or {}).get('name',''),
                    'mode':'unknown','location':None,'suspicious':False,
                    'requires_travel':None,'required_skills':[],
                    'updated_at':job.get('updated_at'), 'source_job_id':str(job.get('id','')),
                    'sensitive_questions':None,'captcha':None,'mfa':None})
                if len(offers)>=200: return offers
        return offers
