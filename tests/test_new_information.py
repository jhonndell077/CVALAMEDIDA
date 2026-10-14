import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import app
from drive_bank import DriveBank, BankError

class NewInformationTests(unittest.TestCase):
    def test_profile_read_bypasses_recent_server_snapshot(self):
        original=copy.deepcopy(app.MASTER_PROFILE)
        updated=copy.deepcopy(original)
        section,record=app.new_information_record(self.payload())
        updated[section].append(record)
        bank=MagicMock()
        bank.load.return_value=(updated,{'pending':0},b'')
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'0'}), patch.object(app,'bank_enabled',return_value=True), patch.object(app,'BANK_CLIENT',bank), patch.object(app,'MASTER_PROFILE',original), patch.object(app,'BANK_READ_STATUS',{'pending':0}), patch.object(app,'BANK_READ_AT',time.monotonic()):
            response=app.app.test_client().get('/api/profile')
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['courses'][-1]['id'],record['id'])
            bank.load.assert_called_once()
        app.refresh_profile_indexes()

    def test_drive_add_delete_and_next_profile_share_persisted_state(self):
        from profile_deletions import apply_deletions
        base=copy.deepcopy(app.MASTER_PROFILE)
        class Bank:
            def load(self,process=False):return apply_deletions(base),{'pending':0},b''
            def add_record(self,section,record,validator):
                base[section].append(copy.deepcopy(record));validator(base)
            def delete_record(self,selector):base.setdefault('_deleted_records',[]).append(selector)
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'0'}), patch.object(app,'bank_enabled',return_value=True), patch.object(app,'BANK_CLIENT',Bank()), patch.object(app,'MASTER_PROFILE',copy.deepcopy(base)), patch.object(app,'BANK_READ_STATUS',None), patch.object(app,'BANK_READ_AT',0):
            client=app.app.test_client()
            response=client.post('/api/profile/information',json=self.payload())
            self.assertEqual(response.status_code,200,response.json)
            profile=response.json['profile'];record=profile['courses'][-1]
            self.assertEqual(client.get('/api/profile').json['courses'][-1],record)
            response=client.post('/api/profile/delete',json={'path':['courses',len(profile['courses'])-1],'expected':record})
            self.assertEqual(response.status_code,200,response.json)
            self.assertNotIn(record,response.json['profile']['courses'])
            self.assertNotIn(record,client.get('/api/profile').json['courses'])
            self.assertIn(record,base['courses'])
            self.assertTrue(base['_deleted_records'])
        app.refresh_profile_indexes()

    def test_reference_fields_are_validated_and_preserved(self):
        payload = {'type': 'references', 'request_id': 'b' * 32,
                   'fields': {'name': 'Referencia de prueba', 'role': 'Supervisora', 'phone': '809-555-0100'}}
        section, record = app.new_information_record(payload)
        self.assertEqual(section, 'references')
        self.assertEqual(record['name'], payload['fields']['name'])
        self.assertNotIn('title', record)
        profile = copy.deepcopy(app.MASTER_PROFILE)
        profile['references'].append(record)
        app.validate_profile(profile)
        from test_app import valid_analysis
        with patch.object(app, 'MASTER_PROFILE', profile):
            self.assertIn(record, app.make_draft(valid_analysis())['references'])
        for field in ('name', 'role', 'phone'):
            invalid = copy.deepcopy(payload)
            invalid['fields'][field] = ' '
            with self.subTest(field=field), self.assertRaises(app.AppError):
                app.new_information_record(invalid)

    def payload(self, kind='courses', **fields):
        return {'type':kind, 'request_id':'a'*32, 'fields':{'title':'Curso nuevo', 'institution':'Instituto', **fields}}

    def test_local_persists_and_retry_does_not_duplicate(self):
        original = copy.deepcopy(app.MASTER_PROFILE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'profile.json'
            path.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(app, 'PROFILE_PATH', path), patch.dict(os.environ, {'CV_BANK_PROVIDER':'local', 'CV_AUTH_REQUIRED':'0', 'CV_ALLOW_REMOTE':'0'}):
                try:
                    client = app.app.test_client()
                    for _ in range(2):
                        response = client.post('/api/profile/information', json=self.payload())
                        self.assertEqual(response.status_code, 200, response.json)
                        self.assertEqual(response.json['profile']['courses'][-1]['id'], response.json['record_id'])
                    saved = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(len(saved['courses']), len(original['courses'])+1)
                    self.assertEqual(saved['experiences'], original['experiences'])
                    self.assertEqual(app.MASTER_PROFILE['courses'][-1]['institution'], 'Instituto')
                finally:
                    app.MASTER_PROFILE = original
                    app.refresh_profile_indexes()

    def test_required_functions_and_unsafe_url_rejected(self):
        with self.assertRaises(app.AppError):
            app.new_information_record(self.payload('experiences', employer='Empresa', category='Cocina'))
        with self.assertRaises(app.AppError):
            app.new_information_record(self.payload('projects', description='Proyecto', url='javascript:alert(1)'))
        for kind in ('education', 'projects', 'experiences'):
            section, record = app.new_information_record(self.payload(kind, employer='Empresa', category='Cocina', responsibilities='Función uno\nFunción dos', description='Mi proyecto'))
            self.assertEqual(section, kind)
            self.assertTrue(record['id'].startswith('manual-'))

    def test_drive_write_preserves_base_and_verifies_retry(self):
        base = copy.deepcopy(app.MASTER_PROFILE)
        section, record = app.new_information_record(self.payload())
        bank = DriveBank({'base_file_id':'base'})
        bank.inventory = lambda: {'base':{'id':'base'}}
        response = MagicMock(content=json.dumps(base).encode(), headers={'ETag':'version-one'})
        written = []
        def request(method, url, **kwargs):
            if method == 'GET':
                response.content = json.dumps(base).encode()
                return response
            written.append(kwargs)
            base.update(json.loads(kwargs['data']))
            return MagicMock()
        bank.request = request
        bank.download = lambda file: (json.dumps(base).encode(), '', '')
        bank.add_record(section, record, app.validate_profile)
        bank.add_record(section, record, app.validate_profile)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]['headers']['If-Match'], 'version-one')
        self.assertEqual(base['courses'][-1], record)
        self.assertEqual(base['candidate'], app.MASTER_PROFILE['candidate'])

    def test_explicit_addition_restores_previously_deleted_record(self):
        from profile_deletions import deletion_for, apply_deletions
        base=copy.deepcopy(app.MASTER_PROFILE)
        section,record=app.new_information_record(self.payload())
        base[section].append(record)
        base['_deleted_records']=[deletion_for(base,[section,len(base[section])-1],record)]
        self.assertNotIn(record,apply_deletions(base)[section])
        bank=DriveBank({'base_file_id':'base'})
        bank.inventory=lambda:{'base':{'id':'base'}}
        writes=[]
        def request(method,url,**kwargs):
            if method=='PATCH':
                writes.append(kwargs);base.update(json.loads(kwargs['data']))
            return MagicMock(content=json.dumps(base).encode(),headers={'ETag':'v1'})
        bank.request=request;bank.download=lambda file:(json.dumps(base).encode(),'','')
        bank.add_record(section,record,app.validate_profile)
        self.assertIn(record,apply_deletions(base)[section])
        bank.add_record(section,record,app.validate_profile)
        self.assertEqual(len(writes),1)

    def test_remote_endpoint_requires_identity(self):
        with patch.dict(os.environ, {'CV_AUTH_REQUIRED':'1', 'CV_ALLOW_REMOTE':'1'}):
            response = app.app.test_client().post('/api/profile/information', json=self.payload())
            self.assertEqual(response.status_code, 401)
