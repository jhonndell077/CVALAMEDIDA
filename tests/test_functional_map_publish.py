"""Release inventory tests use temporary files and mocked HTTP only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import generate_functional_map as generator


class FunctionalMapPublishTests(unittest.TestCase):
    def test_stale_evidence_blocks_publish_without_replacing_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'manifest.json';target.write_text('{"schema":1}',encoding='utf-8')
            evidence=Path(folder)/'evidence.json';evidence.write_text(json.dumps({'sourceHash':'old','passed':True}),encoding='utf-8')
            with patch.object(generator,'MANIFEST',target),patch.object(generator,'EVIDENCE',evidence),patch.object(generator.subprocess,'check_output',return_value='new\n'):
                with self.assertRaisesRegex(RuntimeError,'pruebas aprobadas'):
                    generator.generate(offline=True)
            self.assertEqual(json.loads(target.read_text()),{'schema':1})

    def test_passing_evidence_generates_atomic_artifact_and_carries_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'manifest.json';previous={'schema':1,'current':{'controls':[]}}
            target.write_text(json.dumps(previous),encoding='utf-8')
            evidence=Path(folder)/'evidence.json';evidence.write_text(json.dumps({'sourceHash':'new','passed':True}),encoding='utf-8')
            def build(command,**kwargs):
                data=json.loads(Path(command[-2]).read_text(encoding='utf-8'))
                self.assertEqual(data['previous'],previous);self.assertEqual(data['buildId'],'release')
                Path(command[-1]).write_text(json.dumps({'schema':1,'current':{'sourceHash':'new'}}),encoding='utf-8')
            with patch.object(generator,'MANIFEST',target),patch.object(generator,'EVIDENCE',evidence),patch.object(generator.subprocess,'check_output',return_value='new'),patch.object(generator.subprocess,'run',side_effect=build):
                generator.generate(build_id='release',offline=True)
            self.assertEqual(json.loads(target.read_text())['current']['sourceHash'],'new')
            self.assertFalse(target.with_suffix('.tmp').exists())

    def test_failed_previous_release_lookup_does_not_replace_history(self):
        with patch.object(generator,'urlopen',side_effect=HTTPError('https://fixture.test',503,'unavailable',{},None)):
            with self.assertRaisesRegex(RuntimeError,'versión funcional publicada'):
                generator.generate()

    def test_incompatible_published_inventory_blocks_publication(self):
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"schema":99}'
        with patch.object(generator,'urlopen',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'esquema válido'):
                generator.generate()
