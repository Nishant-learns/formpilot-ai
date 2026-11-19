"""Set-of-Marks (SOM) Visual and Interactive Element Extractor.

Inspired by Skyvern and Set-of-Marks prompting, this module extracts all
physically visible, interactive elements on a web page and assigns them clean
numeric indices [1, 2, 3...].

Instead of hallucinating CSS selectors from raw 50KB HTML DOM dumps, the agent
acts on strictly verified, physically present elements via their unique index.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("formpilot.som_extractor")


@dataclass
class IndexedElement:
    """Represents a visible interactive element tagged with a numeric mark."""
    index: int
    tag: str
    element_type: str
    label: str
    placeholder: str = ""
    value: str = ""
    checked: Optional[bool] = None
    options: List[str] = field(default_factory=list)
    required: bool = False
    disabled: bool = False
    rect: Dict[str, float] = field(default_factory=dict)
    selector: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        """Compact one-line representation for token-efficient LLM prompt injection."""
        parts = [f"[{self.index}] {self.tag.upper()}"]
        if self.element_type and self.element_type not in (self.tag, "text"):
            parts.append(f"type='{self.element_type}'")
        if self.label:
            parts.append(f"label='{self.label}'")
        if self.placeholder:
            parts.append(f"placeholder='{self.placeholder}'")
        if self.value:
            parts.append(f"value='{self.value}'")
        if self.checked is not None:
            parts.append(f"checked={self.checked}")
        if self.options:
            opts_preview = ", ".join(f"'{o}'" for o in self.options[:6])
            if len(self.options) > 6:
                opts_preview += f" ... (+{len(self.options) - 6} more)"
            parts.append(f"options=[{opts_preview}]")
        if self.required:
            parts.append("REQUIRED")
        if self.disabled:
            parts.append("DISABLED")
        return " | ".join(parts)


# JavaScript snippet injected into Playwright to prune the DOM and tag elements
INJECT_SOM_JS = """
(() => {
    // Clean up any previously assigned temporary attributes
    const prevTagged = document.querySelectorAll('[data-formpilot-idx]');
    prevTagged.forEach(el => el.removeAttribute('data-formpilot-idx'));

    const candidates = Array.from(document.querySelectorAll(
        'input, select, textarea, button, a[href], [role="button"], [role="checkbox"], [role="combobox"], [role="radio"], [role="link"]'
    ));

    const results = [];
    let idx = 1;

    function isVisible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') === 0) {
            return false;
        }
        return true;
    }

    function findLabel(el) {
        // 1. Direct aria-label
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

        // 2. aria-labelledby
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const labelEl = document.getElementById(labelledBy);
            if (labelEl && labelEl.innerText.trim()) return labelEl.innerText.trim();
        }

        // 3. Associated <label for="id">
        if (el.id) {
            const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (labelEl && labelEl.innerText.trim()) return labelEl.innerText.trim();
        }

        // 4. Enclosing <label>
        const parentLabel = el.closest('label');
        if (parentLabel && parentLabel.innerText.trim()) {
            // Get text without the element's own value
            const clone = parentLabel.cloneNode(true);
            const insideInputs = clone.querySelectorAll('input, select, textarea');
            insideInputs.forEach(i => i.remove());
            const text = clone.innerText.trim();
            if (text) return text;
        }

        // 5. Preceding sibling or table cell label (common in Indian gov portals)
        const parentCell = el.closest('td');
        if (parentCell && parentCell.previousElementSibling) {
            const prevText = parentCell.previousElementSibling.innerText.trim();
            if (prevText && prevText.length < 100) return prevText;
        }

        // 6. Preceding heading/paragraph in form group
        const formGroup = el.closest('.form-group, .form-row, .mb-3, .form-item, fieldset, tr');
        if (formGroup) {
            const groupLabel = formGroup.querySelector('label, .label, th, legend');
            if (groupLabel && groupLabel.innerText.trim()) return groupLabel.innerText.trim();
        }

        // 7. Title or placeholder fallback
        return el.getAttribute('title') || el.getAttribute('name') || '';
    }

    for (const el of candidates) {
        if (!isVisible(el)) continue;

        // Skip hidden input types
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input' && (type === 'hidden' || type === 'file')) {
            // keep file inputs as they are needed for photo/sign upload checkpoints
            if (type === 'hidden') continue;
        }

        const rect = el.getBoundingClientRect();
        const label = findLabel(el);
        const placeholder = el.getAttribute('placeholder') || '';
        const required = el.required || el.getAttribute('aria-required') === 'true';
        const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';

        let value = '';
        let checked = null;
        let options = [];

        if (tag === 'select') {
            options = Array.from(el.options).map(opt => opt.text.trim()).filter(Boolean);
            value = el.options[el.selectedIndex]?.text?.trim() || el.value || '';
        } else if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
            checked = el.checked;
            value = el.value || '';
        } else if (tag === 'button' || el.getAttribute('role') === 'button') {
            value = el.innerText.trim() || el.getAttribute('value') || '';
        } else {
            value = el.value !== undefined ? String(el.value) : (el.innerText || '');
        }

        // Tag element in DOM with unique attribute
        el.setAttribute('data-formpilot-idx', String(idx));

        results.push({
            index: idx,
            tag: tag,
            element_type: type || tag,
            label: label,
            placeholder: placeholder,
            value: value.slice(0, 100),
            checked: checked,
            options: options.slice(0, 50),
            required: !!required,
            disabled: !!disabled,
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            },
            selector: `[data-formpilot-idx="${idx}"]`
        });

        idx++;
    }

    return results;
})();
"""


class SetOfMarksExtractor:
    """Extracts indexed interactive elements from an active Playwright page."""

    @classmethod
    async def extract_elements(cls, page: Any) -> List[IndexedElement]:
        """Scans page and tags all visible interactive controls with data-formpilot-idx."""
        try:
            raw_elements = await page.evaluate(INJECT_SOM_JS)
            elements: List[IndexedElement] = []
            for item in raw_elements:
                elements.append(
                    IndexedElement(
                        index=item["index"],
                        tag=item["tag"],
                        element_type=item["element_type"],
                        label=item["label"],
                        placeholder=item.get("placeholder", ""),
                        value=item.get("value", ""),
                        checked=item.get("checked"),
                        options=item.get("options", []),
                        required=item.get("required", False),
                        disabled=item.get("disabled", False),
                        rect=item.get("rect", {}),
                        selector=item.get("selector", f"[data-formpilot-idx=\"{item['index']}\"]"),
                    )
                )
            return elements
        except Exception as exc:
            logger.error("Failed to extract Set-of-Marks elements: %s", exc)
            return []

    @classmethod
    def format_for_prompt(cls, elements: List[IndexedElement]) -> str:
        """Formats the list of elements into a clean, concise prompt block."""
        if not elements:
            return "(No visible interactive elements detected)"
        lines = [elem.summary_line() for elem in elements]
        return "\n".join(lines)
