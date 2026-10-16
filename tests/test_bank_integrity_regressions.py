"""Audit H01/H04/H07 regressions: fictional data and in-memory Drive only."""
import copy
import hashlib
import json
import unittest
from urllib.parse import urlsplit

from drive_bank import BankError, DriveBank, clean_facts, merge_profile
from profile_deletions import apply_deletions, deletion_for, identity
from profile_edits import apply as apply_edits, prepare
from profile_records import add_information, consolidate


def blank():
    return {'candidate': {'name': 'María Elena Gómez Pérez', 'email': 'owner@example.invalid', 'phones': []},
            **{section: [] for section in ('projects', 'experiences', 'education', 'courses', 'skills', 'references', 'not_documented')}}


def old_identity(record):
    keys = ('title', 'employer') if 'employer' in record else ('title', 'institution') if 'institution' in record else ('title',)
    return hashlib.sha256(json.dumps({key: record.get(key, '') for key in keys}, ensure_ascii=False, sort_keys=True).casefold().encode()).hexdigest()


def variants(section):
    fields = {'id': 'first', 'title': 'Registro de prueba'}
    if section == 'experiences':
        return [{**fields, 'employer': 'Empresa de prueba', 'start_date': year, 'end_date': year,
                 'responsibilities': [{'id': 'task-' + year, 'text': 'Función común'}]} for year in ('2020', '2023')]
    if section in ('courses', 'education'):
        return [{**fields, 'institution': 'Instituto de prueba', 'date': year} for year in ('2020', '2023')]
    return [{**fields, 'description': 'Proyecto de prueba', 'url': 'https://' + domain + '.example.invalid', 'technologies': []}
            for domain in ('first', 'second')]


class RecordIdentityRegressions(unittest.TestCase):
    def test_deletion_distinguishes_periods_dates_and_project_urls_after_sync(self):
        for section in ('experiences', 'courses', 'education', 'projects'):
            with self.subTest(section=section):
                profile = blank(); records = variants(section)
                profile[section] = records
                self.assertNotEqual(identity(records[0]), identity(records[1]))
                profile['_deleted_records'] = [deletion_for(profile, [section, 0], records[0])]
                self.assertEqual(merge_profile(profile, {})[0][section], [records[1]])

    def test_edit_and_individual_duty_only_affect_selected_period(self):
        profile = blank(); profile['experiences'] = variants('experiences')
        profile['experiences'][1]['id'] = 'second'
        updated = copy.deepcopy(profile)
        updated['experiences'][0]['title'] = 'Cargo corregido'
        saved = prepare(profile, profile, updated)
        rebuilt = apply_edits({**copy.deepcopy(profile), '_manual_edits': saved['_manual_edits']})
        self.assertEqual(rebuilt['experiences'], updated['experiences'])
        profile['_deleted_records'] = [deletion_for(profile, ['experiences', 0, 'responsibilities', 0], profile['experiences'][0]['responsibilities'][0])]
        rebuilt = apply_deletions(profile)
        self.assertEqual(rebuilt['experiences'][0]['responsibilities'], [])
        self.assertEqual(rebuilt['experiences'][1], profile['experiences'][1])

    def test_ambiguous_legacy_deletion_and_edit_preserve_both_periods(self):
        profile = blank(); profile['courses'] = variants('courses')
        token = old_identity(profile['courses'][0])
        profile['_deleted_records'] = [['courses', {'identity': token}]]
        self.assertEqual(apply_deletions(profile)['courses'], profile['courses'])
        profile['_manual_edits'] = [{'section': 'courses', 'identity': token, 'value': None}]
        self.assertEqual(apply_edits(profile)['courses'], profile['courses'])
        rebuilt, warnings = merge_profile(profile, {})
        self.assertEqual(rebuilt['courses'], profile['courses'])
        self.assertTrue(any('ambig' in item['message'].casefold() for item in warnings))

    def test_unique_legacy_selector_still_applies_and_snapshot_disambiguates_edit(self):
        profile = blank(); profile['courses'] = variants('courses')
        token = old_identity(profile['courses'][0])
        replacement = {**profile['courses'][0], 'title': 'Corregido'}
        profile['_manual_edits'] = [{'section': 'courses', 'identity': token,
                                     'previous': copy.deepcopy(profile['courses'][0]), 'value': replacement}]
        self.assertEqual(apply_edits(profile)['courses'], [replacement, profile['courses'][1]])
        profile['courses'] = profile['courses'][:1]
        profile['_deleted_records'] = [['courses', {'identity': token}]]
        self.assertEqual(apply_deletions(profile)['courses'], [])

    def test_legacy_deletion_of_equivalent_spacing_variant_survives_consolidation(self):
        profile = blank(); record = variants('courses')[0]
        profile['courses'] = [record, {**record, 'title': 'Registro  de prueba'}]
        token = old_identity(profile['courses'][1])
        profile['_deleted_records'] = [['courses', {'identity': token}]]
        self.assertEqual(apply_deletions(consolidate(profile))['courses'], [])

    def test_explicit_readdition_clears_only_unambiguous_legacy_exclusion(self):
        profile = blank(); record = variants('courses')[0]
        profile['courses'] = [record]
        token = old_identity(record)
        profile['_deleted_records'] = [['courses', {'identity': token}]]
        add_information(profile, 'courses', {**record, 'id': 'manual-a'})
        self.assertEqual(apply_deletions(profile)['courses'], profile['courses'])
        profile['courses'].append(variants('courses')[1])
        profile['_deleted_records'] = [['courses', {'identity': token}]]
        add_information(profile, 'courses', {**record, 'id': 'manual-b'})
        self.assertIn(['courses', {'identity': token}], profile['_deleted_records'])


