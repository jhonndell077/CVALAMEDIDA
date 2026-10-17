import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from google.api_core.exceptions import NotFound, PreconditionFailed
import diagnostic_store as ds


def event(number=1, **changes):
    result = dict(id=f'{number:032x}', correlationId='a'*32, operationId='b'*32,
                  component='pdf', service='drive-api', endpoint='/export',
                  at=datetime.now(timezone.utc).isoformat(), result='error', code=403,
                  stage='drive-upload', confirmed=True, durationMs=5)
    result.update(changes)
    return result


class Bucket:
    def __init__(self):
        self.data = None
        self.generation = 0
        self.writes = 0
        self.conflicts = 0

    def blob(self, name):
        self.last_name = name
        bucket = self
        class Blob:
            generation = None
            size = None
            def reload(self, **kwargs):
                if bucket.data is None:
                    raise NotFound('missing')
                self.generation = bucket.generation
                self.size = len(bucket.data)
            def download_as_text(self, if_generation_match, **kwargs):
                if if_generation_match != bucket.generation:
                    raise PreconditionFailed('changed')
                return bucket.data
            def upload_from_string(self, data, if_generation_match, **kwargs):
                if bucket.conflicts:
                    bucket.conflicts -= 1
                    raise PreconditionFailed('changed')
                if if_generation_match != bucket.generation:
                    raise PreconditionFailed('changed')
                bucket.data = data
                bucket.generation += 1
                bucket.writes += 1
        return Blob()


class DiagnosticStoreTests(unittest.TestCase):
    def setUp(self):
        self.bucket = Bucket()
        self.store = ds.DiagnosticStore({'pdf', 'drive-api'}, {'/export'}, bucket=self.bucket)

    def test_shared_instances_and_batch_once(self):
        self.store.append_batch([event(), event(2)])
        other = ds.DiagnosticStore({'pdf', 'drive-api'}, {'/export'}, bucket=self.bucket)
        self.assertEqual(len(other.snapshot()), 2)
        self.assertEqual(self.bucket.writes, 1)
        self.assertEqual(self.bucket.last_name, ds.OBJECT_NAME)
        self.assertEqual(self.bucket.writes, 1)  # read never rewrites/deletes

    def test_generation_conflict_retry_and_no_duplicate(self):
        self.bucket.conflicts = 1
        self.store.append_batch([event()])
        self.store.append_batch([event()])
        self.assertEqual(len(self.store.snapshot()), 1)

    def test_conflict_exhaustion_propagates_for_caller_fallback(self):
        self.bucket.conflicts = 10
        with self.assertRaises(PreconditionFailed):
            self.store.append_batch([event()])
        self.assertEqual(self.bucket.writes, 0)

    def test_retention_bound_and_sensitive_fields_stripped(self):
        self.store.append_batch([event(i, token='private', cv='sensitive') for i in range(500)])
        self.assertEqual(len(self.store.snapshot()), ds.MAX_EVENTS)
        self.assertNotIn('private', self.bucket.data)
        self.assertNotIn('sensitive', self.bucket.data)
        with patch.object(self.store, 'clock', return_value=__import__('time').time()+3602):
            self.assertEqual(self.store.snapshot(), [])
        self.assertEqual(self.bucket.writes, 1)

    def test_bad_identifiers_payloads_and_future_events_rejected(self):
        self.store.append_batch([event(operationId='sensitive-user-email'), event(2, component='email'), event(3, endpoint='/export?token=private'), event(4, at='2099-01-01T00:00:00+00:00')])
        self.assertIsNone(self.bucket.data)

    def test_nonfinite_duration_and_uuid_operation(self):
        self.store.append_batch([event(durationMs=float('nan'), operationId='12345678-1234-1234-1234-123456789abc')])
        self.assertIsNone(self.store.snapshot()[0]['durationMs'])

    def test_distributed_hash_operation_retained(self):
        self.store.append_batch([event(operationId='a'*64)])
        self.assertEqual(self.store.snapshot()[0]['operationId'], 'a'*64)

    def test_newest_existing_survives_older_batch(self):
        self.store.append_batch([event(i) for i in range(400)])
        older = event(999, at=datetime.fromtimestamp(__import__('time').time()-120, timezone.utc).isoformat())
        self.store.append_batch([older])
        self.assertEqual(len(self.store.snapshot()), 400)
        self.assertNotIn(older['id'], [item['id'] for item in self.store.snapshot()])

    def test_corrupt_snapshot_fails_without_overwriting(self):
        self.bucket.data = json.dumps({'events': 'bad'})
        with self.assertRaises(ValueError):
            self.store.append_batch([event()])
        self.assertEqual(self.bucket.writes, 0)

    def test_local_does_not_create_client(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(ds.cloud_runtime())
        with patch.dict('os.environ', {'K_SERVICE': 'api'}, clear=True):
            self.assertTrue(ds.cloud_runtime())

class DiagnosticIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.test_architecture_diagnostics import DiagnosticsTests
        self.fixture = DiagnosticsTests()
        self.fixture.setUp()

    def test_request_writes_one_batch_and_failure_is_open(self):
        from unittest.mock import Mock
        shared = Mock()
        self.fixture.core.app.extensions['architecture_shared_diagnostics'] = shared
        response = self.fixture.client.post('/api/export/pdf', headers={'X-CV-Operation-ID': 'c'*32})
        self.assertEqual(response.status_code, 200)
        shared.append_batch.assert_called_once()
        batch = shared.append_batch.call_args.args[0]
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]['operationId'], 'c'*32)
        shared.append_batch.side_effect = RuntimeError('telemetry unavailable')
        self.assertEqual(self.fixture.client.post('/api/export/pdf').status_code, 200)

    def test_shared_read_failure_is_explicit(self):
        from unittest.mock import Mock
        shared = Mock()
        shared.snapshot.side_effect = RuntimeError('unavailable')
        self.fixture.core.app.extensions['architecture_shared_diagnostics'] = shared
        self.fixture.client.post('/api/export/pdf')
        payload = self.fixture.snapshot().json
        self.assertFalse(payload['retention']['sharedAvailable'])
        self.assertIn('no disponible', payload['retention']['scope'])
        self.assertEqual(len(payload['events']), 1)

    def test_client_warning_code_allowlist(self):
        self.store = ds.DiagnosticStore({'pdf', 'drive-api'}, {'/export'}, bucket=Bucket())
        self.store.append_batch([event(stage='oauth-authorization', confirmed=False, code='access_denied'),
                                 event(2, stage='oauth-authorization', confirmed=True, code='access_denied'),
                                 event(3, stage='oauth-authorization', confirmed=False, code='secret')])
        codes = [item['code'] for item in self.store.snapshot()]
        self.assertEqual(codes, ['access_denied', None, None])


if __name__ == '__main__':
    unittest.main()
