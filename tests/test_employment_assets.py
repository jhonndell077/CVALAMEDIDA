import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class AssetTests(unittest.TestCase):
    def setUp(self):
        profile={'candidate':{'photo':'fixture.jpeg'},'experiences':[],'skills':[],'courses':[],
                 'education':[],'projects':[],'references':[],'not_documented':[]}
        real_read=Path.read_text; real_open=Path.open
        def read(path,*a,**k):
            return '{}' if path==ROOT/'data/bank_config.json' else real_read(path,*a,**k)
        def opened(path,*a,**k):
            return io.StringIO(json.dumps(profile)) if path==ROOT/'data/master_profile.json' else real_open(path,*a,**k)
        with patch.object(Path,'read_text',read),patch.object(Path,'open',opened):
            import app
        self.app=app.app

    def test_local_static_assets_are_available(self):
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'0','CV_BANK_PROVIDER':'local'}):
            client=self.app.test_client()
            for asset in ('employment.js','employment.css','vendor/leaflet/leaflet.js','vendor/leaflet/leaflet.css','vendor/leaflet/images/marker-icon.png'):
                with self.subTest(asset=asset),client.get('/'+asset) as response:
                    self.assertEqual(response.status_code,200)

    def test_static_route_cannot_expose_private_profile(self):
        with patch.dict(os.environ,{'CV_AUTH_REQUIRED':'0','CV_ALLOW_REMOTE':'0','CV_BANK_PROVIDER':'local'}):
            self.assertEqual(self.app.test_client().get('/data/master_profile.json').status_code,404)
