"""AES-256-GCM encryption for the Candidate One-Vault and its documents.

The profile JSON stays opt-in: a local demo can still run with a plain file
when ``FORMPILOT_VAULT_KEY`` is unset.  Uploaded documents are different - a
passport photo or an Aadhaar scan must never sit on disk in the clear - so the
document store always has a key.  It uses ``FORMPILOT_VAULT_KEY`` when set and
otherwise a generated key at ``<data>/.formpilot.key`` (mode 0600).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - cryptography is an optional dependency
    AESGCM = None  # type: ignore[assignment]


class VaultCryptoError(RuntimeError):
    pass


class VaultCipher:
    VERSION = 1

    def __init__(self, key_b64: str):
        if AESGCM is None:
            raise VaultCryptoError(
                "FORMPILOT_VAULT_KEY is set but the 'cryptography' package is not installed."
            )
        try:
            key = base64.b64decode(key_b64, validate=True)
        except Exception as exc:
            raise VaultCryptoError("FORMPILOT_VAULT_KEY must be valid base64.") from exc
        if len(key) != 32:
            raise VaultCryptoError("FORMPILOT_VAULT_KEY must decode to exactly 32 bytes for AES-256.")
        self._aes = AESGCM(key)

    def encrypt_bytes(self, plaintext: bytes) -> dict[str, Any]:
        nonce = os.urandom(12)
        ciphertext = self._aes.encrypt(nonce, plaintext, b"formpilot-vault-v1")
        return {
            "version": self.VERSION,
            "encrypted": True,
            "algorithm": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt_bytes(self, envelope: dict[str, Any]) -> bytes:
        try:
            nonce = base64.b64decode(envelope["nonce"])
            ciphertext = base64.b64decode(envelope["ciphertext"])
        except Exception as exc:
            raise VaultCryptoError("Encrypted vault envelope is malformed.") from exc
        try:
            return self._aes.decrypt(nonce, ciphertext, b"formpilot-vault-v1")
        except Exception as exc:
            raise VaultCryptoError(
                "Could not decrypt the vault. Check FORMPILOT_VAULT_KEY."
            ) from exc


def cipher_from_env() -> Optional[VaultCipher]:
    key = os.getenv("FORMPILOT_VAULT_KEY", "").strip()
    return VaultCipher(key) if key else None


def _key_file() -> Path:
    override = os.getenv("FORMPILOT_KEY_FILE", "").strip()
    if override:
        return Path(override)
    data_dir = Path(
        os.getenv("FORMPILOT_DATA_DIR", Path(__file__).resolve().parents[2] / "data")
    )
    return data_dir / ".formpilot.key"


def load_or_create_key() -> str:
    """Return the document key: env var, saved key file, or a new one.

    Documents are always encrypted, so this never returns an empty string.
    The generated key lives beside the data directory with mode 0600; it is
    never served, logged or committed.
    """
    env_key = os.getenv("FORMPILOT_VAULT_KEY", "").strip()
    if env_key:
        return env_key

    path = _key_file()
    try:
        if path.exists():
            saved = path.read_text(encoding="utf-8").strip()
            if saved:
                return saved
    except OSError:
        pass

    key = generate_key_b64()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 0600 from creation, so there is no window where the key is world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return key


def document_cipher() -> VaultCipher:
    """Always-available cipher for uploaded documents."""
    return VaultCipher(load_or_create_key())


def generate_key_b64() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def decode_envelope(raw: str) -> tuple[bool, dict[str, Any] | bytes]:
    """Return (is_encrypted, payload)."""
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("encrypted") is True:
        return True, data
    return False, raw.encode("utf-8")
