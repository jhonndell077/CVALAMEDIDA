"""Duplicate regressions using fictitious profiles and documents only."""
import copy
import unittest
import json
from unittest.mock import MagicMock
from profile_records import consolidate, add_information
from drive_bank import merge_profile, DriveBank

def blank():
    return {'candidate': {'name':'Persona de prueba','phones':[]}, 'projects':[],
            'experiences':[], 'education':[], 'courses':[], 'skills':[],
            'references':[], 'not_documented':[]}

def document(facts):
    return {'active':True,'status':'incorporado','name':'Fixture','fingerprint':'v1','facts':facts}

class ProfileRecordsTests(unittest.TestCase):
    def test_projects_merge_case_variants_without_losing_descriptions_or_technologies(self):
        base=blank();base['projects']=[{'id':'first','title':'Proyecto de prueba','description':'Descripción inicial','technologies':['Python'],'url':''},
            {'id':'second','title':'PROYECTO DE PRUEBA','description':'Detalles complementarios','technologies':['python','SQLite'],'url':''}]
        result=consolidate(base)
        self.assertEqual(len(result['projects']),1);self.assertEqual(result['projects'][0]['id'],'first')
        self.assertIn('Descripción inicial',result['projects'][0]['description'])
        self.assertIn('Detalles complementarios',result['projects'][0]['description'])
        self.assertEqual(result['projects'][0]['technologies'],['Python','SQLite'])
        self.assertEqual(len(base['projects']),2)
        self.assertEqual(consolidate(result),result)

    def test_repeat_add_with_new_request_id_returns_existing_record_for_all_manual_sections(self):
        examples={
            'projects':{'title':'Proyecto','description':'Proyecto documentado','technologies':[],'url':''},
            'courses':{'title':'Curso','institution':'Instituto','date':'2025'},
            'education':{'title':'Carrera','institution':'Universidad','date':'2025'},
            'experiences':{'title':'Camarero','employer':'Empresa de prueba','category':'Servicio','responsibilities':[{'id':'task-a','text':'Atender mesas'}]},
            'references':{'name':'Referencia de prueba','role':'Supervisora','phone':'8095550123'}}
        for section,record in examples.items():
            with self.subTest(section=section):
                profile=blank();record={**record,'id':'manual-'+'a'*32}
                first=add_information(profile,section,record)
                second=add_information(profile,section,{**record,'id':'manual-'+'b'*32})
                self.assertEqual(first,second);self.assertEqual(len(profile[section]),1)
                add_information(profile,section,{**record,'id':'manual-'+'b'*32})
                self.assertEqual(len(profile[section]),1)
                with self.assertRaises(ValueError):add_information(profile,section,{**record,'title':'Dato distinto'})

    def test_skills_references_phones_and_pending_texts_also_consolidate(self):
        profile=blank();profile['skills']=[{'id':'a','label':'SQL'},{'id':'b','label':'sql'},{'id':'c','label':'C++'},{'id':'d','label':'C#'}]
        profile['references']=[{'name':'Referencia','phone':'8095550123','role':'Supervisora'}, {'name':'REFERENCIA','phone':'+1 809-555-0123','role':'Gerente'}]
        profile['candidate']['phones']=['8095550123','+1 809-555-0123']
        profile['not_documented']=['Dato pendiente','DATO PENDIENTE']
        result=consolidate(profile)
        self.assertEqual(len(result['skills']),3);self.assertEqual(len(result['references']),1)
        self.assertIn('Gerente',result['references'][0]['role'])
        self.assertEqual(len(result['candidate']['phones']),1);self.assertEqual(len(result['not_documented']),1)

    def test_real_differences_are_not_merged(self):
        profile=blank()
        profile['projects']=[{'id':'a','title':'Portal','url':'https://one.example.invalid','description':'A'},
                             {'id':'b','title':'Portal','url':'https://two.example.invalid','description':'B'}]
        profile['experiences']=[{'id':str(i),'title':'Camarero','employer':employer,'start_date':date,'end_date':'','responsibilities':[]}
            for i,(employer,date) in enumerate([('Empresa A','2020'),('Empresa B','2020'),('Empresa A','2023')])]
        profile['courses']=[{'id':'a','title':'Curso','institution':'Instituto','date':'2020'}, {'id':'b','title':'Curso','institution':'Instituto','date':'2023'}]
        result=consolidate(profile)
        for section,count in [('projects',2),('experiences',3),('courses',2)]: self.assertEqual(len(result[section]),count)

    def test_documents_with_paraphrased_project_descriptions_merge_with_manual_record(self):
        profile=blank();profile['projects']=[{'id':'manual','title':'Proyecto','description':'Descripción manual','technologies':['Python'],'url':''}]
        docs={'a':document({'projects':[{'title':'PROYECTO','description':'Descripción A','technologies':['SQL'],'url':''}]}),
              'b':document({'projects':[{'title':'Proyecto','description':'Descripción B','technologies':['python'],'url':''}]})}
        result,_=merge_profile(profile,docs)
        self.assertEqual(len(result['projects']),1)
        self.assertEqual(len(result['projects'][0]['source_documents']),2)
        self.assertEqual(result['projects'][0]['technologies'],['Python','SQL'])
        for description in ('Descripción manual','Descripción A','Descripción B'): self.assertIn(description,result['projects'][0]['description'])
        self.assertEqual(merge_profile(profile,docs)[0],result)

    def test_imported_periods_and_skill_symbols_have_distinct_ids(self):
        facts={'experiences':[{'title':'Camarero','employer':'Empresa','category':'Servicio','start_date':year,'end_date':'','responsibilities':['Atender mesas']}
                              for year in ('2020','2023')], 'skills':['C++','C#']}
        result,_=merge_profile(blank(),{'fixture':document(facts)})
        self.assertEqual(len(result['experiences']),2)
        self.assertNotEqual(result['experiences'][0]['id'],result['experiences'][1]['id'])
        self.assertEqual(len(result['skills']),2)
        self.assertNotEqual(result['skills'][0]['id'],result['skills'][1]['id'])

    def test_drive_add_reuses_identity_and_retry_does_not_patch_again(self):
        base=blank();base['projects']=[{'id':'original','title':'Proyecto','description':'Primer detalle','technologies':[],'url':''}]
        bank=DriveBank({'base_file_id':'fixture'})
        bank.inventory=lambda:{'fixture':{'id':'fixture'}}
        writes=[]
        def request(method,url,**kwargs):
            if method=='PATCH':writes.append(kwargs);base.update(json.loads(kwargs['data']))
            return MagicMock(content=json.dumps(base).encode(),headers={'ETag':'fixture-version'})
        bank.request=request;bank.download=lambda _:(json.dumps(base).encode(),'','')
        incoming={'id':'manual-'+'a'*32,'title':'PROYECTO','description':'Segundo detalle','technologies':['Python'],'url':''}
        self.assertEqual(bank.add_record('projects',incoming,lambda _:None),'original')
        self.assertEqual(bank.add_record('projects',incoming,lambda _:None),'original')
        self.assertEqual(len(writes),1);self.assertEqual(writes[0]['headers']['If-Match'],'fixture-version')
        self.assertEqual(len(base['projects']),1);self.assertIn('Segundo detalle',base['projects'][0]['description'])

    def test_consolidation_preserves_prior_deletions_of_equivalent_records(self):
        from profile_deletions import deletion_for, apply_deletions
        profile=blank();profile['projects']=[{'id':'a','title':'Proyecto de prueba','description':'Primero','url':''},
                                           {'id':'b','title':'Proyecto  de prueba','description':'Segundo','url':''}]
        profile['_deleted_records']=[deletion_for(profile,['projects',1],profile['projects'][1])]
        self.assertEqual(apply_deletions(consolidate(profile))['projects'],[])

if __name__=='__main__':unittest.main()
