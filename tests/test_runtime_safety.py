"""Regression guarantees for bounded PDFs and honest capability metadata."""
import base64
import math
import os
import unittest
from unittest.mock import patch

import pymupdf
import app


class RuntimeSafetyTests(unittest.TestCase):
    def test_oversized_scanned_page_is_rejected_before_raster_allocation(self):
        with pymupdf.open() as document:
            document.new_page(width=15000, height=15000)
            raw = document.tobytes()
        payload = {'file_name': 'oversized.pdf', 'file_data': base64.b64encode(raw).decode()}
        class Pixmap:
            def tobytes(self, kind):
                return b'synthetic-jpeg'
        with patch.object(pymupdf.Page, 'get_pixmap', return_value=Pixmap()) as raster:
            with self.assertRaisesRegex(app.AppError, 'resolución|dimensiones|píxeles'):
                app.extract_vacancy(payload)
            raster.assert_not_called()

    def test_normal_scanned_page_still_renders(self):
        with pymupdf.open() as document:
            document.new_page(width=595, height=842)
            raw = document.tobytes()
        payload = {'file_name': 'normal.pdf', 'file_data': base64.b64encode(raw).decode()}
        text, images = app.extract_vacancy(payload)
        self.assertEqual(text, '')
        self.assertEqual(len(images), 1)
        self.assertGreater(len(base64.b64decode(images[0])), 0)

    def test_vertex_health_distinguishes_configuration_from_verified_availability(self):
        with patch.dict(os.environ, {'CV_AI_PROVIDER': 'vertex', 'GOOGLE_CLOUD_PROJECT': 'fixture-project'}):
            with app.app.test_request_context('/api/health'):
                data = app.health().get_json()
        self.assertTrue(data['model_configured'])
        self.assertFalse(data['model_available'])
        self.assertEqual(data['model_status'], 'not_verified')

    def test_privacy_discloses_durable_processing_results(self):
        with patch.dict(os.environ, {'CV_AI_PROVIDER': 'vertex', 'GOOGLE_CLOUD_PROJECT': 'fixture-project'}):
            with app.app.test_request_context('/api/health'):
                data = app.health().get_json()
        self.assertNotIn('no se guardan', data['privacy'])
        self.assertIn('Cloud Storage', data['privacy'])
        self.assertIn('Drive', data['privacy'])


if __name__ == '__main__':
    unittest.main()
