"""Unit tests for credential encryption/decryption helpers (TASK-438)."""
import os
import pytest
from parrot.handlers.credentials_utils import encrypt_credential, decrypt_credential


@pytest.fixture
def master_key():
    """Generate a 32-byte random master key for testing."""
    return os.urandom(32)


@pytest.fixture
def master_keys(master_key):
    """Return a master_keys dict for key_id=1."""
    return {1: master_key}


class TestCredentialEncryption:
    """Tests for encrypt_credential / decrypt_credential round-trips."""

    def test_roundtrip_basic(self, master_key, master_keys):
        """Encrypt then decrypt returns original credential dict."""
        cred = {
            "driver": "pg",
            "host": "localhost",
            "port": 5432,
            "user": "admin",
            "password": "secret",
        }
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        assert isinstance(encrypted, str)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_special_chars(self, master_key, master_keys):
        """Passwords with special characters survive encryption round-trip."""
        cred = {"driver": "mysql", "password": "p@$$w0rd!#&*()_+{}|:<>?"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_unicode(self, master_key, master_keys):
        """Unicode passwords survive encryption round-trip."""
        cred = {"driver": "pg", "password": "contraseña_日本語_пароль"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_empty_params(self, master_key, master_keys):
        """Empty credential dict (driver only) survives round-trip."""
        cred = {"driver": "pg"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_roundtrip_full_asyncdb_credential(self, master_key, master_keys):
        """Full asyncdb-style credential dict survives round-trip."""
        cred = {
            "driver": "pg",
            "params": {
                "host": "db.example.com",
                "port": 5432,
                "user": "app_user",
                "password": "very$ecure!Pass#123",
                "database": "production_db",
            },
        }
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred

    def test_encrypted_is_valid_base64(self, master_key):
        """Encrypted output is valid base64 ASCII."""
        import base64
        cred = {"driver": "pg", "password": "secret"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        # Should not raise
        decoded = base64.b64decode(encrypted)
        assert len(decoded) > 0

    def test_encrypted_is_different_from_plaintext(self, master_key):
        """Encrypted string does not contain the plaintext password."""
        cred = {"driver": "pg", "password": "supersecretpassword"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        assert "supersecretpassword" not in encrypted

    def test_encrypt_produces_different_ciphertexts(self, master_key):
        """Two calls with the same plaintext produce different ciphertexts (nonce randomness)."""
        cred = {"driver": "pg", "password": "secret"}
        enc1 = encrypt_credential(cred, key_id=1, master_key=master_key)
        enc2 = encrypt_credential(cred, key_id=1, master_key=master_key)
        # Different nonces should produce different output
        assert enc1 != enc2

    def test_wrong_key_raises(self, master_key):
        """Decryption with wrong key raises an error."""
        cred = {"driver": "pg", "password": "secret"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        wrong_master_key = os.urandom(32)
        wrong_keys = {1: wrong_master_key}
        with pytest.raises(Exception):
            decrypt_credential(encrypted, wrong_keys)

    def test_missing_key_id_raises(self, master_key, master_keys):
        """Decryption raises KeyError when key_id not in master_keys."""
        cred = {"driver": "pg"}
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        empty_keys: dict = {}
        with pytest.raises(KeyError):
            decrypt_credential(encrypted, empty_keys)

    def test_roundtrip_bigquery_credential(self, master_key, master_keys):
        """BigQuery-style credential with nested JSON survives round-trip."""
        cred = {
            "driver": "bigquery",
            "params": {
                "project": "my-gcp-project",
                "credentials": {
                    "type": "service_account",
                    "project_id": "my-gcp-project",
                    "private_key_id": "key123",
                    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----\n",
                    "client_email": "svc@my-gcp-project.iam.gserviceaccount.com",
                },
            },
        }
        encrypted = encrypt_credential(cred, key_id=1, master_key=master_key)
        decrypted = decrypt_credential(encrypted, master_keys)
        assert decrypted == cred
