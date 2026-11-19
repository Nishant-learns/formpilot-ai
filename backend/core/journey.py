"""Known-path memory for a portal or an exam.

A recipe records one page.  A journey records the *order* of pages a real
application goes through and the action that moved from one to the next.  The
agent writes a step every time it observes a page and marks a step as proven
when a later page was actually reached.

The point is cost and reliability, not bypassing safety:

* the first visit is agent-driven and learns the path;
* the next visit can reuse saved semantic field keys and controls without
  re-deriving them, so fewer model calls are needed;
* CAPTCHA, OTP, live photo, payment, declarations and final submission are
  still human checkpoints, and a step that contains one is never auto-approved.

Only structure is stored.  Input values, file paths, screenshots and raw HTML
are not.  Visible text is redacted against the candidate's own vault values
before it is written, so a journey is safe to inspect and, eventually, to share
between candidates using the same exam.
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
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from . import settings


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _slug(value: str, limit: int = 60) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return text[:limit] or "portal"


def normalize_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        return (urlsplit(raw).hostname or "").lower()
    except ValueError:
        return ""


def journey_key(portal_or_query: str, *, is_url: bool = False) -> str:
    """Return the storage key for an exam query or a portal URL.

    ``JEE`` and ``JEE Main 2027`` are exam keys, so all the portals that make
    up one application (the NTA landing page and the examination-services
    host) live in the same journey.  A pasted URL is a portal key.
    """
    text = str(portal_or_query or "").strip()
    if is_url or text.startswith(("http://", "https://")):
        return f"portal_{_slug(normalize_domain(text))}"
    # A year, session or phase is not a different exam.  "JEE", "JEE Main" and
    # "JEE Main 2027 Session 1" all reuse one learned path.
    cleaned = re.sub(
        r"\b(?:20\d{2}|session\s*\d+|phase\s*\d+|shift\s*\d+|"
        r"jan(?:uary)?|apr(?:il)?|may|sep(?:tember)?|oct(?:ober)?)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    slug = _slug(cleaned)
    if slug in {"jee", "jee_main", "jee_mains", "joint_entrance_examination"}:
        return "exam_jee"
    if slug.startswith(("jee_advanced", "jee_adv", "joint_entrance_examination_advanced")):
        return "exam_jee_advanced"
    return f"exam_{slug}"


def _step_identity(dom: Dict[str, Any], form_map: Dict[str, Any]) -> str:
    fingerprint = str(form_map.get("fingerprint") or "").strip()
    if fingerprint:
        return fingerprint
    url = str(dom.get("url") or form_map.get("url") or "").strip()
    try:
        path = urlsplit(url).path.rstrip("/").lower() or "/"
    except ValueError:
        path = url.lower()
    field_names = "|".join(
        sorted(
            str(field.get("name") or field.get("id") or field.get("semantic_key") or "")
            for field in (form_map.get("fields") or [])
        )
    )
    raw = f"{path}|{form_map.get('page_type') or ''}|{field_names}"
    return "step-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _redact(text: str, secrets: Iterable[str]) -> str:
    value = str(text or "")
    if not value:
        return ""
    for secret in secrets:
        secret = str(secret or "").strip()
        if len(secret) < 4:
            continue
        value = re.sub(re.escape(secret), "<redacted>", value, flags=re.IGNORECASE)
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", "<email>", value)
    value = re.sub(r"\b\d{4}\s?\d{4}\s?\d{4}\b", "<id>", value)
    value = re.sub(r"\b\d{10}\b", "<phone>", value)
    value = re.sub(r"\b\d{12}\b", "<id>", value)
    return value[:4000]


def _durable_element(element: Dict[str, Any], secrets: Iterable[str]) -> Dict[str, Any]:
    attributes = element.get("attributes") if isinstance(element.get("attributes"), dict) else {}
    keep = {}
    for key in (
        "id",
        "name",
        "type",
        "role",
        "placeholder",
        "aria-label",
        "aria-required",
        "required",
        "maxlength",
        "href",
        "title",
    ):
        if attributes.get(key) not in (None, "", [], {}):
            keep[key] = _redact(str(attributes.get(key)), secrets)
    options = [
        {
            "text": _redact(str(option.get("text") or ""), secrets),
            "value": _redact(str(option.get("value") or ""), secrets),
        }
        for option in (element.get("options") or [])
        if isinstance(option, dict)
    ][:20]
    return {
        "tag": str(element.get("tag") or element.get("tagName") or "").lower(),
        "role": str(element.get("role") or "").lower(),
        "name": _redact(str(element.get("name") or ""), secrets),
        "text": _redact(str(element.get("text") or ""), secrets),
        "label": _redact(str(element.get("labelText") or ""), secrets),
        "attributes": keep,
        "options": options,
        "visible": bool(element.get("visible")),
        "enabled": bool(element.get("enabled")),
    }


class JourneyStore:
    """A bounded, atomic JSON store of known application paths."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or (settings.DATA_DIR / "journeys"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path_for(self, key: str) -> Path:
        return self.root / f"{_slug(key, limit=80)}.json"

    def _load(self, key: str) -> Dict[str, Any]:
        path = self.path_for(key)
        empty = {
            "version": 1,
            "key": key,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
            "portals": [],
            "steps": [],
            "transitions": [],
        }
        if not path.is_file():
            return empty
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return empty
        if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
            return empty
        for field, default in empty.items():
            data.setdefault(field, default)
        return data

    def _save(self, key: str, data: Dict[str, Any]) -> None:
        data["updated_at"] = _utcnow()
        data["steps"] = list(data.get("steps") or [])[:80]
        data["transitions"] = list(data.get("transitions") or [])[:200]
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=path.name, suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    # ------------------------------------------------------------------ write

    def observe_page(
        self,
        key: str,
        dom: Dict[str, Any],
        form_map: Dict[str, Any],
        *,
        secrets: Optional[Iterable[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record or refresh one page in the journey.

        A loading shell or an empty redirect page is ignored: it would
        otherwise become a bogus step in the known path.
        """
        if not key:
            return None
        if dom.get("loading"):
            return None
        url = str(dom.get("url") or form_map.get("url") or "")
        # A browser error page or a blank redirect is not a step in the path.
        if not url or url.startswith(("chrome-error://", "edge-error://", "about:")):
            return None
        meaningful = bool(
            dom.get("inputs")
            or dom.get("gateways")
            or dom.get("applicationLinks")
            or str(dom.get("visibleText") or "").strip()
        )
        if not meaningful:
            return None

        secrets = list(secrets or [])
        step_id = _step_identity(dom, form_map)
        now = _utcnow()
        with self._lock:
            data = self._load(key)
            existing = next(
                (step for step in data["steps"] if step.get("step_id") == step_id),
                None,
            )
            domain = normalize_domain(dom.get("url") or form_map.get("url") or "")
            if domain and domain not in data["portals"]:
                data["portals"].append(domain)

            fields = []
            for field in (form_map.get("fields") or [])[:120]:
                fields.append(
                    {
                        "semantic_key": str(field.get("semantic_key") or field.get("key") or ""),
                        "label": _redact(str(field.get("label") or ""), secrets),
                        "name": str(field.get("name") or ""),
                        "id": str(field.get("id") or ""),
                        "type": str(field.get("type") or ""),
                        "required": bool(field.get("required")),
                        "options": [
                            _redact(str(option.get("text") or option), secrets)
                            for option in (field.get("options") or [])
                            if str(option.get("text") or option or "").strip()
                        ][:30],
                    }
                )
            gateways = [
                {
                    "text": _redact(str(item.get("text") or ""), secrets),
                    "type": str(item.get("type") or ""),
                    "href": str(item.get("href") or ""),
                    "tag": str(item.get("tagName") or item.get("tag") or ""),
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "role": str(item.get("role") or ""),
                }
                for item in (dom.get("gateways") or [])
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ][:20]
            application_links = [
                {
                    "text": _redact(str(item.get("text") or ""), secrets),
                    "href": str(item.get("href") or ""),
                    "tag": str(item.get("tagName") or item.get("tag") or ""),
                    "id": str(item.get("id") or ""),
                }
                for item in (dom.get("applicationLinks") or [])
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ][:20]
            controls = [
                {
                    "text": _redact(str(item.get("text") or ""), secrets),
                    "type": str(item.get("type") or ""),
                    "tag": str(item.get("tagName") or item.get("tag") or ""),
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "href": str(item.get("href") or ""),
                    "role": str(item.get("role") or ""),
                    "kind": "next",
                }
                for item in (dom.get("nextButtons") or [])
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ][:20]
            checkpoints = self._checkpoints(dom, form_map)
            snapshot = {
                "url": _redact(str(dom.get("url") or form_map.get("url") or ""), secrets),
                "title": _redact(str(dom.get("title") or ""), secrets),
                "page_type": str(form_map.get("page_type") or ""),
                "step_heading": _redact(str(dom.get("stepHeading") or ""), secrets),
                "visible_text": _redact(str(dom.get("visibleText") or ""), secrets),
                "form_count": int(dom.get("formCount") or 0),
                "form_action": _redact(str(dom.get("formAction") or ""), secrets),
                "frameworks": list(dom.get("frameworks") or [])[:10],
                "elements": [
                    _durable_element(element, secrets)
                    for element in (dom.get("elements") or [])[:400]
                    if isinstance(element, dict)
                ],
            }

            if existing is None:
                existing = {
                    "step_id": step_id,
                    "first_seen": now,
                    "observations": 0,
                    "successes": 0,
                    "failures": 0,
                }
                data["steps"].append(existing)
            existing.update(
                {
                    "page_type": str(form_map.get("page_type") or ""),
                    "fingerprint": str(form_map.get("fingerprint") or ""),
                    "url": snapshot["url"],
                    "url_path": urlsplit(snapshot["url"]).path or "/",
                    "title": snapshot["title"],
                    "step_heading": snapshot["step_heading"],
                    "fields": fields,
                    "gateways": gateways,
                    "application_links": application_links,
                    "controls": controls,
                    "checkpoints": checkpoints,
                    "dom_snapshot": snapshot,
                    "last_seen": now,
                }
            )
            existing["observations"] = int(existing.get("observations") or 0) + 1
            self._save(key, data)
            return dict(existing)

    @staticmethod
    def _checkpoints(dom: Dict[str, Any], form_map: Dict[str, Any]) -> List[str]:
        checkpoints: List[str] = []
        if dom.get("captchaElements"):
            checkpoints.append("captcha")
        if dom.get("otpInputs"):
            checkpoints.append("otp")
        if dom.get("livePhotoRequired"):
            checkpoints.append("live_photo")
        # A credential box on an OAuth/sign-in URL is an identity provider.
        # The candidate signs in there; the step is never auto-approved.
        url = str(dom.get("url") or "").lower()
        if any(
            str(item.get("type") or "").lower() == "password"
            for item in (dom.get("inputs") or [])
        ) and re.search(r"oauth|signin|sign-in|sso|authorize|auth/|consent", url):
            checkpoints.append("identity")
        if dom.get("hasPaymentButton"):
            checkpoints.append("payment")
        choices = [
            item
            for item in (dom.get("inputs") or [])
            if str(item.get("type") or "").lower() in {"radio", "checkbox"}
            and not item.get("checked")
        ]
        if choices:
            checkpoints.append("choice")
        if any(
            re.search(r"declaration|consent|agree|certify", str(item.get("label") or ""), re.IGNORECASE)
            for item in choices
        ):
            checkpoints.append("declaration")
        return checkpoints

    def record_transition(
        self,
        key: str,
        *,
        from_step: str,
        action: str,
        target: str,
        to_step: str,
        success: bool = True,
    ) -> None:
        if not key or not from_step or not to_step:
            return
        with self._lock:
            data = self._load(key)
            transitions = data.get("transitions") or []
            match = next(
                (
                    item
                    for item in transitions
                    if item.get("from_step") == from_step
                    and item.get("to_step") == to_step
                    and item.get("action") == action
                    and item.get("target") == target
                ),
                None,
            )
            if match is None:
                match = {
                    "from_step": from_step,
                    "to_step": to_step,
                    "action": action,
                    "target": target,
                    "attempts": 0,
                    "successes": 0,
                }
                transitions.append(match)
            match["attempts"] = int(match.get("attempts") or 0) + 1
            if success:
                match["successes"] = int(match.get("successes") or 0) + 1
            match["updated_at"] = _utcnow()
            data["transitions"] = transitions
            self._save(key, data)

    def mark_step_success(self, key: str, step_id: str) -> None:
        if not key or not step_id:
            return
        with self._lock:
            data = self._load(key)
            for step in data.get("steps") or []:
                if step.get("step_id") == step_id:
                    step["successes"] = int(step.get("successes") or 0) + 1
                    step["last_success"] = _utcnow()
                    self._save(key, data)
                    return

    def mark_step_failure(self, key: str, step_id: str) -> None:
        if not key or not step_id:
            return
        with self._lock:
            data = self._load(key)
            for step in data.get("steps") or []:
                if step.get("step_id") == step_id:
                    step["failures"] = int(step.get("failures") or 0) + 1
                    self._save(key, data)
                    return

    def record_choice(
        self,
        key: str,
        step_id: str,
        *,
        group: str,
        group_id: str = "",
        concept: str,
        label: str,
    ) -> None:
        """Remember which profile concept a machine-named group represents.

        Only the concept and the chosen option text are stored, never the
        candidate's value.  The value stays in the vault and is re-read on the
        next visit.
        """
        if not key or not step_id or not group or not concept:
            return
        with self._lock:
            data = self._load(key)
            for step in data.get("steps") or []:
                if step.get("step_id") != step_id:
                    continue
                choices = [
                    item
                    for item in (step.get("choices") or [])
                    if isinstance(item, dict)
                    and str(item.get("group") or "") != group
                ]
                choices.append(
                    {
                        "group": group,
                        "group_id": group_id,
                        "concept": concept,
                        "label": label,
                    }
                )
                step["choices"] = choices
                self._save(key, data)
                return

    # ------------------------------------------------------------------- read

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        data = self._load(key)
        return data if data.get("steps") else None

    def summary(self, key: str) -> Dict[str, Any]:
        data = self._load(key)
        steps = data.get("steps") or []
        return {
            "key": key,
            "step_count": len(steps),
            "proven_steps": sum(1 for step in steps if int(step.get("successes") or 0) > 0),
            "portals": list(data.get("portals") or []),
            "updated_at": data.get("updated_at"),
        }

    def match_step(
        self,
        key: str,
        dom: Dict[str, Any],
        form_map: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Return the saved step that best matches the live page.

        Fingerprint equality is exact.  Otherwise the URL path and the overlap
        of semantic field keys decide.  A weak match is not returned, because a
        wrong known path is worse than asking the agent to observe again.
        """
        data = self._load(key)
        steps = data.get("steps") or []
        if not steps:
            return None
        step_id = _step_identity(dom, form_map)
        for step in steps:
            if step.get("step_id") == step_id:
                return dict(step)

        url_path = ""
        try:
            url_path = urlsplit(str(dom.get("url") or form_map.get("url") or "")).path or "/"
        except ValueError:
            pass
        live_keys = {
            str(field.get("semantic_key") or "")
            for field in (form_map.get("fields") or [])
            if str(field.get("semantic_key") or "")
        }
        best: Optional[Tuple[float, Dict[str, Any]]] = None
        for step in steps:
            if url_path and step.get("url_path") == url_path:
                return dict(step)
            saved_keys = {
                str(field.get("semantic_key") or "")
                for field in (step.get("fields") or [])
                if str(field.get("semantic_key") or "")
            }
            if not live_keys or not saved_keys:
                continue
            overlap = len(live_keys & saved_keys) / max(len(live_keys | saved_keys), 1)
            if overlap >= 0.6 and (best is None or overlap > best[0]):
                best = (overlap, step)
        return dict(best[1]) if best else None

    def list_journeys(self) -> List[Dict[str, Any]]:
        journeys = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            steps = data.get("steps") or []
            journeys.append(
                {
                    "key": data.get("key") or path.stem,
                    "step_count": len(steps),
                    "proven_steps": sum(1 for step in steps if int(step.get("successes") or 0) > 0),
                    "portals": data.get("portals") or [],
                    "updated_at": data.get("updated_at"),
                }
            )
        return journeys
