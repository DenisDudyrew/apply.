"""Desktop tokens live in Keychain / Windows Credential Manager, never in the bundle."""
import hashlib
import json
import os
import sys

_CACHE = {}


def desktop():
    return bool(getattr(sys, 'frozen', False)) or os.environ.get('APPLY_DESKTOP') == '1'


def key(directory):
    return 'account-' + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:24]


def load(directory):
    path = directory / 'token.json'
    if not desktop():
        try:
            return json.loads(path.read_text(encoding='utf-8')).get('token', {})
        except (OSError, ValueError, AttributeError):
            return _CACHE.get(str(directory), {})
    if str(directory) not in _CACHE:
        import keyring
        try:
            raw = keyring.get_password('Apply Local', key(directory))
            _CACHE[str(directory)] = json.loads(raw) if raw else {}
        except Exception:
            raise RuntimeError('Не удалось открыть системное хранилище учётных данных.') from None
    return _CACHE[str(directory)]


def save(directory, token):
    if desktop():
        import keyring
        try:
            keyring.set_password('Apply Local', key(directory), json.dumps(token))
        except Exception:
            raise RuntimeError('Не удалось сохранить вход в системном хранилище. Проверьте доступ к Keychain или Диспетчеру учётных данных.') from None
    else:
        # Developer mode keeps backwards compatibility with the existing local setup.
        from hh_auth import private_json
        private_json(directory / 'token.json', {'token': token})
    _CACHE[str(directory)] = dict(token)


def clear(directory):
    if desktop():
        import keyring
        try:
            keyring.delete_password('Apply Local', key(directory))
        except keyring.errors.PasswordDeleteError:
            pass
    _CACHE.pop(str(directory), None)
    (directory / 'token.json').unlink(missing_ok=True)