class MemoryResponse:
    def __init__(self, value, status=200):
        self.value = copy.deepcopy(value); self.content = json.dumps(value).encode()
        self.headers = {}; self.status_code = status; self.ok = status < 400
    def json(self): return copy.deepcopy(self.value)
    def close(self): pass


class VersionedDrive:
    """v3 omits ETag, v2 metadata exposes it; conditional writes enforce CAS."""
    def __init__(self):
        self.values = {'base': blank(), 'index': {'version': 1, 'documents': {}}}
        self.versions = {'base': 1, 'index': 1}; self.writes = []; self.expose_etag = True; self.before_write = None
    def request(self, method, url, **kwargs):
        file_id = urlsplit(url).path.rsplit('/', 1)[-1]
        if method == 'GET':
            if '/drive/v2/' in url and 'fields=etag' in url:
                return MemoryResponse({'etag': str(self.versions[file_id])} if self.expose_etag else {})
            return MemoryResponse(self.values[file_id])
        if self.before_write:
            callback, self.before_write = self.before_write, None; callback(file_id)
        headers = kwargs.get('headers', {})
        if 'If-Match' in headers and headers['If-Match'] != str(self.versions[file_id]):
            return MemoryResponse({}, 412)
        self.values[file_id] = json.loads(kwargs['data']); self.versions[file_id] += 1
        self.writes.append((method, url, headers)); return MemoryResponse(self.values[file_id])


def bank_and_drive():
    drive = VersionedDrive()
    bank = DriveBank({'base_file_id': 'base', 'index_file_id': 'index', 'folder_id': 'folder', 'photo_optional': True}, session=drive)
    files = {key: {'id': key, 'name': key + '.json', 'mimeType': 'application/json', 'md5Checksum': 'v1'} for key in ('base', 'index')}
    bank.inventory = lambda: files
    bank.download = lambda file: (json.dumps(drive.values[file['id']]).encode(), file['name'], file['mimeType'])
    return bank, drive


