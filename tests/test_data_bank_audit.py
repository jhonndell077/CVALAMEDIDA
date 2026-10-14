"""Audit all data sections using temporary files and simulated Drive only."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
from drive_bank import DriveBank, merge_profile


def fixture():
    return {
        'candidate': {'name': 'Persona de prueba', 'national_id': 'Prueba',
                      'address': 'Dirección de prueba', 'residence': 'Residencia de prueba',
                      'email': 'fixture@example.invalid', 'phones': ['8095550100'],
                      'photo': app.MASTER_PROFILE['candidate']['photo']},
        'experiences': [{'id': 'fixture-job', 'title': 'Asistente', 'employer': 'Empresa',
                         'category': 'oficina', 'responsibilities': [{'id': 'fixture-task', 'text': 'Organizar archivos'}]}],
        'skills': [{'id': 'fixture-skill', 'label': 'Organización', 'sources': ['oficina']}],
        'education': [{'id': 'fixture-study', 'title': 'Estudios de prueba', 'institution': 'Instituto'}],
        'courses': [{'id': 'fixture-course', 'title': 'Curso de prueba', 'institution': 'Instituto'}],
        'projects': [{'id': 'fixture-project', 'title': 'Proyecto de prueba', 'description': 'Archivo digital', 'technologies': ['Python'], 'url': ''}],
        'references': [{'name': 'Referencia de prueba', 'role': 'Supervisora', 'phone': '8095550101'}],
        'not_documented': ['Certificado pendiente de prueba'],
    }


class DataBankAuditTests(unittest.TestCase):
    def test_each_of_eight_sections_survives_local_save_and_reload(self):
        for section in fixture():
            with self.subTest(section=section), tempfile.TemporaryDirectory() as directory:
                original=fixture(); updated=copy.deepcopy(original)
                if section=='candidate': updated[section]['address']='Nueva dirección de prueba'
                elif section=='not_documented': updated[section].append('Nueva evidencia pendiente')
                else:
                    record=copy.deepcopy(updated[section][0])
                    if section=='skills': record.update(id='new-skill',label='Comunicación')
                    elif section=='references': record.update(name='Otra referencia',phone='8295550102')
                    else:
                        record.update(id='new-'+section,title='Nuevo registro '+section)
                        if section=='experiences': record['responsibilities']=[{'id':'new-task','text':'Atender consultas'}]
                    updated[section].append(record)
                path=Path(directory)/'profile.json';path.write_text(json.dumps(original),encoding='utf-8')
                with patch.dict(os.environ,{'CV_ALLOW_REMOTE':'0','CV_AUTH_REQUIRED':'0'}), patch.object(app,'bank_enabled',return_value=False), patch.object(app,'PROFILE_PATH',path), patch.object(app,'MASTER_PROFILE',original):
                    client=app.app.test_client(); response=client.put('/api/profile',json=updated)
                    self.assertEqual(response.status_code,200,response.json)
                    persisted=json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(persisted,updated)
                    self.assertEqual(client.get('/api/profile').json,updated)
                    self.assertEqual(merge_profile(persisted,{})[0][section],updated[section])
                app.refresh_profile_indexes()

    def test_each_supported_web_addition_reaches_drive_and_survives_merge(self):
        for index,section in enumerate(('experiences','education','courses','projects','references')):
            with self.subTest(section=section):
                base=fixture()
                fields={'title':'Nuevo registro de prueba','employer':'Nueva empresa','category':'oficina',
                        'institution':'Nuevo instituto','responsibilities':['Atender consultas'],
                        'description':'Proyecto nuevo','technologies':['Python'],'url':'',
                        'name':'Nueva referencia','role':'Gerente','phone':'8295550102'}
                _,record=app.new_information_record({'type':section,'request_id':format(index+1,'032x'),'fields':fields})
                bank=DriveBank({'base_file_id':'base'}); bank.inventory=lambda:{'base':{'id':'base'}}
                writes=[]
                def request(method,url,**kwargs):
                    if method=='PATCH': writes.append(kwargs);base.update(json.loads(kwargs['data']))
                    return MagicMock(content=json.dumps(base).encode(),headers={'ETag':'fixture-v1'})
                bank.request=request;bank.download=lambda file:(json.dumps(base).encode(),'','')
                for _ in range(2): self.assertEqual(bank.add_record(section,record,app.validate_profile),record['id'])
                self.assertEqual(len(writes),1)
                rebuilt,_=merge_profile(base,{})
                self.assertTrue(any(item.get('id')==record['id'] for item in rebuilt[section]))

    def test_web_full_profile_requires_version_for_safe_save(self):
        for section in ('candidate','skills','not_documented'):
            with self.subTest(section=section), self.assertRaises(app.AppError):
                app.new_information_record({'type':section,'request_id':'a'*32,'fields':{}})
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'1'}), patch.object(app,'bank_enabled',return_value=True), patch.object(app,'load_drive_bank',return_value={'pending':0}), patch.object(app,'save_master_profile') as save:
            response=app.app.test_client().put('/api/profile',json=fixture())
            self.assertEqual(response.status_code,400)
            save.assert_not_called()

    def test_web_edits_all_sections_and_keeps_changes_after_document_sync(self):
        from profile_edits import apply
        base=fixture();previous=copy.deepcopy(base);updated=copy.deepcopy(base)
        updated['candidate']['address']='Dirección corregida'
        updated['skills'][0]['label']='Comunicación'
        updated['not_documented'][0]='Pendiente corregido'
        for section in ('experiences','courses','education','projects'): updated[section][0]['title']='Corregido '+section
        updated['references'][0]['role']='Gerente'
        bank=DriveBank({'base_file_id':'base'})
        writes=[]
        def request(method,url,**kwargs):
            if method=='PATCH': writes.append(kwargs);base.update(json.loads(kwargs['data']))
            return MagicMock(content=json.dumps(base).encode(),headers={'ETag':'fixture-v1'},json=lambda:copy.deepcopy(base))
        bank.request=request
        bank.load=lambda process=False:(apply(copy.deepcopy(base)),{'pending':0},b'')
        with patch.dict(os.environ,{'CV_ALLOW_REMOTE':'0','CV_AUTH_REQUIRED':'0'}),patch.object(app,'bank_enabled',return_value=True),patch.object(app,'BANK_CLIENT',bank),patch.object(app,'MASTER_PROFILE',previous):
            client=app.app.test_client()
            response=client.put('/api/profile',json={'profile':updated,'expected_profile':previous})
            self.assertEqual(response.status_code,200,response.json)
            for section in updated:self.assertEqual(response.json['profile'][section],updated[section])
            self.assertEqual(client.put('/api/profile',json={'profile':previous,'expected_profile':previous}).status_code,409)
        app.refresh_profile_indexes()
        self.assertEqual(len(writes),1)
        reimported=copy.deepcopy(previous)
        reimported.update({key:value for key,value in base.items() if key.startswith('_')})
        for section in updated:self.assertEqual(apply(reimported)[section],updated[section])
