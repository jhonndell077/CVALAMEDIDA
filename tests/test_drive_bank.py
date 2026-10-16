import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drive_bank import DriveBank, BankError, clean_facts, merge_profile, fingerprint, extraction_input
import app as cv_app

BASE = json.loads((Path(__file__).resolve().parents[1] / 'data/master_profile.json').read_text(encoding='utf-8'))
CONFIG = {'folder_id': 'bank', 'base_file_id': 'base', 'index_file_id': 'index', 'photo_file_id': 'photo', 'readme_file_id': 'readme'}

def cert(title='Certificado de prueba'):
    return clean_facts({'recipient': BASE['candidate']['name'], 'courses': [{'title': title, 'institution': 'Institución de prueba', 'date': '2026'}]})

class MemoryBank(DriveBank):
    def __init__(self, files, contents, extractor=None):
        super().__init__(CONFIG, extractor=extractor or (lambda *args: cert()))
        self.files = files
        self.contents = contents
        self.writes = []
    def inventory(self):
        return self.files
    def download(self, file):
        return self.contents[file['id']], file['name'], file['mimeType']
    def request(self, method, url, **kwargs):
        file_id = urlsplit(url).path.rsplit('/', 1)[-1]
        if method == 'GET' and 'fields=etag' in url:
            return MagicMock(json=lambda: {'etag': 'fixture-version'})
        if method == 'GET':
            return MagicMock(content=self.contents[file_id])
        self.writes.append((method, url))
        self.contents[file_id] = kwargs['data']
        return MagicMock()

def memory():
    files = {i: {'id': i, 'name': i, 'mimeType': 'text/plain', 'md5Checksum': 'v1'} for i in ('base', 'index', 'photo', 'readme', 'certificate')}
    output = io.BytesIO()
    Image.new('RGB', (3, 4)).save(output, format='JPEG')
    contents = {'base': json.dumps(BASE).encode(), 'index': b'{"version":1,"documents":{}}', 'photo': output.getvalue(), 'certificate': b'certificate'}
    files['photo'].update({'name': 'hoja_de_vida.jpeg', 'mimeType': 'image/jpeg', 'parents': ['bank']})
    return files, contents

