"""Persistent lessons learned from a portal.

A lesson is a small, reviewable fact: on this portal domain, for this error or
situation, this action worked (or did not).  Lessons are deliberately narrow.
They never store field values, screenshots, documents or personal data.

The orchestrator consults them before repeating a recovery that already failed
and records the outcome afterwards, so a mistake made once on an account is not
made again on the same portal.  An account owns its own lesson file; nothing is
shared across accounts.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from . import settings


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def normalize_domain(value: str) -> str:
    """Return a bare hostname for a URL or a domain string."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        return (urlsplit(raw).hostname or "").lower()
    except ValueError:
        return ""


def normalize_signature(value: str) -> str:
    """Collapse volatile parts of an error message into a stable signature.

    IDs, timestamps and numbers change between attempts; the message does not.
    Keeping them would make every occurrence a "new" lesson.
    """
    text = str(value or "").lower()
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text)
    text = re.sub(r"\d+", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", (value or "").lower()).strip("._-")[:160]


class LessonStore:
    """A bounded, atomic JSON store of portal lessons."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path) if path else settings.DATA_DIR / "lessons.json"
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {"version": 1, "updated_at": _utcnow(), "lessons": []}
        self._load()

    @classmethod
    def get_instance(cls) -> "LessonStore":
        instance = getattr(cls, "_instance", None)
        if instance is None:
            instance = cls()
            cls._instance = instance
        return instance

    def _load(self) -> None:
        try:
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict) and isinstance(data.get("lessons"), list):
                    self._data = data
        except (OSError, ValueError):
            # A corrupt lesson file must never stop a run.
            self._data = {"version": 1, "updated_at": _utcnow(), "lessons": []}

    def _save(self) -> None:
        self._data["updated_at"] = _utcnow()
        # Keep the file bounded and newest-first so it stays cheap to read.
        # ``or []`` is wrong here: an empty list is falsy, so it would replace
        # the list that ``record`` just appended to and silently lose lessons.
        lessons = self._data.get("lessons")
        if not isinstance(lessons, list):
            lessons = []
        lessons.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        self._data["lessons"] = lessons[:500]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".lessons-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except (OSError, UnboundLocalError):
                pass

    def record(
        self,
        *,
        domain: str,
        signature: str,
        action: str,
        outcome: str,
        note: str = "",
    ) -> Dict[str, Any]:
        """Record one attempt and its outcome.  Repeat attempts are merged."""
        host = normalize_domain(domain)
        sig = normalize_signature(signature)
        action_key = _safe_id(action)
        if not host or not sig or not action_key:
            return {}
        with self._lock:
            lessons = self._data.get("lessons")
            if not isinstance(lessons, list):
                lessons = []
                self._data["lessons"] = lessons
            existing = next(
                (
                    item
                    for item in lessons
                    if item.get("domain") == host
                    and item.get("signature") == sig
                    and item.get("action") == action_key
                ),
                None,
            )
            now = _utcnow()
            if existing is None:
                existing = {
                    "lesson_id": "lesson-"
                    + hashlib.sha1(f"{host}|{sig}|{action_key}".encode("utf-8")).hexdigest()[:12],
                    "domain": host,
                    "signature": sig,
                    "action": action_key,
                    "outcome": outcome,
                    "note": note[:300],
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                lessons.append(existing)
            existing["attempts"] = int(existing.get("attempts") or 0) + 1
            if outcome in {"success", "opened_application", "recovered", "worked"}:
                existing["successes"] = int(existing.get("successes") or 0) + 1
            elif outcome in {"failed", "did_not_work", "no_change"}:
                existing["failures"] = int(existing.get("failures") or 0) + 1
            existing["outcome"] = outcome
            if note:
                existing["note"] = note[:300]
            existing["updated_at"] = now
            self._save()
            return dict(existing)

    def recall(self, *, domain: str, signature: str) -> Optional[Dict[str, Any]]:
        """Return the most recent lesson for this domain and signature."""
        host = normalize_domain(domain)
        sig = normalize_signature(signature)
        if not host or not sig:
            return None
        with self._lock:
            matches = [
                item
                for item in (self._data.get("lessons") or [])
                if item.get("domain") == host and item.get("signature") == sig
            ]
        if not matches:
            return None
        matches.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return dict(matches[0])

    def for_domain(self, domain: str) -> List[Dict[str, Any]]:
        host = normalize_domain(domain)
        if not host:
            return []
        with self._lock:
            items = [
                dict(item)
                for item in (self._data.get("lessons") or [])
                if item.get("domain") == host
            ]
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return items[:40]

    def summary(self, domain: str) -> List[Dict[str, Any]]:
        """A small, public view for chat and the operator brief."""
        return [
            {
                "action": item.get("action"),
                "outcome": item.get("outcome"),
                "successes": item.get("successes", 0),
                "failures": item.get("failures", 0),
                "note": item.get("note", ""),
            }
            for item in self.for_domain(domain)
        ]
