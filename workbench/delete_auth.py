"""Server-only deletion passphrase verification with bounded retry tracking."""
import hmac
import threading
import time

_lock = threading.Lock()
_failures = {}


def verify(value, client):
    expected = 'DEL'
    now = time.monotonic()
    with _lock:
        for address in list(_failures):
            _failures[address] = [t for t in _failures[address] if now - t < 60]
            if not _failures[address]:
                del _failures[address]
        attempts = _failures.get(client, [])
        if len(attempts) >= 5:
            raise PermissionError('口令错误次数过多，请一分钟后再试。')
        if not isinstance(value, str) or not hmac.compare_digest(value.encode(), expected.encode()):
            if len(_failures) >= 1024 and client not in _failures:
                raise PermissionError('删除验证繁忙，请稍后重试。')
            _failures[client] = attempts + [now]
            raise PermissionError('删除口令错误，未删除任何文件。')
        _failures.pop(client, None)
