"""Persistent credentials store for portal accounts.

Saves and retrieves generated or user-provided portal account credentials
(site name, URL, username/application id, password, created_at, notes)
so they never disappear on page refresh, session restart, or browser crash.
"""

from __future__ import annotations

import json
import os
import secrets
import string
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from . import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_compliant_password(length: int = 12) -> str:
    """Generate a strong password adhering to strict government portal rules.

    Rules typically required by NIC / JEE / UPSC:
    - 8 to 13 characters (we default to 12)
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character from {!@#$%^&*}
    """
    length = max(8, min(length, 13))  # Keep within 8-13 range standard for NIC portals
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*"

    # Guarantee at least one from each character class
    chars = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(special),
    ]

    all_allowed = upper + lower + digits + special
    for _ in range(length - 4):
        chars.append(secrets.choice(all_allowed))

    # Shuffle cryptographically
    shuffled = chars[:]
    for i in range(len(shuffled) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]

    return "".join(shuffled)


@dataclass
class CredentialRecord:
    id: str
    site_name: str
    url: str
    username: str
    password: str
    created_at: str
    updated_at: str
    domain: str = ""
    notes: str = ""
    account_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CredentialStore:
    """Persistent storage for portal account passwords and credentials."""

    _instance: Optional[CredentialStore] = None

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = Path(storage_dir or settings.DATA_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_dir / "credentials.json"
        self._cache: Dict[str, CredentialRecord] = {}
        self._load()

    @classmethod
    def get_instance(cls, storage_dir: Optional[Path] = None) -> CredentialStore:
        if cls._instance is None:
            cls._instance = cls(storage_dir=storage_dir)
        return cls._instance

    def _load(self) -> None:
        if not self.file_path.exists():
            self._cache = {}
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._cache = {
                item["id"]: CredentialRecord(
                    id=item.get("id", str(uuid.uuid4())),
                    site_name=item.get("site_name", "Portal"),
                    url=item.get("url", ""),
                    username=item.get("username", ""),
                    password=item.get("password", ""),
                    created_at=item.get("created_at", _now()),
                    updated_at=item.get("updated_at", _now()),
                    domain=item.get("domain", ""),
                    notes=item.get("notes", ""),
                    account_id=item.get("account_id"),
                )
                for item in data
                if isinstance(item, dict) and item.get("id")
            }
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        try:
            tmp = self.file_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([rec.to_dict() for rec in self._cache.values()], f, indent=2)
            tmp.replace(self.file_path)
        except Exception:
            pass

    def list_credentials(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self._load()
        results = []
        for rec in self._cache.values():
            if account_id and rec.account_id and rec.account_id != account_id:
                continue
            results.append(rec.to_dict())
        # Sort newest first
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results

    def save_credential(
        self,
        site_name: str,
        url: str,
        username: str,
        password: str,
        notes: str = "",
        account_id: Optional[str] = None,
        cred_id: Optional[str] = None,
    ) -> CredentialRecord:
        self._load()
        domain = urlparse(url).netloc.lower() if url else ""
        cid = cred_id or str(uuid.uuid4())
        now = _now()
        existing = self._cache.get(cid)
        created_at = existing.created_at if existing else now

        record = CredentialRecord(
            id=cid,
            site_name=site_name or domain or "Portal",
            url=url,
            username=username,
            password=password,
            created_at=created_at,
            updated_at=now,
            domain=domain,
            notes=notes,
            account_id=account_id,
        )
        self._cache[cid] = record
        self._save()
        return record

    def delete_credential(self, cred_id: str, account_id: Optional[str] = None) -> bool:
        self._load()
        if cred_id in self._cache:
            if account_id and self._cache[cred_id].account_id and self._cache[cred_id].account_id != account_id:
                return False
            del self._cache[cred_id]
            self._save()
            return True
        return False

    def find_by_domain_or_url(self, url: str, account_id: Optional[str] = None) -> Optional[CredentialRecord]:
        self._load()
        target_domain = urlparse(url).netloc.lower() if url else ""
        for rec in self._cache.values():
            if account_id and rec.account_id and rec.account_id != account_id:
                continue
            if rec.domain and rec.domain == target_domain:
                return rec
            if url and rec.url and (url in rec.url or rec.url in url):
                return rec
        return None
