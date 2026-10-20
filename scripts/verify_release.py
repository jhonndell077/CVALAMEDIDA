"""Shared release gate. Tests run in a disposable copy, with network disabled."""
from __future__ import annotations
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_COVERAGE = 82.96


def child(sandbox, output):
    import socket
    import unittest
    import coverage
    os.chdir(sandbox)
    sys.path[:0] = [str(sandbox), str(sandbox / 'tests')]
    for name in ('CV_MULTI_ACCOUNT', 'CV_AUTH_REQUIRED', 'CV_ALLOW_REMOTE',
                 'CV_BANK_PROVIDER', 'CV_ARCHIVE_PROVIDER', 'CV_AI_PROVIDER'):
        os.environ.pop(name, None)
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(sandbox / 'audit-no-credentials.json')
    def no_network(*args, **kwargs):
        raise OSError('RELEASE_TEST_NETWORK_DISABLED')
    socket.create_connection = no_network
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    import google.auth
    google.auth.default = no_network
    cov = coverage.Coverage(branch=True, source=[str(sandbox)],
        omit=['*/tests/*', '*/scripts/*', '*/main.py', '*/generate_*.py'],
        data_file=str(output / '.coverage'))
    cov.start()
    suite = unittest.defaultTestLoader.discover(str(sandbox / 'tests'), pattern='test_*.py')
    with (output / 'python-tests.txt').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    cov.stop(); cov.save()
    cov.json_report(outfile=str(output / 'coverage.json'))
    with (output / 'coverage.txt').open('w', encoding='utf-8') as stream:
        percent = cov.report(file=stream, show_missing=False)
    summary = {'tests': result.testsRun, 'failures': len(result.failures),
        'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_names': [str(test) for test, _ in result.failures + result.errors],
        'coverage_percent': round(percent, 2), 'minimum_coverage_percent': MINIMUM_COVERAGE,
        'coverage_passed': percent >= MINIMUM_COVERAGE, 'python': sys.version.split()[0],
        'network': 'blocked', 'original_runtime_files_modified': False}
    (output / 'python-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary))
    return 0 if result.wasSuccessful() and percent >= MINIMUM_COVERAGE else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', nargs=2, metavar=('SANDBOX', 'OUTPUT'))
    parser.add_argument('--output', default=str(ROOT / 'tmp' / 'verification'))
    args = parser.parse_args()
    if args.child:
        return child(*(Path(value) for value in args.child))
    from check_requirements import verify
    verify(ROOT)
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    source_hash = subprocess.check_output(['node', str(ROOT / 'generate_functional_map.cjs'), '--hash'], cwd=ROOT, text=True).strip()
    for path in ROOT.glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=path.name)
    for path in (ROOT / 'static').glob('*.js'):
        subprocess.run(['node', '--check', str(path)], check=True)
    with (output / 'node-tests.txt').open('w', encoding='utf-8') as stream:
        node = subprocess.run(['node', '--require', str(ROOT / 'scripts' / 'offline_node.cjs'), '--test', *map(str, sorted((ROOT / 'tests').glob('*.test.js'))),
                               *map(str, sorted((ROOT / 'tests').glob('*.test.cjs')))],
                              cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    with tempfile.TemporaryDirectory(prefix='cvalamedida-verification-') as directory:
        sandbox = Path(directory)
        for source in ROOT.glob('*.py'):
            shutil.copy2(source, sandbox / source.name)
        for name in ('static', 'tests'):
            shutil.copytree(ROOT / name, sandbox / name,
                ignore=shutil.ignore_patterns('node_modules', '__pycache__', '*.log'))
        shutil.copy2(ROOT / 'firebase.json', sandbox / 'firebase.json')
        (sandbox / 'data').mkdir()
        # Explicit runtime bootstrap only. Never copy token stores, .env or keys.
        for name in ('master_profile.json', 'bank_config.json', 'archive_config.json', 'hoja_de_vida.jpeg'):
            source = ROOT / 'data' / name
            if source.is_file(): shutil.copy2(source, sandbox / 'data' / name)
        backend = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child',
                                  str(sandbox), str(output)], cwd=ROOT)
    summary = {'frontend_exit': node.returncode, 'backend_exit': backend.returncode,
               'passed': node.returncode == backend.returncode == 0,
               'frontend_network': 'blocked', 'backend_network': 'blocked'}
    (output / 'release-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    python_summary = json.loads((output / 'python-summary.json').read_text(encoding='utf-8'))
    node_output = (output / 'node-tests.txt').read_text(encoding='utf-8')
    import re
    count = re.search(r'(?:#|ℹ) tests (\d+)', node_output)
    evidence = {'sourceHash': source_hash, 'passed': summary['passed'],
        'checkedAt': datetime.now(timezone.utc).isoformat(),
        'pythonTests': python_summary['tests'], 'javascriptTests': int(count.group(1)) if count else None,
        'coveragePercent': python_summary['coverage_percent'], 'network': 'blocked',
        'scope': 'Suite local; no acredita cada acción ni servicios desplegados.'}
    (ROOT / 'tmp').mkdir(exist_ok=True)
    (ROOT / 'tmp' / 'functional-map-test-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(summary))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
