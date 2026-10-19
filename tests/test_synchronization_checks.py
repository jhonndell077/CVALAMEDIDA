import unittest
import hashlib
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask, g, jsonify, request
import synchronization_checks as checks
import resume_routes


FOLDER = {'mimeType':'application/vnd.google-apps.folder',
          'capabilities':{'canListChildren':True,'canAddChildren':True}}


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status_code = status


class SynchronizationChecksTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.core = SimpleNamespace(g=g, request=request, jsonify=jsonify, AppError=AppError,
            account_state=SimpleNamespace(BANK_CONFIG={'folder_id':'bank'}, ARCHIVE_CONFIG={'folder_id':'archive'}),
            verify_google_identity=Mock(side_effect=lambda:setattr(g, 'google_identity', {'uid':'user'})),
            drive_request=Mock(return_value=FOLDER))
        self.stages = patch.object(checks.architecture_diagnostics, 'stage', side_effect=lambda *args:nullcontext())
        self.stage = self.stages.start()
        self.addCleanup(self.stages.stop)

    def grant(self, scopes=None):
        return Mock(side_effect=lambda:jsonify(scope=' '.join(scopes if scopes is not None else checks.DRIVE_SCOPES | {checks.GMAIL_SCOPE}), expires_in=3600))

    def test_verifies_identity_scopes_and_both_folders_without_writing(self):
        with self.app.test_request_context(headers={'X-Drive-Access-Token':'fixture'}):
            result = checks.verify(self.core, self.grant())
            self.assertTrue(result.json['ok'])
            self.assertEqual([item['id'] for item in result.json['checks']], ['drive-authorization','gmail-authorization','bank','archive'])
            self.assertNotIn('fixture', result.get_data(as_text=True))
            self.assertEqual(self.core.drive_request.call_count, 2)
            self.assertIn('/bank?', self.core.drive_request.call_args_list[0].args[0])
            self.assertIn('/archive?', self.core.drive_request.call_args_list[1].args[0])
            self.core.verify_google_identity.assert_called_once()
            self.assertEqual([call.args[1:] for call in self.stage.call_args_list], [
                ('google','drive-api','oauth-authorization'), ('google','gmail','oauth-authorization'),
                ('bank','drive-api','drive-readback'), ('drive','drive-api','drive-readback')])

    def test_missing_scope_blocks_success_and_folder_checks(self):
        for scopes in (checks.DRIVE_SCOPES, {checks.GMAIL_SCOPE}):
            with self.subTest(scopes=scopes), self.app.test_request_context():
                with self.assertRaises(AppError) as error:
                    checks.verify(self.core, self.grant(scopes))
                self.assertEqual(error.exception.status_code, 403)
        self.core.drive_request.assert_not_called()

    def test_missing_account_record_does_not_use_legacy_folders(self):
        marker = checks.user_accounts.CURRENT.set({'uid':'new-user','record':None})
        try:
            with self.app.test_request_context():
                grant = self.grant()
                with self.assertRaises(AppError) as error:
                    checks.verify(self.core, grant)
                self.assertEqual(error.exception.status_code, 409)
                grant.assert_not_called()
        finally:
            checks.user_accounts.CURRENT.reset(marker)

    def test_invalid_archive_and_provider_failure_never_report_success(self):
        for metadata in ({'mimeType':'application/pdf'}, {'mimeType':'application/vnd.google-apps.folder','trashed':True}):
            with self.subTest(metadata=metadata), self.app.test_request_context():
                self.core.drive_request.side_effect=[FOLDER,metadata]
                with self.assertRaises(AppError): checks.verify(self.core, self.grant())
        with self.app.test_request_context():
            self.core.drive_request.side_effect=RuntimeError('private-provider-content')
            with self.assertRaises(AppError) as error: checks.verify(self.core, self.grant())
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn('private-provider-content',str(error.exception))

    def test_grant_failure_does_not_probe_folders(self):
        with self.app.test_request_context():
            with self.assertRaises(AppError):
                checks.verify(self.core, Mock(side_effect=AppError('Google rechazó la autorización.',401)))
            self.core.drive_request.assert_not_called()

    def test_authentication_noop_cannot_verify_without_uid(self):
        self.core.verify_google_identity.side_effect = None
        with self.app.test_request_context():
            grant = self.grant()
            with self.assertRaises(AppError) as error: checks.verify(self.core, grant)
            self.assertEqual(error.exception.status_code, 401)
            grant.assert_not_called()
            self.core.drive_request.assert_not_called()

    def test_folder_capabilities_are_required_including_missing_values(self):
        for capabilities in ({}, {'canListChildren':False}, {'canListChildren':True,'canAddChildren':False}):
            with self.subTest(capabilities=capabilities), self.app.test_request_context():
                self.core.drive_request.return_value = {'mimeType':'application/vnd.google-apps.folder','capabilities':capabilities}
                with self.assertRaises(AppError) as error: checks.verify(self.core, self.grant())
                self.assertEqual(error.exception.status_code, 403)