class DriveBankTests(unittest.TestCase):
    def test_download_cache_reuses_unchanged_files_but_never_caches_index(self):
        bank = DriveBank(CONFIG)
        file = {'id': 'document', 'name': 'perfil.json', 'mimeType': 'application/json', 'md5Checksum': 'v1'}
        with patch.object(bank, '_download', return_value=(b'content', 'perfil.json', 'application/json')) as download:
            bank.download(file); bank.download(file)
            self.assertEqual(download.call_count, 1)
            bank.download({**file, 'md5Checksum': 'v2'})
            self.assertEqual(download.call_count, 2)
            bank.download({**file, 'id': 'index'}); bank.download({**file, 'id': 'index'})
            self.assertEqual(download.call_count, 4)

    def test_master_profile_is_fresh_when_inventory_fingerprint_lags(self):
        bank = DriveBank(CONFIG)
        file = {'id': 'base', 'name': 'perfil.json', 'mimeType': 'application/json', 'md5Checksum': 'unchanged'}
        with patch.object(bank, '_download', side_effect=[(b'old', '', ''), (b'added-record', '', ''), (b'deleted-record', '', '')]):
            self.assertEqual(bank.download(file)[0], b'old')
            self.assertEqual(bank.download(file)[0], b'added-record')
            self.assertEqual(bank.download(file)[0], b'deleted-record')

    def test_unchanged_sync_does_not_rewrite_index(self):
        files, contents = memory()
        bank = MemoryBank(files, contents)
        bank.load(process=True)
        writes = len(bank.writes)
        bank.load(process=True)
        self.assertEqual(len(bank.writes), writes)

    def test_replacing_photo_with_same_name_uses_new_file_id_and_bytes(self):
        files, contents = memory()
        bank = MemoryBank(files, contents)
        _, old_status, old_photo = bank.load()
        file = files.pop('photo')
        file.update({'id': 'replacement', 'md5Checksum': 'new-photo'})
        files['replacement'] = file
        output = io.BytesIO()
        Image.new('RGB', (8, 9), 'red').save(output, format='JPEG')
        contents['replacement'] = output.getvalue()
        _, new_status, new_photo = bank.load(process=True)
        self.assertEqual(new_status['photo']['file_id'], 'replacement')
        self.assertNotEqual(old_photo, new_photo)
        self.assertEqual(new_photo, contents['replacement'])
        self.assertEqual(new_status['pending'], 0)
        self.assertNotIn('replacement', json.loads(contents['index'])['documents'])

    def test_duplicate_photo_names_are_rejected(self):
        files, contents = memory()
        files['duplicate'] = {**files['photo'], 'id': 'duplicate'}
        with self.assertRaisesRegex(BankError, 'varias fotografías'):
            MemoryBank(files, contents).load()

    def test_photo_in_subfolder_is_available_after_organization(self):
        files, contents = memory()
        files['photo']['parents'] = ['subfolder']
        _, status, photo = MemoryBank(files, contents).load()
        self.assertEqual(status['photo']['file_id'], 'photo')
        self.assertEqual(photo, contents['photo'])

    def test_personal_data_and_references_are_merged_without_erasing_missing_fields(self):
        facts = clean_facts({'recipient': BASE['candidate']['name'], 'candidate': {'residence': 'Nueva residencia'}, 'references': [
            {'name': 'Referencia de prueba', 'role': 'Supervisor', 'phone': '555-0100'}]})
        profile, _ = merge_profile(BASE, {'doc': {'active': True, 'status': 'incorporado',
            'name': 'nota.txt', 'fingerprint': 'v1', 'facts': facts}})
        self.assertEqual(profile['candidate']['residence'], 'Nueva residencia')
        self.assertEqual(profile['candidate']['email'], BASE['candidate']['email'])
        self.assertEqual(profile['references'][-1]['name'], 'Referencia de prueba')
        cv_app.validate_profile(profile)

    def test_empty_category_folders_do_not_block_cv_profile(self):
        files, contents = memory()
        del files['certificate']
        for name in ('Informacion personal', 'Informacion laboral', 'Estudios', 'Referencias', 'Conocimiento o aprendizaje'):
            files[name] = {'id': name, 'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': ['bank']}
        profile, status, _ = MemoryBank(files, contents).load(process=True)
        self.assertEqual(status['pending'], 0)
        self.assertEqual(profile, BASE)

    def test_corrupt_replacement_photo_has_actionable_error(self):
        files, contents = memory()
        contents['photo'] = b'invalid image'
        with self.assertRaisesRegex(BankError, 'imagen válida'):
            MemoryBank(files, contents).load()

    def test_certificate_addition_cached_and_removal(self):
        files, contents = memory()
        calls = []
        def extract(*args):
            calls.append(args)
            return cert()
        bank = MemoryBank(files, contents, extract)
        initial, status, _ = bank.load()
        self.assertEqual(status['pending'], 1)
        self.assertEqual(initial['courses'], BASE['courses'])
        merged, status, _ = bank.load(process=True)
        self.assertEqual(status['pending'], 0)
        self.assertEqual(len(merged['courses']), len(BASE['courses']) + 1)
        self.assertEqual(merged['courses'][-1]['source_documents'][0]['file_id'], 'certificate')
        cv_app.validate_profile(merged)
        bank.load(process=True)
        self.assertEqual(len(calls), 1)
        del files['certificate']
        merged, status, _ = bank.load(process=True)
        self.assertEqual(merged['courses'], BASE['courses'])
        self.assertEqual(status['documents'], [])
        self.assertNotIn('certificate', json.loads(contents['index'])['documents'])

    def test_changed_document_excludes_previous_facts_until_reread(self):
        files, contents = memory()
        bank = MemoryBank(files, contents)
        bank.load(process=True)
        files['certificate']['md5Checksum'] = 'v2'
        profile, status, _ = bank.load()
        self.assertEqual(profile['courses'], BASE['courses'])
        self.assertEqual(status['pending'], 1)
        bank.extractor = lambda *args: cert('Curso corregido')
        profile, status, _ = bank.load(process=True)
        self.assertEqual(profile['courses'][-1]['title'], 'Curso corregido')
        stored = json.loads(contents['index'])['documents']['certificate']
        self.assertEqual(len(stored['history']), 1)

    def test_duplicate_certificate_does_not_duplicate_course(self):
        facts = cert()
        docs = {i: {'active': True, 'status': 'incorporado', 'name': i, 'fingerprint': 'v1', 'facts': facts} for i in ('a', 'b')}
        profile, _ = merge_profile(BASE, docs)
        self.assertEqual(len(profile['courses']), len(BASE['courses']) + 1)
        self.assertEqual(len(profile['courses'][-1]['source_documents']), 2)

    def test_other_recipient_is_flagged_without_incorporation(self):
        facts = cert()
        facts['recipient'] = 'Persona Ajena'
        profile, warnings = merge_profile(BASE, {'a': {'active': True, 'status': 'incorporado', 'name': 'a', 'fingerprint': 'v1', 'facts': facts}})
        self.assertEqual(profile['courses'], BASE['courses'])
        self.assertEqual(len(warnings), 1)

    def test_unsupported_format_is_registered_for_review(self):
        files, contents = memory()
        def extract(*args):
            raise BankError('Formato no admitido', 415)
        profile, status, _ = MemoryBank(files, contents, extract).load(process=True)
        self.assertEqual(status['documents'][0]['status'], 'revision')
        self.assertEqual(status['pending'], 0)
        self.assertEqual(profile['courses'], BASE['courses'])

    def test_transient_ai_failure_remains_pending(self):
        files, contents = memory()
        def extract(*args):
            raise RuntimeError('Transient model failure')
        profile, status, _ = MemoryBank(files, contents, extract).load(process=True)
        self.assertEqual(status['pending'], 1)
        self.assertNotIn('fingerprint', json.loads(contents['index'])['documents']['certificate'])

    def test_permission_error_prevents_stale_use(self):
        files, contents = memory()
        def extract(*args):
            raise BankError('No access')
        bank = MemoryBank(files, contents, extract)
        with self.assertRaises(BankError):
            bank.load(process=True)
        self.assertEqual(bank.writes, [])

    def test_image_passed_as_visual_evidence(self):
        output = io.BytesIO()
        Image.new('RGB', (100, 100)).save(output, format='PNG')
        text, media, mime = extraction_input('certificado.png', 'image/png', output.getvalue())
        self.assertEqual(text, '')
        self.assertEqual(mime, 'image/jpeg')
        self.assertTrue(media)

    def test_minimal_role_is_retained_without_inventing_employer_or_dates(self):
        facts = clean_facts({'experiences': [{'title': 'Jefe', 'responsibilities': ['Gestionar']}], 'courses': [{'title': 'Curso', 'institution': 'Centro'}]})
        self.assertEqual(facts['experiences'][0]['employer'], 'Empleador no indicado')
        self.assertEqual(facts['experiences'][0]['start_date'], '')
        self.assertEqual(facts['courses'][0]['date'], '')

    def test_short_note_merges_with_documented_duties(self):
        note = clean_facts({'experiences': [{'title': 'Camarero', 'employer': 'Farah Modern Kitchen'}]})
        document = clean_facts({'experiences': [{'title': 'Camarero', 'employer': 'Farah Modern Kitchen', 'responsibilities': ['Atención de mesas'], 'start_date': '2024'}]})
        docs = {key: {'active': True, 'status': 'incorporado', 'name': key, 'fingerprint': 'v1', 'facts': facts}
                for key, facts in [('note', note), ('document', document)]}
        profile, _ = merge_profile(BASE, docs)
        experience = next(e for e in profile['experiences'] if e['employer'] == 'Farah Modern Kitchen' and e['title'] == 'Camarero')
        self.assertEqual(experience['start_date'], '2024')
        self.assertEqual(len(experience['source_documents']), 2)
        self.assertIn('Atención de mesas', [r['text'] for r in experience['responsibilities']])
        cv_app.validate_profile(profile)

    def test_generated_role_duties_reach_cv_without_inventing_dates(self):
        duties = ['Atención de mesas', 'Toma de pedidos', 'Servicio de alimentos y bebidas']
        facts = clean_facts({'experiences': [{'title': 'Camarero', 'employer': 'Restaurante de prueba',
                                             'generated_responsibilities': duties}]})
        self.assertEqual(facts['experiences'][0]['responsibilities'], [])
        docs = {'note': {'active': True, 'status': 'incorporado', 'name': 'nota.txt', 'fingerprint': 'v1', 'facts': facts}}
        profile, _ = merge_profile(BASE, docs)
        experience = next(e for e in profile['experiences'] if e['employer'] == 'Restaurante de prueba')
        self.assertEqual(experience['start_date'], '')
        self.assertEqual([r['text'] for r in experience['responsibilities']], duties)
        self.assertTrue(all(r['origin'] == 'generada_por_puesto' for r in experience['responsibilities']))
        cv_app.validate_profile(profile)
        analysis = {'matching': {'selected_experiences': [{'experience_id': experience['id'],
                    'responsibility_ids': [r['id'] for r in experience['responsibilities']]}]}}
        with patch.object(cv_app, 'EXPERIENCE_BY_ID', {experience['id']: experience}), patch.object(cv_app, 'MASTER_PROFILE', profile):
            selected = cv_app.selected_experience_items(analysis)
            self.assertEqual(selected[0]['selected_responsibilities'], duties)
            context = next(e for e in cv_app.profile_context()['experiences'] if e['id'] == experience['id'])
            self.assertEqual(context['responsibilities'][0]['origin'], 'generada_por_puesto')

    def test_documented_function_overrides_generated_origin(self):
        docs = {key: {'active': True, 'status': 'incorporado', 'name': key, 'fingerprint': 'v1',
                'facts': clean_facts({'experiences': [{'title': 'Camarero', 'employer': 'Restaurante de prueba',
                                                     field: ['Atención de mesas']}]})}
                for key, field in [('a', 'generated_responsibilities'), ('b', 'responsibilities')]}
        profile, _ = merge_profile(BASE, docs)
        tasks = next(e for e in profile['experiences'] if e['employer'] == 'Restaurante de prueba')['responsibilities']
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['origin'], 'documentada')
        self.assertEqual(len(tasks[0]['source_documents']), 2)

    def test_images_and_notes_inside_project_are_read_independently(self):
        files, contents = memory()
        files['project'] = {'id': 'project', 'name': 'Portfolio', 'mimeType': 'application/vnd.google-apps.folder', 'parents': ['bank']}
        for key, name, mime in [('code', 'app.js', 'text/javascript'), ('note', 'experiencia.txt', 'text/plain'), ('scan', 'nota.png', 'image/png')]:
            files[key] = {'id': key, 'name': name, 'mimeType': mime, 'parents': ['project'], 'md5Checksum': 'v1'}
            contents[key] = b'evidence'
        calls = []
        bank = MemoryBank(files, contents, lambda name, *args: (calls.append(name) or cert(name)))
        _, status, _ = bank.load(process=True, max_documents=10)
        self.assertEqual(status['pending'], 0)
        self.assertIn('experiencia.txt', calls)
        self.assertIn('nota.png', calls)
        self.assertNotIn('app.js', calls)

    def test_app_uses_drive_and_blocks_analysis_until_synchronized(self):
        with patch.dict('os.environ', {'CV_BANK_PROVIDER': 'drive', 'CV_ALLOW_REMOTE': '1', 'CV_AUTH_REQUIRED': '0'}), patch.object(cv_app, 'load_drive_bank', return_value={'pending': 1}) as load:
            client = cv_app.app.test_client()
            self.assertEqual(client.get('/api/profile').status_code, 200)
            response = client.post('/api/analyze', json={'text': 'vacante'})
            self.assertEqual(response.status_code, 409)
            self.assertIn('Sincronizar', response.json['error'])
            self.assertEqual(client.put('/api/profile', json=BASE).status_code, 409)

    def test_inventory_recurses_real_folders_without_external_shortcuts(self):
        config = dict(CONFIG)
        bank = DriveBank(config)
        requests = []
        def response(method, url, **kwargs):
            requests.append(url)
            class Result:
                def json(self):
                    if 'child' in url:
                        return {'files': [{'id': 'nestedcert', 'mimeType': 'image/png'}]}
                    return {'files': [{'id': i, 'mimeType': 'text/plain'} for i in ('base', 'index', 'photo')] + [{'id': 'child', 'mimeType': 'application/vnd.google-apps.folder'}, {'id': 'shortcut', 'mimeType': 'application/vnd.google-apps.shortcut'}]}
            return Result()
        bank.request = response
        result = bank.inventory()
        self.assertIn('nestedcert', result)
        self.assertEqual(len(requests), 2)

if __name__ == '__main__':
    unittest.main()
