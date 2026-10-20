import types
import unittest
from unittest.mock import patch
from flask import Flask, g
import distributed_diagnostics as traces


class DistributedDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.fields = {'diagnostics_operation': 'a' * 64, 'diagnostics_correlation': 'b' * 32}

    def test_capture_preserves_operation_without_payload(self):
        with self.app.test_request_context('/'):
            g.architecture_observation = {'id': 'b' * 32, 'operationId': 'a' * 64, 'token': 'private'}
            self.assertEqual(traces.capture(), self.fields)
        self.assertEqual(traces.capture(), {})

    def test_worker_restore_and_exception_recovery(self):
        with self.app.test_request_context('/telegram/work'):
            original = {'id': 'c' * 32, 'endpoint': '/telegram/work'}
            g.architecture_observation = original
            with self.assertRaises(RuntimeError):
                with traces.restore(self.fields):
                    self.assertEqual(g.architecture_observation['id'], 'b' * 32)
                    self.assertEqual(g.architecture_observation['operationId'], 'a' * 64)
                    raise RuntimeError()
            self.assertIs(g.architecture_observation, original)

    def test_malformed_ids_cannot_poison_trace(self):
        with self.app.test_request_context('/'):
            original = {'id': 'c' * 32}
            g.architecture_observation = original
            with traces.restore({'diagnostics_operation': 'user@example.test', 'diagnostics_correlation': 'token'}):
                self.assertIs(g.architecture_observation, original)

    def test_telegram_retry_is_stable_and_distinct_update_is_separate(self):
        first = traces.telegram_trace(12345)
        self.assertEqual(first["diagnostics_operation"], traces.telegram_trace(12345)["diagnostics_operation"])
        self.assertEqual(len(first["diagnostics_correlation"]), 32)
        self.assertNotEqual(first["diagnostics_operation"], traces.telegram_trace(12346)["diagnostics_operation"])
        self.assertNotIn('12345', repr(first))

    def test_background_worker_restores_only_after_scope_validated(self):
        import background_jobs
        job = {**self.fields, 'owner_uid': 'fixture', 'owner_email': 'fixture@example.test'}
        from test_period_admission import Store
        store = Store()
        store.write('fixture', job, 0)
        entered = []
        class Scope:
            def __enter__(self): entered.append(True)
            def __exit__(self, *args): entered.append(False)
        core = types.SimpleNamespace(AppError=ValueError)
        def process(*args):
            self.assertEqual(entered, [True])
            self.assertEqual(g.architecture_observation['operationId'], 'a' * 64)
        with self.app.test_request_context('/telegram/work'), patch.object(background_jobs.notifications, 'unprotect', return_value={}), patch.object(background_jobs.user_accounts, 'scope', return_value=Scope()), patch.object(background_jobs, '_process_job', side_effect=process):
            background_jobs.process_job(core, 'fixture', store)
        self.assertEqual(entered, [True, False])

    def test_nested_export_evidence_reaches_outer_flush_batch(self):
        with self.app.test_request_context('/telegram/work'):
            original = {'id': 'c' * 32, 'endpoint': '/telegram/work', 'events': []}
            g.architecture_observation = original
            with traces.restore(self.fields):
                g.architecture_observation['events'].append({'stage': 'worker'})
                with self.app.test_request_context('/api/export/pdf'), traces.restore(self.fields):
                    g.architecture_observation['events'].append({'stage': 'pdf-generated'})
            self.assertIs(g.architecture_observation, original)
            self.assertEqual([e['stage'] for e in original['events']], ['worker', 'pdf-generated'])

    def test_nested_export_request_keeps_trace(self):
        with self.app.test_request_context('/telegram/work'), traces.restore(self.fields):
            with self.app.test_request_context('/api/export/pdf'), traces.restore(self.fields):
                self.assertEqual(traces.capture(), self.fields)
            self.assertEqual(traces.capture(), self.fields)


if __name__ == '__main__':
    unittest.main()
