"""Exercise the Functions Framework entry points offline, in a clean process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class FunctionBootstrapTests(unittest.TestCase):
    def test_api_and_worker_initialize_through_functions_framework(self):
        script = textwrap.dedent('''
            import json, socket
            def blocked(*args, **kwargs):
                raise RuntimeError('BOOTSTRAP_NETWORK_DISABLED')
            socket.create_connection = blocked
            socket.socket.connect = blocked
            socket.socket.connect_ex = blocked
            import google.auth
            google.auth.default = blocked
            from functions_framework import create_app
            api = create_app(target='api', source='main.py')
            response = api.test_client().get('/api/health')
            assert response.status_code == 200, response.status_code
            worker = create_app(target='telegram_worker', source='main.py')
            rejected = worker.test_client().get('/not-a-worker-route')
            assert rejected.status_code == 404, rejected.status_code
            print(json.dumps({'api_health': response.status_code, 'worker_route_guard': rejected.status_code}))
        ''')
        env = {**os.environ, 'CV_AUTH_REQUIRED': '0', 'CV_MULTI_ACCOUNT': '0',
               'CV_ALLOW_REMOTE': '0', 'CV_BANK_PROVIDER': 'local', 'CV_AI_PROVIDER': 'vertex'}
        result = subprocess.run([sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]),
                         {'api_health': 200, 'worker_route_guard': 404})
