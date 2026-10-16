import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import connection_probes as p


def response(data=None, status=200):
    return SimpleNamespace(status_code=status,ok=status<400,json=lambda:data or {})


class ProbeTests(unittest.TestCase):
    def setUp(self):
        p._cache.clear()
        p._push_pending.clear()

    def test_push_targets_only_registered_owner_and_requires_receipt(self):
        identity={'uid':'owner','email':'owner@example.test'}
        nonce='12345678-1234-1234-1234-123456789abc'
        with self.assertRaises(p.ProbeFailure):p.send_push_probe(identity,'endpoint','bad')
        with patch.object(p.job_runtime,'JobStore') as store,patch('web_notifications.configuration',return_value={'private_key':'fixture'}),patch('web_notifications.valid_subscription',return_value=True),patch('pywebpush.webpush') as send:
            store.return_value.read.return_value=({'subscriptions':{}},0)
            with self.assertRaises(p.ProbeFailure):p.send_push_probe(identity,'endpoint',nonce)
            send.assert_not_called()
            store.return_value.read.return_value=({'subscriptions':{'registered':{'endpoint':'endpoint'}}},0)
            self.assertIn('esperando',p.send_push_probe(identity,'endpoint',nonce))
            self.assertIsNone(p.cached_check('owner','push'))
            with self.assertRaises(p.ProbeFailure):p.send_push_probe(identity,'endpoint',nonce)
            with self.assertRaises(p.ProbeFailure):p.confirm_push_probe('other',nonce)
            with self.assertRaises(p.ProbeFailure):p.confirm_push_probe('owner','wrong')
            self.assertEqual(p.confirm_push_probe('owner',nonce)['state'],'ok')
            self.assertIn('No acredita',p.cached_check('owner','push')['detail'])
            with self.assertRaises(p.ProbeFailure):p.confirm_push_probe('owner',nonce)

    def test_exception_values_are_never_returned(self):
        def fail():raise RuntimeError('secret-value')
        result=p.checked('x',fail)
        self.assertEqual(result['state'],'unknown')
        self.assertNotIn('secret-value',str(result))
        self.assertEqual(p.checked('x',lambda:'passed')['state'],'ok')
        def expected():raise p.ProbeFailure('safe')
        self.assertEqual(p.checked('x',expected)['state'],'error')

    def test_http_failures_classify_access_separately(self):
        for status in (401,403,429,500):
            with self.assertRaises(p.ProbeFailure) as error:p.response_json(response(status=status))
            self.assertEqual(error.exception.state,'unknown' if status in (401,403) else 'error')
        self.assertEqual(p.response_json(response({'ok':True})),{'ok':True})

    def test_cache_is_owner_scoped_and_expires(self):
        p.remember('owner',{'id':'gmail','state':'ok'},300)
        self.assertEqual(p.cached_check('owner','gmail')['state'],'ok')
        self.assertIsNone(p.cached_check('other','gmail'))
        with patch.object(p.time,'monotonic',return_value=10**15):self.assertIsNone(p.cached_check('owner','gmail'))

    def test_cloud_get_has_bounded_timeout(self):
        with patch('google.auth.default',return_value=('credential','project')),patch('google.auth.transport.requests.AuthorizedSession') as session:
            session.return_value.__enter__.return_value.get.return_value=response({'state':'RUNNING'})
            self.assertEqual(p.cloud_get('https://example.test')['state'],'RUNNING')
            self.assertEqual(session.return_value.__enter__.return_value.get.call_args.kwargs['timeout'],12)

    def test_drive_only_reads_metadata_and_closes(self):
        with patch('drive_bank.DriveBank') as bank:
            bank.return_value.session.get.return_value=response({'mimeType':'application/vnd.google-apps.folder'})
            self.assertIn('Drive respondió',p.drive({'folder_id':'bank','service_account':'bank@example.test'},{'folder_id':'archive'}))
            self.assertEqual(bank.return_value.session.get.call_count,1)
            self.assertEqual(bank.return_value.session.get.call_args.kwargs['params']['fields'],'id,mimeType,trashed')
            bank.return_value._session.close.assert_called_once()
            bank.return_value.session.get.return_value=response({'trashed':True})
            with self.assertRaises(p.ProbeFailure):p.drive({'folder_id':'bank','service_account':'bank@example.test'},{'folder_id':'archive'})
        with self.assertRaises(p.ProbeFailure):p.drive({}, {})

    def test_storage_reads_metadata(self):
        with patch('google.cloud.storage.Client') as client:
            client.return_value.__enter__.return_value.list_blobs.return_value=[]
            self.assertIn('metadatos',p.storage())
            client.return_value.__enter__.return_value.list_blobs.assert_called_once()

    def test_queue_must_be_running(self):
        with patch.object(p,'cloud_get',return_value={'state':'RUNNING'}):self.assertIn('RUNNING',p.tasks())
        with patch.object(p,'cloud_get',return_value={'state':'PAUSED'}):
            with self.assertRaises(p.ProbeFailure):p.tasks()

    def test_worker_requires_explicit_success_contract(self):
        with patch('google.oauth2.id_token.fetch_id_token',return_value='fixture'),patch.object(p.requests,'get',return_value=response({'ok':True,'service':'telegram_worker'})) as get:
            self.assertIn('autenticada',p.worker())
            self.assertEqual(get.call_args.kwargs['timeout'],15)
            get.return_value=response({'ok':True})
            with self.assertRaises(p.ProbeFailure):p.worker()

    def test_worker_health_accepts_only_runtime_identity_and_audience(self):
        request=SimpleNamespace(headers={})
        self.assertEqual(p.worker_health(request)[1],401)
        request.headers={'Authorization':'Bearer fixture'}
        with patch('google.oauth2.id_token.verify_oauth2_token',return_value={'email':'cv-runtime@'+p.job_runtime.PROJECT+'.iam.gserviceaccount.com','email_verified':True}) as verify:
            self.assertEqual(p.worker_health(request)[1],200)
            self.assertTrue(verify.call_args.kwargs['audience'].endswith('/telegram_worker'))
            verify.return_value={'email':'other','email_verified':True}
            self.assertEqual(p.worker_health(request)[1],403)
            verify.side_effect=ValueError('secret')
            self.assertEqual(p.worker_health(request),({'error':'Unauthorized'},401))

    def test_vertex_runs_only_synthetic_prompt_and_closes(self):
        with patch('google.genai.Client') as client:
            client.return_value.models.generate_content.return_value=SimpleNamespace(text='{"ok":true}')
            self.assertIn('sintético',p.vertex('gemini-3.8-flash'))
            self.assertNotIn('laboral',client.return_value.models.generate_content.call_args.kwargs['contents'])
            client.return_value.close.assert_called_once()
            client.return_value.models.generate_content.return_value=SimpleNamespace(text='{}')
            with self.assertRaises(p.ProbeFailure):p.vertex('other')

    def test_telegram_checks_identity_webhook_and_recent_errors_without_sending(self):
        bot={'ok':True,'result':{'is_bot':True}}
        webhook={'ok':True,'result':{'url':'https://cvalamedida.web.app/telegram/webhook'}}
        with patch.object(p.job_runtime,'configuration',return_value={'bot_token':'fixture'}),patch.object(p.requests,'get',side_effect=[response(bot),response(webhook)]) as get:
            self.assertIn('No se enviaron',p.telegram())
            self.assertTrue(all(call.args[0].endswith(('getMe','getWebhookInfo')) for call in get.call_args_list))
        with patch.object(p.job_runtime,'configuration',return_value={}):
            with self.assertRaises(p.ProbeFailure):p.telegram()
        for value in ({'url':'https://wrong.invalid'}, {'url':webhook['result']['url'],'last_error_date':p.time.time()}):
            with patch.object(p.job_runtime,'configuration',return_value={'bot_token':'fixture'}),patch.object(p.requests,'get',side_effect=[response(bot),response({'ok':True,'result':value})]):
                with self.assertRaises(p.ProbeFailure):p.telegram()

    def test_push_never_claims_delivery_from_configuration(self):
        with patch('google.cloud.storage.Client') as client:
            for blob in (None,object()):
                client.return_value.__enter__.return_value.bucket.return_value.get_blob.return_value=blob
                with self.assertRaises(p.ProbeFailure) as error:p.push('owner')
                self.assertEqual(error.exception.state,'unknown')

    def test_gmail_requires_same_verified_identity_and_effective_scope(self):
        identity={'email':'owner@example.test'}
        with self.assertRaises(p.ProbeFailure):p.gmail(identity,'')
        with patch.object(p.requests,'get',return_value=response({'email':'other','email_verified':True})):
            with self.assertRaises(p.ProbeFailure):p.gmail(identity,'fixture')
        with patch.object(p.requests,'get',return_value=response({'email':identity['email'],'email_verified':True})),patch.object(p.requests,'post',return_value=response({'scope':'https://www.googleapis.com/auth/gmail.send'})) as post:
            self.assertIn('No se envió',p.gmail(identity,'fixture'))
            self.assertNotIn('fixture',post.call_args.args[0])
            post.return_value=response({'scope':''})
            with self.assertRaises(p.ProbeFailure):p.gmail(identity,'fixture')

    def test_inspection_caches_individual_services(self):
        core=SimpleNamespace(account_state=SimpleNamespace(BANK_CONFIG={},ARCHIVE_CONFIG={}),VERTEX_MODEL='model')
        names=('drive','storage','tasks','worker','vertex','telegram','push')
        from contextlib import ExitStack
        with ExitStack() as stack:
            mocks=[stack.enter_context(patch.object(p,name,return_value='safe')) for name in names]
            first=p.inspect(core,{'uid':'owner'});second=p.inspect(core,{'uid':'owner'})
            self.assertEqual(len(first),7)
            self.assertEqual(first,second)
            self.assertTrue(all(mock.call_count==1 for mock in mocks))
