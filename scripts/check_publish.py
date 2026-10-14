"""Block accidental publication of private files or recognizable credentials."""
import re
import subprocess

files = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
patterns = [rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
            rb'gh[opusr]_[A-Za-z0-9]{30,}', rb'github_pat_[A-Za-z0-9_]{30,}', rb'1//[A-Za-z0-9_-]{40,}']
failures = []
for name in filter(None, files):
    if name.startswith(('data/', 'tmp/', 'auditoria/', '.firebase/')) or name.endswith(('.pdf', '.docx', '.pem', '.key')):
        failures.append(name); continue
    raw = subprocess.check_output(['git', 'show', ':' + name])
    if any(re.search(pattern, raw) for pattern in patterns): failures.append(name)
if failures:
    print('Excluded files or credential patterns detected. File locations only:')
    print('\n'.join(failures)); raise SystemExit(1)
print('Publication check passed; private data and credential patterns are excluded.')
