"""FormPilot app accounts: signup, login, sessions and private workspaces.

The portal account (the one a candidate creates on a government site) and a
FormPilot account are different things.  This module is the second one: it is
what makes "my vault" mean *my* vault.

Design rules
------------
* A password is never stored, logged or returned.  Only a PBKDF2-HMAC-SHA256
  digest with a per-account random salt is written to disk.
* A session token is returned to the client once.  The store keeps only its
  SHA-256 digest, so a copy of ``accounts.json`` cannot be replayed.
* Every account gets a directory of its own: ``candidate_vault.json``,
  ``documents/``, ``runs/`` and ``uploads/``.  There is no shared global vault
  behind the login screen.
* File writes are atomic and ``0600``; the in-process lock keeps two FastAPI
  worker threads from clobbering each other.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import settings

# OWASP's 2023 floor for PBKDF2-HMAC-SHA256.  The iteration count is stored per
# account so it can be raised later without invalidating old passwords.  Tests
# lower it through the environment; production keeps the real floor.
PBKDF2_ITERATIONS = max(
    1_000, int(os.getenv("FORMPILOT_PBKDF2_ITERATIONS", "600000"))
)
SALT_BYTES = 16
TOKEN_BYTES = 32

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 200
MAX_NAME_LENGTH = 80
MAX_EMAIL_LENGTH = 254

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
_ACCOUNT_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class AccountError(ValueError):
    """A user-actionable account failure.  Safe to show in the UI."""


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    name: str
    created_at: str

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "created_at": self.created_at,
        }


def normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or len(email) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(email):
        raise AccountError("Enter a valid email address.")
    return email


def _hash_password(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class AccountStore:
    """JSON-backed account and session store with per-account workspaces."""

    _instance: Optional["AccountStore"] = None
    _instance_path: Optional[str] = None

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else settings.ACCOUNTS_DIR / "accounts.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def get_instance(cls) -> "AccountStore":
        path = str(settings.ACCOUNTS_DIR / "accounts.json")
        if cls._instance is None or cls._instance_path != path:
            cls._instance = AccountStore(Path(path))
            cls._instance_path = path
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None
        cls._instance_path = None

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "accounts": {}, "sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise AccountError(
                "The account store could not be read. Restore it from a backup."
            ) from exc
        if not isinstance(data, dict):
            raise AccountError("The account store is not a JSON object.")
        data.setdefault("version", 1)
        data.setdefault("accounts", {})
        data.setdefault("sessions", {})
        return data

    def _write(self) -> None:
        body = json.dumps(self._data, indent=2, ensure_ascii=False).encode("utf-8")
        fd, tmp_name = tempfile.mkstemp(
            prefix=".accounts.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # -------------------------------------------------------------- queries

    def count(self) -> int:
        with self._lock:
            return len(self._data.get("accounts") or {})

    def get(self, account_id: str) -> Optional[Account]:
        with self._lock:
            record = (self._data.get("accounts") or {}).get(str(account_id or ""))
            return self._public(record) if record else None

    def find_by_email(self, email: str) -> Optional[Account]:
        try:
            wanted = normalize_email(email)
        except AccountError:
            return None
        with self._lock:
            for record in (self._data.get("accounts") or {}).values():
                if record.get("email") == wanted:
                    return self._public(record)
        return None

    def _public(self, record: Dict[str, Any]) -> Account:
        return Account(
            id=str(record.get("id") or ""),
            email=str(record.get("email") or ""),
            name=str(record.get("name") or ""),
            created_at=str(record.get("created_at") or ""),
        )

    # ------------------------------------------------------------- signup

    def signup(
        self, email: str, password: str, name: str = ""
    ) -> Tuple[Account, str]:
        normalized = normalize_email(email)
        password = str(password or "")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AccountError(
                f"Use at least {MIN_PASSWORD_LENGTH} characters for your password."
            )
        if len(password) > MAX_PASSWORD_LENGTH:
            raise AccountError("That password is too long.")
        display_name = str(name or "").strip()[:MAX_NAME_LENGTH]

        with self._lock:
            for record in (self._data.get("accounts") or {}).values():
                if record.get("email") == normalized:
                    raise AccountError("An account with that email already exists.")

            salt = secrets.token_bytes(SALT_BYTES)
            account_id = uuid_hex()
            record = {
                "id": account_id,
                "email": normalized,
                "name": display_name,
                "salt": base64.b64encode(salt).decode("ascii"),
                "password_hash": base64.b64encode(
                    _hash_password(password, salt, PBKDF2_ITERATIONS)
                ).decode("ascii"),
                "iterations": PBKDF2_ITERATIONS,
                "created_at": _iso(_now()),
                "updated_at": _iso(_now()),
            }
            self._data.setdefault("accounts", {})[account_id] = record
            token = self._issue_session(account_id)
            self._write()
            return self._public(record), token

    # -------------------------------------------------------------- login

    def login(self, email: str, password: str) -> Tuple[Account, str]:
        try:
            normalized = normalize_email(email)
        except AccountError:
            # Do not reveal whether the address exists.
            raise AccountError("Email or password is incorrect.") from None
        password = str(password or "")

        with self._lock:
            match = None
            for record in (self._data.get("accounts") or {}).values():
                if record.get("email") == normalized:
                    match = record
                    break
            if not match:
                # Spend comparable time so a missing account is not obvious.
                _hash_password(password or "x", b"\0" * SALT_BYTES, PBKDF2_ITERATIONS)
                raise AccountError("Email or password is incorrect.")

            try:
                salt = base64.b64decode(match.get("salt") or "")
                expected = base64.b64decode(match.get("password_hash") or "")
                iterations = int(match.get("iterations") or PBKDF2_ITERATIONS)
            except Exception:
                raise AccountError("Email or password is incorrect.") from None

            actual = _hash_password(password, salt, iterations)
            if not hmac.compare_digest(actual, expected):
                raise AccountError("Email or password is incorrect.")

            match["updated_at"] = _iso(_now())
            token = self._issue_session(match["id"])
            self._write()
            return self._public(match), token

    def demo_login(
        self, email: str = "demo@formpilot.local", name: str = "Candidate Nishant"
    ) -> Tuple[Account, str]:
        """Provide or create a demo account with an active session in 1 click."""
        with self._lock:
            for record in (self._data.get("accounts") or {}).values():
                if record.get("email") == email:
                    token = self._issue_session(record["id"])
                    self._write()
                    return self._public(record), token

            salt = secrets.token_bytes(SALT_BYTES)
            account_id = uuid_hex()
            record = {
                "id": account_id,
                "email": email,
                "name": name,
                "salt": base64.b64encode(salt).decode("ascii"),
                "password_hash": base64.b64encode(
                    _hash_password("DemoPassword123!", salt, PBKDF2_ITERATIONS)
                ).decode("ascii"),
                "iterations": PBKDF2_ITERATIONS,
                "created_at": _iso(_now()),
                "updated_at": _iso(_now()),
            }
            self._data.setdefault("accounts", {})[account_id] = record
            token = self._issue_session(account_id)
            self._write()
            return self._public(record), token

    def google_login(
        self, email: str, name: str = "", google_sub: str = ""
    ) -> Tuple[Account, str]:
        """Sign in or auto-create an account via verified Google identity."""
        normalized = normalize_email(email)
        display_name = str(name or "").strip()[:MAX_NAME_LENGTH] or normalized.split("@")[0]

        with self._lock:
            # Check if an account already exists with this email
            for record in (self._data.get("accounts") or {}).values():
                if record.get("email") == normalized:
                    if google_sub:
                        record["google_sub"] = google_sub
                    if not record.get("name") and display_name:
                        record["name"] = display_name
                    record["updated_at"] = _iso(_now())
                    token = self._issue_session(record["id"])
                    self._write()
                    return self._public(record), token

            # Create new account for verified Google user
            salt = secrets.token_bytes(SALT_BYTES)
            account_id = uuid_hex()
            dummy_password = secrets.token_urlsafe(32)
            record = {
                "id": account_id,
                "email": normalized,
                "name": display_name,
                "salt": base64.b64encode(salt).decode("ascii"),
                "password_hash": base64.b64encode(
                    _hash_password(dummy_password, salt, PBKDF2_ITERATIONS)
                ).decode("ascii"),
                "iterations": PBKDF2_ITERATIONS,
                "google_sub": google_sub,
                "auth_provider": "google",
                "created_at": _iso(_now()),
                "updated_at": _iso(_now()),
            }
            self._data.setdefault("accounts", {})[account_id] = record
            token = self._issue_session(account_id)
            self._write()
            return self._public(record), token


    # ------------------------------------------------------------ sessions

    def _issue_session(self, account_id: str) -> str:
        self._prune_sessions()
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = _now()
        self._data.setdefault("sessions", {})[_token_digest(token)] = {
            "account_id": account_id,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(days=settings.SESSION_DAYS)),
            "last_seen": _iso(now),
        }
        return token

    def _prune_sessions(self) -> None:
        sessions = self._data.get("sessions") or {}
        now = _now()
        for digest, record in list(sessions.items()):
            expires = _parse_iso(record.get("expires_at"))
            if expires is None or expires <= now:
                sessions.pop(digest, None)

    def resolve(self, token: str) -> Optional[Account]:
        """Return the account for a live session token, or ``None``."""
        token = str(token or "").strip()
        if not token:
            return None
        digest = _token_digest(token)
        with self._lock:
            sessions = self._data.get("sessions") or {}
            record = sessions.get(digest)
            if not record:
                return None
            expires = _parse_iso(record.get("expires_at"))
            if expires is None or expires <= _now():
                sessions.pop(digest, None)
                self._write()
                return None
            account = (self._data.get("accounts") or {}).get(record.get("account_id"))
            if not account:
                sessions.pop(digest, None)
                self._write()
                return None
            record["last_seen"] = _iso(_now())
            return self._public(account)

    def logout(self, token: str) -> bool:
        digest = _token_digest(str(token or ""))
        with self._lock:
            sessions = self._data.get("sessions") or {}
            if digest not in sessions:
                return False
            sessions.pop(digest, None)
            self._write()
            return True

    def logout_all(self, account_id: str) -> int:
        with self._lock:
            sessions = self._data.get("sessions") or {}
            doomed = [
                digest
                for digest, record in sessions.items()
                if record.get("account_id") == account_id
            ]
            for digest in doomed:
                sessions.pop(digest, None)
            if doomed:
                self._write()
            return len(doomed)

    # ----------------------------------------------------------- workspace

    def workspace_dir(self, account_id: str) -> Path:
        if not _ACCOUNT_ID_RE.match(str(account_id or "")):
            raise AccountError("Invalid account id.")
        directory = settings.ACCOUNTS_DIR / account_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def delete_account(self, account_id: str) -> bool:
        """Remove an account and its session tokens, never its data silently."""
        with self._lock:
            accounts = self._data.get("accounts") or {}
            if account_id not in accounts:
                return False
            self.logout_all(account_id)
            accounts.pop(account_id, None)
            self._write()
            return True


def uuid_hex() -> str:
    return secrets.token_hex(16)
