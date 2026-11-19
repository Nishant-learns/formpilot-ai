"""Deterministic recognition of page-level actions.

A portal page is not only a list of fields.  Some pages ask for a decision
(consent, authorisation), some offer a single forward button, and some offer a
destructive button next to an affirmative one.  Those pages used to be treated
as forms with zero fillable fields, which produced a misleading "section
review" gate or a dead end.

The helpers here are pure functions over the scanner output.  They are shared
by the orchestrator and the chat assistant so both surfaces describe the same
page the same way.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


# A page whose purpose is to collect consent or authorise access.
CONSENT_URL_RE = re.compile(
    r"(?:^|[/._-])(?:consent|authorize|authorise|oauth|permissions?|scope)(?:[/._?&=-]|$)",
    re.IGNORECASE,
)

# A checkbox that accepts terms, privacy or data sharing.  It is not a profile
# fact and not a final declaration about the truth of the application.
SHARE_CONSENT_RE = re.compile(
    r"(?:consent|authori[sz]e|permission|data\s*shar|share\s*(?:my|your)?\s*"
    r"(?:data|information|details)|terms\s*(?:of\s*use|and\s*conditions|&)|"
    r"privacy\s*policy|allow\s*access|marksheet|certificate|profile|aadhaar|document)",
    re.IGNORECASE,
)

# "Select all" controls.  Portals often use a parent checkbox whose onclick
# ticks every child consent.
SELECT_ALL_RE = re.compile(
    r"(?:select\s*all|all\s*(?:documents?|items?|consents?)|"
    r"(?:^|[_-])parent(?:[_-]|$)|chkall|checkall)",
    re.IGNORECASE,
)

PURPOSE_RE = re.compile(r"\b(?:purpose|scope|reason)\b", re.IGNORECASE)

AFFIRMATIVE_RE = re.compile(
    r"^\s*(?:allow|authori[sz]e|approve|accept|agree|i\s*agree|confirm|"
    r"continue|proceed|ok|okay|yes|submit|save)\b",
    re.IGNORECASE,
)
NEGATIVE_RE = re.compile(
    r"^\s*(?:deny|reject|decline|disagree|cancel|close|back|previous|"
    r"logout|sign\s*out|delete|remove|reset|not\s*now)\b",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(
    r"^\s*(?:default\s*select|select|choose|please\s*select|none|--.*--|-+)\s*$",
    re.IGNORECASE,
)

# A checkbox that only subscribes to marketing is not a consent gate.
NON_CONSENT_RE = re.compile(
    r"\b(?:remember\s*me|subscribe|newsletter|notify|updates?|offers?|whatsapp)\b",
    re.IGNORECASE,
)


def _text(item: Dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "") for key in ("label", "name", "id", "value")
    ).strip()


def is_checkbox(item: Dict[str, Any]) -> bool:
    return str(item.get("type") or "").lower() == "checkbox"


def is_select_all(item: Dict[str, Any]) -> bool:
    """True for a checkbox that ticks a group of consent boxes."""
    if not is_checkbox(item):
        return False
    haystack = " ".join(str(item.get(key) or "") for key in ("label", "name", "id"))
    return bool(SELECT_ALL_RE.search(haystack))


def is_share_consent(item: Dict[str, Any]) -> bool:
    """True for terms/privacy/data-sharing consent, not a final declaration."""
    if not is_checkbox(item):
        return False
    haystack = _text(item)
    if not haystack:
        return False
    if NON_CONSENT_RE.search(haystack):
        return False
    return bool(SHARE_CONSENT_RE.search(haystack))


def consent_controls(dom: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Unchecked checkboxes that a consent page needs ticked.

    The select-all control comes first so a single click can satisfy a whole
    list, and the remaining boxes are returned in page order for portals that
    do not wire the parent.
    """
    controls = [
        item
        for item in (dom.get("inputs") or [])
        if isinstance(item, dict)
        and is_checkbox(item)
        and not item.get("checked")
        and not NON_CONSENT_RE.search(_text(item))
    ]
    controls.sort(
        key=lambda item: 0 if is_select_all(item) else (1 if is_share_consent(item) else 2)
    )
    return controls


