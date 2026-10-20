"""Account-wide, CAS-owned write reservation; never expires maintenance.

TTL permits replacing an idle, abandoned holder, not an in-flight/unknown write.
Every business effect rechecks ownership and the administrative fence. Lease
metadata has a separate object so its renewals cannot invalidate business CAS.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import time
from uuid import uuid4
from google.api_core.exceptions import PreconditionFailed
import admission_policy

TTL_SECONDS = 180
_current = ContextVar('cv_account_write', default=None)
_internal = ContextVar('cv_account_write_metadata', default=False)
MESSAGES = {
    'job_account_maintenance': 'Esta cuenta tiene una acción administrativa pendiente. El administrador debe revisarla antes de continuar.',
    'account_write_busy': 'Otra sesión está actualizando esta cuenta. Espera y vuelve a intentar.',
    'account_write_lease_lost': 'La reserva de escritura venció o cambió. Sincroniza antes de reintentar.',
    'account_write_outcome_unknown': 'Una escritura perdió su confirmación. Revisa su resultado antes de repetirla.',
    'account_write_owner_mismatch': 'La reserva no pertenece a la cuenta de esta operación.',
}


class WriteBlocked(Exception):
    status_code = 409
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def current():
    return _current.get()


def key(uid):
    return 'account-write-' + hashlib.sha256(uid.encode()).hexdigest()


def write_terminal(store, uid, plan_id, identifier, data, generation):
    """Record an admin outcome even when its external effect is uncertain.

    This capability can change only terminal audit fields, never account data,
    receipts or maintenance ownership. It does not grant another business write.
    """
    lease = current()
    owned, _ = store.read(key(uid))
    if not lease or lease.uid != uid or lease.maintenance != plan_id or not owned or owned.get('holder') != lease.holder:
        raise WriteBlocked('account_write_owner_mismatch')
    before, _ = store.read(identifier)
    allowed = {'state', 'code', 'stage', 'correlationId', 'finishedAt'}
    if identifier == admission_policy.queue_key(uid):
        prior, after = (before or {}).get('maintenance') or {}, data.get('maintenance') or {}
        unchanged = prior.get('planId') == plan_id and {k:v for k,v in (before or {}).items() if k != 'maintenance'} == {k:v for k,v in data.items() if k != 'maintenance'}
    elif identifier == 'admin-user-action-' + plan_id:
        prior, after, unchanged = before or {}, data, True
        unchanged = unchanged and prior.get('uid') == uid and prior.get('id') == plan_id
    else:
        raise WriteBlocked('account_write_owner_mismatch')
    if not unchanged or after.get('state') not in {'failed', 'completed'} or any(prior.get(k) != after.get(k) for k in set(prior) | set(after) if k not in allowed):
        raise WriteBlocked('account_write_owner_mismatch')
    marker = _internal.set(True)
    try:
        store.write(identifier, data, generation)
    finally:
        _internal.reset(marker)


class Reservation:
    def __init__(self, store, uid, purpose, maintenance=False):
        self.store, self.uid, self.purpose = store, uid, purpose
        self.key, self.holder = key(uid), uuid4().hex
        self.maintenance = maintenance
        self.depth = 0

    def _write(self, data, version):
        marker = _internal.set(True)
        try:
            self.store.write(self.key, data, version)
        finally:
            _internal.reset(marker)

    def fence(self):
        queue, _ = self.store.read(admission_policy.queue_key(self.uid))
        fence = (queue or {}).get('maintenance')
        if fence and not (self.maintenance is True or isinstance(fence, dict) and fence.get('planId') == self.maintenance):
            raise WriteBlocked('job_account_maintenance')

    def acquire(self):
        self.fence()
        for attempt in range(11):
            lease, version = self.store.read(self.key)
            if lease and lease.get('state') in {'in_flight', 'uncertain'}:
                raise WriteBlocked('account_write_outcome_unknown' if lease.get('state') == 'uncertain' or lease.get('expiresAt', 0) <= time.time() else 'account_write_busy')
            if lease and lease.get('expiresAt', 0) > time.time():
                if attempt == 10:
                    raise WriteBlocked('account_write_busy')
                time.sleep(.05)
                continue
            try:
                self._write(dict(holder=self.holder, owner=hashlib.sha256(self.uid.encode()).hexdigest(),
                    purpose=self.purpose, state='held', expiresAt=time.time() + TTL_SECONDS), version)
                return
            except PreconditionFailed:
                if attempt == 10:
                    raise WriteBlocked('account_write_busy') from None

    def check(self):
        lease, _ = self.store.read(self.key)
        if not lease or lease.get('holder') != self.holder or lease.get('expiresAt', 0) <= time.time():
            raise WriteBlocked('account_write_lease_lost')
        if lease.get('state') == 'uncertain':
            raise WriteBlocked('account_write_outcome_unknown')
        self.fence()

    def _state(self, state):
        lease, version = self.store.read(self.key)
        if not lease or lease.get('holder') != self.holder:
            raise WriteBlocked('account_write_lease_lost')
        self._write({**lease, 'state': state, 'expiresAt': time.time() + TTL_SECONDS}, version)

    @contextmanager
    def effect(self, *, uncertain_on_error=True):
        self.check()
        if self.depth:
            yield
            return
        self._state('in_flight')
        self.depth += 1
        try:
            self.check()
            yield
        except Exception as error:
            # A definite provider/validation response is not a lost response.
            status = getattr(error, 'status_code', None) or getattr(error, 'code', None)
            self._state('held' if not uncertain_on_error or isinstance(status, int) else 'uncertain')
            raise
        else:
            self._state('held')
        finally:
            self.depth -= 1

    def release(self):
        lease, version = self.store.read(self.key)
        if lease and lease.get('holder') == self.holder and lease.get('state') == 'held':
            self._write({**lease, 'state': 'released', 'expiresAt': 0}, version)


@contextmanager
def reserve(store, uid, purpose, *, maintenance=False):
    previous = current()
    if previous:
        if previous.uid != uid:
            raise WriteBlocked('account_write_owner_mismatch')
        previous.check()
        yield previous
        return
    reservation = Reservation(store, uid, purpose, maintenance)
    reservation.acquire()
    marker = _current.set(reservation)
    try:
        reservation.check()
        yield reservation
    finally:
        try:
            reservation.release()
        finally:
            _current.reset(marker)


@contextmanager
def boundary(core, store, uid, purpose):
    try:
        with reserve(store, uid, purpose) as reservation:
            yield reservation
    except WriteBlocked as failure:
        error = core.AppError(str(failure), failure.status_code)
        error.code = failure.code
        raise error from None


@contextmanager
def effect(store=None, uid=None, *, uncertain_on_error=True):
    if _internal.get():
        yield
        return
    reservation = current()
    if reservation:
        if uid is not None and uid != reservation.uid:
            raise WriteBlocked('account_write_owner_mismatch')
        with reservation.effect(uncertain_on_error=uncertain_on_error):
            yield
        return
    if uid is None:
        import user_accounts
        uid = user_accounts.owner() or None
    if uid is None:
        yield  # Unauthenticated local fixtures have no account to fence.
        return
    if store is None:
        import job_runtime
        store = job_runtime.JobStore()
    with reserve(store, uid, 'effect') as reservation, reservation.effect(uncertain_on_error=uncertain_on_error):
        yield
