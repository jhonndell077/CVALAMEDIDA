import unittest
from unittest.mock import patch
import account_writes
import app
import background_jobs as jobs
import web_notifications
from tests.test_background_jobs import Store, job, ID

class NotificationReleaseTests(unittest.TestCase):
    def test_notification_runs_after_account_release_and_allows_next_operation(self):
        store=Store();job(store,owner_uid='fixture')
        def complete(*args):
            data,version=store.read(ID);data['state']='done';store.write(ID,data,version)
        def notification(*args):
            self.assertIsNone(account_writes.current())
            self.assertEqual(store.read(account_writes.key('fixture'))[0]['state'],'released')
            with account_writes.reserve(store,'fixture','next-stage'):
                pass
        with patch.object(jobs,'_process_owned_job',side_effect=complete),patch.object(web_notifications,'notify',side_effect=notification) as notify:
            jobs.process_job(app,ID,store);jobs.process_job(app,ID,store)
        notify.assert_called_once()

    def test_notification_failure_does_not_change_confirmed_result_or_keep_reservation(self):
        store=Store();job(store,owner_uid='fixture')
        def complete(*args):
            data,version=store.read(ID);data.update(state='done',result={'ok':True});store.write(ID,data,version)
        with patch.object(jobs,'_process_owned_job',side_effect=complete),patch.object(web_notifications,'notify',side_effect=RuntimeError('Fixture')):
            jobs.process_job(app,ID,store)
        self.assertEqual(store.read(ID)[0]['state'],'done')
        self.assertEqual(store.read(account_writes.key('fixture'))[0]['state'],'released')
