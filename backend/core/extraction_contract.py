"""The contract for "extract my documents with ChatGPT/Gemini, paste the JSON".

FormPilot does not call a paid model to read a candidate's marksheets.  The
candidate uses the AI they already have, with a prompt this module generates,
and pastes the JSON back.  This module is the other half of that deal:

* ``EXTRACTION_PROMPT`` is what the candidate copies;
* ``build_import_plan`` validates the pasted JSON, normalises it, maps every
  leaf onto a canonical vault key through the same registry the fill loop
  uses, and returns a per-field verdict (new / same / conflict / uncertain /
  invalid) so nothing is ever overwritten silently.

Mapping is deterministic on purpose.  An LLM is good at reading a marksheet;
it is not allowed to decide that "S/o" means a different person.  Anything the
contract does not recognise is kept as an extra rather than guessed at.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import concepts, field_registry

SCHEMA_VERSION = "formpilot_profile_v1"
PROMPT_VERSION = "2"

# Every leaf is an empty placeholder.  The prompt must never contain a real or
# example value that a model could copy into its answer.  Format guidance lives
# in FIELD_GUIDE and the prompt rules instead.
SCHEMA: Dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "profile": {
        "full_name": "",
        "father_name": "",
        "mother_name": "",
        "dob": "",
        "gender": "",
        "marital_status": "",
        "religion": "",
        "nationality": "",
        "category": "",
    },
    "contact": {
        "mobile": "",
        "email": "",
        "address": {
            "line1": "",
            "line2": "",
            "city": "",
            "district": "",
            "state": "",
            "pincode": "",
        },
    },
    "identity": {
        "aadhaar_number": "",
        "pan_number": "",
        "photo_id_type": "",
        "photo_id_number": "",
    },
    "education": [
        {
            "level": "",
            "board": "",
            "school_or_college": "",
            "stream": "",
            "roll_number": "",
            "roll_code": "",
            "passing_year": "",
            "total_marks": "",
            "obtained_marks": "",
            "percentage": "",
            "cgpa": "",
            "certificate_number": "",
        }
    ],
    "extras": {},
}

# Human-readable guidance for the model.  This is deliberately separate from
# the JSON template so the template stays placeholder-only.
FIELD_GUIDE: List[Dict[str, str]] = [
    {"path": "profile.full_name", "format": "text", "hint": "Name exactly as printed on the document, without Mr./Shri/Smt."},
    {"path": "profile.father_name", "format": "text", "hint": "Father's name as printed."},
    {"path": "profile.mother_name", "format": "text", "hint": "Mother's name as printed."},
    {"path": "profile.dob", "format": "YYYY-MM-DD", "hint": "Date of birth. Convert DD/MM/YYYY or DD-MM-YYYY to YYYY-MM-DD."},
    {"path": "profile.gender", "format": "Male | Female | Other", "hint": "Use the document's gender, not a guess."},
    {"path": "profile.marital_status", "format": "text", "hint": "Only when the document states it."},
    {"path": "profile.religion", "format": "text", "hint": "Only when the document states it."},
    {"path": "profile.nationality", "format": "text", "hint": "Only when the document states it."},
    {"path": "profile.category", "format": "UR | EWS | OBC-NCL | SC | ST", "hint": "Use the category printed on a certificate, never infer it."},
    {"path": "contact.mobile", "format": "10 digits", "hint": "Digits only, without +91 or spaces."},
    {"path": "contact.email", "format": "email", "hint": "Only when the document shows it."},
    {"path": "contact.address.line1", "format": "text", "hint": "First address line."},
    {"path": "contact.address.line2", "format": "text", "hint": "Second address line, if any."},
    {"path": "contact.address.city", "format": "text", "hint": "Village, town or city."},
    {"path": "contact.address.district", "format": "text", "hint": "District."},
    {"path": "contact.address.state", "format": "text", "hint": "State."},
    {"path": "contact.address.pincode", "format": "6 digits", "hint": "PIN code."},
    {"path": "identity.aadhaar_number", "format": "12 digits", "hint": "Aadhaar number, digits only. Never invent a digit."},
    {"path": "identity.pan_number", "format": "text", "hint": "PAN, if shown."},
    {"path": "identity.photo_id_type", "format": "text", "hint": "Type of photo ID shown."},
    {"path": "identity.photo_id_number", "format": "text", "hint": "Photo ID number, if shown."},
    {"path": "education[].level", "format": "10th | 12th | graduation", "hint": "One record per certificate. 10th = matric/SSLC, 12th = intermediate/HSC, graduation = degree."},
    {"path": "education[].board", "format": "text", "hint": "Board or university that issued the certificate."},
    {"path": "education[].school_or_college", "format": "text", "hint": "School or college name."},
    {"path": "education[].stream", "format": "text", "hint": "Stream or subjects, if printed."},
    {"path": "education[].roll_number", "format": "text", "hint": "Roll number."},
    {"path": "education[].roll_code", "format": "text", "hint": "Roll code, if printed separately."},
    {"path": "education[].passing_year", "format": "YYYY", "hint": "Year of passing."},
    {"path": "education[].total_marks", "format": "number", "hint": "Maximum marks."},
    {"path": "education[].obtained_marks", "format": "number", "hint": "Marks obtained."},
    {"path": "education[].percentage", "format": "number", "hint": "Percentage, if printed."},
    {"path": "education[].cgpa", "format": "number", "hint": "CGPA/GPA, if printed."},
    {"path": "education[].certificate_number", "format": "text", "hint": "Certificate number, if printed."},
    {"path": "extras", "format": "object", "hint": "Any other detail the document shows that the shape does not cover, with a clear snake_case key."},
]

_FIELD_GUIDE_TEXT = "\n".join(
    f"- {item['path']} ({item['format']}): {item['hint']}" for item in FIELD_GUIDE
)

EXTRACTION_PROMPT = f"""You are helping me fill an Indian government recruitment application. \
I will attach documents (marksheets, certificates, ID, address proof). Read only the \
attached documents and return my details as ONE JSON object.

