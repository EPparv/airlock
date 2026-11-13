"""Automatic local access. macOS stores only this app's key in login Keychain.

The app still needs its private browser session. This removes an application
password, not the OS account boundary. No secrets are sent in process arguments.
"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import secrets
import stat
import sys


class DeviceAccessError(Exception):
    pass


class MacKeychain:
    label = "macOS Keychain"
    service = b"Private AI device encryption"

    def __init__(self, path):
        self.account = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest().encode()
        self.security = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes = [C.c_void_p]
        self.cf.CFRelease.restype = None
        signatures = {
            'SecKeychainFindGenericPassword': [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.POINTER(C.c_uint32), C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)],
            'SecKeychainAddGenericPassword': [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)],
            'SecKeychainItemModifyAttributesAndData': [C.c_void_p, C.c_void_p, C.c_uint32, C.c_void_p],
            'SecKeychainItemFreeContent': [C.c_void_p, C.c_void_p],
            'SecKeychainItemDelete': [C.c_void_p],
        }
        for name, args in signatures.items():
            fn = getattr(self.security, name)
            fn.argtypes, fn.restype = args, C.c_int32

    def _find(self, length=None, data=None, item=None):
        return self.security.SecKeychainFindGenericPassword(
            None, len(self.service), self.service, len(self.account), self.account,
            length, data, item)

    @staticmethod
    def _check(status):
        if status:
            raise DeviceAccessError("Airlock Chat could not access macOS Keychain. Allow access in the Mac prompt, then try again. Your saved data has not been reset.")

    def get(self):
        length, data = C.c_uint32(), C.c_void_p()
        status = self._find(C.byref(length), C.byref(data))
        if status == -25300:  # errSecItemNotFound
            return None
        self._check(status)
        try:
            if length.value != 32:
                raise DeviceAccessError("The saved device key is invalid. Enter your original passphrase to reconnect your data.")
            return C.string_at(data, length.value)
        finally:
            self.security.SecKeychainItemFreeContent(None, data)

    def set(self, key):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("Invalid device key")
        item = C.c_void_p()
        status = self._find(item=C.byref(item))
        buffer = C.create_string_buffer(key)
        if status == -25300:
            self._check(self.security.SecKeychainAddGenericPassword(
                None, len(self.service), self.service, len(self.account), self.account,
                len(key), buffer, None))
        else:
            self._check(status)
            try:
                self._check(self.security.SecKeychainItemModifyAttributesAndData(item, None, len(key), buffer))
            finally:
                self.cf.CFRelease(item)

    def delete(self):
        """Used to clean up synthetic test credentials; never called on user data."""
        item = C.c_void_p()
        status = self._find(item=C.byref(item))
        if status == -25300:
            return
        self._check(status)
        try:
            self._check(self.security.SecKeychainItemDelete(item))
        finally:
            self.cf.CFRelease(item)


class LocalKeyFile:
    """Portable fallback. OS user permissions, not a separate password boundary.

    Not used on macOS, including when Keychain access fails.
    """
    label = "this device's user profile"

    def __init__(self, path):
        self.path = Path(str(Path(path).expanduser()) + '.device-key')

    def get(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or (os.name != 'nt' and (info.st_mode & 0o077 or info.st_uid != os.getuid())):
            raise DeviceAccessError("The device key must be a private file owned by your user account.")
        key = self.path.read_bytes()
        if len(key) != 32:
            raise DeviceAccessError("The saved device key is invalid. Enter your original passphrase to reconnect your data.")
        return key

    def set(self, key):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("Invalid device key")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as out:
                out.write(key)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class DeviceAccess:
    def __init__(self, vault, store=None):
        self.vault = vault
        self.store = store if store is not None else (MacKeychain(vault.path) if sys.platform == 'darwin' else LocalKeyFile(vault.path))
        self.error = ''
        self.needs_passphrase = False

    def status(self):
        return {"automatic": True, "key_storage": self.store.label,
                "needs_passphrase": self.needs_passphrase, "error": self.error}

    def open(self):
        """Never overwrite an existing vault or reset it after failed decryption."""
        self.error = ''
        self.needs_passphrase = False
        if self.vault.unlocked:
            return False
        try:
            key = self.store.get()
            if self.vault.exists:
                if key is None:
                    self.needs_passphrase = True
                    return False
                try:
                    self.vault.unlock_key(key)
                except ValueError:
                    self.needs_passphrase = True
                    raise DeviceAccessError("This device key does not open your saved data. Enter the original passphrase once to reconnect it.") from None
                return False
            # Store and verify the key BEFORE committing a new vault. A failed
            # Keychain write must never leave an inaccessible first-run vault.
            key = key or secrets.token_bytes(32)
            self.store.set(key)
            if self.store.get() != key:
                raise DeviceAccessError("The device could not remember its encryption key. Please try again.")
            self.vault.key, self.vault.salt = key, secrets.token_bytes(16)
            from .vault import defaults
            self.vault.data = defaults()
            try:
                self.vault.save()
            except Exception:
                self.vault.lock()
                raise
            return True
        except DeviceAccessError as error:
            self.error = str(error)
            return False
        except OSError:
            self.error = "Could not save local storage. Check that your device has space and the app can write to its data folder."
            return False

    def migrate(self, passphrase):
        self.vault.unlock(passphrase)
        try:
            self.store.set(self.vault.key)
            if self.store.get() != self.vault.key:
                raise DeviceAccessError("The device could not remember its encryption key. Please try again.")
        except Exception:
            self.vault.lock()
            raise
        self.error = ''
        self.needs_passphrase = False