def purpose_select(dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the data-sharing purpose selector, if the page has one."""
    for item in dom.get("inputs") or []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").lower()
        field_type = str(item.get("type") or "").lower()
        if tag != "select" and field_type not in {"select-one", "select"}:
            continue
        haystack = " ".join(
            str(item.get(key) or "") for key in ("label", "name", "id")
        )
        if PURPOSE_RE.search(haystack):
            return item
    return None


def selectable_options(item: Dict[str, Any]) -> List[Dict[str, str]]:
    """Options with a real value, excluding the placeholder row."""
    options: List[Dict[str, str]] = []
    for option in item.get("options") or []:
        if isinstance(option, dict):
            text = str(option.get("text") or "").strip()
            value = str(option.get("value") or "").strip()
        else:
            text = str(option or "").strip()
            value = text
        if not value:
            continue
        if PLACEHOLDER_RE.match(text):
            continue
        options.append({"text": text, "value": value})
    return options


def _buttons(dom: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    seen: set = set()
    for button in dom.get("nextButtons") or []:
        if not isinstance(button, dict):
            continue
        if button.get("visible") is False or button.get("interactable") is False:
            continue
        if button.get("covered_by") or button.get("coveredBy"):
            continue
        text = str(button.get("text") or button.get("value") or "").strip()
        if not text:
            continue
        key = (text.lower(), str(button.get("element_id") or button.get("id") or ""))
        if key in seen:
            continue
        seen.add(key)
        yield dict(button, text=text)


def affirmative_button(dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The control that grants access, never the one that denies it.

    Priority is deliberate: ``Allow``/``Authorize`` beat ``Confirm`` which
    beats ``Continue``.  A control that matches both patterns is rejected
    because guessing between grant and deny is worse than asking.
    """
    ranked: List[tuple] = []
    for button in _buttons(dom):
        text = button["text"]
        if NEGATIVE_RE.search(text):
            continue
        if not AFFIRMATIVE_RE.search(text):
            continue
        if re.search(r"\ballow|authori[sz]e|approve\b", text, re.IGNORECASE):
            rank = 0
        elif re.search(r"\b(?:accept|agree|confirm)\b", text, re.IGNORECASE):
            rank = 1
        else:
            rank = 2
        ranked.append((rank, button))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0])
    return ranked[0][1]


def negative_button(dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for button in _buttons(dom):
        if NEGATIVE_RE.search(button["text"]):
            return button
    return None


def _has_credential_surface(dom: Dict[str, Any]) -> bool:
    if dom.get("otpInputs"):
        return True
    return any(
        str(item.get("type") or "").lower() == "password"
        for item in (dom.get("inputs") or [])
        if isinstance(item, dict)
    )


def is_consent_page(dom: Dict[str, Any], form_map: Optional[Dict[str, Any]] = None) -> bool:
    """True for a consent/authorisation screen rather than an application form.

    The page must actually collect consent: a consent checkbox, an
    ``Allow``/``Authorize`` button, or a purpose selector.  A URL keyword alone
    is not enough, and a credential box always means an identity gate instead.
    """
    if _has_credential_surface(dom):
        return False
    if dom.get("hasPaymentButton"):
        return False
    controls = consent_controls(dom)
    purpose = purpose_select(dom)
    affirmative = affirmative_button(dom)
    url = str(dom.get("url") or (form_map or {}).get("url") or "")
    text = str(dom.get("visibleText") or "").lower()
    url_signal = bool(CONSENT_URL_RE.search(url))
    text_signal = "consent" in text and bool(controls or affirmative)
    if not (controls or purpose or affirmative):
        return False
    return bool(url_signal or text_signal or (controls and affirmative))


def page_snapshot(
    dom: Dict[str, Any],
    form_map: Optional[Dict[str, Any]] = None,
    *,
    gate: Optional[Dict[str, Any]] = None,
    live_session: Optional[Dict[str, Any]] = None,
    last_action: str = "",
    revision: int = 0,
) -> Dict[str, Any]:
    """One synchronized description of what the human and the agent both see."""
    form_map = form_map or {}
    fields = list(form_map.get("fields") or [])
    filled = sum(1 for field in fields if field.get("has_value"))
    pending = sum(1 for field in fields if field.get("needs_user_input"))
    controls = []
    for button in list(_buttons(dom))[:12]:
        controls.append(
            {
                "text": button.get("text") or "",
                "id": button.get("id") or "",
                "type": button.get("type") or "",
                "role": button.get("role") or "",
            }
        )
    consent = consent_controls(dom)
    purpose = purpose_select(dom)
    return {
        "revision": revision,
        "url": str(dom.get("url") or form_map.get("url") or ""),
        "title": str(dom.get("title") or form_map.get("title") or ""),
        "page_type": str(form_map.get("page_type") or ""),
        "heading": str(dom.get("stepHeading") or form_map.get("step_heading") or ""),
        "fields_total": len(fields),
        "fields_filled": filled,
        "fields_pending": pending,
        "controls": controls,
        "consent_pending": [str(item.get("label") or item.get("name") or "") for item in consent],
        "purpose_options": selectable_options(purpose) if purpose else [],
        "is_consent_page": is_consent_page(dom, form_map),
        "affirmative_action": (affirmative_button(dom) or {}).get("text") or "",
        "gate": {
            "type": str((gate or {}).get("gate_type") or ""),
            "title": str((gate or {}).get("title") or ""),
        }
        if gate
        else None,
        "live_url": str((live_session or {}).get("url") or ""),
        "last_action": last_action,
    }
