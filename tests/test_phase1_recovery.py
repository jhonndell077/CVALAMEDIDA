"""Phase 1 administrative regression: fake storage and mocked providers only."""
import unittest
from unittest.mock import patch
import admin_user_actions as actions
import admission_policy
import tests.test_admin_user_actions as fixtures


class TerminalRecoveryTests(unittest.TestCase):
    headers = fixtures.ActionTests.headers
    setUp = fixtures.ActionTests.setUp
    preview = fixtures.ActionTests.preview
    execute = fixtures.ActionTests.execute
    failed_before_delete = fixtures.ActionTests.failed_before_delete

    def test_failed_deletion_has_safe_terminal_evidence_in_plan_and_fence(self):
        plan = self.failed_before_delete()
        identifier = plan['planId'].split('.')[0]
        stored = self.store.read(actions._key(identifier))[0]
        fence = self.store.read(admission_policy.queue_key('alice'))[0]['maintenance']
        for record in (stored, fence):
            self.assertEqual(record['state'], 'failed')
            self.assertEqual(record['code'], 'admin_delete_failed')
            self.assertEqual(record['stage'], 'auth-revoke')
            self.assertRegex(record['correlationId'], r'^[a-f0-9]{32}$')
            self.assertGreater(record['finishedAt'], 0)
            self.assertNotIn('fixture-provider-error', str(record))
        self.assertEqual(stored['correlationId'], fence['correlationId'])

    def test_completed_recovery_replays_receipt_without_mutations_even_after_plan_ttl(self):
        self.failed_before_delete()
        plan = self.preview('recover_access').json
        first = self.execute(plan)
        self.assertEqual(first.status_code, 200)
        writes = len(self.store.writes)
        with patch.object(actions.time, 'time', return_value=plan['expiresAt'] + 100):
            replay = self.execute(plan)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.json, replay.json)
        self.assertEqual(len(self.store.writes), writes)
        self.delete.assert_not_called()

    def test_recovery_resumes_after_unlock_acknowledgement_failure_without_clearing_new_state(self):
        self.failed_before_delete()
        plan = self.preview('recover_access').json
        key = actions._key(plan['planId'].split('.')[0])
        write = self.store.write
        failed = False
        def fail_ack(identifier, value, generation):
            nonlocal failed
            if identifier == key and value.get('state') == 'completed' and not failed:
                failed = True
                raise RuntimeError('PRIVATE ACK FAILURE')
            return write(identifier, value, generation)
        with patch.object(self.store, 'write', side_effect=fail_ack):
            response = self.execute(plan)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE', response.text)
        queue_key = admission_policy.queue_key('alice')
        queue, generation = self.store.read(queue_key)
        queue['maintenance'] = {'action': 'unknown', 'at': 1}
        self.store.write(queue_key, queue, generation)
        replay = self.execute(plan)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(self.store.read(queue_key)[0]['maintenance']['action'], 'unknown')
