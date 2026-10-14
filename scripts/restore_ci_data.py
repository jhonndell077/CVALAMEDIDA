"""Restore runtime files from an encrypted GitHub secret, never from source control."""
import json
import os
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1] / 'data'
payload = os.environ.get('CV_BOOTSTRAP_DATA')
if not payload:
    raise SystemExit('Configure the CV_BOOTSTRAP_DATA GitHub Actions secret before deploying.')
data = json.loads(payload)
expected = {'master_profile.json', 'bank_config.json', 'archive_config.json'}
if not isinstance(data, dict) or set(data) != expected or any(not isinstance(value, dict) for value in data.values()):
    raise SystemExit('The private bootstrap configuration has an invalid structure.')
root.mkdir(exist_ok=True)
for name in expected:
    (root / name).write_text(json.dumps(data[name], ensure_ascii=False), encoding='utf-8')
# Unit tests need an image fixture. It is removed before the Firebase deployment.
Image.new('RGB', (40, 50), 'white').save(root / 'hoja_de_vida.jpeg', format='JPEG')
