"""Stamp the HTML and public version atomically before every Hosting deployment."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent / "static"


def generate():
    now = datetime.now(timezone.utc)
    build = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    from generate_functional_map import generate as generate_map
    generate_map(build_id=build)
    path = ROOT / "index.html"
    html = path.read_text(encoding="utf-8")
    tag = f'<meta name="cv-build" content="{build}">'
    if re.search(r'<meta name="cv-build" content="[^"]*">', html):
        html = re.sub(r'<meta name="cv-build" content="[^"]*">', tag, html)
    else:
        html = html.replace("<head>", "<head>\n    " + tag, 1)
    path.write_text(html, encoding="utf-8")
    (ROOT / "version.json").write_text(json.dumps({"buildId": build, "updatedAt": now.isoformat()}, indent=2), encoding="utf-8")
    print("Versión de Hosting preparada:", build)


if __name__ == "__main__":
    generate()
