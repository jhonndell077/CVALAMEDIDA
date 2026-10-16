"""Storage reads must distinguish missing objects from superseded generations."""
import json
import unittest
from unittest.mock import MagicMock, patch
from google.api_core.exceptions import NotFound, PreconditionFailed
import job_runtime


class StorageConsistencyTests(unittest.TestCase):
    def store(self, blob):
        with patch('job_runtime.storage.Client') as client:
            client.return_value.bucket.return_value.blob.return_value = blob
            return job_runtime.JobStore()

    def test_replaced_generation_is_retried_instead_of_reporting_missing_job(self):
        blob = MagicMock(generation=2)
        blob.download_as_text.side_effect = [NotFound('old generation removed'), '{"state":"done"}']
        result, generation = self.store(blob).read('web-fixture')
        self.assertEqual(result, {'state': 'done'})
        self.assertEqual(generation, 2)
        self.assertEqual(blob.reload.call_count, 2)

    def test_generation_precondition_conflict_is_retried(self):
        blob = MagicMock(generation=2)
        blob.download_as_text.side_effect = [PreconditionFailed('concurrent write'), '{"state":"done"}']
        self.assertEqual(self.store(blob).read('web-fixture')[0], {'state': 'done'})

    def test_actually_absent_object_remains_absent(self):
        blob = MagicMock()
        blob.reload.side_effect = NotFound('missing metadata')
        self.assertEqual(self.store(blob).read('web-fixture'), (None, 0))
        blob.download_as_text.assert_not_called()

    def test_continuous_generation_churn_returns_transient_error_not_missing(self):
        blob = MagicMock(generation=2)
        blob.download_as_text.side_effect = NotFound('superseded generation')
        with self.assertRaises(job_runtime.JobError):
            self.store(blob).read('web-fixture')
        self.assertLessEqual(blob.reload.call_count, 4)


if __name__ == '__main__':
    unittest.main()
