"""Page State Validator and Self-Healing Error Detector.

Inspired by Skyvern's page.validate() primitive, this module verifies whether
actions succeeded, detects inline validation errors / alert banners, and prevents
infinite loops using action history and circuit breaking.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("formpilot.page_validator")


class ValidationState(str, Enum):
    ADVANCED = "advanced"              # Page URL or step heading changed to next step
    SAME_STEP = "same_step"            # Same step, no obvious errors detected
    VALIDATION_ERROR = "validation_error"  # Inline form errors or alerts appeared
    STUCK_LOOP = "stuck_loop"          # Circuit breaker tripped: repeated failure


@dataclass
class PageValidationResult:
    """Outcome of validating page state after an automated action."""
    state: ValidationState
    success: bool
    current_url: str
    step_title: str
    error_messages: List[str] = field(default_factory=list)
    invalid_element_indices: List[int] = field(default_factory=list)
    needs_human_intervention: bool = False
    intervention_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


CHECK_PAGE_ERRORS_JS = """
(() => {
    const errors = [];
    const invalidIndices = [];

    // 1. Check aria-invalid elements
    const ariaInvalids = document.querySelectorAll('[aria-invalid="true"]');
    ariaInvalids.forEach(el => {
        const idx = el.getAttribute('data-formpilot-idx');
        if (idx) invalidIndices.push(parseInt(idx, 10));
    });

    // 2. Check standard error containers
    const errorSelectors = [
        '.is-invalid',
        '.has-error',
        '.field-validation-error',
        '.form-error',
        '.error-message',
        '.alert-danger',
        '.alert-warning',
        '[role="alert"]',
        '.text-danger',
        '.err-msg',
        'span.error'
    ];

    const errorElements = document.querySelectorAll(errorSelectors.join(', '));
    errorElements.forEach(el => {
        // Must be visible
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
            const text = (el.innerText || el.textContent || '').trim();
            if (text && text.length < 250 && !errors.includes(text)) {
                errors.push(text);
            }
        }
    });

    // 3. Extract active step title / heading
    const heading = document.querySelector('h1, h2, .step-title, .active-step, legend, .card-header');
    const stepTitle = heading ? (heading.innerText || heading.textContent || '').trim() : '';

    return {
        errors: errors,
        invalidIndices: invalidIndices,
        stepTitle: stepTitle
    };
})();
"""


class PageStateValidator:
    """Monitors page transitions and halts loops when validation errors appear."""

    def __init__(self, max_retries_per_step: int = 2):
        self.max_retries_per_step = max_retries_per_step
        self._action_history: List[str] = []
        self._retry_counts: Dict[str, int] = {}
        self.last_url: Optional[str] = None
        self.last_step_title: Optional[str] = None

    def reset(self) -> None:
        self._action_history.clear()
        self._retry_counts.clear()
        self.last_url = None
        self.last_step_title = None

    async def validate_state(
        self,
        page: Any,
        action_summary: str = "",
    ) -> PageValidationResult:
        """Inspects page after an action to verify progression or catch errors."""
        try:
            current_url = getattr(page, "url", "")
            scan_data = await page.evaluate(CHECK_PAGE_ERRORS_JS)
            errors: List[str] = scan_data.get("errors", [])
            invalid_indices: List[int] = scan_data.get("invalidIndices", [])
            step_title: str = scan_data.get("stepTitle", "")

            # Create a deterministic fingerprint of this state
            fp_raw = f"{current_url}|{step_title}|{';'.join(sorted(errors))}"
            fingerprint = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:16]

            # Track retries on the exact same state
            count = self._retry_counts.get(fingerprint, 0) + 1
            self._retry_counts[fingerprint] = count

            # Circuit breaker: if we hit the exact same error/state more than max_retries
            if count > self.max_retries_per_step and errors:
                logger.warning(
                    "Circuit breaker tripped on fingerprint %s after %d retries. Errors: %s",
                    fingerprint, count, errors
                )
                return PageValidationResult(
                    state=ValidationState.STUCK_LOOP,
                    success=False,
                    current_url=current_url,
                    step_title=step_title,
                    error_messages=errors,
                    invalid_element_indices=invalid_indices,
                    needs_human_intervention=True,
                    intervention_reason=(
                        f"Repeated validation failure ({count} times): "
                        f"{'; '.join(errors[:3])}. Pausing for candidate review."
                    ),
                )

            # Check if validation errors exist
            if errors:
                return PageValidationResult(
                    state=ValidationState.VALIDATION_ERROR,
                    success=False,
                    current_url=current_url,
                    step_title=step_title,
                    error_messages=errors,
                    invalid_element_indices=invalid_indices,
                    needs_human_intervention=False,
                    intervention_reason=f"Found {len(errors)} validation alert(s).",
                )

            # Check if URL or step heading changed (indicating successful advance)
            if self.last_url and (current_url != self.last_url or (step_title and step_title != self.last_step_title)):
                self.last_url = current_url
                self.last_step_title = step_title
                return PageValidationResult(
                    state=ValidationState.ADVANCED,
                    success=True,
                    current_url=current_url,
                    step_title=step_title,
                    error_messages=[],
                )

            self.last_url = current_url
            self.last_step_title = step_title
            return PageValidationResult(
                state=ValidationState.SAME_STEP,
                success=True,
                current_url=current_url,
                step_title=step_title,
                error_messages=[],
            )

        except Exception as exc:
            logger.error("Error during page state validation: %s", exc)
            return PageValidationResult(
                state=ValidationState.SAME_STEP,
                success=True,
                current_url=getattr(page, "url", ""),
                step_title="",
                error_messages=[],
            )
