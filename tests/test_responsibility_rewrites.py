import copy
import unittest
from unittest.mock import patch

import pymupdf
from docx import Document
import app
from test_app import valid_analysis


class ResponsibilityRewriteTests(unittest.TestCase):
    def test_rewrite_reaches_both_exports_without_changing_bank(self):
        original = copy.deepcopy(app.MASTER_PROFILE)
        analysis = valid_analysis()
        selection = analysis['matching']['selected_experiences'][2]
        text = 'Recepción y clasificación de mercancías en almacén.'
        selection['responsibility_rewrites'] = [
            {'responsibility_id': 'recepcion-clasificacion', 'text': text},
            {'responsibility_id': 'reponer-organizar', 'text': 'Función ajena'},
        ]
        cleaned = app.sanitize_analysis(analysis)
        self.assertEqual(len(cleaned['matching']['selected_experiences'][2]['responsibility_rewrites']), 1)
        draft = app.make_draft(cleaned)
        pdf = pymupdf.open(stream=app.make_pdf(draft).getvalue(), filetype='pdf')
        self.assertIn(text, ' '.join(' '.join(p.get_text().split()) for p in pdf))
        doc = Document(app.make_docx(draft))
        self.assertIn(text, '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells))
        self.assertEqual(app.MASTER_PROFILE, original)

    def test_invalid_or_missing_rewrites_fall_back_to_original(self):
        analysis = valid_analysis()
        baseline = app.selected_experience_items(analysis)
        for value in [None, {}, 'invalid', [{'responsibility_id': [], 'text': 'x'}],
                      [{'responsibility_id': 'reponer-organizar', 'text': ' '}],
                      [{'responsibility_id': 'reponer-organizar', 'text': 'x' * 451}]]:
            with self.subTest(value=value):
                analysis['matching']['selected_experiences'][0]['responsibility_rewrites'] = value
                self.assertEqual(app.selected_experience_items(analysis), baseline)

    def test_schema_requests_rewrites_and_prompt_limits_them_to_source(self):
        schema = app.analysis_output_schema()['properties']['matching']['properties']
        self.assertIn('responsibility_rewrites', schema['selected_experiences']['items']['required'])


if __name__ == '__main__':
    unittest.main()
