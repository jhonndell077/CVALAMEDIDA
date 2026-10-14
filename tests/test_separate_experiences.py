import copy
import unittest
from unittest.mock import patch

import pymupdf
from docx import Document
import app
from test_app import valid_analysis


class SeparateExperiencesTests(unittest.TestCase):
    def test_same_role_exports_as_two_headings_with_own_responsibilities(self):
        original = copy.deepcopy(app.MASTER_PROFILE)
        analysis = valid_analysis()
        analysis['vacancy']['position'] = 'Camarero'
        analysis['matching']['selected_project_ids'] = []
        analysis['matching']['selected_experiences'] = [
            {'experience_id': 'fixture-forno', 'responsibility_ids': ['forno-task']},
            {'experience_id': 'fixture-farah', 'responsibility_ids': ['farah-task']},
        ]
        profile = copy.deepcopy(original)
        profile['experiences'] = [
            {'id': 'fixture-forno', 'title': 'Camarero', 'employer': 'Forno Bravo', 'category': 'Servicio',
             'responsibilities': [{'id': 'forno-task', 'text': 'Atención a mesas y preparación de bebidas.'}]},
            {'id': 'fixture-farah', 'title': 'Camarero', 'employer': 'Farah', 'category': 'Servicio',
             'responsibilities': [{'id': 'farah-task', 'text': 'Atención a mesas y recepción de comensales.'}]},
        ]
        with patch.object(app, 'MASTER_PROFILE', profile), patch.object(app, 'EXPERIENCE_BY_ID', {e['id']: e for e in profile['experiences']}):
            draft = app.make_draft(app.sanitize_analysis(analysis))
            self.assertEqual([e['id'] for e in draft['experiences']], ['fixture-forno', 'fixture-farah'])
            for entry, source in zip(draft['experiences'], profile['experiences']):
                self.assertEqual(entry['selected_responsibilities'], [source['responsibilities'][0]['text']])
            pdf = pymupdf.open(stream=app.make_pdf(draft).getvalue(), filetype='pdf')
            pdf_text = '\n'.join(page.get_text() for page in pdf)
            doc = Document(app.make_docx(draft))
            word_text = '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
            for text in (pdf_text, word_text):
                normalized = ' '.join(text.split())
                self.assertIn('Camarero: Forno Bravo', normalized)
                self.assertIn('Camarero: Farah', normalized)
                self.assertNotIn('Forno Bravo / Farah', normalized)
            self.assertEqual(app.MASTER_PROFILE, profile)
        self.assertEqual(app.MASTER_PROFILE, original)
