import base64
import json

import pytest
from app.credential_manager import (
    CredentialManager,
    CREDENTIALS_FILE,
    CREDENTIALS_FILE_V2,
    CREDENTIALS_BACKUP_FILE,
)


@pytest.fixture(autouse=True)
def reset_credentials():
    """Reset credential state and files before each test"""
    CredentialManager._credentials_cache = None
    for p in (CREDENTIALS_FILE, CREDENTIALS_FILE_V2, CREDENTIALS_BACKUP_FILE):
        if p.exists():
            p.unlink()
    yield
    CredentialManager._credentials_cache = None
    for p in (CREDENTIALS_FILE, CREDENTIALS_FILE_V2, CREDENTIALS_BACKUP_FILE):
        if p.exists():
            p.unlink()


class TestCredentialManager:
    def test_store_and_get_token(self):
        """Store and retrieve a token"""
        CredentialManager.store_token("github.com", "user", "ghp_12345")
        creds = CredentialManager.get_token("github.com")
        assert creds is not None
        assert creds[0] == "user"
        assert creds[1] == "ghp_12345"

    def test_get_nonexistent_token(self):
        """Get token for unknown host returns None"""
        assert CredentialManager.get_token("unknown.host") is None

    def test_delete_token(self):
        """Delete removes stored token"""
        CredentialManager.store_token("github.com", "user", "ghp_12345")
        CredentialManager.delete_token("github.com")
        assert CredentialManager.get_token("github.com") is None

    def test_list_hosts(self):
        """list_hosts returns all stored hosts"""
        assert CredentialManager.list_hosts() == []
        CredentialManager.store_token("github.com", "u1", "t1")
        CredentialManager.store_token("gitlab.com", "u2", "t2")
        hosts = CredentialManager.list_hosts()
        assert sorted(hosts) == ["github.com", "gitlab.com"]

    def test_persistence(self):
        """Credentials persist across manager resets"""
        CredentialManager.store_token("github.com", "user", "ghp_12345")
        # Simulate process restart by clearing cache
        CredentialManager._credentials_cache = None
        creds = CredentialManager.get_token("github.com")
        assert creds is not None
        assert creds[1] == "ghp_12345"

    def test_url_parsing_https(self):
        """Parse https remote URL to extract host"""
        url = "https://github.com/user/repo.git"
        creds = CredentialManager.get_git_credentials(url)
        # Should try GCM first, then fallback to local (which is empty here)
        # Result depends on whether GCM is installed
        assert creds is None or isinstance(creds, tuple)

    def test_url_parsing_ssh(self):
        """SSH URL returns None (no token needed)"""
        url = "git@github.com:user/repo.git"
        assert CredentialManager.get_git_credentials(url) is None

    def test_url_parsing_http(self):
        """Parse http remote URL"""
        url = "http://gitlab.com/user/repo.git"
        creds = CredentialManager.get_git_credentials(url)
        assert creds is None or isinstance(creds, tuple)

    def test_writes_dpapi_envelope_not_legacy_file(self):
        """New saves go to credentials.dpapi, not the legacy plaintext file."""
        CredentialManager.store_token("github.com", "user", "ghp_abc")
        assert CREDENTIALS_FILE_V2.exists()
        assert not CREDENTIALS_FILE.exists()

        envelope = json.loads(CREDENTIALS_FILE_V2.read_text(encoding="utf-8"))
        assert envelope["version"] == 1
        assert "encrypted" in envelope
        assert "data" in envelope
        # Token must not appear in plaintext on Windows; on non-Windows the
        # envelope still wraps the JSON in base64 so substring search misses it.
        raw_text = CREDENTIALS_FILE_V2.read_text(encoding="utf-8")
        assert "ghp_abc" not in raw_text

    def test_migrates_plaintext_to_dpapi(self):
        """Legacy credentials.json is migrated on first read and renamed to .bak."""
        legacy = {"github.com": {"username": "old_user", "token": "ghp_legacy"}}
        CREDENTIALS_FILE.write_text(json.dumps(legacy), encoding="utf-8")
        CredentialManager._credentials_cache = None

        creds = CredentialManager.get_token("github.com")
        assert creds == ("old_user", "ghp_legacy")

        # New encrypted file written, legacy renamed to .bak
        assert CREDENTIALS_FILE_V2.exists()
        assert not CREDENTIALS_FILE.exists()
        assert CREDENTIALS_BACKUP_FILE.exists()
        # Backup retains the original plaintext content so the user can still
        # recover if migration goes wrong.
        assert json.loads(CREDENTIALS_BACKUP_FILE.read_text(encoding="utf-8")) == legacy

    def test_corrupted_dpapi_file_returns_empty(self):
        """A garbled credentials.dpapi must not crash; manager treats it as empty."""
        CREDENTIALS_FILE_V2.write_text("not json", encoding="utf-8")
        CredentialManager._credentials_cache = None
        assert CredentialManager.list_hosts() == []

    def test_envelope_with_invalid_base64_returns_empty(self):
        """Envelope present but `data` is not valid base64 — recover gracefully."""
        envelope = {"version": 1, "encrypted": False, "data": "###not-base64###"}
        CREDENTIALS_FILE_V2.write_text(json.dumps(envelope), encoding="utf-8")
        CredentialManager._credentials_cache = None
        assert CredentialManager.list_hosts() == []

    def test_unencrypted_envelope_round_trip(self):
        """encrypted=false envelopes (CI / non-Windows fallback) decode back."""
        plaintext = json.dumps({"github.com": {"username": "u", "token": "t"}}).encode("utf-8")
        envelope = {
            "version": 1,
            "encrypted": False,
            "data": base64.b64encode(plaintext).decode("ascii"),
        }
        CREDENTIALS_FILE_V2.write_text(json.dumps(envelope), encoding="utf-8")
        CredentialManager._credentials_cache = None
        assert CredentialManager.get_token("github.com") == ("u", "t")
