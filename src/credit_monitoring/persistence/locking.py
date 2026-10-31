"""Process-local locks for short database writes and individual document caches."""

from threading import Lock, RLock

_GUARD = Lock()
_LOCKS: dict[tuple[str, ...], RLock] = {}


def resource_lock(*key: str) -> RLock:
    with _GUARD:
        return _LOCKS.setdefault(key, RLock())