class SynchronizationIntegrationTests(unittest.TestCase):
    def test_registered_endpoint_records_real_stage_results_for_account_and_operation(self):
        app = Flask(__name__)
        identity = {'uid':'normal-user','email':'user@example.test'}
        def authenticate(): g.google_identity = identity
        core = SimpleNamespace(app=app,g=g,request=request,jsonify=jsonify,AppError=AppError,
            ORIGINAL_OWNER_EMAIL='other-owner@example.test', verify_google_identity=authenticate,
            account_state=SimpleNamespace(BANK_CONFIG={'folder_id':'bank'},
                ARCHIVE_CONFIG={'folder_id':'archive','allowed_email':identity['email']}))
        def drive_read(url, token):
            if 'userinfo' in url: return {'email':identity['email'],'email_verified':True}
            return FOLDER
        core.drive_request = Mock(side_effect=drive_read)
        @app.errorhandler(AppError)
        def failed(error): return jsonify(error=str(error)), error.status_code
        with patch.object(checks.architecture_diagnostics.diagnostic_store, 'cloud_runtime', return_value=False):
            checks.architecture_diagnostics.register_routes(core)
        resume_routes.register_routes(core)
        grant = SimpleNamespace(ok=True,json=lambda:{'scope':' '.join(checks.DRIVE_SCOPES | {checks.GMAIL_SCOPE}),'expires_in':3600})
        operation = 'a'*32
        with patch.object(resume_routes.requests, 'post', return_value=grant):
            response = app.test_client().post('/api/account/connections/verify',
                headers={'X-Drive-Access-Token':'private-fixture','X-CV-Operation-ID':operation})
        self.assertEqual(response.status_code, 200)
        events = app.extensions['architecture_diagnostics'].snapshot()
        stages = [event for event in events if event['stage'] != 'http-backend']
        self.assertEqual(len(stages), 4)
        for event in stages:
            self.assertEqual(event['operationId'], operation)
            self.assertEqual(event['accountKey'], hashlib.sha256(identity['uid'].encode()).hexdigest())
            self.assertEqual(event['correlationId'], response.headers['X-Correlation-ID'])
            self.assertEqual(event['result'], 'success')
            self.assertTrue(event['confirmed'])
        self.assertNotIn('private-fixture', str(events))
        def read_only_archive(url, token):
            if '/archive?' in url:
                return {'mimeType':'application/vnd.google-apps.folder','capabilities':{'canAddChildren':False}}
            return drive_read(url, token)
        core.drive_request.side_effect = read_only_archive
        failed_operation = 'b'*32
        with patch.object(resume_routes.requests, 'post', return_value=grant):
            failed_response = app.test_client().post('/api/account/connections/verify',
                headers={'X-Drive-Access-Token':'private-fixture','X-CV-Operation-ID':failed_operation})
        self.assertEqual(failed_response.status_code, 403)
        failures = [event for event in app.extensions['architecture_diagnostics'].snapshot()
                    if event['operationId'] == failed_operation and event['stage'] == 'drive-readback' and event['component'] == 'drive']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['result'], 'error')
        self.assertEqual(failures[0]['code'], 403)
        self.assertTrue(failures[0]['confirmed'])


if __name__ == '__main__':
    unittest.main()
