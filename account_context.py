"""Request and worker account state, independent of the Flask module globals."""
from contextvars import ContextVar
from types import ModuleType

FIELDS = frozenset(('MASTER_PROFILE', 'EXPERIENCE_BY_ID', 'SKILL_BY_ID', 'COURSE_BY_ID',
    'BANK_CONFIG', 'ARCHIVE_CONFIG', 'BANK_CLIENT', 'BANK_PHOTO_PATH', 'BANK_READ_STATUS',
    'BANK_READ_AT', 'BANK_PHOTO_DIGEST'))


class AccountState:
    def __init__(self):
        object.__setattr__(self, '_default', {})
        object.__setattr__(self, '_current', ContextVar('cv_bank_state', default=None))

    def _values(self):
        current = self._current.get()
        return self._default if current is None else current

    def __getattr__(self, name):
        try:
            return self._values()[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name not in FIELDS:
            raise AttributeError(name)
        self._values()[name] = value

    def __delattr__(self, name):
        try:
            del self._values()[name]
        except KeyError:
            raise AttributeError(name) from None

    def enter(self, values):
        return self._current.set(dict(values))

    def exit(self, token):
        self._current.reset(token)


class AccountModule(ModuleType):
    """Preserve app.FIELD access for integrations and existing test patches."""
    def __getattr__(self, name):
        if name in FIELDS:
            return getattr(self.account_state, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in FIELDS:
            setattr(self.account_state, name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in FIELDS:
            delattr(self.account_state, name)
        else:
            super().__delattr__(name)


def install_compatibility(module, state):
    module.account_state = state
    module.__class__ = AccountModule
