import base64
import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.runtime_paths import runtime_dir

logger = logging.getLogger(__name__)

# 凭据存储文件
PROJECTS_DIR = runtime_dir("projects")
CREDENTIALS_FILE = PROJECTS_DIR / "credentials.json"        # legacy plaintext (for one-time migration only)
CREDENTIALS_FILE_V2 = PROJECTS_DIR / "credentials.dpapi"    # encrypted envelope (current)
CREDENTIALS_BACKUP_FILE = PROJECTS_DIR / "credentials.json.bak"
_DPAPI_DESCRIPTION = "Desktop Agent credentials"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _encrypt_blob(plaintext: bytes) -> Tuple[bytes, bool]:
    """Encrypt with Windows DPAPI when available; fall back to identity.

    Returns (blob, encrypted_flag). The flag is recorded in the envelope so
    decrypt knows whether to call DPAPI on read. Non-Windows hosts (CI, dev
    on macOS/Linux) record encrypted=false; the file is still strict-read
    perms so it is no worse than the previous plaintext file.
    """
    if _is_windows():
        try:
            import win32crypt  # pywin32 — Windows-only
            blob = win32crypt.CryptProtectData(
                plaintext, _DPAPI_DESCRIPTION, None, None, None, 0
            )
            return bytes(blob), True
        except Exception as exc:
            logger.warning("[CredentialManager] DPAPI encrypt failed, falling back to plaintext: {exc}")
    return plaintext, False


