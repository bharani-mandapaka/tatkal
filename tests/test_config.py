import pytest

from config import save_config, load_config, config_exists, CONFIG_PATH, SALT_PATH

_DATA = {
    "username": "testuser",
    "password": "s3cr3tP@ss",
    "train_number": "12951",
    "captcha_api_key": None,
}


@pytest.fixture(autouse=True)
def _cleanup():
    """Remove config artefacts before and after every test."""
    for p in (CONFIG_PATH, SALT_PATH):
        p.unlink(missing_ok=True)
    yield
    for p in (CONFIG_PATH, SALT_PATH):
        p.unlink(missing_ok=True)


def test_save_creates_files():
    save_config(_DATA, "passphrase123")
    assert CONFIG_PATH.exists()
    assert SALT_PATH.exists()


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
    raw = CONFIG_PATH.read_bytes()
    assert b"testuser" not in raw
    assert b"s3cr3tP@ss" not in raw
    assert b"12951" not in raw


def test_config_exists_true_after_save():
    assert not config_exists()
    save_config(_DATA, "x")
    assert config_exists()


def test_config_exists_false_when_salt_missing():
    save_config(_DATA, "x")
    SALT_PATH.unlink()
    assert not config_exists()


def test_different_passphrases_produce_different_ciphertext():
    save_config(_DATA, "pass_a")
    ct_a = CONFIG_PATH.read_bytes()
    save_config(_DATA, "pass_b")
    ct_b = CONFIG_PATH.read_bytes()
    assert ct_a != ct_b


def test_salt_is_random_across_saves():
    save_config(_DATA, "x")
    salt_a = SALT_PATH.read_bytes()
    save_config(_DATA, "x")
    salt_b = SALT_PATH.read_bytes()
    assert salt_a != salt_b
