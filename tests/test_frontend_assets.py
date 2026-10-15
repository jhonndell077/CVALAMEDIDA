"""Every local page dependency must be served without exposing other files."""
import re
import unittest
from pathlib import Path
from unittest.mock import patch
import app


class FrontendAssetTests(unittest.TestCase):
    def test_page_dependencies_are_available_through_flask(self):
        root = Path(app.app.static_folder)
        paths = set()
        for page in ('index.html', 'manual.html', 'drive-auth.html'):
            paths.update(re.findall(r'(?:src|href)="(/[^"#?]+)"', (root / page).read_text(encoding='utf-8')))
        with patch.dict('os.environ', {'CV_ALLOW_REMOTE': '0', 'CV_AUTH_REQUIRED': '0'}):
            with app.app.test_client() as client:
                for path in sorted(paths):
                    with self.subTest(path=path):
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200)
                        response.close()
                for path in ('/app.py', '/data/master_profile.json', '/../app.py'):
                    self.assertEqual(client.get(path).status_code, 404)