class DriveConcurrencyRegressions(unittest.TestCase):
    def test_add_delete_and_index_require_v2_etag_and_conditional_put(self):
        for action in ('add', 'delete', 'index'):
            with self.subTest(action=action):
                bank, drive = bank_and_drive()
                if action == 'add':
                    bank.add_record('courses', {**variants('courses')[0], 'id': 'manual-a'}, lambda _: None)
                elif action == 'delete':
                    drive.values['base']['courses'] = variants('courses')[:1]
                    bank.delete_record(deletion_for(drive.values['base'], ['courses', 0], drive.values['base']['courses'][0]))
                else:
                    drive.values['index']['documents'] = {'removed': {'active': True}}
                    bank.load(process=True)
                self.assertEqual(len(drive.writes), 1)
                method, url, headers = drive.writes[0]
                self.assertEqual(method, 'PUT'); self.assertIn('/upload/drive/v2/files/', url)
                self.assertEqual(headers['If-Match'], '1')

    def test_absent_etag_never_falls_back_to_unconditional_write(self):
        for action in ('add', 'delete', 'index'):
            with self.subTest(action=action):
                bank, drive = bank_and_drive(); drive.expose_etag = False
                drive.values['index']['documents'] = {'removed': {'active': True}}
                with self.assertRaises(BankError) as caught:
                    if action == 'add': bank.add_record('courses', {**variants('courses')[0], 'id': 'manual-a'}, lambda _: None)
                    elif action == 'delete': bank.delete_record(['courses', {'identity': 'synthetic'}])
                    else: bank.load(process=True)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(drive.writes, [])

    def test_concurrent_change_returns_conflict_and_preserves_other_write(self):
        for action in ('add', 'delete', 'index'):
            with self.subTest(action=action):
                bank, drive = bank_and_drive()
                drive.values['index']['documents'] = {'removed': {'active': True}}
                def concurrent_change(file_id):
                    drive.values[file_id]['concurrent_marker'] = True; drive.versions[file_id] += 1
                drive.before_write = concurrent_change
                with self.assertRaises(BankError) as caught:
                    if action == 'add': bank.add_record('courses', {**variants('courses')[0], 'id': 'manual-a'}, lambda _: None)
                    elif action == 'delete': bank.delete_record(['courses', {'identity': 'synthetic'}])
                    else: bank.load(process=True)
                self.assertEqual(caught.exception.status_code, 409)
                file_id = 'index' if action == 'index' else 'base'
                self.assertTrue(drive.values[file_id]['concurrent_marker'])
                self.assertEqual(drive.writes, [])

    def test_two_overlapping_deletes_cannot_both_succeed_and_lose_one(self):
        bank, drive = bank_and_drive()
        profile = drive.values['base']; profile['courses'] = variants('courses')
        first = deletion_for(profile, ['courses', 0], profile['courses'][0])
        second = deletion_for(profile, ['courses', 1], profile['courses'][1])
        other = DriveBank(bank.config, session=drive)
        drive.before_write = lambda _: other.delete_record(second)
        with self.assertRaises(BankError) as caught: bank.delete_record(first)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(drive.values['base']['_deleted_records'], [second])
        bank.delete_record(first)
        self.assertEqual(drive.values['base']['_deleted_records'], [second, first])

    def test_changes_between_version_and_content_read_are_not_overwritten(self):
        bank, drive = bank_and_drive()
        original_request = drive.request; changed = False
        def racing_request(method, url, **kwargs):
            nonlocal changed
            if method == 'GET' and 'alt=media' in url and not changed:
                changed = True; drive.versions['base'] += 1
                drive.values['base']['concurrent_marker'] = True
            return original_request(method, url, **kwargs)
        drive.request = racing_request
        with self.assertRaises(BankError) as caught: bank.delete_record(['courses', {'identity': 'synthetic'}])
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(drive.values['base']['concurrent_marker']); self.assertEqual(drive.writes, [])


class DocumentAttributionRegressions(unittest.TestCase):
    def merge(self, raw):
        return merge_profile(blank(), {'doc': {'active': True, 'status': 'incorporado', 'name': 'fixture.json',
            'fingerprint': 'v1', 'facts': clean_facts(raw)}})

    def test_partial_names_initials_and_conflicting_candidate_do_not_change_profile(self):
        for recipient, candidate in [('María López', {}), ('M. Elena Gómez Pérez', {}),
                                     ('María Elena Gómez Pérez', {'name': 'María Elena López'})]:
            with self.subTest(recipient=recipient, candidate=candidate):
                profile, warnings = self.merge({'recipient': recipient, 'candidate': {**candidate, 'email': 'other@example.invalid'},
                    'courses': [{'title': 'Curso ajeno', 'institution': 'Centro'}], 'generated_skills': ['Habilidad ajena']})
                self.assertEqual(profile['candidate'], blank()['candidate']); self.assertEqual(profile['courses'], [])
                self.assertEqual(profile['skills'], []); self.assertTrue(warnings)

    def test_full_name_normalization_accepts_accents_spacing_and_compound_names(self):
        profile, warnings = self.merge({'recipient': '  MARIA   ELENA GOMEZ PEREZ ',
            'candidate': {'email': 'confirmed@example.invalid'}, 'courses': [{'title': 'Curso propio', 'institution': 'Centro'}]})
        self.assertEqual(profile['candidate']['email'], 'confirmed@example.invalid')
        self.assertEqual(len(profile['courses']), 1); self.assertEqual(warnings, [])

    def test_unnamed_document_cannot_replace_contacts_or_bootstrap_a_new_identity(self):
        profile, warnings = self.merge({'candidate': {'email': 'unconfirmed@example.invalid'}})
        self.assertEqual(profile['candidate']['email'], blank()['candidate']['email']); self.assertTrue(warnings)
        profile, warnings = self.merge({'candidate': {'name': 'Otra Persona', 'email': 'other@example.invalid'}})
        self.assertEqual(profile['candidate'], blank()['candidate']); self.assertTrue(warnings)


if __name__ == '__main__': unittest.main()
