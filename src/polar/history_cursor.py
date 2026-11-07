"""Bounded authenticated history cursors; dedicated persisted key, no token registry."""
import base64
import hashlib
import hmac
import os
import stat

from .history_bundle import canonical, decode


class HistoryCursorError(Exception):
    def __init__(self, code="HISTORY_INVALID_CURSOR", status=422):
        self.code, self.status = code, status
        super().__init__(code)


class CursorCodec:
    def __init__(self, key):
        if type(key) is not bytes or len(key) != 32:
            raise HistoryCursorError("HISTORY_CURSOR_KEY_UNAVAILABLE", 503)
        self._key = key

    @classmethod
    def from_file(cls, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != 32:
                    raise HistoryCursorError("HISTORY_CURSOR_KEY_UNAVAILABLE", 503)
                key = stream.read(33)
            return cls(key)
        except (OSError, TypeError, ValueError):
            raise HistoryCursorError("HISTORY_CURSOR_KEY_UNAVAILABLE", 503) from None

    def encode(self, payload):
        signature = hmac.new(self._key, canonical(payload), hashlib.sha256).hexdigest()
        envelope = {"version": "polar.history-auth-cursor/1", "payload": payload, "mac": signature}
        token = base64.urlsafe_b64encode(canonical(envelope)).decode()
        if len(token) > 2048:
            raise HistoryCursorError("HISTORY_RESPONSE_LIMIT", 503)
        return token

    def decode(self, token):
        try:
            if type(token) is not str or not token or len(token) > 2048 or not token.isascii():
                raise HistoryCursorError()
            envelope = decode(base64.b64decode(token, altchars=b"-_", validate=True))
            if (type(envelope) is not dict or set(envelope) != {"version", "payload", "mac"} or
                    envelope["version"] != "polar.history-auth-cursor/1" or type(envelope["payload"]) is not dict or
                    type(envelope["mac"]) is not str or len(envelope["mac"]) != 64):
                raise HistoryCursorError()
            expected = hmac.new(self._key, canonical(envelope["payload"]), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(envelope["mac"], expected):
                raise HistoryCursorError()
            if token != base64.urlsafe_b64encode(canonical(envelope)).decode():
                raise HistoryCursorError()
            return envelope["payload"]
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HistoryCursorError() from None
