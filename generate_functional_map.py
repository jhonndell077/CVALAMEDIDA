"""Publish a source-bound functional inventory; never reuse stale passing checks."""
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'static' / 'functional-map.manifest.json'
EVIDENCE = ROOT / 'tmp' / 'functional-map-test-evidence.json'


def generate(build_id=None, offline=False):
    previous = None
    if offline:
        if MANIFEST.exists():
            previous = json.loads(MANIFEST.read_text(encoding='utf-8'))
    else:
        try:
            with urlopen('https://cvalamedida.web.app/functional-map.manifest.json', timeout=20) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise RuntimeError('El historial funcional excede el tamaño permitido.')
                previous = json.loads(raw)
        except HTTPError as error:
            if error.code != 404:
                raise RuntimeError('No se pudo consultar la versión funcional publicada.') from None
        if previous and (previous.get('schema') != 1 or not isinstance(previous.get('current', {}).get('controls'), list)):
            raise RuntimeError('El historial funcional publicado no tiene un esquema válido.')
    evidence = json.loads(EVIDENCE.read_text(encoding='utf-8')) if EVIDENCE.exists() else None
    current_hash = subprocess.check_output(['node', str(ROOT / 'generate_functional_map.cjs'), '--hash'], cwd=ROOT, text=True).strip()
    if not evidence or evidence.get('sourceHash') != current_hash or evidence.get('passed') is not True:
        raise RuntimeError('Ejecuta scripts/verify_release.py: faltan pruebas aprobadas para este código.')
    with tempfile.TemporaryDirectory(prefix='cv-functional-') as folder:
        input_path, output_path = Path(folder) / 'input.json', Path(folder) / 'map.json'
        input_path.write_text(json.dumps({'previous': previous, 'evidence': evidence, 'buildId': build_id}), encoding='utf-8')
        subprocess.run(['node', str(ROOT / 'generate_functional_map.cjs'), '--build', str(input_path), str(output_path)], cwd=ROOT, check=True)
        staging = MANIFEST.with_suffix('.tmp')
        staging.write_bytes(output_path.read_bytes())
        staging.replace(MANIFEST)
    print('Mapa funcional generado y vinculado a pruebas aprobadas.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    generate(offline=parser.parse_args().offline)
