import pytest
import config as cfg_module
from config import save_config, load_config, config_exists

_DATA = {
    "username": "testuser",
    "password": "s3cr3tP@ss",
    "train_number": "12951",
    "captcha_api_key": None,
}


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Redirect CONFIG_PATH and SALT_PATH to a temp dir so tests never
    touch the real encrypted config on disk."""
    monkeypatch.setattr(cfg_module, "CONFIG_PATH", tmp_path / "booking_config.enc")
    monkeypatch.setattr(cfg_module, "SALT_PATH",   tmp_path / "booking_salt.bin")
    yield
    # tmp_path is cleaned up automatically by pytest — nothing to do


def test_save_creates_files():
    save_config(_DATA, "passphrase123")
    assert cfg_module.CONFIG_PATH.exists()
    assert cfg_module.SALT_PATH.exists()


def test_roundtrip_correct_passphrase():
    save_config(_DATA, "my_passphrase")
    loaded = load_config("my_passphrase")
    assert loaded == _DATA


def test_wrong_passphrase_raises():
    save_config(_DATA, "correct_pass")
    with pytest.raises(Exception):
        load_config("wrong_pass")


def test_config_not_stored_in_plaintext():
    save_config(_DATA, "my_passphrase")
    raw = cfg_module.CONFIG_PATH.read_bytes()
    assert b"testuser" not in raw
    assert b"s3cr3tP@ss" not in raw
    assert b"12951" not in raw


def test_config_exists_true_after_save():
    assert not config_exists()
    save_config(_DATA, "passphrase1")
    assert config_exists()


def test_config_exists_false_when_salt_missing():
    save_config(_DATA, "passphrase1")
    cfg_module.SALT_PATH.unlink()
    assert not config_exists()


def test_different_passphrases_produce_different_ciphertext():
    save_config(_DATA, "passphrase_a")
    ct_a = cfg_module.CONFIG_PATH.read_bytes()
    save_config(_DATA, "passphrase_b")
    ct_b = cfg_module.CONFIG_PATH.read_bytes()
    assert ct_a != ct_b


def test_salt_is_random_across_saves():
    save_config(_DATA, "passphrase1")
    salt_a = cfg_module.SALT_PATH.read_bytes()
    save_config(_DATA, "passphrase1")
    salt_b = cfg_module.SALT_PATH.read_bytes()
    assert salt_a != salt_b


def test_weak_passphrase_rejected():
    """A weak passphrase is the real attack surface (PBKDF2+Fernet is fine) —
    save_config must refuse anything under MIN_PASSPHRASE_LEN."""
    with pytest.raises(ValueError):
        save_config(_DATA, "short")
    assert not config_exists()
