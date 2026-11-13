"""Authenticated, passphrase-encrypted local storage. No plaintext database."""
import base64
import copy
import json
import os
from pathlib import Path
import secrets
import threading

from .model_defaults import OUTPUT_TOKENS

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

AAD = b"private-ai-vault-v1"
MAX_VAULT = 64 * 1024 * 1024


def defaults():
    return {"version": 1, "memories": [], "skills": [], "chats": [], "routing_examples":[], "routing_salt":secrets.token_hex(32),
            "agent_tokens": [], "settings": {"privacy": "local", "venice_key": "",
            "ollama_model": "", "classifier_model": "", "sensitive_strings": [],
            "max_output_tokens": OUTPUT_TOKENS, "embedding_model":"", "routing_mode":"provisional", "min_acceptance":0.8, "use_benchmark_evidence":True, "cloud_chat_direct":False}}


class Vault:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.key = None
        self.salt = None
        self.data = None
        self._committed = None
        self.mutex = threading.RLock()

    @property
    def exists(self):
        return self.path.exists()

    @property
    def unlocked(self):
        return self.key is not None

    @staticmethod
    def derive(passphrase, salt):
        if not isinstance(passphrase, str) or len(passphrase) > 1024:
            raise ValueError("Invalid passphrase")
        return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(passphrase.encode())

    def create(self, passphrase):
        with self.mutex:
            if self.exists:
                raise ValueError("A vault already exists")
            if len(passphrase) < 12:
                raise ValueError("Use at least 12 characters; several random words are better")
            self.salt = secrets.token_bytes(16)
            self.key = self.derive(passphrase, self.salt)
            self.data = defaults()
            try:
                self.save()
            except Exception:
                self.lock()
                raise

    def unlock(self, passphrase):
        self._unlock(passphrase=passphrase)

    def unlock_key(self, key):
        """Open with a device credential; never return it through the browser API."""
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("Invalid device key")
        self._unlock(device_key=key)

    def _unlock(self, passphrase=None, device_key=None):
        with self.mutex:
            try:
                if self.path.stat().st_size > MAX_VAULT:
                    raise ValueError()
                envelope = json.loads(self.path.read_bytes())
                if envelope["version"] != 1:
                    raise ValueError()
                salt = base64.b64decode(envelope["salt"], validate=True)
                nonce = base64.b64decode(envelope["nonce"], validate=True)
                if len(salt) != 16 or len(nonce) != 12:
                    raise ValueError()
                key = device_key if device_key is not None else self.derive(passphrase, salt)
                plain = AESGCM(key).decrypt(nonce, base64.b64decode(envelope["ciphertext"], validate=True), AAD)
                data = json.loads(plain)
                if data.get("version") != 1 or not isinstance(data.get("settings"), dict) or any(not isinstance(data.get(k), list) for k in ("memories", "skills", "chats", "agent_tokens")):
                    raise ValueError()
                fresh = defaults()
                data["settings"] = {**fresh["settings"], **data["settings"]}
                data.setdefault("routing_examples", [])
                data.setdefault("routing_salt", fresh["routing_salt"])
                if not isinstance(data["routing_examples"], list) or not isinstance(data["routing_salt"], str):
                    raise ValueError()
            except Exception:
                raise ValueError("Could not unlock: incorrect passphrase or damaged vault") from None
            self.salt, self.key, self.data = salt, key, data
            self._committed = copy.deepcopy(data)

    def backup(self, passphrase):
        """Portable backup with its own password, independent of this device key."""
        if not isinstance(passphrase, str) or not 12 <= len(passphrase) <= 1024:
            raise ValueError("Use at least 12 characters for your backup password")
        with self.mutex:
            if not self.unlocked:
                raise ValueError("Vault is locked")
            salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
            plain = json.dumps(self.data, ensure_ascii=False).encode()
            key = self.derive(passphrase, salt)
            return json.dumps({"version": 1, "salt": base64.b64encode(salt).decode(),
                               "nonce": base64.b64encode(nonce).decode(),
                               "ciphertext": base64.b64encode(AESGCM(key).encrypt(nonce, plain, AAD)).decode()})

    def save(self):
        """On a write failure, memory reverts to the last committed state."""
        try:
            self._save()
        except Exception:
            self.data = copy.deepcopy(self._committed)
            raise

    def _save(self):
        with self.mutex:
            if not self.unlocked:
                raise ValueError("Vault is locked")
            committed = copy.deepcopy(self.data)
            plain = json.dumps(committed, ensure_ascii=False).encode()
            if len(plain) > MAX_VAULT // 2:
                raise ValueError("Vault size limit reached; remove old chats before continuing")
            nonce = secrets.token_bytes(12)
            envelope = {"version": 1, "salt": base64.b64encode(self.salt).decode(),
                        "nonce": base64.b64encode(nonce).decode(),
                        "ciphertext": base64.b64encode(AESGCM(self.key).encrypt(nonce, plain, AAD)).decode()}
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.path.with_name(self.path.name + "." + secrets.token_hex(8) + ".tmp")
            try:
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as out:
                    out.write(json.dumps(envelope).encode())
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp, self.path)
                self._committed = committed
                if os.name != "nt":
                    try:
                        parent_fd = os.open(self.path.parent, os.O_RDONLY)
                        try:
                            os.fsync(parent_fd)
                        finally:
                            os.close(parent_fd)
                    except OSError:
                        pass  # Some filesystems do not support directory fsync.
            finally:
                temp.unlink(missing_ok=True)

    def lock(self):
        with self.mutex:
            self.key = self.salt = self.data = self._committed = None
            # Python cannot promise physical zeroization of previous allocations.

    def change_passphrase(self, current, new):
        with self.mutex:
            if not self.unlocked or not secrets.compare_digest(self.derive(current, self.salt), self.key):
                raise ValueError("Current passphrase is incorrect")
            if not isinstance(new, str) or not 12 <= len(new) <= 1024:
                raise ValueError("New passphrase must contain 12–1,024 characters")
            old_key, old_salt = self.key, self.salt
            self.salt = secrets.token_bytes(16)
            self.key = self.derive(new, self.salt)
            try:
                self.save()
            except Exception:
                self.key, self.salt = old_key, old_salt
                raise


class VaultLease:
    """One process per vault; OS releases the lock after a crash."""
    def __init__(self, vault_path):
        path = Path(vault_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = os.fdopen(os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600), "r+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.file.seek(0, os.SEEK_END) == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError("This vault is already open. Use the existing app window or stop its terminal first.") from None

    def close(self):
        self.file.close()
