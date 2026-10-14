import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app
import pymupdf
from docx import Document
from drive_bank import DriveBank, merge_profile
from profile_deletions import apply_deletions, deletion_for
from test_app import valid_analysis


class ProfileDeletionTests(unittest.TestCase):
    def test_all_cards_and_individual_functions_can_be_deleted(self):
        original = copy.deepcopy(app.MASTER_PROFILE)
        paths = [[section, 0] for section in ('experiences', 'skills', 'education', 'courses', 'projects', 'references', 'not_documented') if original[section]]
        paths += [['candidate', 'email'], ['candidate', 'phones', 0], ['experiences', 0, 'responsibilities', 0]]
        for path in paths:
            with self.subTest(path=path):
                profile = copy.deepcopy(original)
                value = profile
                for part in path:
                    value = value[part]
                selector = deletion_for(profile, path, value)
                profile['_deleted_records'] = [selector]
                filtered = apply_deletions(profile)
                app.validate_profile(filtered)
                parent = filtered
                for part in path[:-1]:
                    parent = parent[part]
                if isinstance(parent, list):
                    self.assertNotIn(value, parent)
                else:
                    self.assertEqual(parent[path[-1]], '')
                self.assertEqual(app.MASTER_PROFILE, original)

    def test_document_sync_does_not_resurrect_deleted_record_with_new_id(self):
        base = copy.deepcopy(app.MASTER_PROFILE)
        record = {'id': 'manual-test', 'title': 'Curso exclusivo', 'institution': 'Instituto', 'date': '2026'}
        base['courses'].append(record)
        base['_deleted_records'] = [deletion_for(base, ['courses', len(base['courses']) - 1], record)]
        base['courses'].pop()
        documents = {'doc': {'active': True, 'status': 'incorporado', 'name': 'Certificado', 'fingerprint': 'v2', 'facts': {'courses': [record]}}}
        profile, _ = merge_profile(base, documents)
        self.assertFalse(any(item['title'] == record['title'] for item in profile['courses']))

    def test_stale_invalid_and_metadata_targets_rejected(self):
        for path in [None, [], ['courses', -1], ['courses', {}], ['_deleted_records'], ['candidate', 'photo'], ['experiences', 0, 'id']]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                deletion_for(app.MASTER_PROFILE, path, None)
        with self.assertRaises(ValueError):
            deletion_for(app.MASTER_PROFILE, ['courses', 0], {'title': 'outdated'})

    def test_local_endpoint_persists_and_old_analysis_is_rejected(self):
        original = copy.deepcopy(app.MASTER_PROFILE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            path.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(app, 'PROFILE_PATH', path), patch.dict(os.environ, {'CV_BANK_PROVIDER': 'local', 'CV_AUTH_REQUIRED': '0', 'CV_ALLOW_REMOTE': '0'}):
                try:
                    response = app.app.test_client().post('/api/profile/delete', json={'path': ['references', 0], 'expected': original['references'][0]})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertNotIn(original['references'][0], json.loads(path.read_text())['references'])
                    with self.assertRaisesRegex(app.AppError, 'Vuelve a analizar'):
                        app.make_draft(valid_analysis())
                    draft = app.make_draft(app.sanitize_analysis(valid_analysis()))
                    self.assertNotIn(original['references'][0], draft['references'])
                    removed_name = original['references'][0]['name']
                    pdf = pymupdf.open(stream=app.make_pdf(draft).getvalue(), filetype='pdf')
                    self.assertNotIn(removed_name, ''.join(page.get_text() for page in pdf))
                    document = Document(app.make_docx(draft))
                    self.assertNotIn(removed_name, '\n'.join(cell.text for table in document.tables for row in table.rows for cell in row.cells))
                finally:
                    app.MASTER_PROFILE = original
                    app.refresh_profile_indexes()

    def test_drive_write_uses_etag_preserves_sources_and_verifies(self):
        base = copy.deepcopy(app.MASTER_PROFILE)
        selector = deletion_for(base, ['courses', 0], base['courses'][0])
        bank = DriveBank({'base_file_id': 'base'})
        writes = []
        def request(method, url, **kwargs):
            if method == 'PATCH':
                writes.append(kwargs)
                base.update(json.loads(kwargs['data']))
            response = MagicMock(content=json.dumps(base).encode(), headers={'ETag': 'v1'})
            response.json.return_value = copy.deepcopy(base)
            return response
        bank.request = request
        bank.delete_record(selector)
        self.assertEqual(writes[0]['headers']['If-Match'], 'v1')
        self.assertIn(selector, base['_deleted_records'])
        self.assertEqual(base['courses'], app.MASTER_PROFILE['courses'])
        self.assertNotIn(base['courses'][0], apply_deletions(base)['courses'])

    def test_remote_delete_requires_login(self):
        with patch.dict(os.environ, {'CV_AUTH_REQUIRED': '1', 'CV_ALLOW_REMOTE': '1'}):
            self.assertEqual(app.app.test_client().post('/api/profile/delete', json={}).status_code, 401)

    def test_last_experience_function_and_contact_can_be_removed(self):
        base = copy.deepcopy(app.MASTER_PROFILE)
        base['_deleted_records'] = []
        for index, experience in enumerate(base['experiences']):
            for task_index, task in enumerate(experience['responsibilities']):
                base['_deleted_records'].append(deletion_for(base, ['experiences', index, 'responsibilities', task_index], task))
        filtered = apply_deletions(base)
        app.validate_profile(filtered)
        self.assertTrue(all(not item['responsibilities'] for item in filtered['experiences']))
        for index, experience in enumerate(base['experiences']):
            base['_deleted_records'].append(deletion_for(base, ['experiences', index], experience))
        for index, phone in enumerate(base['candidate']['phones']):
            base['_deleted_records'].append(deletion_for(base, ['candidate', 'phones', index], phone))
        base['_deleted_records'].append(deletion_for(base, ['candidate', 'name'], base['candidate']['name']))
        filtered = apply_deletions(base)
        app.validate_profile(filtered)
        self.assertEqual(filtered['experiences'], [])
        self.assertEqual(filtered['candidate']['phones'], [])
        self.assertEqual(filtered['candidate']['name'], '')
