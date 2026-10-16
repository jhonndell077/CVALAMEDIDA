"""Check direct pins against a fully hashed lock without network access."""
from pathlib import Path
import re
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def entries(text, hashed=False):
    result = {}
    for raw in re.sub(r'\\\r?\n', '', text).splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line.split(' --hash=')[0].strip())
        specs = list(requirement.specifier)
        if requirement.url or len(specs) != 1 or specs[0].operator != '==' or '*' in specs[0].version:
            raise ValueError('Cada dependencia debe tener una versión exacta de registro.')
        if hashed and not re.search(r'--hash=sha256:[0-9a-f]{64}(?:\s|$)', line):
            raise ValueError('Cada dependencia del lock necesita un hash SHA-256.')
        result.setdefault(canonicalize_name(requirement.name), set()).add(specs[0].version)
    return result


def verify(root):
    for base in ('requirements', 'requirements-dev'):
        direct = entries((root / (base + '.in')).read_text(encoding='utf-8-sig'))
        locked = entries((root / (base + '.txt')).read_text(encoding='utf-8-sig'), hashed=True)
        if not direct or not all(locked.get(name) == versions for name, versions in direct.items()):
            raise ValueError(f'{base}: el lock no coincide con las dependencias directas.')


if __name__ == '__main__':
    verify(Path(__file__).resolve().parents[1])
    print('Runtime and tool dependency locks match exact direct pins and contain SHA-256 hashes.')
