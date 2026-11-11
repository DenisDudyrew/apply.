"""Nonblocking locks on both Windows and macOS."""
import portalocker


def acquire(path):
    lock = portalocker.Lock(str(path), mode='a+b', timeout=0,
                            flags=portalocker.LOCK_EX | portalocker.LOCK_NB)
    try:
        lock.acquire()
    except portalocker.exceptions.LockException:
        raise RuntimeError('Другой экземпляр уже выполняет эту операцию. Дождитесь его завершения.') from None
    return lock
