import base64
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Anchored to the directory this file lives in so config is found
# regardless of the Python process's working directory.
_HERE = Path(__file__).resolve().parent
CONFIG_PATH = _HERE / "booking_config.enc"
SALT_PATH   = _HERE / "booking_salt.bin"

# A weak passphrase is the real attack surface here, not the cipher (PBKDF2
# 480k + Fernet is fine). There is no recovery path if it's lost or brute-
# forced — enforce a minimum length at the one place every local save funnels
# through.
MIN_PASSPHRASE_LEN = 8


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def save_config(data: dict, passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise ValueError(
            f"Passphrase must be at least {MIN_PASSPHRASE_LEN} characters."
        )
    salt = os.urandom(16)
    SALT_PATH.write_bytes(salt)
    key = _derive_key(passphrase, salt)
    token = Fernet(key).encrypt(json.dumps(data).encode())
    CONFIG_PATH.write_bytes(token)


def load_config(passphrase: str) -> dict:
    salt = SALT_PATH.read_bytes()
    key = _derive_key(passphrase, salt)
    raw = Fernet(key).decrypt(CONFIG_PATH.read_bytes())
    return json.loads(raw.decode())


def config_exists() -> bool:
    return CONFIG_PATH.exists() and SALT_PATH.exists()
