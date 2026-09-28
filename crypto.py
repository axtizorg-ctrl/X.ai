"""AES-256-GCM vault. A random master key is wrapped by a passphrase-derived key (scrypt).
Backends: pycryptodome (Android build) or `cryptography` (desktop testing) - same wire format."""
import hashlib, json, os

try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import scrypt as _scrypt

    def _enc(key, nonce, aad, pt):
        c = AES.new(key, AES.MODE_GCM, nonce=nonce)
        c.update(aad)
        ct, tag = c.encrypt_and_digest(pt)
        return ct + tag

    def _dec(key, nonce, aad, blob):
        c = AES.new(key, AES.MODE_GCM, nonce=nonce)
        c.update(aad)
        return c.decrypt_and_verify(blob[:-16], blob[-16:])

    def _kdf(pw, salt):
        return _scrypt(pw.encode(), salt, 32, N=2 ** 15, r=8, p=1)
except ImportError:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    def _enc(key, nonce, aad, pt):
        return AESGCM(key).encrypt(nonce, pt, aad)

    def _dec(key, nonce, aad, blob):
        return AESGCM(key).decrypt(nonce, blob, aad)

    def _kdf(pw, salt):
        return hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 15, r=8, p=1, dklen=32,
                              maxmem=64 * 1024 * 1024)

MAGIC = b"XE1"


class Vault:
    def __init__(self, path):
        self.path = path
        self._key = None

    def exists(self):
        return os.path.exists(self.path)

    def unlocked(self):
        return self._key is not None

    def create(self, passphrase):
        key, salt = os.urandom(32), os.urandom(16)
        self._write(passphrase, key, salt)
        self._key = key

    def unlock(self, passphrase):
        with open(self.path) as f:
            meta = json.load(f)
        blob = bytes.fromhex(meta["wrapped"])
        try:
            self._key = _dec(_kdf(passphrase, bytes.fromhex(meta["salt"])),
                             blob[:12], b"wrap", blob[12:])
        except Exception:
            raise ValueError("wrong passphrase")

    def change_passphrase(self, new):
        self._need()
        self._write(new, self._key, os.urandom(16))

    def _write(self, pw, key, salt):
        nonce = os.urandom(12)
        wrapped = nonce + _enc(_kdf(pw, salt), nonce, b"wrap", key)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"salt": salt.hex(), "wrapped": wrapped.hex()}, f)
        os.replace(tmp, self.path)

    def _need(self):
        if self._key is None:
            raise PermissionError("vault is locked")

    def encrypt(self, data, aad=b""):
        self._need()
        nonce = os.urandom(12)
        return MAGIC + nonce + _enc(self._key, nonce, aad, data)

    def decrypt(self, blob, aad=b""):
        self._need()
        if blob[:3] != MAGIC:
            raise ValueError("bad format")
        return _dec(self._key, blob[3:15], aad, blob[15:])
