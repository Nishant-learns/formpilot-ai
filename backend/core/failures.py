"""A small, stable failure taxonomy.

Skyvern classifies failures after the fact (``failure_classifier.py``) so a
retry policy and a support engineer can talk about the same thing.  FormPilot
needs the same vocabulary, but much smaller: our failures happen on one form
flow with a human watching.

A code is recorded on a run step.  It is descriptive, not causal: it says what
went wrong, not why the portal did it.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class FailureCode(str, Enum):
    NAVIGATION = "navigation_failure"
    AUTH = "auth_failure"
    ANTI_BOT = "anti_bot"
    ELEMENT_NOT_FOUND = "element_not_found"
    FIELD_NOT_HELD = "field_not_held"
    WRONG_PAGE = "wrong_page"
    TIMEOUT = "timeout"
    NO_PROGRESS = "no_progress"
    BUDGET = "budget_exceeded"
    VALIDATION = "validation_failure"
    PORTAL_ERROR = "portal_error"
    INTERNAL = "internal_error"


# Ordered rules: the first match wins, so specific codes come before generic
# ones.  Keep the vocabulary closed; an unknown failure is INTERNAL.
#
# A real portal reports failures in many words ("Invalid Aadhaar", "Session
# expired", "Some error occurred").  The old vocabulary only recognised the
# word "error" in a narrow phrase, so most of those pages were classified as
# INTERNAL and never reached the recovery path.  VALIDATION is deliberately
# separate from PORTAL_ERROR: bad data needs a human, while a server hiccup can
# be retried safely.
_RULES = (
    (FailureCode.ANTI_BOT, r"captcha|security\s*check|anti[-\s]?bot|blocked|robot|access\s*denied|forbidden"),
    (FailureCode.AUTH, r"login|sign[-\s]?in|password|credential|unauthori[sz]ed|otp|session\s*(?:expired|timed?\s*out)|logged?\s*out|not\s+logged"),
    (FailureCode.FIELD_NOT_HELD, r"did not keep|not held|empty after|dropped the value"),
    (FailureCode.ELEMENT_NOT_FOUND, r"not found|could not be reached|disappeared|no such element"),
    (FailureCode.NAVIGATION, r"did not move|navigation|did not advance|wrong step"),
    (FailureCode.WRONG_PAGE, r"unexpected page|wrong page|not the .* page"),
    (FailureCode.TIMEOUT, r"timed? ?out|timeout|too long"),
    (FailureCode.NO_PROGRESS, r"no progress|not changed|unchanged|stalled|same page"),
    (FailureCode.BUDGET, r"budget|too many (?:steps|attempts)"),
    (FailureCode.VALIDATION, r"invalid|not\s+(?:valid|allowed|available|registered)|"
        r"please\s+(?:enter|select|choose|check|fill|upload|verify)|"
        r"enter\s+(?:a\s+)?valid|select\s+(?:a\s+)?valid|provide\s+(?:a\s+)?valid|"
        r"\b(?:is|are)\s+required\b|must\s+be|should\s+be|"
        r"already\s+(?:registered|exists)|limit\s+exceeded|incorrect"),
    (FailureCode.PORTAL_ERROR, r"portal\s+(?:reported|error|rejected)|server|network|"
        r"connection|unavailable|try\s+again|something\s+went\s+wrong|"
        r"unexpected\s+error|error\s+occurred|failed|failure|unable|could\s*not"),
)

_RETRYABLE = {
    FailureCode.NAVIGATION,
    FailureCode.ELEMENT_NOT_FOUND,
    FailureCode.TIMEOUT,
    FailureCode.PORTAL_ERROR,
}


def classify_failure(message: Optional[str], *, default: FailureCode = FailureCode.INTERNAL) -> FailureCode:
    """Map a human-readable failure message to a stable code."""
    text = str(message or "").strip().lower()
    if not text:
        return default
    for code, pattern in _RULES:
        if re.search(pattern, text):
            return code
    return default


def is_retryable(code: FailureCode | str) -> bool:
    """Whether another attempt could plausibly succeed without a human."""
    try:
        return FailureCode(code) in _RETRYABLE
    except ValueError:
        return False
