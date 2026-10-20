"""CAS reservation tests use in-memory storage; every provider is a fixture."""
import unittest
from unittest.mock import Mock, patch
from google.api_core.exceptions import PreconditionFailed
import account_writes as writes
import admission_policy
import app
import job_runtime
import user_accounts as users
from test_period_admission import Store
REAL_JOB_STORE = job_runtime.JobStore


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.now = 1000
        clock = patch.object(writes.time, 'time', side_effect=lambda:self.now)
        clock.start(); self.addCleanup(clock.stop)

    def put(self, value):
        _, version = self.store.read(writes.key('alice'))
        self.store.write(writes.key('alice'), value, version)

    def test_expired_idle_holder_is_replaced_without_resetting_usage(self):
        self.put({'holder':'old','state':'held','expiresAt':self.now-1})
        queue = {'pending':[], 'usage':{'daily':2,'receipts':{'r':1}}}
        self.store.write(admission_policy.queue_key('alice'), queue, 0)
        with writes.reserve(self.store, 'alice', 'save') as lease:
            lease.check()
            with writes.effect(self.store, 'alice'):
                self.assertEqual(self.store.read(lease.key)[0]['state'], 'in_flight')
            self.assertEqual(self.store.read(lease.key)[0]['state'], 'held')
        self.assertEqual(self.store.read(admission_policy.queue_key('alice'))[0], queue)
        self.assertEqual(self.store.read(lease.key)[0]['state'], 'released')
        self.assertIsNone(writes.current())

    def test_inflight_and_unknown_writes_never_expire_into_new_permission(self):
        for state in ('in_flight', 'uncertain'):
            self.put({'holder':'old','state':state,'expiresAt':1})
            with self.assertRaises(writes.WriteBlocked) as caught:
                with writes.reserve(self.store, 'alice', 'delete'):
                    self.fail('must not acquire')
            self.assertEqual(caught.exception.code, 'account_write_outcome_unknown')
            self.assertEqual(self.store.read(writes.key('alice'))[0]['holder'], 'old')

    def test_live_inflight_and_held_writes_refuse_another_holder(self):
        for state in ('in_flight', 'held'):
            self.put({'holder':'other','state':state,'expiresAt':self.now+10})
            with patch.object(writes.time, 'sleep'), self.assertRaises(writes.WriteBlocked) as caught:
                with writes.reserve(self.store, 'alice', 'delete'): pass
            self.assertEqual(caught.exception.code, 'account_write_busy')

    def test_nested_same_account_reuses_holder_and_other_account_is_rejected(self):
        with writes.reserve(self.store, 'alice', 'request') as lease:
            with writes.reserve(self.store, 'alice', 'admit') as nested:
                self.assertIs(lease, nested)
            with self.assertRaises(writes.WriteBlocked):
                with writes.reserve(self.store, 'bob', 'save'): pass
            with self.assertRaises(writes.WriteBlocked):
                with writes.effect(self.store, 'bob'): pass
            with writes.effect(self.store), writes.effect(self.store):
                self.assertEqual(lease.depth, 1)

    def test_ownership_and_ttl_checked_before_every_effect(self):
        with writes.reserve(self.store, 'alice', 'save') as lease:
            self.now += writes.TTL_SECONDS + 1
            with self.assertRaises(writes.WriteBlocked) as caught:
                with writes.effect(self.store): self.fail('no expired effect')
            self.assertEqual(caught.exception.code, 'account_write_lease_lost')
        with writes.reserve(self.store, 'alice', 'save') as lease:
            self.put({'holder':'new','state':'held','expiresAt':self.now+180})
            with self.assertRaises(writes.WriteBlocked): lease.check()
        self.assertEqual(self.store.read(lease.key)[0]['holder'], 'new')

    def test_boundary_translates_safe_code_and_never_provider_text(self):
        self.store.write(admission_policy.queue_key('alice'), {'maintenance':{'action':'delete_user'}}, 0)
        with self.assertRaises(app.AppError) as caught:
            with writes.boundary(app, self.store, 'alice', 'save'): pass
        self.assertEqual(caught.exception.code, 'job_account_maintenance')
        with writes.reserve(self.store, 'alice', 'review', maintenance=True):
            with writes.effect(self.store): pass
        with self.assertRaises(writes.WriteBlocked):
            with writes.reserve(self.store, 'alice', 'delete', maintenance='different-plan'): pass

    def test_missing_and_uncertain_holder_are_rejected(self):
        lease = writes.Reservation(self.store, 'alice', 'save')
        with self.assertRaises(writes.WriteBlocked): lease.check()
        with self.assertRaises(writes.WriteBlocked): lease._state('held')
        with writes.reserve(self.store, 'alice', 'save') as lease:
            self.put({'holder':lease.holder,'state':'uncertain','expiresAt':self.now+10})
            with self.assertRaises(writes.WriteBlocked): lease.check()

    def test_lost_network_response_stays_uncertain_but_cas_metadata_can_reconcile(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with writes.reserve(self.store, 'alice', 'drive'):
                with writes.effect(self.store): raise RuntimeError('fixture')
        self.assertEqual(self.store.read(writes.key('alice'))[0]['state'], 'uncertain')
        _, version = self.store.read(writes.key('alice'))
        self.store.write(writes.key('alice'), {'expiresAt':0}, version)
        with writes.reserve(self.store, 'alice', 'metadata'):
            with self.assertRaises(RuntimeError):
                with writes.effect(self.store, uncertain_on_error=False): raise RuntimeError('fixture')
            with self.assertRaises(app.AppError):
                with writes.effect(self.store): raise app.AppError('fixture',503)
        self.assertEqual(self.store.read(writes.key('alice'))[0]['state'], 'released')

    def test_cas_conflicts_are_bounded_and_do_not_steal(self):
        with patch.object(self.store, 'write', side_effect=PreconditionFailed('fixture')):
            with self.assertRaises(writes.WriteBlocked) as caught:
                with writes.reserve(self.store, 'alice', 'save'): pass
            self.assertEqual(caught.exception.code, 'account_write_busy')
        with writes.reserve(self.store, 'alice', 'save') as lease:
            with patch.object(self.store, 'write', side_effect=PreconditionFailed('fixture')):
                with self.assertRaises(PreconditionFailed): lease._state('in_flight')

    def test_fence_appearing_during_acquisition_is_checked_again_before_effect(self):
        write = self.store.write
        def concurrent_fence(key, data, version):
            write(key, data, version)
            if key == writes.key('alice') and data.get('state') == 'held':
                write(admission_policy.queue_key('alice'), {'maintenance':{'action':'delete_user'}}, 0)
        with patch.object(self.store, 'write', side_effect=concurrent_fence), self.assertRaises(writes.WriteBlocked):
            with writes.reserve(self.store, 'alice', 'save'): self.fail('no business effect')
        self.assertEqual(self.store.read(writes.key('alice'))[0]['state'], 'released')

    def test_effect_without_owned_account_is_only_local_and_never_creates_a_cloud_client(self):
        with patch.object(job_runtime, 'JobStore') as factory, patch.object(users, 'owner', return_value=''):
            with writes.effect(): pass
            factory.assert_not_called()

    def test_unknown_admin_effect_can_record_terminal_state_but_never_alter_usage(self):
        plan_id = 'a' * 32
        plan_key = 'admin-user-action-' + plan_id
        plan = {'id':plan_id, 'uid':'alice','state':'executing','action':'delete_user'}
        queue_key = admission_policy.queue_key('alice')
        queue = {'maintenance':{'planId':plan_id,'state':'executing'},'usage':{'daily':2}}
        self.store.write(plan_key, plan, 0)
        self.store.write(queue_key, queue, 0)
        with writes.reserve(self.store, 'alice', 'admin-delete', maintenance=plan_id) as lease:
            with self.assertRaises(RuntimeError):
                with writes.effect(self.store): raise RuntimeError('fixture lost auth delete')
            with self.assertRaises(writes.WriteBlocked): lease.check()
            with self.assertRaises(writes.WriteBlocked):
                writes.write_terminal(self.store,'alice',plan_id,queue_key,{**queue,'usage':{'daily':0},'maintenance':{**queue['maintenance'],'state':'failed'}},1)
            with self.assertRaises(writes.WriteBlocked):
                writes.write_terminal(self.store,'alice',plan_id,'unrelated',{},0)
            writes.write_terminal(self.store,'alice',plan_id,plan_key,{**plan,'state':'failed','code':'admin_delete_failed'},1)
            writes.write_terminal(self.store,'alice',plan_id,queue_key,{**queue,'maintenance':{**queue['maintenance'],'state':'failed'}},1)
        self.assertEqual(self.store.read(queue_key)[0]['usage']['daily'],2)
        self.assertEqual(self.store.read(writes.key('alice'))[0]['state'],'uncertain')
        with self.assertRaises(writes.WriteBlocked):
            writes.write_terminal(self.store,'alice',plan_id,plan_key,{**plan,'state':'failed'},2)

    def test_terminal_audit_refuses_another_account_and_maintenance_owner(self):
        plan_id = 'a' * 32
        with writes.reserve(self.store,'alice','admin-delete',maintenance=plan_id):
            with self.assertRaises(writes.WriteBlocked):
                writes.write_terminal(self.store,'bob',plan_id,'admin-user-action-'+plan_id,{},0)
            key = admission_policy.queue_key('alice')
            value = {'maintenance':{'planId':'b'*32,'state':'executing'}}
            self.store.write(key,value,0)
            with self.assertRaises(writes.WriteBlocked):
                writes.write_terminal(self.store,'alice',plan_id,key,{**value,'maintenance':{**value['maintenance'],'state':'failed'}},1)


class ProviderGuards(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.write(admission_policy.queue_key('alice'), {'maintenance':{'action':'delete_user'}}, 0)
        marker = users.CURRENT.set({'uid':'alice'})
        self.addCleanup(users.CURRENT.reset, marker)
        factory = patch.object(job_runtime, 'JobStore', return_value=self.store)
        factory.start(); self.addCleanup(factory.stop)

    def test_drive_and_gmail_do_not_call_provider_when_fenced(self):
        with patch.object(app.urllib.request, 'urlopen') as call:
            for operation in (app.drive_request, app.gmail_request):
                with self.assertRaises(writes.WriteBlocked):
                    operation('https://example.invalid/write', 'fixture-token', b'fixture')
            call.assert_not_called()

    def test_bank_and_task_dispatch_recheck_fence_before_effect(self):
        from drive_bank import DriveBank
        session = Mock()
        with self.assertRaises(writes.WriteBlocked):
            DriveBank({}, session=session).request('PUT', 'https://example.invalid/put')
        session.request.assert_not_called()
        with patch.object(job_runtime, '_session', session):
            with self.assertRaises(writes.WriteBlocked):
                job_runtime.enqueue('fixture', {'owner_uid':'alice','webhook_secret':'fixture'})
        session.post.assert_not_called()

    def test_real_gcs_adapter_refuses_account_write_before_upload(self):
        store = REAL_JOB_STORE.__new__(REAL_JOB_STORE)
        store.read = self.store.read
        store.bucket = Mock()
        with self.assertRaises(writes.WriteBlocked):
            store.write('fixture', {'owner_uid':'alice'}, 0)
        store.bucket.blob.assert_not_called()
