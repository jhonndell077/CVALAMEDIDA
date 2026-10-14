import unittest
from unittest.mock import MagicMock, patch
from google.genai.errors import ClientError
import app as cv_app
import vertex_retry


class VertexCapacityTests(unittest.TestCase):
    def test_schema_rejection_falls_back_once_to_validated_json_mode(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [ClientError(400, {'error': {'message': 'Request contains an invalid argument.'}}), MagicMock(text='{"ok":true}')]
        with patch.dict('os.environ', {'GOOGLE_CLOUD_PROJECT': 'test'}), patch('google.genai.Client', return_value=client):
            self.assertEqual(cv_app.vertex_json('test', 'evidence', [], {'type': 'object'}), '{"ok":true}')
        calls = client.models.generate_content.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(calls[0].kwargs['config'].response_schema)
        self.assertIsNone(calls[1].kwargs['config'].response_schema)
        self.assertEqual(calls[1].kwargs['config'].response_mime_type, 'application/json')
        self.assertEqual(calls[0].kwargs['contents'], calls[1].kwargs['contents'])

    def test_invalid_argument_fallback_does_not_loop(self):
        client = MagicMock()
        client.models.generate_content.side_effect = ClientError(400, {'error': {'message': 'Request contains an invalid argument.'}})
        with patch.dict('os.environ', {'GOOGLE_CLOUD_PROJECT': 'test'}), patch('google.genai.Client', return_value=client), self.assertRaises(cv_app.AppError):
            cv_app.vertex_json('test', 'evidence', [], {'type': 'object'})
        self.assertEqual(client.models.generate_content.call_count, 2)

    def test_total_budget_shortens_the_last_request(self):
        from google.genai import types
        elapsed=[0]
        timeouts=[]
        def request(**kwargs):
            timeout=kwargs['config'].http_options.timeout
            timeouts.append(timeout)
            elapsed[0]+=timeout/1000
            raise ClientError(504, {'error':{'message':'Deadline expired'}})
        client=MagicMock();client.models.generate_content.side_effect=request
        with patch('vertex_retry.time.monotonic',side_effect=lambda:elapsed[0]),patch('vertex_retry.time.sleep',side_effect=lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds)),patch('vertex_retry.random.uniform',return_value=0),self.assertRaises(ClientError):
            vertex_retry.generate_content(client,config=types.GenerateContentConfig())
        self.assertEqual(timeouts,[75000,75000,24000])
        self.assertEqual(elapsed[0],180)

    def test_deadline_and_transport_timeout_retry(self):
        import httpx
        from google.genai import types
        for error in [ClientError(504, {"error":{"message":"Deadline expired"}}),httpx.ReadTimeout('timeout')]:
            client=MagicMock(); client.models.generate_content.side_effect=[error,'ok']
            with patch('vertex_retry.time.sleep'),patch('vertex_retry.random.uniform',return_value=0):
                self.assertEqual(vertex_retry.generate_content(client,model='gemini-3.8-flash',config=types.GenerateContentConfig()),'ok')
            self.assertEqual(client.models.generate_content.call_count,2)
            self.assertLessEqual(client.models.generate_content.call_args.kwargs['config'].http_options.timeout,75000)

    def test_capacity_error_retries_then_returns_the_real_response(self):
        client = MagicMock()
        expected = object()
        client.models.generate_content.side_effect = [ClientError(429, {"error": {"message": "Resource exhausted"}}), expected]
        with patch("vertex_retry.time.sleep") as sleep, patch("vertex_retry.random.uniform", return_value=0):
            result = vertex_retry.generate_content(client, model="test", contents=["same-request"])
        self.assertIs(result, expected)
        sleep.assert_called_once_with(2)
        self.assertEqual(client.models.generate_content.call_count, 2)
        self.assertEqual(client.models.generate_content.call_args_list[0], client.models.generate_content.call_args_list[1])

    def test_invalid_request_is_not_retried(self):
        client = MagicMock()
        client.models.generate_content.side_effect = ClientError(400, {"error": {"message": "Invalid argument"}})
        with patch("vertex_retry.time.sleep") as sleep, self.assertRaises(ClientError):
            vertex_retry.generate_content(client, model="test")
        sleep.assert_not_called()
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_exhausted_capacity_is_bounded_and_explained_in_spanish(self):
        client = MagicMock()
        client.models.generate_content.side_effect = ClientError(429, {"error": {"message": "Resource exhausted"}})
        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "test-project"}), \
             patch("google.genai.Client", return_value=client), \
             patch("vertex_retry.time.sleep") as sleep, patch("vertex_retry.random.uniform", return_value=0), \
             self.assertRaises(cv_app.AppError) as error:
            cv_app.vertex_json("test-model", "test prompt", [], {"type": "object"})
        self.assertEqual(client.models.generate_content.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        self.assertEqual(error.exception.status_code, 503)
        self.assertIn("dos reintentos", str(error.exception))


if __name__ == "__main__":
    unittest.main()
