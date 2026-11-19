"""Smart Autonomous Agent Cognition & Action Dispatcher.

Combines Set-of-Marks visual element extraction with LLM reasoning (or a zero-cost
semantic heuristic fallback) to reliably fill forms without selector hallucinations,
verify progression, and prevent infinite loops.

Guarantees 100% free local execution:
- Works with Gemini Free Tier, Groq Free Tier, Ollama local ($0), or
  the built-in zero-cost semantic matcher if no API key is provided.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .page_validator import PageStateValidator, PageValidationResult, ValidationState
from .som_extractor import IndexedElement, SetOfMarksExtractor

logger = logging.getLogger("formpilot.smart_agent")


@dataclass
class AgentAction:
    action_type: str  # "fill", "select", "click", "handover"
    index: int
    value: str = ""
    reason: str = ""


@dataclass
class AgentStepResult:
    success: bool
    actions_executed: List[Dict[str, Any]] = field(default_factory=list)
    validation: Optional[Dict[str, Any]] = None
    needs_human: bool = False
    message: str = ""


# Field mapping dictionary for the 100% free zero-cost semantic matcher
# Ordered from highest specificity to generic fallback
COMMON_FIELD_SYNONYMS = {
    "mother_name": ["mother_name", "mother's name", "mother name", "mother / guardian name", "mother / guardian", "mother", "माता", "माता का नाम", "माता / अभिभावक"],
    "father_name": ["father_name", "father's name", "father name", "father / guardian name", "father / guardian", "father", "पिता", "पिता का नाम", "पिता / अभिभावक", "guardian_name"],
    "dob": ["dob", "date_of_birth", "birth_date", "date of birth", "birthdate", "जन्म तिथि", "जन्म"],
    "email": ["email", "email_address", "e-mail", "candidate_email", "mail", "ईमेल"],
    "mobile": ["mobile", "phone", "mobile_number", "contact_number", "phone_number", "tel", "मोबाइल", "फोन"],
    "gender": ["gender", "sex", "लिंग"],
    "category": ["category", "caste", "social_category", "community", "श्रेणी", "वर्ग"],
    "pincode": ["pincode", "pin_code", "postal_code", "zip", "zipcode", "पिन कोड"],
    "state": ["state", "state_of_residence", "domicile_state", "राज्य"],
    "district": ["district", "city", "ज़िला", "जिला"],
    "aadhaar": ["aadhaar", "aadhaar_number", "aadhar", "national_id", "आधार"],
    "roll_number": ["roll_number", "roll_no", "hall_ticket_number", "registration_no", "रोल नंबर"],
    "present_address": ["present_address", "correspondence_address", "current_address", "पत्राचार पता", "वर्तमान पता"],
    "permanent_address": ["permanent_address", "स्थाई पता", "मूल पता"],
    "address": ["address", "residential_address", "पता"],
    "name": ["candidate_name", "full_name", "applicant_name", "candidate's name", "applicant name", "name", "अभ्यर्थी का नाम", "नाम"],
}


class SmartFormAgent:
    """Autonomous agent that fills forms via Set-of-Marks and self-healing validation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gemini-2.0-flash",
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
        self.model = model

        # Auto-load from data/llm_config.json if not explicitly provided
        if not self.api_key:
            cfg_path = os.path.join("data", "llm_config.json")
            if os.path.isfile(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                    self.api_key = cfg_data.get("api_key", self.api_key)
                    self.base_url = cfg_data.get("base_url", self.base_url)
                    self.model = cfg_data.get("model", self.model)
                except Exception as exc:
                    logger.debug("Could not read data/llm_config.json: %s", exc)

        self.validator = PageStateValidator(max_retries_per_step=2)

    def _normalize_string(self, text: str) -> str:
        # Preserve alphanumeric and Unicode word characters (including Devanagari / Hindi)
        return re.sub(r"[^\w\d]+", "", (text or "").lower(), flags=re.UNICODE)

    def match_fields_offline(
        self,
        elements: List[IndexedElement],
        profile: Dict[str, Any],
    ) -> List[AgentAction]:
        """100% Free Semantic Heuristic Matcher.

        Used when running offline with no LLM API key, guaranteeing zero cost.
        """
        actions: List[AgentAction] = []
        flattened_profile: Dict[str, str] = {}

        # Flatten nested profile dict
        def _flatten(d: Dict[str, Any], prefix: str = ""):
            for k, v in d.items():
                if isinstance(v, dict):
                    _flatten(v, prefix=f"{prefix}{k}_")
                elif v is not None and not isinstance(v, (list, bytes)):
                    flattened_profile[f"{prefix}{k}".lower()] = str(v)

        _flatten(profile)

        for el in elements:
            if el.disabled:
                continue

            # Skip buttons and links during value filling phase
            if el.tag in ("button", "a") or el.element_type in ("submit", "button"):
                continue

            target_label = self._normalize_string(f"{el.label} {el.placeholder}")
            if not target_label:
                continue
            matched_value: Optional[str] = None
            matched_key: Optional[str] = None

            # Look for synonym matches
            for canonical_key, synonyms in COMMON_FIELD_SYNONYMS.items():
                # Disambiguation: generic candidate name must NEVER match father/mother/guardian
                if canonical_key == "name":
                    if any(t in target_label for t in ("father", "mother", "guardian", "पिता", "माता", "अभिभावक", "spouse", "husband")):
                        continue
                if canonical_key == "father_name":
                    if any(t in target_label for t in ("mother", "माता", "mom")):
                        continue

                norm_syns = [self._normalize_string(syn) for syn in synonyms]
                norm_syns = [s for s in norm_syns if s]  # Strip any empty strings
                if any(s in target_label for s in norm_syns):
                    for prof_k, prof_v in flattened_profile.items():
                        norm_prof_k = self._normalize_string(prof_k)
                        if not norm_prof_k:
                            continue
                        # Never match candidate name into father/mother or vice versa
                        if canonical_key in ("father_name", "mother_name") and "father" not in norm_prof_k and "mother" not in norm_prof_k and "guardian" not in norm_prof_k:
                            continue
                        if any(s in norm_prof_k or norm_prof_k in s for s in norm_syns):
                            matched_value = prof_v
                            matched_key = prof_k
                            break
                    if matched_value:
                        break

            # Generic fallback: check if any profile key is a substring of label
            if not matched_value:
                for prof_k, prof_v in flattened_profile.items():
                    norm_k = self._normalize_string(prof_k)
                    if norm_k and (norm_k in target_label or target_label in norm_k):
                        matched_value = prof_v
                        matched_key = prof_k
                        break

            if matched_value:
                if el.tag == "select":
                    # Match best option
                    best_opt = None
                    norm_val = self._normalize_string(matched_value)
                    for opt in el.options:
                        if norm_val in self._normalize_string(opt):
                            best_opt = opt
                            break
                    actions.append(
                        AgentAction(
                            action_type="select",
                            index=el.index,
                            value=best_opt or matched_value,
                            reason=f"Matched profile key '{matched_key}' to select element",
                        )
                    )
                elif el.element_type in ("checkbox", "radio"):
                    # Check if true/positive
                    if str(matched_value).lower() in ("true", "yes", "1"):
                        actions.append(
                            AgentAction(
                                action_type="click",
                                index=el.index,
                                reason=f"Matched affirmative checkbox for '{matched_key}'",
                            )
                        )
                else:
                    actions.append(
                        AgentAction(
                            action_type="fill",
                            index=el.index,
                            value=matched_value,
                            reason=f"Matched profile key '{matched_key}' to text input",
                        )
                    )

        return actions

    async def _execute_actions(self, page: Any, actions: List[AgentAction]) -> List[Dict[str, Any]]:
        """Executes actions on page using native Playwright events."""
        executed = []
        for act in actions:
            try:
                selector = f'[data-formpilot-idx="{act.index}"]'
                loc = page.locator(selector).first
                if await loc.count() == 0:
                    continue

                if act.action_type == "fill":
                    await loc.scroll_into_view_if_needed()
                    await loc.click()
                    await loc.fill(act.value)
                    # Dispatch input and change events to notify frameworks (React, Angular)
                    await loc.evaluate(
                        "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); el.blur(); }"
                    )
                    executed.append({"action": "fill", "index": act.index, "value": act.value})

                elif act.action_type == "select":
                    await loc.scroll_into_view_if_needed()
                    try:
                        await loc.select_option(label=act.value)
                    except Exception:
                        await loc.select_option(value=act.value)
                    await loc.evaluate(
                        "el => { el.dispatchEvent(new Event('change', { bubbles: true })); el.blur(); }"
                    )
                    executed.append({"action": "select", "index": act.index, "value": act.value})

                elif act.action_type == "click":
                    await loc.scroll_into_view_if_needed()
                    await loc.click()
                    executed.append({"action": "click", "index": act.index})

                await asyncio.sleep(0.05)
            except Exception as exc:
                logger.warning("Failed to execute action on index %d: %s", act.index, exc)

        return executed

    async def match_fields_with_llm(
        self,
        elements: List[IndexedElement],
        profile: Dict[str, Any],
        goal: str = "",
    ) -> List[AgentAction]:
        """Uses Gemini Flash / OpenAI model to reason about complex form fields."""
        if not self.api_key:
            return self.match_fields_offline(elements, profile)

        prompt_elements = SetOfMarksExtractor.format_for_prompt(elements)
        system_prompt = (
            "You are FormPilot's autonomous browser cognition engine. Given a list of indexed interactive elements "
            "on the webpage and candidate profile JSON, decide the exact actions to fill the form.\n"
            "Return a JSON array of actions: [{\"action_type\": \"fill\"|\"select\"|\"click\", \"index\": N, \"value\": \"...\"}].\n"
            "Only return the valid JSON array without any markdown formatting or commentary. Do NOT click final submit or payment."
        )
        user_message = (
            f"Candidate Profile:\n{json.dumps(profile, indent=2)}\n\n"
            f"Visible Elements on Page:\n{prompt_elements}\n\n"
            f"Goal: {goal}"
        )

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "temperature": 0.1,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
                    parsed = json.loads(clean)
                    if isinstance(parsed, list) and parsed:
                        return [
                            AgentAction(
                                action_type=item.get("action_type", "fill"),
                                index=int(item["index"]),
                                value=str(item.get("value", "")),
                                reason="Decided by Gemini reasoning",
                            )
                            for item in parsed
                            if "index" in item
                        ]
        except Exception as exc:
            logger.warning("Gemini LLM call failed, falling back to offline matcher: %s", exc)

        return self.match_fields_offline(elements, profile)

    async def step(
        self,
        page: Any,
        profile: Dict[str, Any],
        goal: str = "Fill form fields and verify page",
    ) -> AgentStepResult:
        """Runs one full perception-action-verification step on the page."""
        # 1. Perception (Set-of-Marks)
        elements = await SetOfMarksExtractor.extract_elements(page)
        if not elements:
            return AgentStepResult(success=True, message="No interactive elements found on page.")

        # 2. Cognition (Determine actions via Gemini Flash or offline matcher)
        actions = await self.match_fields_with_llm(elements, profile, goal)

        # 3. Action Execution
        executed = await self._execute_actions(page, actions)

        # 4. Verification & Error Catching
        validation = await self.validator.validate_state(page, action_summary=f"Executed {len(executed)} actions")

        if validation.state == ValidationState.STUCK_LOOP:
            return AgentStepResult(
                success=False,
                actions_executed=executed,
                validation=validation.to_dict(),
                needs_human=True,
                message=validation.intervention_reason,
            )

        return AgentStepResult(
            success=True,
            actions_executed=executed,
            validation=validation.to_dict(),
            needs_human=validation.needs_human_intervention,
            message=f"Filled {len(executed)} fields successfully. State: {validation.state.value}",
        )
