import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app
import cv_analysis
from test_app import valid_analysis


class CvDeduplicationTests(unittest.TestCase):
    def test_same_employer_and_role_merge_selected_tasks_without_mutating_sources(self):
        records = [
            {'id': 'a', 'title': 'Asistente Administrativo', 'employer': 'Cris Technical Services S.R.L.',
             'selected_responsibilities': ['GestiÃ³n de documentos.', 'AtenciÃ³n a clientes.']},
            {'id': 'b', 'title': 'asistente administrativo', 'employer': 'Cris Technical Services S.R.L.',
             'selected_responsibilities': ['GestiÃ³n de documentos.', 'OrganizaciÃ³n de archivos.']},
        ]
        original = copy.deepcopy(records)
        result = cv_analysis.consolidate_experiences(SimpleNamespace(), records)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['selected_responsibilities'],
                         ['GestiÃ³n de documentos.', 'AtenciÃ³n a clientes.', 'OrganizaciÃ³n de archivos.'])
        self.assertEqual(records, original)

    def test_distinct_employers_and_periods_remain_separate(self):
        records = [{'id': str(i), 'title': 'Asistente', 'employer': employer, 'start_date': date,
                    'selected_responsibilities': ['Archivar documentos.']}
                   for i, (employer, date) in enumerate([('Cris', '2020'), ('Cris', '2023'), ('Otra', '2020')])]
        self.assertEqual(len(cv_analysis.consolidate_experiences(SimpleNamespace(), records)), 3)

    def test_draft_deduplicates_all_exported_sections(self):
        profile = copy.deepcopy(app.MASTER_PROFILE)
        analysis = valid_analysis()
        for section in ('education', 'references'):
            if profile[section]:
                duplicate = copy.deepcopy(profile[section][0])
                duplicate['id'] = 'duplicate-' + section
                profile[section].append(duplicate)
        for key in ('selected_skills', 'selected_course_ids', 'selected_project_ids'):
            analysis['matching'][key] = analysis['matching'][key][:1] * 2
        with patch.object(app, 'MASTER_PROFILE', profile):
            draft = app.make_draft(analysis)
        for section in ('skills', 'courses', 'projects'):
            self.assertLessEqual(len(draft[section]), 1)
        from profile_records import consolidate
        expected = consolidate(profile)
        for section in ('education', 'references'):
            self.assertEqual(len(draft[section]), len(expected[section]))