def _decrypt_blob(blob: bytes, is_encrypted: bool) -> Optional[bytes]:
    if not is_encrypted:
        return blob
    if not _is_windows():
        return None
    try:
        import win32crypt
        _desc, plaintext = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return bytes(plaintext)
    except Exception as exc:
        print(f"[CredentialManager] DPAPI decrypt failed: {exc}")
        return None


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class CredentialManager:
    """管理 Git 凭据：优先使用系统 GCM，fallback 到本地加密存储"""

    _credentials_cache: Optional[Dict[str, Dict[str, str]]] = None
    _cache_loaded_at: float = 0.0
    _CACHE_TTL: float = 300.0

    @classmethod
    def has_gcm(cls) -> bool:
        """检测系统是否安装了 Git Credential Manager"""
        system = platform.system()
        try:
            if system == "Windows":
                # Git for Windows 自带 GCM
                result = subprocess.run(
                    ["git", "config", "--system", "credential.helper"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if "manager" in result.stdout.lower():
                    return True
                # 或者直接检查 git-credential-manager-core.exe
                result = subprocess.run(
                    ["where", "git-credential-manager.exe"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode == 0:
                    return True
            else:
                result = subprocess.run(
                    ["git", "config", "--system", "credential.helper"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if result.stdout.strip():
                    return True
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            pass
        return False

    @classmethod
    def configure_gcm(cls, project_path: str) -> None:
        """在项目仓库中配置 GCM"""
        try:
            subprocess.run(
                ["git", "-C", project_path, "config", "credential.helper", "manager"],
                capture_output=True, timeout=5
            )
            subprocess.run(
                ["git", "-C", project_path, "config", "credential.useHttpPath", "true"],
                capture_output=True, timeout=5
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    @classmethod
    def _load_credentials(cls) -> Dict[str, Dict[str, str]]:
        """加载凭据：优先 DPAPI 文件；不存在时迁移旧明文文件。"""
        now = time.time()
        if cls._credentials_cache is not None and (now - cls._cache_loaded_at) < cls._CACHE_TTL:
            return cls._credentials_cache

        data = cls._load_from_v2()
        if data is not None:
            cls._credentials_cache = data
            cls._cache_loaded_at = time.time()
            return cls._credentials_cache

        # Legacy plaintext fallback + one-time migration.
        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    legacy = json.load(f)
            except (OSError, json.JSONDecodeError):
                legacy = None
            if isinstance(legacy, dict):
                cls._credentials_cache = legacy
                cls._save_credentials(legacy)
                try:
                    if CREDENTIALS_BACKUP_FILE.exists():
                        CREDENTIALS_BACKUP_FILE.unlink()
                    CREDENTIALS_FILE.rename(CREDENTIALS_BACKUP_FILE)
                except OSError as exc:
                    logger.warning("[CredentialManager] Plaintext backup rename failed: {exc}")
                return cls._credentials_cache

        cls._credentials_cache = {}
        cls._cache_loaded_at = time.time()
        return cls._credentials_cache

    @classmethod
    def reload_credentials(cls) -> None:
        """Invalidate cache and force reload on next access."""
        cls._credentials_cache = None
        cls._cache_loaded_at = 0.0

    @classmethod
    def _load_from_v2(cls) -> Optional[Dict[str, Dict[str, str]]]:
        if not CREDENTIALS_FILE_V2.exists():
            return None
        try:
            envelope = json.loads(CREDENTIALS_FILE_V2.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(envelope, dict):
            return None
        try:
            blob = base64.b64decode(envelope.get("data", ""), validate=True)
        except (ValueError, TypeError):
            return None
        plaintext = _decrypt_blob(blob, bool(envelope.get("encrypted", False)))
        if plaintext is None:
            return None
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def _save_credentials(cls, data: Dict[str, Dict[str, str]]) -> None:
        """以 DPAPI 加密信封写入 credentials.dpapi（非 Windows 平台 fallback 到明文同文件）"""
        cls._credentials_cache = data
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        blob, encrypted = _encrypt_blob(plaintext)
        envelope = {
            "version": 1,
            "encrypted": encrypted,
            "data": base64.b64encode(blob).decode("ascii"),
        }
        try:
            _atomic_write_text(CREDENTIALS_FILE_V2, json.dumps(envelope, indent=2))
        except OSError as exc:
            logger.warning("[CredentialManager] Failed to save credentials: {exc}")

    @classmethod
    def store_token(cls, host: str, username: str, token: str) -> None:
        """存储 token 到本地（host → {username, token}）"""
        creds = cls._load_credentials()
        creds[host] = {"username": username, "token": token}
        cls._save_credentials(creds)

    @classmethod
    def get_token(cls, host: str) -> Optional[Tuple[str, str]]:
        """从本地存储获取指定 host 的凭据，返回 (username, token)"""
        creds = cls._load_credentials()
        entry = creds.get(host)
        if entry:
            return (entry.get("username", ""), entry.get("token", ""))
        return None

    @classmethod
    def delete_token(cls, host: str) -> None:
        """删除指定 host 的凭据"""
        creds = cls._load_credentials()
        if host in creds:
            del creds[host]
            cls._save_credentials(creds)

    @classmethod
    def list_hosts(cls) -> List[str]:
        """返回所有已存储凭据的 host 列表"""
        return list(cls._load_credentials().keys())

    @classmethod
    def gcm_fill(cls, protocol: str, host: str, path: str = "") -> Optional[Tuple[str, str]]:
        """通过 GCM 获取凭据。返回 (username, password/token)"""
        try:
            # git credential fill
            input_data = f"protocol={protocol}\nhost={host}\n"
            if path:
                input_data += f"path={path}\n"
            input_data += "\n"

            result = subprocess.run(
                ["git", "credential", "fill"],
                input=input_data, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                return None

            username = None
            password = None
            for line in result.stdout.strip().split("\n"):
                if line.startswith("username="):
                    username = line[len("username="):]
                elif line.startswith("password="):
                    password = line[len("password="):]

            if username and password:
                return (username, password)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    @classmethod
    def gcm_approve(cls, protocol: str, host: str, username: str, password: str, path: str = "") -> bool:
        """通过 GCM 存储凭据"""
        try:
            input_data = f"protocol={protocol}\nhost={host}\n"
            if path:
                input_data += f"path={path}\n"
            input_data += f"username={username}\npassword={password}\n\n"

            result = subprocess.run(
                ["git", "credential", "approve"],
                input=input_data, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    @classmethod
    def get_git_credentials(cls, remote_url: str) -> Optional[Tuple[str, str]]:
        """综合获取 Git 凭据：先尝试 GCM，fallback 到本地存储"""
        parsed = urlparse(remote_url)
        if parsed.scheme in ("http", "https"):
            protocol = parsed.scheme
            host = parsed.hostname or ""
            path = parsed.path.lstrip("/") or ""
        elif "@" in remote_url and ":" in remote_url:
            return None  # SSH 不需要 token
        else:
            return None

        # 1. 尝试 GCM
        if cls.has_gcm():
            creds = cls.gcm_fill(protocol, host, path)
            if creds:
                return creds

        # 2. Fallback 到本地存储
        return cls.get_token(host)