Do not guess, complete, infer or invent any value. If a document does not show a \
value, leave that value as an empty string. Do not copy this instruction text or the \
field guide into the JSON values.

Use exactly this shape (schema {SCHEMA_VERSION}). Every value below is an empty \
placeholder; replace a placeholder only with text that is visible in the documents:

{json.dumps(SCHEMA, indent=2, ensure_ascii=False)}

Field guide:
{_FIELD_GUIDE_TEXT}

Requirements:
1. Extract only what the documents actually show. Never guess or complete a value.
2. Write dates as YYYY-MM-DD and years as YYYY.
3. Keep names exactly as printed. Do not add titles like Mr./Shri/Smt.
4. If a value is blurry or you are not sure, write it as {{"value": "the text you can read", "uncertain": true}}.
5. If a document shows something this shape does not cover, put it in "extras" with a \
clear snake_case key. Do not drop it.
6. One education record per certificate. Use "10th" for matric/SSLC/class 10, "12th" for \
intermediate/HSC/class 12, "graduation" for a degree.
7. Do not include any commentary, markdown fences or explanation. JSON only.
"""

# --------------------------------------------------------------- normalisation

_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), ("y", "m", "d")),
    (re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$"), ("d", "m", "y")),
    (re.compile(r"^(\d{1,2})[.\s](\d{1,2})[.\s](\d{4})$"), ("d", "m", "y")),
    (re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"), ("y", "m", "d")),
)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_HONORIFICS = re.compile(
    r"^(?:mr|mrs|ms|miss|dr|shri|shree|smt|sri|kumari|km|prof)\.?\s+",
    re.IGNORECASE,
)


def normalize_date(value: Any) -> Optional[str]:
    """Return YYYY-MM-DD, or None when the value is not a real date.

    A wrong date of birth is a rejected application, so an unparseable value is
    reported rather than coerced.
    """
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(",", " ").strip()
    for pattern, order in _DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        parts = dict(zip(order, match.groups()))
        try:
            year = int(parts["y"])
            month = int(parts["m"])
            day = int(parts["d"])
        except (KeyError, ValueError):
            return None
        if year < 1900 or year > datetime.date.today().year:
            return None
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return None

    match = re.match(r"^(\d{1,2})[\s-]+([A-Za-z]{3,9})[\s-]+(\d{4})$", text)
    if match:
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.lower()[:4].rstrip("."))
        if not month:
            month = _MONTHS.get(month_name.lower()[:3])
        if month:
            try:
                return datetime.date(int(year), month, int(day)).isoformat()
            except ValueError:
                return None
    return None


def normalize_phone(value: Any) -> Optional[str]:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0091"):
        digits = digits[4:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if 10 <= len(digits) <= 13:
        return digits
    return None


def strip_honorific(name: Any) -> str:
    text = re.sub(r"\s+", " ", str(name or "")).strip()
    return _HONORIFICS.sub("", text).strip()


def split_full_name(full_name: str) -> Dict[str, Optional[str]]:
    """Split a name the way a careful human would, not by string rules alone.

    Two tokens: first + last, middle known absent.  Three or more: first,
    middle (joined), last.  Single token: first only.
    """
    tokens = [token for token in strip_honorific(full_name).split() if token]
    if not tokens:
        return {"first": None, "middle": None, "last": None, "middle_known_absent": True}
    if len(tokens) == 1:
        return {"first": tokens[0], "middle": None, "last": None, "middle_known_absent": True}
    if len(tokens) == 2:
        return {
            "first": tokens[0],
            "middle": None,
            "last": tokens[1],
            "middle_known_absent": True,
        }
    return {
        "first": tokens[0],
        "middle": " ".join(tokens[1:-1]),
        "last": tokens[-1],
        "middle_known_absent": False,
    }


def _canonical_gender(value: Any) -> Optional[str]:
    key = concepts.normalize(str(value or ""))
    return {
        "m": "Male", "male": "Male", "boy": "Male",
        "f": "Female", "female": "Female", "girl": "Female",
        "o": "Other", "other": "Other", "transgender": "Other",
    }.get(key)


# ------------------------------------------------------------------- mapping

_LEVELS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:10|10th|tenth|matric|matriculation|ssc|sslc|class\s*10|"
            r"high\s*school|secondary\s*school)\b"
        ),
        "matric",
    ),
    (
        re.compile(
            r"\b(?:12|12th|twelfth|intermediate|inter\b|hsc|class\s*12|"
            r"senior\s*secondary|higher\s*secondary|plus\s*two|puc)\b"
        ),
        "intermediate",
    ),
    (
        re.compile(r"\b(?:graduation|graduate|bachelor|degree|b\.?\s*(?:a|sc|com|tech|e))\b"),
        "graduation",
    ),
)

_LEVEL_PREFIX = {"matric": "matric", "intermediate": "intermediate", "graduation": "graduation"}

_ATTR_ALIASES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\broll\s*code\b"), "roll_code"),
    (re.compile(r"\b(?:roll\s*(?:number|no)|roll)\b"), "roll_number"),
    (re.compile(r"\b(?:certificate\s*(?:number|no)|cert\s*no)\b"), "certificate_number"),
    (re.compile(r"\b(?:passing\s*year|year\s*of\s*passing|exam\s*year|year)\b"), "passing_year"),
    (re.compile(r"\b(?:total\s*marks|maximum\s*marks|max\s*marks|out\s*of)\b"), "total_marks"),
    (re.compile(r"\b(?:obtained\s*marks|marks\s*obtained|marks|score)\b"), "obtained_marks"),
    (re.compile(r"\b(?:percentage|percent|%)\b"), "percentage"),
    (re.compile(r"\b(?:cgpa|gpa|grade\s*point)\b"), "cgpa"),
    (re.compile(r"\b(?:board|university\s*board|examining\s*body)\b"), "board"),
    (re.compile(r"\b(?:school|school\s*name|institution|institute)\b"), "school_name"),
    (re.compile(r"\b(?:college|college\s*name)\b"), "college_name"),
    (re.compile(r"\b(?:university)\b"), "university"),
    (re.compile(r"\b(?:stream|subjects?|faculty)\b"), "stream"),
    (re.compile(r"\b(?:degree|course)\b"), "degree_name"),
)

_DIRECT_ALIASES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    # Specific relations first: "Father's Name" contains the word "name", so a
    # generic name rule placed earlier would swallow it.
    (re.compile(r"\b(?:father|fathers|father s|paternal)\b"), "father_name"),
    (re.compile(r"\b(?:mother|mothers|mother s|maternal)\b"), "mother_name"),
    (re.compile(r"\b(?:guardian)\b"), "guardian_name"),
    (re.compile(r"\b(?:full\s*name|candidate\s*name|applicant\s*name|student\s*name|name\s*of\s*(?:the\s*)?candidate)\b"), "full_name"),
    (re.compile(r"\b(?:date\s*of\s*birth|dob|birth\s*date|d\.o\.b)\b"), "dob"),
    (re.compile(r"\b(?:gender|sex)\b"), "gender"),
    (re.compile(r"\b(?:marital\s*status)\b"), "marital_status"),
    (re.compile(r"\b(?:religion)\b"), "religion"),
    (re.compile(r"\b(?:nationality|citizenship)\b"), "nationality"),
    (re.compile(r"\b(?:category|social\s*category|reservation)\b"), "category"),
    (re.compile(r"\b(?:sub\s*caste|caste)\b"), "sub_caste"),
    (re.compile(r"\b(?:aadhaar|aadhar|adhar|uid)\b"), "aadhaar_number"),
    (re.compile(r"\b(?:pan)\b"), "pan_number"),
    (re.compile(r"\b(?:mobile|phone|contact\s*number|cell)\b"), "mobile"),
    (re.compile(r"\b(?:email|e\s*mail|mail\s*id)\b"), "email"),
    (re.compile(r"\b(?:pincode|pin\s*code|postal\s*code|zip)\b"), "pincode"),
    (re.compile(r"\b(?:district)\b"), "district"),
    (re.compile(r"\b(?:state)\b"), "state"),
    (re.compile(r"\b(?:city|town|village|place)\b"), "village_town_city"),
    (re.compile(r"\b(?:address\s*line\s*2|address2|line\s*2)\b"), "address_line_2"),
    (re.compile(r"\b(?:address|address\s*line\s*1|address1|line\s*1|residence)\b"), "address_line_1"),
    # Last resort: a bare "name" is the candidate's name.
    (re.compile(r"\b(?:name)\b"), "full_name"),
)

_DATE_KEYS = {"dob", "caste_cert_issue_date"}
_PHONE_KEYS = {"mobile", "alternate_mobile"}


@dataclass
class ImportField:
    key: str
    label: str
    value: str
    verdict: str
    current: Optional[str] = None
    note: str = ""
    source_path: str = ""

    def public(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "verdict": self.verdict,
            "current": self.current,
            "note": self.note,
            "source_path": self.source_path,
        }


@dataclass
class ImportPlan:
    fields: List[ImportField] = field(default_factory=list)
    extras: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def public(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {
            "new": 0,
            "same": 0,
            "conflict": 0,
            "uncertain": 0,
            "invalid": 0,
        }
        for item in self.fields:
            counts[item.verdict] = counts.get(item.verdict, 0) + 1
        return {
            "schema_version": SCHEMA_VERSION,
            "fields": [item.public() for item in self.fields],
            "extras": self.extras,
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": counts,
        }

    def acceptable(self) -> List[ImportField]:
        """Fields that can be applied without asking a human."""
        return [item for item in self.fields if item.verdict in {"new", "same"}]


def _iter_leaves(node: Any, path: Tuple[str, ...] = ()) -> Iterable[Tuple[Tuple[str, ...], Any, bool]]:
    """Yield (path, value, uncertain) for every scalar leaf."""
    if isinstance(node, dict):
        uncertain = bool(node.get("uncertain") is True)
        if uncertain and "value" in node:
            yield path, node.get("value"), True
            return
        # An education record names its level in a value ("level": "10th"),
        # so promote that value into the path and skip the key itself.
        level_value = ""
        for key in ("level", "exam", "examination", "class", "standard", "qualification"):
            candidate = node.get(key)
            if isinstance(candidate, str) and candidate.strip():
                level_value = candidate.strip()
                break
        for key, value in node.items():
            if str(key).lower() in {"uncertain", "confidence"}:
                continue
            if level_value and key in {"level", "exam", "examination", "class", "standard", "qualification"}:
                continue
            next_path = path + ((level_value,) if level_value else ()) + (str(key),)
            yield from _iter_leaves(value, next_path)
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_leaves(value, path + (str(index),))
        return
    if node is None:
        return
    if isinstance(node, str) and not node.strip():
        return
    yield path, node, False


def _level_from(text: str) -> Optional[str]:
    for pattern, level in _LEVELS:
        if pattern.search(text):
            return level
    return None


def _registry_key(path: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
    """Map a JSON path to (registry key, extra key).

    Exactly one of the two is returned: a recognised field, or an extra name
    built from the path so nothing is lost.
    """
    parts = [concepts.normalize(part) for part in path if part]
    if not parts:
        return None, None
    # Drop container words that carry no meaning of their own.
    containers = {"profile", "contact", "identity", "education", "address", "details", "data"}
    meaningful = [part for part in parts if part not in containers]
    if not meaningful:
        return None, None

    joined = " ".join(meaningful)
    level = _level_from(joined)

    # Education record: the attribute is the leaf that is not the level.
    if level:
        attr_text = " ".join(
            part for part in meaningful if not _level_from(part)
        )
        attr = None
        # "School or college" means different columns per level.
        if re.search(r"\b(?:school|college|institution|institute)\b", attr_text) and not re.search(
            r"\buniversity\b", attr_text
        ):
            attr = "school_name" if level == "matric" else ("college_name" if level == "intermediate" else "university")
        if attr is None:
            for pattern, name in _ATTR_ALIASES:
                if pattern.search(attr_text):
                    attr = name
                    break
        if attr:
            key = f"{_LEVEL_PREFIX[level]}_{attr}"
            if key in field_registry.FIELD_SPECS:
                return key, None
        return None, "_".join([_LEVEL_PREFIX[level]] + [p for p in meaningful if p != level])

    for pattern, name in _DIRECT_ALIASES:
        if pattern.search(joined):
            if name in field_registry.FIELD_SPECS:
                return name, None
            # A real concept without a vault column (guardian, PAN) is kept as
            # an extra instead of being forced into an unrelated field.
            return None, name

    return None, "_".join(meaningful)


def _clean_extra_key(path: Tuple[str, ...]) -> str:
    raw = "_".join(part for part in path if part)
    return re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")[:80]


def _normalise_for(key: str, value: Any) -> Tuple[Optional[str], str]:
    """Return (normalised value, note).  None means the value is invalid."""
    spec = field_registry.spec_for(key)
    kind = spec.kind if spec else "text"
    text = str(value).strip()

    if key in _DATE_KEYS or kind == "date":
        parsed = normalize_date(text)
        return (parsed, "") if parsed else (None, "Not a valid date.")

    if key in _PHONE_KEYS:
        parsed = normalize_phone(text)
        return (parsed, "") if parsed else (None, "Not a valid phone number.")

    if key == "gender":
        parsed = _canonical_gender(text)
        return (parsed, "") if parsed else (None, "Not a recognised gender.")

    if key in {"full_name", "father_name", "mother_name", "verify_full_name", "verify_father_name", "verify_mother_name"}:
        cleaned = strip_honorific(text)
        if not cleaned:
            return None, "The name is empty after removing titles."
        return cleaned, ""

    if key.endswith("_percentage"):
        digits = re.sub(r"[^0-9.]", "", text)
        return (digits, "") if digits else (None, "Not a percentage.")

    if key.endswith("_passing_year"):
        match = re.search(r"(19|20)\d{2}", text)
        return (match.group(0), "") if match else (None, "Not a valid year.")

    if key == "aadhaar_number":
        digits = re.sub(r"\D", "", text)
        if len(digits) != 12:
            return None, "Aadhaar numbers have 12 digits."
        return digits, ""

    if key == "pincode":
        digits = re.sub(r"\D", "", text)
        return (digits, "") if len(digits) == 6 else (None, "PIN codes have 6 digits.")

    return text, ""


def _values_equivalent(key: str, current: Any, incoming: str) -> bool:
    """True when two spellings mean the same value.

    "88.4" and "88.40" are the same percentage, and "Nishant  Kumar" is the
    same name.  A real difference must still surface as a conflict.
    """
    if key.endswith(("_percentage", "_cgpa", "_total_marks", "_obtained_marks")):
        try:
            return abs(float(current) - float(incoming)) < 1e-9
        except (TypeError, ValueError):
            pass
    left = re.sub(r"\s+", " ", str(current or "")).strip().strip(".").lower()
    right = re.sub(r"\s+", " ", str(incoming or "")).strip().strip(".").lower()
    return bool(left) and left == right


def build_import_plan(payload: Any, vault: Any) -> ImportPlan:
    """Validate, normalise and map a pasted extraction onto the vault."""
    plan = ImportPlan()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            plan.errors.append(f"That is not valid JSON (line {exc.lineno}, column {exc.colno}).")
            return plan
    if not isinstance(payload, dict):
        plan.errors.append("The pasted JSON must be a single object, not a list or a value.")
        return plan

    declared_version = str(payload.get("schema_version") or "").strip()
    if declared_version and declared_version != SCHEMA_VERSION:
        plan.warnings.append(
            f"This was extracted with schema '{declared_version}', but FormPilot expects "
            f"'{SCHEMA_VERSION}'. Fields that still match are imported; the rest are kept as extras."
        )

    # Name parts can arrive without a full name; compose it so the fill loop
    # has one authoritative value.
    parts = {
        key: payload.get(key)
        for key in ("first_name", "middle_name", "last_name")
        if isinstance(payload.get(key), str) and payload.get(key).strip()
    }
    if parts and not any(
        str(value).strip()
        for key, value in payload.items()
        if key in {"full_name", "name"} and isinstance(value, str)
    ):
        composed = " ".join(
            str(parts[key]).strip()
            for key in ("first_name", "middle_name", "last_name")
            if parts.get(key)
        )
        payload = {
            key: value
            for key, value in payload.items()
            if key not in {"first_name", "middle_name", "last_name"}
        }
        # Insert first so the composed value wins over any stray name leaf.
        payload = {"full_name": composed, **payload}

    seen_keys: Dict[str, str] = {}
    name_part_keys = {"first_name", "middle_name", "last_name"}
    for path, raw_value, uncertain in _iter_leaves(payload):
        if path and path[0] in {"schema_version", "extras"}:
            continue
        # Name parts were already composed into full_name; importing them again
        # would look like a second, conflicting name.
        if path and str(path[-1]).lower() in name_part_keys:
            continue
        key, extra = _registry_key(path)
        if not key:
            if extra:
                plan.extras[_clean_extra_key((extra,))] = str(raw_value).strip()
            continue

        value, note = _normalise_for(key, raw_value)
        spec = field_registry.spec_for(key)
        label = spec.label if spec else key
        source_path = ".".join(path)

        if value is None:
            plan.fields.append(
                ImportField(key=key, label=label, value="", verdict="invalid", note=note, source_path=source_path)
            )
            continue

        if key in seen_keys and seen_keys[key] != value:
            plan.warnings.append(
                f"'{label}' appears twice with different values ('{seen_keys[key]}' and '{value}'). "
                "The first one is used; please check it."
            )
            continue
        seen_keys[key] = value

        current = field_registry.resolve_value(vault, key)
        if uncertain:
            verdict = "uncertain"
        elif current and _values_equivalent(key, current, value):
            verdict = "same"
        elif current:
            verdict = "conflict"
        else:
            verdict = "new"
        plan.fields.append(
            ImportField(
                key=key,
                label=label,
                value=value,
                verdict=verdict,
                current=str(current) if current else None,
                note=note,
                source_path=source_path,
            )
        )

    # The extras bag is part of the contract, so keep it even when a leaf was
    # nested under "extras".
    extras_bag = payload.get("extras")
    if isinstance(extras_bag, dict):
        for key, value in extras_bag.items():
            if isinstance(value, (dict, list)):
                continue
            if str(value).strip():
                plan.extras[_clean_extra_key((str(key),))] = str(value).strip()

    if not plan.fields and not plan.extras and not plan.errors:
        plan.errors.append(
            "No recognised fields were found. Copy the prompt again and paste the AI's JSON exactly."
        )
    return plan


_CONFIRMATIONS = {
    "full_name": "verify_full_name",
    "father_name": "verify_father_name",
    "mother_name": "verify_mother_name",
    "email": "confirm_email",
}


def apply_import(
    plan: ImportPlan,
    vault_manager: Any,
    *,
    accept: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Write the accepted fields.  Conflicts are never applied implicitly."""
    allowed = set(accept) if accept is not None else {item.key for item in plan.acceptable()}
    applied: List[str] = []
    skipped: List[str] = []

    for item in plan.fields:
        if item.key not in allowed:
            skipped.append(item.key)
            continue
        if item.verdict in {"invalid"}:
            skipped.append(item.key)
            continue
        if item.verdict == "conflict" and item.key not in allowed:
            skipped.append(item.key)
            continue
        try:
            vault_manager.set_semantic_field(item.key, item.value)
            applied.append(item.key)
            confirmation = _CONFIRMATIONS.get(item.key)
            if confirmation:
                vault_manager.set_semantic_field(confirmation, item.value)
        except Exception:
            skipped.append(item.key)

    for key, value in plan.extras.items():
        try:
            vault_manager.add_custom_field(key, value)
        except Exception:
            continue

    return {"applied": applied, "skipped": skipped, "extras": sorted(plan.extras)}
