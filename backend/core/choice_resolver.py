"""Resolve a radio/checkbox group from the candidate's own vault.

A choice group on a government form is usually a question the candidate has
already answered in their profile: nationality, category, gender, marital
status, religion.  Reading the option text is enough to identify the concept
even when the portal names the control ``rblOption``.

This module only *maps* a stored fact to an option.  It never invents a value:
if the vault has no answer, or two options match equally, the group is left for
the human.  The resolved mapping is returned so the orchestrator can remember it
in the exam journey and reuse it on the next visit.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _labels(group: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(item.get("label") or item.get("text") or "") for item in group]


def infer_concept(labels: List[str], page_text: str = "") -> Optional[str]:
    """Identify which profile fact a choice group is asking for.

    Only concepts whose option text is self-describing are inferred.  A bare
    Yes/No group is *not* guessed from surrounding page text: on a long
    instruction page every word appears somewhere, and a wrong answer to a
    disability or ex-serviceman question is worse than asking.
    """
    joined = " ".join(labels).lower()
    if not joined.strip():
        return None
    if re.search(r"indian\s+national|foreign\s+national|\bnri\b|\boci\b", joined):
        return "nationality"
    if re.search(
        r"\bgeneral\b|\bobc\b|scheduled\s+caste|\bscheduled\s+tribe\b|"
        r"\bsc\b|\bst\b|\bews\b|other\s+backward",
        joined,
    ):
        return "category"
    if re.search(r"\bmale\b|\bfemale\b|transgender|third\s+gender", joined):
        return "gender"
    if re.search(r"married|unmarried|divorced|widow", joined):
        return "marital_status"
    if re.search(
        r"\bhindu\b|\bmuslim\b|\bchristian\b|\bsikh\b|\bbuddhist\b|"
        r"\bjain\b|\bparsi\b",
        joined,
    ):
        return "religion"
    return None


_SYNONYMS: Dict[str, Dict[str, List[str]]] = {
    "nationality": {
        "indian": ["indiannational", "indian"],
        "nri": ["nri", "nonresidentindian"],
        "foreign": ["foreignnational", "foreign"],
    },
    "category": {
        "general": ["general", "unreserved", "ur"],
        "ews": ["ews", "genews", "economicallyweakersection"],
        "obc": ["obc", "obcncl", "otherbackwardclass"],
        "sc": ["sc", "scheduledcaste"],
        "st": ["st", "scheduledtribe"],
    },
    "gender": {
        "male": ["male", "m"],
        "female": ["female", "f"],
        "transgender": ["transgender", "thirdgender"],
    },
    "marital_status": {
        "unmarried": ["unmarried", "single"],
        "married": ["married"],
        "divorced": ["divorced"],
        "widowed": ["widowed", "widow"],
    },
    "religion": {
        "hindu": ["hindu"],
        "muslim": ["muslim", "islam"],
        "christian": ["christian"],
        "sikh": ["sikh"],
        "buddhist": ["buddhist"],
        "jain": ["jain"],
        "parsi": ["parsi", "zoroastrian"],
    },
}


def _candidates(value: str, concept: str) -> List[str]:
    base = _norm(value)
    if not base:
        return []
    values = [base]
    for key, aliases in _SYNONYMS.get(concept, {}).items():
        normalized_aliases = {_norm(alias) for alias in aliases}
        if base == key or base in normalized_aliases:
            values = [key, *aliases]
            break
    seen: List[str] = []
    for item in values:
        normalized = _norm(item)
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def pick_option(
    group: List[Dict[str, Any]], value: str, concept: str
) -> Optional[Dict[str, Any]]:
    """Return the single option that represents ``value``.

    Exact matches win.  A prefix match is accepted only when it is unique, so
    "male" never selects "female" and "general" never selects "General/EWS".
    """
    candidates = _candidates(value, concept)
    if not candidates:
        return None
    normalized = [(_norm(item.get("label") or item.get("text") or ""), item) for item in group]

    for candidate in candidates:
        exact = [item for label, item in normalized if label == candidate]
        if len(exact) == 1:
            return exact[0]

    for candidate in candidates:
        prefixed = [
            item
            for label, item in normalized
            if label.startswith(candidate) or candidate.startswith(label)
        ]
        if len(prefixed) == 1:
            return prefixed[0]

    for candidate in candidates:
        contained = [item for label, item in normalized if candidate in label]
        if len(contained) == 1:
            return contained[0]
    return None


def resolve_group(
    items: List[Dict[str, Any]],
    item: Dict[str, Any],
    vault: Any,
    *,
    page_text: str = "",
    learned: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve one radio/checkbox group against the vault.

    ``learned`` maps a group machine name to a concept remembered from a
    previous visit.  It is used when option text alone is ambiguous.
    """
    field_type = str(item.get("type") or "").lower()
    if field_type not in {"radio", "checkbox"}:
        return None
    name = str(item.get("name") or "").strip()
    group_id = str(item.get("id") or "").strip()
    if name:
        group = [
            entry
            for entry in items
            if str(entry.get("type") or "").lower() == field_type
            and str(entry.get("name") or "").strip() == name
        ]
    else:
        group = [item]
    if not group:
        return None

    labels = _labels(group)
    learned_map = {
        str(key or "").strip().lower(): value
        for key, value in (learned or {}).items()
    }
    concept = learned_map.get(name.lower()) or learned_map.get(group_id.lower())
    if not concept:
        concept = infer_concept(labels, page_text)
    if not concept:
        return None

    value = getattr(vault, concept, None)
    if value in (None, "", [], {}):
        return None
    chosen = pick_option(group, str(value), concept)
    if chosen is None:
        return None
    return {
        "concept": concept,
        "value": str(value),
        "group": name or group_id,
        "group_id": group_id,
        "item": chosen,
        "label": str(chosen.get("label") or ""),
        "options": labels,
    }
