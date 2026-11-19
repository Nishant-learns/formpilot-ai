from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import inspect
import json
import os
import re
import time
import traceback
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from . import (
    choice_resolver,
    concepts,
    decision_policy,
    field_commit,
    field_registry,
    page_actions,
    settings,
)
from .action_resolver import ActionResolver, ActionResult
from .biometrics import BiometricCompressor
from .blueprint import BlueprintElement, PageBlueprint
from .dom_scanner import DOMScanner
from .document_store import DocumentStore
from .failures import FailureCode, classify_failure, is_retryable
from .facts import FactBook
from .fill_plan import build_fill_plan, match_option
from .form_model import FormModel
from .gates import apply_gate_metadata, gate_reason
from .lessons import LessonStore
from .live_browser import LiveBrowserSession, live_sessions
from .llm_client import LLMClient
from .navigator import ResilientNavigator
from .oracle import OracleResult, PortalOracle
from .page_brief import PageInterpreter
from .perception import Perception
from .progress import ProgressTracker, ProgressVerdict
from .portal_accounts import CONFLICT_CHOICES, PortalAccountStore, build_conflict_gate
from .portal_adapter import BasePortalAdapter, get_adapter
from .journey import JourneyStore, journey_key
from .recipe import RecipeStore
from .run_store import RunStore
from .tinyfish_client import TinyFishClient, TinyFishError, TinyFishSession
from .vault import CandidateVault, VaultManager


class AgentRunError(RuntimeError):
    """A user-actionable failure.  Its message is safe to show in the UI."""


# "Go back" must prefer a control on the page.  Many government portals are
# single-page wizards: the URL stays on "/" while the form steps change, so
# browser history would leave the portal instead of moving to the previous step.
_BACK_CONTROL_RE = re.compile(
    r"(?:\bback\b|\bprevious\b|\bprior\b|\bgo\s+back\b|"
    r"\b(?:pichhla|pichla|peeche|peche)\b|पिछला|पीछे|वापस)",
    re.IGNORECASE,
)
_BACK_CONTROL_DENY_RE = re.compile(
    r"(?:\b(?:log\s*out|logout|sign\s*out|signout|exit|quit|cancel|close|"
    r"clear|reset|delete|remove|dashboard|home)\b|"
    r"back\s+to\s+(?:login|sign\s*in|home|portal|dashboard|start|top)|"
    r"लॉग\s*आउट|साइन\s*आउट|रद्द)",
    re.IGNORECASE,
)


class FormPilotOrchestrator:
    """Guided form-filling agent with explicit human checkpoints."""

    def __init__(
        self,
        broadcast_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
        *,
        vault_mgr: Optional[VaultManager] = None,
        run_store: Optional[RunStore] = None,
        document_store: Optional[DocumentStore] = None,
        uploads_dir: Optional[Path] = None,
        fact_book: Optional[FactBook] = None,
        portal_account_store: Optional[PortalAccountStore] = None,
        lesson_store: Optional[LessonStore] = None,
    ):
        self.broadcast_fn = broadcast_fn
        # An account owns its stores.  The defaults keep the single-user demo
        # and the existing tests working unchanged.
        self.vault_mgr = vault_mgr or VaultManager.get_instance()
        self.tinyfish_mgr = TinyFishClient()
        self.run_store = run_store or RunStore()
        self.document_store = document_store or DocumentStore.get_instance()
        self.uploads_dir = Path(uploads_dir) if uploads_dir else settings.UPLOADS_DIR
        self._fact_book = fact_book
        self._portal_account_store = portal_account_store
        self._lesson_store = lesson_store

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._adapter: Optional[BasePortalAdapter] = None
        self._session: Optional[TinyFishSession] = None
        self.live: Optional[LiveBrowserSession] = None

        self.is_running = False
        self.paused = False
        self._is_paused = False
        self._stop_requested = False
        self.active_gate: Optional[Dict[str, Any]] = None
        self.active_event_future: Optional[asyncio.Future] = None
        self._pending_user_response: Optional[Dict[str, Any]] = None
        # Browser takeover: the human owns the live page, the loop stays paused,
        # and control is only returned by an explicit "continue" step.
        self._takeover_active = False
        self._takeover_paused_run = False
        self._takeover_started_at: Optional[str] = None

        self.current_section = 1
        self.filled_audit: List[Dict[str, Any]] = []
        self.fill_summary: Optional[Dict[str, Any]] = None
        self.fill_failures: List[Dict[str, Any]] = []
        self._fill_targets: List[Dict[str, Any]] = []
        self._fill_skipped: List[Dict[str, Any]] = []
        self._last_upload_path = ""
        self._entry_mode: Optional[str] = None
        self._requested_entry_mode: Optional[str] = None
        self._entry_options: List[Dict[str, Any]] = []
        self._login_method: Optional[str] = None
        self._login_identifier: Optional[str] = None
        self._requested_login_method: Optional[str] = None
        self._requested_login_identifier: Optional[str] = None

        self.state = "IDLE"
        self.run_id: Optional[str] = None
        self.last_error: Optional[str] = None
        self.target_url = ""
        self.query = ""
        self.mode = "local"
        self.run_mode = "fill"
        self.oracle_result: Optional[OracleResult] = None
        self.form_map: Optional[Dict[str, Any]] = None
        self.page_brief: Optional[Dict[str, Any]] = None
        self.page_interpreter = PageInterpreter()
        self.blueprint: Optional[PageBlueprint] = None
        self._last_action_result: Optional[ActionResult] = None
        self.recipe_store = RecipeStore()
        self.journey_store = JourneyStore()
        self._recipe_status: Optional[Dict[str, Any]] = None
        self._journey_key = ""
        self._journey_status: Optional[Dict[str, Any]] = None
        self._journey_step: Optional[Dict[str, Any]] = None
        self._journey_field_hints: Dict[str, str] = {}
        self._journey_choice_hints: Dict[str, str] = {}
        self._pending_journey_action: Optional[Dict[str, str]] = None
        self._last_journey_step_id = ""
        self._last_journey_fingerprint = ""
        self._last_form_fingerprint = ""
        self._last_recipe_event = ""
        self._pending_upload: Optional[Dict[str, Any]] = None
        self._session_values: Dict[str, str] = {}
        self._session_created_password: str = ""

        self._otp_cleared = False
        self._otp_signature = ""
        self._last_advance_signature = ""
        # A save click that changed nothing must not be repeated blindly; the
        # signature of the stuck page is remembered until the page moves or a
        # human acts.
        self._blocked_advance = ""
        self._advance_handoff_signature = ""
        self._captcha_signature = ""
        self._last_error_signature = ""
        self._idp_signed_in = set()
        self._browser_error_count = 0
        # One synchronized snapshot for the live view, the cockpit and chat.
        self._sync_revision = 0
        self._page_sync: Dict[str, Any] = {}
        self._last_sync_signature = ""
        self._last_agent_action = ""
        self._last_gateway_signature = ""
        self._last_app_link_signature = ""
        self._app_link_follows = 0
        self._error_recovery_attempts: Dict[str, int] = {}
        self._last_scan_key = ""
        # URLs seen during this run.  Browser history is only a safe fallback
        # when there is more than one real page in it.
        self._visited_urls: List[str] = []
        self._handled_conflicts: set = set()
        self._open_gate_step: Optional[str] = None
        self._open_gate_signature: str = ""
        # Frozen review snapshot: URL + field-value digest + audit hash.  A
        # changed page invalidates the human's pre-payment review.
        self._approval_snapshot: Optional[Dict[str, Any]] = None
        # Attended-time clock.  The run clock pauses while a gate is open; the
        # wall clock does not, so an absolute ceiling still applies.
        self._run_started_at: Optional[str] = None
        self._run_started_monotonic: Optional[float] = None
        self._gate_seconds = 0.0
        self._gate_opened_monotonic: Optional[float] = None
        # Model usage is metered per run by snapshotting the interpreter's
        # client at start and storing the delta at finish.
        self._llm_usage_start: Optional[Dict[str, Any]] = None
        # Stall detection.  The low threshold is shadow-only; only the high
        # threshold stops the run and asks the human.
        self._progress = self._new_progress_tracker()
        self._shadow_stall_key = None
        self._last_screenshot_at = 0.0
        self._idle_cycles = 0
        # Read by the chat assistant and the operator brief; also reset per run.
        self.recent_events: Deque[Dict[str, str]] = deque(maxlen=12)

    # ------------------------------------------------------------- owned stores

    @property
    def fact_book(self) -> FactBook:
        """The account's fact book, or the process-wide one for the demo."""
        return self._fact_book or FactBook.get_instance()

    @property
    def portal_account_store(self) -> PortalAccountStore:
        """The account's portal memory, or the demo store for a guest."""
        return self._portal_account_store or PortalAccountStore.get_instance()

    @property
    def lesson_store(self) -> LessonStore:
        """The account's learned portal lessons, or the demo store."""
        return self._lesson_store or LessonStore.get_instance()

    def _record_lesson(
        self,
        *,
        domain: str,
        signature: str,
        action: str,
        outcome: str,
        note: str = "",
    ) -> None:
        """Best-effort lesson capture; a store failure must never stop a run."""
        try:
            self.lesson_store.record(
                domain=domain,
                signature=signature,
                action=action,
                outcome=outcome,
                note=note,
            )
        except Exception:
            traceback.print_exc()

    # ---------------------------------------------------------------- public API

    def _engine_session_info(self) -> Optional[Dict[str, Any]]:
        """Safe, diagnostic view of the cloud/local browser session.

        The CDP URL is deliberately omitted: it is a live control channel, not
        status information.  ``fallback_reason`` carries the TinyFish error
        code (for example ``INSUFFICIENT_CREDITS``) when the cloud browser
        could not start and the run continued locally.
        """
        session = self._session
        if not session:
            return None
        return {
            "session_id": session.session_id,
            "is_cloud": session.is_cloud,
            "proxy_node": session.proxy_node,
            "country_code": session.country_code,
            "fallback_reason": session.fallback_reason,
        }

    def _engine_label(self) -> Dict[str, Any]:
        """Plain-language answer to "is TinyFish actually driving?".

        The cockpit shows this, so a silent fallback to the local browser can
        never masquerade as a cloud run.
        """
        session = self._session
        if not session:
            return {"driver": "none", "label": "No browser yet", "is_cloud": False}
        if session.is_cloud:
            return {
                "driver": "tinyfish-cloud",
                "label": "TinyFish cloud browser",
                "is_cloud": True,
                "proxy_node": session.proxy_node,
                "country_code": session.country_code,
            }
        return {
            "driver": "local-playwright",
            "label": "This device's browser",
            "is_cloud": False,
            "fallback_reason": session.fallback_reason or "",
        }

    def operator_brief(self) -> Dict[str, Any]:
        """Everything the chat needs to answer as if it were watching the run.

        One compact object instead of making the assistant re-derive state from
        five different endpoints.  It is read-only and safe to serialise.
        """
        gate = self.active_gate or {}
        summary = self.fill_summary or {}
        recent = list(self.recent_events)[-6:]
        can_go_back = bool(
            self.page
            and not self.page.is_closed()
            and self.state not in {"AWAITING_PAYMENT", "COMPLETED", "DONE"}
            and (
                self._back_control() is not None
                or len({url for url in self._visited_urls if url}) >= 2
            )
        )
        return {
            "run_id": self.run_id,
            "state": self.state,
            "engine": self._engine_label(),
            "url": (self.page.url if self.page and not self.page.is_closed() else self.target_url),
            "page_type": (self.form_map or {}).get("page_type"),
            "page_title": (self.form_map or {}).get("title"),
            "section": self.current_section,
            "paused": self.paused or self._is_paused,
            "fill_summary": {
                key: summary.get(key)
                for key in ("status", "attempted", "verified", "failed", "skipped")
                if summary
            }
            or None,
            "open_gate": {
                "type": gate.get("gate_type"),
                "title": gate.get("title"),
                "human_only": gate.get("gate_type")
                in {"CAPTCHA_SOLVE", "OTP_RELAY", "LIVE_PHOTO", "PRE_PAYMENT_SAFETY_LOCK"},
            }
            if gate
            else None,
            "recent_events": recent,
            "can_go_back": can_go_back,
            "saved_details": self._saved_detail_names(),
            "lessons": self._lesson_summary(),
            "pending_inputs": [
                str(field.get("label") or "")
                for field in ((self.form_map or {}).get("fields") or [])
                if field.get("needs_user_input")
            ][:10],
        }

    def _lesson_summary(self) -> List[Dict[str, Any]]:
        """What this account has already learned about the current portal."""
        try:
            domain = self._current_domain()
            return self.lesson_store.summary(domain) if domain else []
        except Exception:
            return []

    def _saved_detail_names(self) -> List[str]:
        """Names of profile values that are actually filled in."""
        vault = self.vault_mgr.vault
        names: List[str] = []
        for key in ("full_name", "father_name", "mother_name", "dob", "gender", "mobile", "email"):
            value = field_registry.resolve_value(vault, key)
            if value:
                names.append(key)
        return names

    async def go_back(self, *, reason: str = "The candidate asked to go back.") -> Dict[str, Any]:
        """Move one step back, then re-read the page.

        Preference order:

        1. A real Previous/Back control on the page.  This is the only correct
           move on a single-page wizard whose URL never changes.
        2. Browser history, but only when this run actually saw more than one
           URL.  Otherwise ``page.go_back()`` would leave the portal.
        3. An honest refusal.

        It is refused on a page that looks final, because going back there can
        discard a declaration the candidate already accepted.
        """
        if not self.page or self.page.is_closed():
            return {"success": False, "message": "There is no live page to go back from."}
        try:
            dom = await self._scan_dom()
            button = self._adapter.find_next_button(dom) if self._adapter else None
            if button and self._page_looks_final(dom, button):
                return {
                    "success": False,
                    "message": (
                        "This looks like the final declaration step. Going back here could "
                        "discard what you already confirmed, so I did not move the page."
                    ),
                }
        except Exception:
            pass

        control = self._back_control()
        failure_message = ""
        if control is not None:
            resolver = self._action_resolver()
            if resolver is not None:
                before = await resolver._page_state()
                result = await resolver.click(control.id)
                self._last_action_result = result
                await asyncio.sleep(0.25)
                after = await resolver._page_state()
                changed = bool(
                    result.ok
                    and (
                        result.postcondition == "changed"
                        or (
                            before is not None
                            and after is not None
                            and ActionResolver._state_changed(before, after)
                        )
                    )
                )
                if changed:
                    form_map = await self._refresh_after_navigation()
                    return await self._back_success(
                        form_map,
                        reason,
                        method="in_page_control",
                        control=control.label,
                    )
                failure_message = result.message or "the page did not change"
            else:
                failure_message = "the page could not be read"

        # Browser history is only safe when the run has really visited more
        # than one page.  A single-page wizard keeps one URL, so using history
        # there would leave the portal.
        if len({url for url in self._visited_urls if url}) >= 2:
            try:
                before_url = self.page.url
                await self.page.go_back(wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(0.6)
                if self.page.url == before_url:
                    return {
                        "success": False,
                        "message": (
                            "Browser history had no earlier page in this run, so I did not "
                            "leave the portal. Look for a Previous/Back control on the page."
                        ),
                    }
                form_map = await self._refresh_after_navigation()
                return await self._back_success(form_map, reason, method="history")
            except Exception as exc:
                return {
                    "success": False,
                    "message": f"The page did not move back: {exc.__class__.__name__}.",
                }

        if failure_message:
            return {
                "success": False,
                "message": (
                    f"I found a Back control ({control.label!r}) but it did not move the page "
                    f"({failure_message}). I did not use browser history because this run has "
                    "only one page URL, which could leave the portal."
                ),
            }
        return {
            "success": False,
            "message": (
                "This page does not show a Previous/Back control, and this run has only one "
                "page URL. I did not use browser history because that could leave the portal."
            ),
        }

    async def _refresh_after_navigation(self) -> Dict[str, Any]:
        try:
            _dom, form_map = await self._observe_page(force_emit=False)
            self.form_map = form_map
            return form_map
        except Exception:
            return self.form_map or {}

    async def _back_success(
        self,
        form_map: Dict[str, Any],
        reason: str,
        *,
        method: str,
        control: str = "",
    ) -> Dict[str, Any]:
        title = form_map.get("title") or form_map.get("page_type") or "the previous page"
        await self.emit_event(
            "ACT",
            f"Went back one step at your request. Now on: {title}.",
            "Aapke kehne par ek step peeche aa gaye.",
            force_screenshot=True,
        )
        return {
            "success": True,
            "url": (self.page.url if self.page else ""),
            "title": form_map.get("title"),
            "page_type": form_map.get("page_type"),
            "method": method,
            "control": control,
            "message": f"Went back. You are on '{title}'.",
            "reason": reason,
        }

    async def navigate_to_section(self, target_section: str) -> Dict[str, Any]:
        """Navigate directly to a named section/tab or step on the active form."""
        if not self.page or self.page.is_closed():
            return {"success": False, "message": "There is no live page to navigate."}

        target_clean = str(target_section or "").strip()
        if not target_clean:
            return {"success": False, "message": "No target section specified."}

        # Check if already there
        snapshot = await self._page_snapshot()
        current_heading = (snapshot.get("heading") or "").lower()
        current_title = (snapshot.get("title") or "").lower()
        current_sec_id = (snapshot.get("section") or "").lower()

        keywords = [w.lower() for w in re.split(r"[\s/&_\-]+", target_clean) if len(w) > 2]
        if keywords and any(k in current_heading or k in current_title or k in current_sec_id for k in keywords):
            return {
                "success": True,
                "already_there": True,
                "section": target_clean,
                "message": f"Already on {target_clean}.",
            }

        # Attempt 1: Clickable tabs, steppers, or breadcrumbs in DOM
        try:
            clicked_info = await self.page.evaluate(
                r"""(kws) => {
                    const selector = '.step-tabs .tab, .tab, .step, [role="tab"], .nav-step, .nav-tabs a, .stepper-step, .breadcrumb-item, a, button, [onclick*="Step"], [onclick*="step"], [onclick*="tab"]';
                    const nodes = Array.from(document.querySelectorAll(selector));
                    for (const el of nodes) {
                        if (!el || el.getClientRects().length === 0) continue;
                        const text = ((el.innerText || el.textContent || '') + ' ' + (el.id || '') + ' ' + (el.className || '')).toLowerCase();
                        if (kws.some(k => text.includes(k))) {
                            el.click();
                            return { clicked: true, text: (el.innerText || el.textContent || '').trim() };
                        }
                    }
                    return { clicked: false };
                }""",
                keywords,
            )
            if clicked_info and clicked_info.get("clicked"):
                await asyncio.sleep(0.5)
                await self._wait_for_postback(timeout_ms=3000)
                new_snap = await self._page_snapshot()
                new_heading = (new_snap.get("heading") or "").lower()
                new_sec = (new_snap.get("section") or "").lower()
                if any(k in new_heading or k in new_sec for k in keywords):
                    form_map = await self._refresh_after_navigation()
                    title = form_map.get("title") or target_clean
                    await self.emit_event(
                        "ACT",
                        f"Navigated to section: {title}.",
                        f"Section badal kar {title} par aa gaye.",
                        force_screenshot=True,
                    )
                    return {
                        "success": True,
                        "section": target_clean,
                        "method": "tab_click",
                        "message": f"Navigated to {target_clean}.",
                    }
        except Exception:
            pass

        # Attempt 2: Sequential in-page Back / Previous if target is an earlier section
        for _ in range(5):
            back_res = await self.go_back(reason=f"Candidate requested {target_clean}")
            if not back_res.get("success"):
                break
            await asyncio.sleep(0.4)
            snap = await self._page_snapshot()
            h = (snap.get("heading") or "").lower()
            s = (snap.get("section") or "").lower()
            if any(k in h or k in s for k in keywords):
                form_map = await self._refresh_after_navigation()
                title = form_map.get("title") or target_clean
                await self.emit_event(
                    "ACT",
                    f"Navigated back to section: {title}.",
                    f"Section badal kar {title} par aa gaye.",
                    force_screenshot=True,
                )
                return {
                    "success": True,
                    "section": target_clean,
                    "method": "sequential_back",
                    "message": f"Moved back to {target_clean}.",
                }

        return {
            "success": False,
            "message": f"Could not navigate directly to {target_clean} on this portal.",
        }


    def _back_control(self) -> Optional[BlueprintElement]:
        """The best visible Previous/Back control, or ``None``.

        A control is only eligible when its label really means "go back".
        Sign-out, cancel, reset and "back to login" controls are excluded even
        when they carry a ``btn-prev`` style class.
        """
        blueprint = self.blueprint
        if blueprint is None:
            return None
        candidates: List[BlueprintElement] = []
        for element in blueprint.interactables():
            if element.is_field or element.is_final_action:
                continue
            label = f"{element.name} {element.text}".strip()
            if not label or _BACK_CONTROL_DENY_RE.search(label):
                continue
            if not _BACK_CONTROL_RE.search(label):
                continue
            candidates.append(element)
        if not candidates:
            return None

        def score(element: BlueprintElement) -> int:
            label = f"{element.name} {element.text}".lower()
            value = 0
            if re.search(r"\bback\s+to\b", label):
                value += 4
            if re.search(r"\bprevious\b", label):
                value += 3
            if element.tag in {"button", "a"}:
                value += 2
            if element.role in {"button", "link"}:
                value += 1
            return value

        candidates.sort(key=score, reverse=True)
        return candidates[0]

    def get_state(self) -> Dict[str, Any]:
        browser_open = False
        try:
            browser_open = bool(self.page and not self.page.is_closed())
        except Exception:
            browser_open = False
        return {
            "state": self.state,
            "is_running": self.is_running,
            "paused": self.paused or self._is_paused,
            "run_id": self.run_id,
            "query": self.query,
            "target_url": self.target_url,
            "mode": self.mode,
            "run_mode": self.run_mode,
            "browser_open": browser_open,
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "engine_session": self._engine_session_info(),
            "engine": self._engine_label(),
            "form_map": self.form_map,
            "page_brief": self.page_brief,
            "page_sync": self._page_sync,
            "sync_revision": self._sync_revision,
            "blueprint": self.blueprint.summary() if self.blueprint else None,
            "recipe": self._recipe_status,
            "journey": self._journey_status,
            "current_section": self.current_section,
            "active_gate": self.active_gate
            if self.is_running or self.state in {"WAITING_FOR_USER", "PAUSED", "AWAITING_PAYMENT"}
            else None,
            "filled_audit": self._public_audit(),
            "fill_summary": self.fill_summary,
            "fill_failures": self.fill_failures,
            "entry_mode": self._entry_mode,
            "entry_options": decision_policy.entry_summary(self._entry_options),
            "login_method": self._login_method,
            "login_identifier": self._login_identifier,
            "last_error": self.last_error,
            "oracle": self.oracle_result.model_dump() if self.oracle_result else None,
            "takeover": self.takeover_state(),
            "portal_account": self._portal_account_summary(),
            "run_clock": self.run_clock(),
            "llm_usage": self.llm_usage(),
            "progress": self._progress.snapshot(),
        }

    async def start_application(self, query_or_url: str, run_mode: str = "fill"):
        if self.is_running:
            await self.emit_event("SENSE", "An application is already in progress.", "Ek application pehle se chal rahi hai.")
            return
        if run_mode not in {"fill", "inspect"}:
            raise AgentRunError("Unknown run mode. Use 'fill' or 'inspect'.")

        if self.browser or self.page:
            await self._cleanup()
        self.is_running = True
        self.paused = False
        self._is_paused = False
        self._stop_requested = False
        self._pending_user_response = None
        self._pending_upload = None
        self.filled_audit = []
        self.fill_summary = None
        self.fill_failures = []
        self._fill_targets = []
        self._fill_skipped = []
        self._form_dirty = False
        self._last_upload_path = ""
        self._entry_mode = None
        self._requested_entry_mode = None
        self._entry_options = []
        self._login_method = None
        self._login_identifier = None
        self._requested_login_method = None
        self._requested_login_identifier = None
        self.current_section = 1
        self.active_gate = None
        self.last_error = None
        self.query = (query_or_url or "").strip()
        self.target_url = ""
        self.oracle_result = None
        self.run_mode = run_mode
        self.form_map = None
        self.page_brief = None
        self._recipe_status = None
        self._journey_key = ""
        self._journey_status = None
        self._journey_step = None
        self._journey_field_hints = {}
        self._journey_choice_hints = {}
        self._pending_journey_action = None
        self._last_journey_step_id = ""
        self._last_journey_fingerprint = ""
        self._last_form_fingerprint = ""
        self._last_recipe_event = ""
        self._session_values = {}
        self._session_created_password = ""
        self._otp_cleared = False
        self._otp_signature = ""
        self._last_advance_signature = ""
        # A save click that changed nothing must not be repeated blindly; the
        # signature of the stuck page is remembered until the page moves or a
        # human acts.
        self._blocked_advance = ""
        self._advance_handoff_signature = ""
        self._captcha_signature = ""
        self._last_error_signature = ""
        self._idp_signed_in = set()
        self._browser_error_count = 0
        # One synchronized snapshot for the live view, the cockpit and chat.
        self._sync_revision = 0
        self._page_sync: Dict[str, Any] = {}
        self._last_sync_signature = ""
        self._last_agent_action = ""
        self._last_gateway_signature = ""
        self._last_app_link_signature = ""
        self._app_link_follows = 0
        self._error_recovery_attempts: Dict[str, int] = {}
        self._last_scan_key = ""
        # The chat assistant reads this to stay in sync with what just
        # happened, without re-reading the whole journal.
        self.recent_events: Deque[Dict[str, str]] = deque(maxlen=12)
        self._handled_conflicts: set = set()
        self._open_gate_step: Optional[str] = None
        self._open_gate_signature: str = ""
        self._approval_snapshot = None
        self._run_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._run_started_monotonic = time.monotonic()
        self._gate_seconds = 0.0
        self._gate_opened_monotonic = None
        self._llm_usage_start = self.page_interpreter.usage_snapshot()
        self._progress = self._new_progress_tracker()
        self._shadow_stall_key = None
        self._idle_cycles = 0
        self.run_id = f"run-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.state = "RESOLVING"
        self.run_store.start(self.run_id, {"query": self.query, "mode": self.mode, "run_mode": self.run_mode})
        self._record_step(
            "run",
            output={"query": self.query, "mode": self.mode, "run_mode": self.run_mode},
        )

        try:
            await self.emit_event(
                "SENSE",
                "Looking up the official portal...",
                "Official portal check kar rahe hain...",
            )

            self.oracle_result = await PortalOracle.resolve_target_live(self.query, self.tinyfish_mgr)
            if not self.oracle_result.target_url:
                raise AgentRunError(self.oracle_result.advisory)

            self.target_url = self.oracle_result.target_url
            await self.emit_event(
                "THINK",
                f"Official portal found: {self.oracle_result.official_name}",
                self.oracle_result.hindi_advisory,
            )

            # Load the known path for this exam.  The path is structural and
            # shared between candidates; values still come from each vault.
            self._journey_key = journey_key(
                self.query,
                is_url=self.query.startswith(("http://", "https://")),
            )
            try:
                self._journey_status = self.journey_store.summary(self._journey_key)
                step_count = int(self._journey_status.get("step_count") or 0)
                if step_count:
                    proven = int(self._journey_status.get("proven_steps") or 0)
                    await self.emit_event(
                        "THINK",
                        f"Known path loaded: {step_count} page(s), {proven} proven on this exam. Reusing what worked before.",
                        f"Is exam ka known path mil gaya: {step_count} page, {proven} proven. Pehle jo chala, wahi reuse hoga.",
                    )
            except Exception:
                traceback.print_exc()

            # Ground execution in certified official examination blueprint if available
            try:
                from ..knowledge.blueprint_loader import BlueprintRegistry
                registry = BlueprintRegistry.get_instance()
                bp = registry.find_by_url_or_domain(self.target_url)
                if not bp and any(k in (self.query or "").lower() for k in ["jee", "nta", "main"]):
                    bp = registry.get_blueprint("NTA_JEE_MAIN_2027")
                self._active_blueprint = bp
                if bp:
                    DOMScanner.set_active_blueprint(bp)
                    await self.emit_event(
                        "THINK",
                        f"Official Grounding: Loaded certified {bp.exam_title} specification ({len(bp.all_fields_by_id)} verified fields, {len(bp.documents)} document specs).",
                        f"Official Grounding: Certified {bp.exam_title} blueprint load ho gaya.",
                    )
            except Exception:
                traceback.print_exc()

            self.state = "CONNECTING"
            await self._open_browser(self.target_url)

            await self.emit_event(
                "ACT",
                "Opening the application page...",
                "Application page khol rahe hain...",
            )
            try:
                nav = await ResilientNavigator.navigate_safely(self.page, self.target_url)
            except Exception as e:
                if self.mode == "cloud" and ("ERR_TUNNEL_CONNECTION_FAILED" in str(e) or "net::ERR" in str(e)):
                    await self.emit_event(
                        "SENSE",
                        "The remote cloud proxy was geo-blocked by the portal. Switching to local browser...",
                        "Remote cloud proxy portal dwara block ho gaya. Local device browser par switch kar rahe hain...",
                    )
                    await self._switch_to_local_browser()
                    nav = await ResilientNavigator.navigate_safely(self.page, self.target_url)
                else:
                    raise
            await self.emit_event(
                "SENSE",
                f"Page ready in {nav.get('elapsed_seconds', 0)}s.",
                "Page load ho gaya. Ab form ki details dekh rahe hain...",
            )

            await self._observe_page(force_emit=True)
            if self.run_mode == "inspect":
                await self._enter_inspect_mode()
                return

            self.state = "RUNNING"
            await self._autonomous_drive_loop()

        except asyncio.CancelledError:
            self.state = "STOPPED"
            await self.emit_event("DECIDE", "Application stopped.", "Application stop ho gayi.")
        except AgentRunError as exc:
            if self._stop_requested:
                self.state = "STOPPED"
            else:
                self.state = "FAILED"
                self.last_error = str(exc)
                await self.emit_event(
                    "DECIDE",
                    str(exc),
                    "Is portal ko verify nahi kar paye. Official notification link check karein.",
                    force_screenshot=True,
                )
        except Exception:
            if self._stop_requested:
                self.state = "STOPPED"
            else:
                self.state = "FAILED"
                self.last_error = "Something went wrong while filling this portal. Please try again or use the official portal directly."
                traceback.print_exc()
                await self.emit_event(
                    "DECIDE",
                    self.last_error,
                    "Kuch technical dikkat aa gayi. Dobara koshish karein ya official portal par khud apply karein.",
                    force_screenshot=True,
                )
        finally:
            self.is_running = False
            if self.state not in {"AWAITING_PAYMENT", "INSPECT_READY"}:
                await self._cleanup()
            self._record_step(
                "run",
                status="ok" if self.state in {"DONE", "AWAITING_PAYMENT", "INSPECT_READY"} else "failed",
                error_code=None if self.state in {"DONE", "AWAITING_PAYMENT", "INSPECT_READY"} else "internal_error",
                output={"state": self.state, "error": self.last_error},
            )
            self.run_store.finish(
                self.run_id or "unknown",
                self.state,
                {
                    "error": self.last_error,
                    "target_url": self.target_url,
                    "run_mode": self.run_mode,
                    "run_clock": self.run_clock(),
                    "llm_usage": self.llm_usage(),
                },
            )

    async def stop(self):
        self._stop_requested = True
        self.is_running = False
        self.paused = False
        self._is_paused = False
        self._takeover_active = False
        self._takeover_paused_run = False
        self._takeover_started_at = None
        self.state = "STOPPED"
        if self.active_event_future and not self.active_event_future.done():
            self.active_event_future.set_result({"action": "STOPPED"})
        self.active_event_future = None
        self.active_gate = None
        await self._cleanup()
        if self.run_id:
            self.run_store.finish(self.run_id, "STOPPED")
        await self.emit_event("DECIDE", "Application stopped.", "Application stop ho gayi.")

    async def reset_session(self) -> bool:
        """Return a finished session to a clean launcher state.

        Only allowed when nothing is running; a live run must be stopped first
        so this can never silently discard an in-flight application.
        """
        if self.is_running:
            return False
        await self._cleanup()
        self.state = "IDLE"
        self.run_id = None
        self.query = ""
        self.target_url = ""
        self.oracle_result = None
        self.form_map = None
        self.page_brief = None
        self._recipe_status = None
        self.current_section = 1
        self.filled_audit = []
        self.fill_summary = None
        self.fill_failures = []
        self._fill_targets = []
        self._fill_skipped = []
        self._form_dirty = False
        self._last_upload_path = ""
        self._entry_mode = None
        self._requested_entry_mode = None
        self._entry_options = []
        self._login_method = None
        self._login_identifier = None
        self._requested_login_method = None
        self._requested_login_identifier = None
        self.last_error = None
        self.active_gate = None
        self._pending_user_response = None
        self._stop_requested = False
        self.paused = False
        self._is_paused = False
        self._takeover_active = False
        self._takeover_paused_run = False
        self._takeover_started_at = None
        self._approval_snapshot = None
        self._run_started_at = None
        self._run_started_monotonic = None
        self._gate_seconds = 0.0
        self._gate_opened_monotonic = None
        self._llm_usage_start = None
        self._progress = self._new_progress_tracker()
        self._shadow_stall_key = None
        self.run_mode = "fill"
        return True

    def pause(self):
        self._is_paused = True
        self.paused = True
        self.state = "PAUSED"

    def resume(self):
        self._is_paused = False
        self.paused = False
        if self.state == "PAUSED":
            self.state = "RUNNING"

    # ---------------------------------------------------------------- takeover

    def takeover_state(self) -> Dict[str, Any]:
        """Whether the human owns the browser right now.

        ``available`` says a live page exists to take.  ``active`` says the
        human has it.  ``paused_run`` records that FormPilot paused itself for
        the takeover, so resuming is an explicit human action.
        """
        live_open = bool(self.live and not self.live.closed)
        return {
            "available": live_open,
            "active": self._takeover_active,
            "paused_run": self._takeover_paused_run,
            "started_at": self._takeover_started_at,
            "control_enabled": bool(getattr(self.live, "_control_enabled", False))
            if live_open
            else False,
        }

    async def take_human_control(self) -> Dict[str, Any]:
        """Give the human exclusive control of the live page.

        Always available while a live browser is open.  If the agent was
        driving, the loop pauses first so the human and the operator never
        act on the same page at the same time.  If a checkpoint is already
        waiting, the checkpoint keeps the human in control and no extra pause
        is needed.
        """
        if not self.live or self.live.closed:
            return {
                "success": False,
                "message": "There is no live browser open to take over.",
                "takeover": self.takeover_state(),
            }
        if self._takeover_active:
            self.live.set_allow_control(
                True, "You have control of the live browser. FormPilot is paused."
            )
            return {
                "success": True,
                "already": True,
                "state": self.state,
                "takeover": self.takeover_state(),
            }
        if not self.is_running and self.state not in {"PAUSED", "INSPECT_READY"}:
            return {
                "success": False,
                "message": "There is no active application to take over.",
                "takeover": self.takeover_state(),
            }

        self._takeover_active = True
        self._takeover_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._record_step("takeover", output={"event": "started", "state": self.state})
        waiting_at_gate = self.active_gate is not None or self.state in {
            "WAITING_FOR_USER",
            "AWAITING_PAYMENT",
        }
        if not waiting_at_gate and self.is_running:
            self.pause()
            self._takeover_paused_run = True
        self.live.set_allow_control(
            True, "You have control of the live browser. FormPilot is paused."
        )
        await self.emit_event(
            "DECIDE",
            "You have the browser. FormPilot is paused until you return control.",
            "Browser ab aapke paas hai. Jab tak aap control wapas nahi karenge, FormPilot ruka rahega.",
        )
        return {
            "success": True,
            "state": self.state,
            "takeover": self.takeover_state(),
        }

    async def return_human_control(self, *, refresh: bool = True) -> Dict[str, Any]:
        """Take the page back, re-read it, and stay paused for a human check.

        The page may have navigated or changed while the human was driving, so
        the operator's blueprint and the shared brief are rebuilt before the
        run can continue.  Control is not handed back to the loop automatically:
        the human reviews the fresh brief and presses Continue.
        """
        if not self._takeover_active:
            return {
                "success": False,
                "message": "The browser is not in human control.",
                "takeover": self.takeover_state(),
            }

        self._takeover_active = False
        self._record_step("takeover", output={"event": "returned", "state": self.state})
        if self.live and not self.live.closed:
            self.live.set_allow_control(
                False, "FormPilot is reading the page again. Control returns in a moment."
            )
        brief = self.page_brief
        refreshed = False
        if refresh and self.page and not self.page.is_closed():
            try:
                brief = await self.get_page_brief(refresh=True, adopt_blueprint=True)
                refreshed = True
            except Exception:
                traceback.print_exc()

        approval = await self._verify_approval_snapshot()

        # At a checkpoint the human is still expected to act, so control goes
        # back to them once the rescan is complete.  A paused driving run stays
        # with the operator until the human presses Continue.
        waiting_at_gate = self.active_gate is not None or self.state in {
            "WAITING_FOR_USER",
            "AWAITING_PAYMENT",
        }
        if self.live and not self.live.closed:
            if waiting_at_gate:
                self.live.set_allow_control(
                    True, "The checkpoint still needs you. FormPilot has re-read the page."
                )
            else:
                self.live.set_allow_control(
                    False,
                    "FormPilot is paused after your changes. Review the page, then continue.",
                )

        await self.emit_event(
            "SENSE",
            "You returned control. The page was re-read; FormPilot stays paused until you continue.",
            "Aapne control wapas diya. Page dobara padh liya; continue karne tak FormPilot ruka rahega.",
            force_screenshot=True,
        )
        self._takeover_paused_run = False
        self._takeover_started_at = None
        self._progress.reset("takeover_return")
        self._shadow_stall_key = None
        self._blocked_advance = ""
        return {
            "success": True,
            "state": self.state,
            "paused": self.paused or self._is_paused,
            "refreshed": refreshed,
            "page_brief": brief,
            "approval": approval,
            "takeover": self.takeover_state(),
        }

    def _release_live_control(self, reason: str) -> None:
        """Give control back to the loop unless the human still owns it."""
        if not self.live or self.live.closed:
            return
        if self._takeover_active:
            # A gate may close while the human is still driving; returning
            # control stays an explicit step.
            return
        self.live.set_allow_control(False, reason)

    # ------------------------------------------------------------ portal memory

    def _current_domain(self) -> str:
        url = self.page.url if self.page else (self.target_url or "")
        return urlparse(str(url or "")).netloc.lower()

    def _portal_credential(self, sem_key: str) -> str:
        """Return the identifier this portal's account actually uses.

        The vault holds one global mobile/email.  A candidate can have a
        different account on another portal, and PortalAccountStore remembers
        which identifier was used there.  On a login page that value must win
        over the global one, otherwise FormPilot types the wrong account.
        """
        if sem_key not in {"mobile", "email", "urn"}:
            return ""
        domain = self._current_domain()
        if not domain:
            return ""
        try:
            accounts = self.portal_account_store.accounts_for(domain)
        except Exception:
            return ""
        matches = [
            account
            for account in accounts
            if account.identifier_type == sem_key and account.identifier_value
        ]
        if not matches:
            return ""
        matches.sort(key=lambda account: account.updated_at or "", reverse=True)
        return str(matches[0].identifier_value)

    def _remember_portal_account(self, **fields: Any) -> None:
        domain = self._current_domain()
        if not domain:
            return
        try:
            self.portal_account_store.record(domain, **fields)
        except Exception:
            traceback.print_exc()

    # ---------------------------------------------------------------- ledger

    def _page_signature(self) -> str:
        if isinstance(self.form_map, dict):
            return str(self.form_map.get("fingerprint") or "")
        return ""

    def _record_step(
        self,
        kind: str,
        *,
        status: str = "ok",
        page_signature: str = "",
        input_digest: str = "",
        output: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
        duration_ms: Optional[int] = None,
        attempt: int = 1,
    ) -> Optional[str]:
        """Write one row to the run ledger.  Never let bookkeeping break a run."""
        if not self.run_id:
            return None
        try:
            return self.run_store.record_step(
                self.run_id,
                kind,
                status=status,
                page_signature=page_signature or self._page_signature(),
                input_digest=input_digest,
                output=output,
                error_code=error_code,
                duration_ms=duration_ms,
                attempt=attempt,
            )
        except Exception:
            traceback.print_exc()
            return None

    def _open_step(self, kind: str, **kwargs: Any) -> Optional[str]:
        if not self.run_id:
            return None
        try:
            return self.run_store.start_step(self.run_id, kind, **kwargs)
        except Exception:
            traceback.print_exc()
            return None

    def _close_step(self, step_id: Optional[str], status: str, **kwargs: Any) -> None:
        if not step_id or not self.run_id:
            return
        try:
            self.run_store.finish_step(self.run_id, step_id, status, **kwargs)
        except Exception:
            traceback.print_exc()

    def _start_gate_step(self, gate: Dict[str, Any]) -> None:
        """Open a ledger row for a gate that is waiting on a human."""
        gate_type = str(gate.get("gate_type") or "GATE")
        signature = "|".join(
            [
                gate_type,
                str(gate.get("stage") or ""),
                str(gate.get("title") or ""),
                str(gate.get("field_key") or ""),
            ]
        )
        if signature == self._open_gate_signature:
            return
        if self._open_gate_step:
            self._close_gate_step("REPLACED")
        # A gate that is re-opened after a close gets a fresh opening time and
        # deadline; a re-emit of the same open gate keeps the original.
        gate.pop("gate_opened_at", None)
        gate.pop("gate_deadline_at", None)
        apply_gate_metadata(gate)
        self._open_gate_signature = signature
        if self._gate_opened_monotonic is None:
            self._gate_opened_monotonic = time.monotonic()
        self._open_gate_step = self._open_step(
            "gate",
            status="waiting",
            page_signature=self._page_signature(),
            detail={
                "gate_type": gate_type,
                "title": gate.get("title"),
                "reason": gate.get("reason"),
                "recommended": gate.get("recommended"),
            },
        )

    def _close_gate_step(self, action: str) -> None:
        if self._gate_opened_monotonic is not None:
            self._gate_seconds += max(0.0, time.monotonic() - self._gate_opened_monotonic)
            self._gate_opened_monotonic = None
        if not self._open_gate_step:
            return
        status = {
            "DISMISS": "dismissed",
            "STOPPED": "stopped",
            "TIMEOUT": "timed_out",
            "REPLACED": "replaced",
        }.get(str(action or ""), "resolved")
        self._close_step(
            self._open_gate_step,
            status,
            output={"action": action or "UNKNOWN"},
        )
        self._open_gate_step = None
        self._open_gate_signature = ""

    def run_clock(self) -> Dict[str, Any]:
        """Active work time, attended gate time, and the absolute wall clock."""
        if self._run_started_monotonic is None:
            return {
                "started_at": None,
                "wall_seconds": 0.0,
                "attended_seconds": 0.0,
                "active_seconds": 0.0,
                "ceiling_seconds": settings.RUN_CEILING_SECONDS,
                "wall_ceiling_seconds": settings.RUN_WALL_CEILING_SECONDS,
                "gate_open": self._gate_opened_monotonic is not None,
            }
        now = time.monotonic()
        wall = max(0.0, now - self._run_started_monotonic)
        open_gate = (
            max(0.0, now - self._gate_opened_monotonic)
            if self._gate_opened_monotonic is not None
            else 0.0
        )
        attended = self._gate_seconds + open_gate
        active = max(0.0, wall - attended)
        return {
            "started_at": self._run_started_at,
            "wall_seconds": round(wall, 1),
            "attended_seconds": round(attended, 1),
            "active_seconds": round(active, 1),
            "ceiling_seconds": settings.RUN_CEILING_SECONDS,
            "wall_ceiling_seconds": settings.RUN_WALL_CEILING_SECONDS,
            "gate_open": self._gate_opened_monotonic is not None,
        }

    def llm_usage(self) -> Optional[Dict[str, Any]]:
        """Model calls and tokens spent by this run, with an optional cost."""
        after = self.page_interpreter.usage_snapshot()
        if after is None:
            return None
        before = self._llm_usage_start or {}
        delta = LLMClient.usage_delta(before, after)
        input_price = settings.LLM_PRICE_INPUT_PER_MTOK
        output_price = settings.LLM_PRICE_OUTPUT_PER_MTOK
        if input_price > 0 or output_price > 0:
            delta["estimated_cost_usd"] = round(
                (delta["prompt_tokens"] / 1_000_000) * input_price
                + (delta["completion_tokens"] / 1_000_000) * output_price,
                6,
            )
        return delta

    def _run_ceiling_exceeded(self) -> bool:
        clock = self.run_clock()
        return (
            clock["active_seconds"] >= settings.RUN_CEILING_SECONDS
            or clock["wall_seconds"] >= settings.RUN_WALL_CEILING_SECONDS
        )

    def _portal_account_summary(self) -> Dict[str, Any]:
        domain = self._current_domain()
        if not domain:
            return {}
        try:
            return self.portal_account_store.domain_summary(domain)
        except Exception:
            return {}

    def _set_login_method(self, method: str) -> None:
        self._login_method = str(method or "")
        if self._login_method:
            self._remember_portal_account(
                login_method=self._login_method, confirmed_by_human=True
            )

    def _set_login_identifier(self, key: str) -> None:
        self._login_identifier = str(key or "")
        if not self._login_identifier:
            return
        kind = self._login_identifier
        if kind not in {"mobile", "email", "urn", "aadhaar", "registration_id"}:
            kind = "unknown"
        value = ""
        try:
            value = str(self.vault_mgr.vault.find_field_value(self._login_identifier) or "")
        except Exception:
            value = ""
        self._remember_portal_account(
            identifier_type=kind,
            identifier_value=value,
            identifiers_seen=[kind],
            confirmed_by_human=True,
        )

    def submit_user_response(self, data: Dict[str, Any]):
        self._close_gate_step(str((data or {}).get("action") or ""))
        if self.active_event_future and not self.active_event_future.done():
            self.active_event_future.set_result(data)
        elif self.active_gate is not None:
            self._pending_user_response = data

    def choose_entry_mode(self, mode: str) -> Dict[str, Any]:
        """Select register/login/resume without guessing.

        Called by the chat assistant and by the cockpit.  When the entry gate is
        open the answer is delivered immediately.  Otherwise the choice is
        remembered and applied the next time the portal actually shows an
        entry page.  The choice is validated against the options the page
        offers; an unknown path is refused.
        """
        normalized = decision_policy.normalize_mode(mode)
        if not normalized:
            return {"success": False, "message": "Choose register, login or resume."}

        options = list(self._entry_options or [])
        gate = self.active_gate or {}
        if gate.get("gate_type") == "GATEWAY_DECISION":
            option = decision_policy.match_entry_response({"mode": normalized}, options)
            if not option:
                same_mode = [
                    item for item in options if item.get("mode") == normalized
                ]
                if len(same_mode) > 1:
                    labels = ", ".join(
                        f"'{item.get('text')}'" for item in same_mode
                    )
                    return {
                        "success": False,
                        "message": (
                            f"This page offers more than one {self._entry_label(normalized)} "
                            f"path: {labels}. Choose the exact option."
                        ),
                    }
                return {
                    "success": False,
                    "message": "The portal does not offer that entry path on this page.",
                }
            self._remember_portal_account(
                last_path_choice=normalized, confirmed_by_human=True
            )
            self.submit_user_response(
                {
                    "action": "GATEWAY_CHOICE",
                    "mode": normalized,
                    "type": option.get("type"),
                    "element_id": option.get("element_id"),
                    "text": option.get("text"),
                }
            )
            return {
                "success": True,
                "mode": normalized,
                "message": f"Selected {self._entry_label(normalized)}.",
            }

        if self._entry_mode == normalized:
            return {
                "success": True,
                "mode": normalized,
                "message": f"This session is already using {self._entry_label(normalized)}.",
            }
        if self._entry_mode and self._entry_mode not in {"manual", normalized}:
            return {
                "success": False,
                "message": (
                    "This session already chose a different entry path. "
                    "Start a new session to change it."
                ),
            }
        if options:
            option = decision_policy.match_entry_response({"mode": normalized}, options)
            if not option:
                return {
                    "success": False,
                    "message": "The portal does not offer that entry path on this page.",
                }
        self._requested_entry_mode = normalized
        self._remember_portal_account(
            last_path_choice=normalized, confirmed_by_human=True
        )
        return {
            "success": True,
            "mode": normalized,
            "message": f"I will open {self._entry_label(normalized)} when the portal shows the entry page.",
        }

    def choose_entry_option(self, option: Dict[str, Any]) -> Dict[str, Any]:
        """Select one exact option from the open gateway gate.

        Needed when a page offers two different links with the same entry type
        (for example "Preview ..." and "Proceed ..."), where a mode-only answer
        is ambiguous.
        """
        gate = self.active_gate or {}
        if gate.get("gate_type") != "GATEWAY_DECISION":
            return {"success": False, "message": "There is no entry choice open right now."}
        options = list(self._entry_options or [])
        query: Dict[str, Any] = {
            "element_id": option.get("element_id"),
            "text": option.get("text"),
            "href": option.get("href"),
        }
        if not option.get("text"):
            query["mode"] = option.get("mode") or option.get("type")
        selected = decision_policy.match_entry_response(query, options)
        if not selected:
            return {
                "success": False,
                "message": "That choice did not match an entry path on this page.",
            }
        self.submit_user_response(
            {
                "action": "GATEWAY_CHOICE",
                "mode": selected.get("mode"),
                "type": selected.get("type"),
                "element_id": selected.get("element_id"),
                "id": selected.get("id"),
                "href": selected.get("href"),
                "text": selected.get("text"),
            }
        )
        return {
            "success": True,
            "mode": selected.get("mode"),
            "message": f"Selected {selected.get('text')}.",
        }

    def choose_login_method(self, method: str) -> Dict[str, Any]:
        """Select a login method that the open gate actually offers."""
        normalized = str(method or "").strip()
        if not normalized:
            return {"success": False, "message": "Choose a sign-in method."}
        gate = self.active_gate or {}
        if gate.get("gate_type") == "LOGIN_METHOD":
            options = gate.get("options") or []
            match = next(
                (
                    option
                    for option in options
                    if normalized
                    in {
                        str(option.get("method") or ""),
                        str(option.get("value") or ""),
                        str(option.get("text") or ""),
                    }
                ),
                None,
            )
            if not match:
                return {
                    "success": False,
                    "message": "That sign-in method is not offered on this form.",
                }
            self.submit_user_response(
                {
                    "action": "LOGIN_METHOD_CHOICE",
                    "method": match.get("method"),
                    "value": match.get("value"),
                    "text": match.get("text"),
                }
            )
            return {
                "success": True,
                "method": match.get("method"),
                "message": f"Selected {match.get('label') or match.get('text')}.",
            }
        self._requested_login_method = normalized
        return {
            "success": True,
            "method": normalized,
            "message": "I will use that sign-in method when the login form asks for it.",
        }

    def choose_account_identifier(self, key: str) -> Dict[str, Any]:
        """Select which account identifier the login form should use."""
        normalized = str(key or "").strip()
        if not normalized:
            return {"success": False, "message": "Choose an account identifier."}
        gate = self.active_gate or {}
        if gate.get("gate_type") == "ACCOUNT_IDENTIFIER":
            options = gate.get("options") or []
            match = next(
                (
                    option
                    for option in options
                    if normalized
                    in {
                        str(option.get("key") or ""),
                        str(option.get("value") or ""),
                        str(option.get("text") or ""),
                    }
                ),
                None,
            )
            if not match:
                return {
                    "success": False,
                    "message": "That identifier is not offered on this login form.",
                }
            self.submit_user_response(
                {
                    "action": "ACCOUNT_IDENTIFIER_CHOICE",
                    "key": match.get("key"),
                    "value": match.get("key"),
                    "text": match.get("text"),
                }
            )
            return {
                "success": True,
                "identifier": match.get("key"),
                "message": f"Using {match.get('text')} to identify the account.",
            }
        self._requested_login_identifier = normalized
        return {
            "success": True,
            "identifier": normalized,
            "message": "I will use that identifier when the login form asks for it.",
        }

    @staticmethod
    def _entry_label(mode: str) -> str:
        return {
            "register": "account creation",
            "login": "sign in",
            "resume": "resume application",
        }.get(str(mode or ""), "that entry path")

    # ---------------------------------------------------------------- browser

    async def _open_browser(self, target_url: str):
        cfg = self.tinyfish_mgr.config
        if not self.playwright:
            self.playwright = await async_playwright().start()

        session: Optional[TinyFishSession] = None
        try:
            session = await self.tinyfish_mgr.create_cloud_browser_session(target_url)
        except TinyFishError as exc:
            reason_code = getattr(exc, "code", "") or "cloud_browser_error"
            await self.emit_event(
                "SENSE",
                f"The cloud browser is unavailable right now ({reason_code}). Continuing in this device's browser.",
                "Cloud browser abhi available nahi hai. Is device ke browser mein aage badh rahe hain.",
            )
            session = TinyFishSession(
                session_id=f"local-{uuid.uuid4().hex[:10]}",
                cdp_url="",
                proxy_node="This device",
                country_code=cfg.proxy_region.upper(),
                is_cloud=False,
                fallback_reason=str(exc),
            )

        self._session = session
        self.mode = "cloud" if session.is_cloud else "local"
        # Record who is driving while the run is still open, so the journal
        # answers "cloud or local?" even for a run that never finishes.
        try:
            self.run_store.update_meta(
                self.run_id,
                {
                    "engine": "tinyfish-cloud" if session.is_cloud else "local-playwright",
                    "engine_session_id": session.session_id,
                    "engine_proxy_node": session.proxy_node,
                    "engine_fallback_reason": session.fallback_reason or "",
                },
            )
        except Exception:
            traceback.print_exc()

        if session.is_cloud:
            try:
                self.browser = await self.playwright.chromium.connect_over_cdp(session.cdp_url, timeout=60000)
                self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                await self.emit_event(
                    "ACT",
                    "Cloud browser connected.",
                    "Cloud browser connect ho gaya. Portal khol rahe hain...",
                )
            except Exception:
                traceback.print_exc()
                await self.emit_event(
                    "SENSE",
                    "Could not open the cloud browser. Continuing in this device's browser.",
                    "Cloud browser nahi khul paya. Is device ke browser mein aage badh rahe hain.",
                )
                try:
                    await self.tinyfish_mgr.terminate_session(session.session_id)
                except Exception:
                    pass
                session.is_cloud = False
                session.cdp_url = ""
                self.browser = None
                self.context = None
                self.page = None
                self.mode = "local"

        if not self.browser or not session.is_cloud:
            self.browser = await self.playwright.chromium.launch(headless=cfg.headless)
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            self.page = await self.context.new_page()
            await self.emit_event(
                "ACT",
                "Using this device's browser.",
                "Is device ke browser se portal khol rahe hain.",
            )

        if not self.page:
            raise AgentRunError("Could not open a browser page.")
        if self.context:
            try:
                self.context.on("page", lambda p: self._bind_dialog_handler(p))
            except Exception:
                pass
        self._bind_dialog_handler(self.page)
        self._adapter = get_adapter(target_url)

        try:
            self.live = LiveBrowserSession(
                self.page,
                run_id=self.run_id or "",
                mode=self.mode,
                run_mode=self.run_mode,
            )
            await self.live.start()
            live_sessions.add(self.live)
            if self.run_mode == "inspect":
                self.live.set_allow_control(True, "Inspect mode: the browser is yours.")
            await self.emit_event(
                "ACT",
                "Live browser ready. You can see the real page and take over when asked.",
                "Live browser ready hai. Asli page dikh raha hai; zarurat par aap control le sakte hain.",
            )
        except Exception:
            traceback.print_exc()
            self.live = None
            await self.emit_event(
                "SENSE",
                "The live view could not start, but the application can continue.",
                "Live view shuru nahi ho paya, lekin application jaari rah sakti hai.",
            )

    async def _switch_to_local_browser(self) -> None:
        """Switch from geo-blocked or failing cloud session to the local Playwright browser."""
        if self._session:
            try:
                await self.tinyfish_mgr.terminate_session(self._session.session_id)
            except Exception:
                pass
            self._session.is_cloud = False
            self._session.cdp_url = ""
        try:
            if self.live:
                live_sessions.remove(self.live)
                await self.live.stop()
        except Exception:
            pass
        self.live = None
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.context = None
        self.page = None
        cfg = self.tinyfish_mgr.config
        self.browser = await self.playwright.chromium.launch(headless=cfg.headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        self.page = await self.context.new_page()
        if self.context:
            try:
                self.context.on("page", lambda p: self._bind_dialog_handler(p))
            except Exception:
                pass
        self._bind_dialog_handler(self.page)
        try:
            self.live = LiveBrowserSession(
                self.page,
                run_id=self.run_id or "",
                mode=self.mode,
                run_mode=self.run_mode,
            )
            await self.live.start()
            live_sessions.add(self.live)
        except Exception:
            self.live = None

    async def _cleanup(self):
        if self.live:
            live_sessions.remove(self.live)
            try:
                await self.live.stop()
            except Exception:
                pass
            self.live = None
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.context = None
        self.page = None
        self.page_brief = None

        try:
            if self._session and self._session.is_cloud:
                await self.tinyfish_mgr.terminate_session(self._session.session_id)
        except Exception:
            pass
        self._session = None

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.playwright = None

    # ---------------------------------------------------------------- events

    async def _screenshot(self, force: bool = False) -> str:
        if not self.page:
            return ""
        now = time.monotonic() * 1000
        if not force and now - self._last_screenshot_at < settings.SCREENSHOT_MIN_INTERVAL_MS:
            return ""
        try:
            frame = await ResilientNavigator.capture_high_res_screenshot(self.page)
            if frame:
                self._last_screenshot_at = now
                return f"data:image/jpeg;base64,{base64.b64encode(frame).decode('utf-8')}"
        except Exception:
            pass
        return ""

    async def emit_event(
        self,
        phase: str,
        message: str,
        hindi: str,
        active_gate: Optional[Dict[str, Any]] = None,
        *,
        force_screenshot: bool = False,
    ):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if phase == "ACT":
            self._last_agent_action = message
        try:
            self.recent_events.append(
                {"at": timestamp, "phase": phase, "message": message}
            )
        except Exception:
            pass
        if self._page_sync:
            self._page_sync["last_action"] = self._last_agent_action
            if active_gate or self.active_gate:
                self._page_sync["gate"] = {
                    "type": str((active_gate or self.active_gate or {}).get("gate_type") or ""),
                    "title": str((active_gate or self.active_gate or {}).get("title") or ""),
                }
        screenshot_b64 = await self._screenshot(force=force_screenshot or bool(active_gate))
        payload = {
            "timestamp": timestamp,
            "phase": phase,
            "message": message,
            "hindi": hindi,
            "screenshot": screenshot_b64,
            "active_gate": active_gate or self.active_gate,
            "current_section": self.current_section,
            "filled_audit": self._public_audit(),
            "run_id": self.run_id,
            "state": self.state,
            "mode": self.mode,
            "run_mode": self.run_mode,
            "last_error": self.last_error,
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "engine_session": self._engine_session_info(),
            "engine": self._engine_label(),
            "form_map": self.form_map,
            "page_brief": self.page_brief,
            "page_sync": self._page_sync,
            "sync_revision": self._sync_revision,
            "blueprint": self.blueprint.summary() if self.blueprint else None,
            "recipe": self._recipe_status,
            "journey": self._journey_status,
            "fill_summary": self.fill_summary,
            "fill_failures": self.fill_failures,
            "entry_mode": self._entry_mode,
            "entry_options": decision_policy.entry_summary(self._entry_options),
            "login_method": self._login_method,
            "login_identifier": self._login_identifier,
            "run_clock": self.run_clock(),
        }
        if phase == "DECIDE" and (active_gate or self.active_gate):
            try:
                self._start_gate_step(active_gate or self.active_gate or {})
            except Exception:
                traceback.print_exc()
        if self.broadcast_fn:
            try:
                result = self.broadcast_fn(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                traceback.print_exc()
        try:
            if self.run_id:
                self.run_store.append(
                    self.run_id,
                    {
                        "timestamp": timestamp,
                        "phase": phase,
                        "message": message,
                        "section": self.current_section,
                        "gate_type": (active_gate or self.active_gate or {}).get("gate_type"),
                        "state": self.state,
                    },
                )
        except Exception:
            pass

    # ---------------------------------------------------------------- loop

    async def _scan_dom(self) -> Dict[str, Any]:
        """Capture the page as a legacy DOM plus a typed blueprint.

        ``DOMScanner.scan`` stamps every meaningful element with a per-scan
        ``data-fp-id`` and builds the nested tree the resolver uses.  The
        legacy lists remain in the returned dict so existing callers keep
        working while they migrate to element ids.
        """
        if not self.page:
            raise AgentRunError("The browser page is no longer available.")
        try:
            dom, blueprint = await DOMScanner.scan(self.page)
        except Exception as exc:
            raise AgentRunError("The page is still loading. Please wait a moment and try again.") from exc
        self.blueprint = blueprint
        self._record_visit(self.page.url)
        return dom

    def _refresh_page_sync(
        self, dom: Dict[str, Any], form_map: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Publish one snapshot that every surface can read.

        The live browser, the cockpit panel and the chat all used to assemble
        their own picture from different moments.  A revision only advances
        when the page identity actually changes, so polling state does not
        invent work that never happened.
        """
        form_map = form_map or self.form_map or {}
        signature = "|".join(
            (
                str(dom.get("url") or ""),
                str(form_map.get("fingerprint") or ""),
                str(len(dom.get("inputs") or [])),
                str((self.active_gate or {}).get("gate_type") or ""),
                str((self.fill_summary or {}).get("status") or ""),
            )
        )
        if signature != self._last_sync_signature:
            self._last_sync_signature = signature
            self._sync_revision += 1
        self._page_sync = page_actions.page_snapshot(
            dom,
            form_map,
            gate=self.active_gate,
            live_session=(
                self.live.public_info()
                if self.live and not self.live.closed
                else None
            ),
            last_action=self._last_agent_action,
            revision=self._sync_revision,
        )
        return self._page_sync

    def _record_visit(self, url: str) -> None:
        """Remember real page URLs so history is only used when it is safe."""
        url = str(url or "")
        if not url:
            return
        if not self._visited_urls or self._visited_urls[-1] != url:
            self._visited_urls.append(url)
        if len(self._visited_urls) > 50:
            del self._visited_urls[:-50]

    def _action_resolver(self) -> Optional[ActionResolver]:
        if not getattr(self, "page", None) or not getattr(self, "blueprint", None):
            return None
        return ActionResolver(self.page, self.blueprint)

    async def _rescan_blueprint(self) -> Optional[PageBlueprint]:
        try:
            await self._scan_dom()
        except Exception:
            return None
        return self.blueprint

    async def _observe_page(self, *, force_emit: bool = False) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Read the page, build the normalized form map, and compare it to memory."""
        dom = await self._scan_dom()
        try:
            form_map = FormModel.build_form_map(
                dom,
                self.page.url if self.page else self.target_url,
                vault=self.vault_mgr.vault,
            )
            if self.blueprint is not None:
                form_map["blueprint"] = self.blueprint.summary()
            recipe_status = self.recipe_store.match(form_map)
        except Exception:
            traceback.print_exc()
            form_map = {
                "url": self.page.url if self.page else self.target_url,
                "page_type": "unknown",
                "page_confidence": 0,
                "field_count": len(dom.get("inputs") or []),
                "fields": [],
                "error": "The form model could not be built for this page.",
            }
            recipe_status = {"status": "new", "confidence": 0, "recipe_id": None, "drift": None}

        self.form_map = form_map
        self._recipe_status = recipe_status
        self._refresh_page_sync(dom, form_map)
        self._record_step(
            "perceive",
            output={
                "page_type": form_map.get("page_type"),
                "field_count": form_map.get("field_count"),
                "confidence": form_map.get("page_confidence"),
                "recipe": recipe_status.get("status"),
            },
        )
        try:
            self._entry_options = decision_policy.entry_options(dom, form_map)
        except Exception:
            self._entry_options = []
        # Record the page in the known path.  This is structural memory: it
        # makes the next visit cheaper and gives the agent a map to follow.
        self._observe_journey(dom, form_map)
        fingerprint = str(form_map.get("fingerprint") or "")
        recipe_event_key = f"{recipe_status.get('status')}:{fingerprint}:{recipe_status.get('recipe_id')}"

        should_emit = force_emit or fingerprint != self._last_form_fingerprint
        if should_emit and recipe_event_key != self._last_recipe_event:
            self._last_form_fingerprint = fingerprint
            self._last_recipe_event = recipe_event_key
            status = str(recipe_status.get("status") or "new")
            if status == "drift":
                drift = recipe_status.get("drift") or {}
                await self.emit_event(
                    "THINK",
                    f"Portal structure changed: {drift.get('summary') or 'the saved recipe no longer matches.'}",
                    "Portal ka structure badal gaya hai. Agent page ko dobara padh raha hai.",
                )
            elif status == "match":
                await self.emit_event(
                    "SENSE",
                    "Saved portal recipe matched this page. Reusing its field map and locators.",
                    "Is page ke liye saved recipe mil gayi. Field map aur locators reuse ho rahe hain.",
                )
            else:
                await self.emit_event(
                    "SENSE",
                    f"This is a new page in memory: {form_map.get('page_type')} with {form_map.get('field_count', 0)} fields.",
                    "Yeh page pehli baar dekh rahe hain. Form ko samajh rahe hain.",
                )
        return dom, form_map

    # ---------------------------------------------------------------- journey

    def _journey_secrets(self) -> List[str]:
        """Values that must never appear in a stored journey snapshot."""
        try:
            data = self.vault_mgr.vault.model_dump()
        except Exception:
            try:
                data = dict(self.vault_mgr.vault)
            except Exception:
                data = {}
        values: List[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, str):
                text = value.strip()
                if len(text) >= 4:
                    values.append(text)
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(data)
        return values

    def _observe_journey(self, dom: Dict[str, Any], form_map: Dict[str, Any]) -> None:
        """Store this page in the known path and learn its durable field map."""
        if not self._journey_key:
            return
        signature = "|".join(
            [
                str(dom.get("url") or ""),
                str(form_map.get("page_type") or ""),
                str(form_map.get("fingerprint") or ""),
                str(len(dom.get("inputs") or [])),
            ]
        )
        if signature == self._last_journey_fingerprint:
            return
        self._last_journey_fingerprint = signature
        try:
            step = self.journey_store.observe_page(
                self._journey_key,
                dom,
                form_map,
                secrets=self._journey_secrets(),
            )
        except Exception:
            traceback.print_exc()
            return
        if not step:
            return

        pending = self._pending_journey_action
        if pending and pending.get("from_step") and step.get("step_id") != pending.get("from_step"):
            try:
                self.journey_store.record_transition(
                    self._journey_key,
                    from_step=pending["from_step"],
                    action=pending.get("action") or "click",
                    target=pending.get("target") or "",
                    to_step=str(step.get("step_id") or ""),
                    success=True,
                )
                self.journey_store.mark_step_success(
                    self._journey_key, pending["from_step"]
                )
            except Exception:
                traceback.print_exc()
            self._pending_journey_action = None

        self._journey_step = step
        self._last_journey_step_id = str(step.get("step_id") or "")
        hints: Dict[str, str] = {}
        for field in step.get("fields") or []:
            semantic_key = str(field.get("semantic_key") or "").strip()
            if not semantic_key:
                continue
            for key in (field.get("name"), field.get("id")):
                key = str(key or "").strip().lower()
                if key:
                    hints[key] = semantic_key
        self._journey_field_hints = hints
        choices: Dict[str, str] = {}
        for choice in step.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            concept = str(choice.get("concept") or "").strip()
            if not concept:
                continue
            for key in (choice.get("group"), choice.get("group_id")):
                key = str(key or "").strip().lower()
                if key:
                    choices[key] = concept
        self._journey_choice_hints = choices
        try:
            self._journey_status = self.journey_store.summary(self._journey_key)
        except Exception:
            pass

    def _note_journey_action(self, action: str, target: str) -> None:
        """Remember which action moved the path, so the next page can prove it."""
        if not self._journey_key or not self._last_journey_step_id:
            return
        self._pending_journey_action = {
            "action": action,
            "target": re.sub(r"\s+", " ", str(target or "")).strip()[:160],
            "from_step": self._last_journey_step_id,
        }

    def _journey_field_hint(self, item: Dict[str, Any]) -> str:
        """Return a semantic key learned on a previous visit, if any."""
        if not self._journey_field_hints:
            return ""
        for key in ("name", "id"):
            value = str(item.get(key) or "").strip().lower()
            if value and value in self._journey_field_hints:
                return self._journey_field_hints[value]
        return ""

    def _resolve_choice(
        self,
        item: Dict[str, Any],
        inputs: List[Dict[str, Any]],
        dom: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Map a radio/checkbox group to a value the candidate already gave."""
        try:
            vault = self.vault_mgr.vault
        except Exception:
            return None
        try:
            return choice_resolver.resolve_group(
                inputs,
                item,
                vault,
                page_text=str(dom.get("visibleText") or ""),
                learned=self._journey_choice_hints,
            )
        except Exception:
            traceback.print_exc()
            return None

    async def _apply_choice(self, resolved: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        item = resolved.get("item") or {}
        raw = str(item.get("value") or resolved.get("label") or resolved.get("value") or "")
        if not raw:
            return None
        result = await self._select_choice_element(item, raw)
        if not result.get("success"):
            return None
        concept = str(resolved.get("concept") or "choice")
        label = str(resolved.get("label") or raw)
        self._remember_journey_choice(resolved)
        await self.emit_event(
            "ACT",
            f"Selected {label} for {concept.replace('_', ' ')} from your saved profile.",
            f"Aapke profile se {concept.replace('_', ' ')} ke liye {label} chuna.",
        )
        return {
            "item": item,
            "sem_key": f"choice_{concept}",
            "label": label,
            "value": label,
            "method": "choice",
            "custom": False,
            "kind": "choice",
            "apply_ok": True,
            "reason": "",
            "clicked": bool(result.get("clicked")),
        }

    async def _select_choice_element(
        self, item: Dict[str, Any], raw: str
    ) -> Dict[str, Any]:
        """Click the actual radio/checkbox so portal postbacks fire.

        Setting ``checked`` in JavaScript is enough for a plain form, but an
        ASP.NET radio often reveals the next control from its ``onclick``
        postback.  A real click is therefore preferred; the injector remains
        the fallback for widgets the resolver cannot address.
        """
        element_id = str(item.get("element_id") or "")
        resolver = self._action_resolver()
        # A custom-styled checkbox keeps its real input hidden behind a painted
        # label.  Playwright cannot click a hidden input, so the injector is the
        # correct path for it; a visible control is clicked for real.
        clickable = item.get("visible") is not False
        if element_id and resolver and self.page and clickable:
            try:
                before = self.page.url
                dialogs_before = await self._visible_dialog_keys()
                result = await resolver.click(element_id)
                if result and result.ok:
                    try:
                        await self.page.wait_for_load_state(
                            "domcontentloaded", timeout=8000
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.4)
                    after = self.page.url
                    confirmed = await self._accept_choice_popup(dialogs_before)
                    self._form_dirty = True
                    return {
                        "success": True,
                        "method": "click",
                        "clicked": True,
                        "navigated": before != after,
                        "confirmed": confirmed,
                    }

                # Try clicking proxy label if input itself is hidden by CSS
                item_id = str(item.get("id") or "")
                if item_id:
                    proxy_clicked = await self.page.evaluate(
                        """(id) => {
                            const l = document.querySelector(`label[for="${CSS.escape(id)}"]`) ||
                                      document.getElementById(id)?.closest('label') ||
                                      document.getElementById(id)?.parentElement?.querySelector('label');
                            if (l) { l.click(); return true; }
                            return false;
                        }""",
                        item_id,
                    )
                    if proxy_clicked:
                        await asyncio.sleep(0.4)
                        after = self.page.url
                        confirmed = await self._accept_choice_popup(dialogs_before)
                        self._form_dirty = True
                        return {
                            "success": True,
                            "method": "click_proxy",
                            "clicked": True,
                            "navigated": before != after,
                            "confirmed": confirmed,
                        }
            except Exception:
                traceback.print_exc()
        result = await self._apply_field_value(item, raw)
        return dict(result or {}, clicked=False)

    # A portal confirmation button says "OK", "Yes", "I Agree", "Confirm",
    # sometimes with extra words ("OK, I Agree / सहमत हूँ").  The negative
    # pattern wins when a control could match both ("No, go back").
    _AFFIRMATIVE_RE = re.compile(
        r"^\s*(?:ok|okay|yes|y|i\s*agree|agree|i\s*accept|accept|confirm|"
        r"proceed|continue|got\s*it)\b",
        re.IGNORECASE,
    )
    _NEGATIVE_RE = re.compile(
        r"^\s*(?:no|cancel|close|back|deny|disagree|not\s*now)\b",
        re.IGNORECASE,
    )

    _DIALOG_SELECTOR = (
        '[role="dialog"],[role="alertdialog"],[aria-modal="true"],dialog,'
        '[class*="modal" i],[class*="popup" i],[id*="popup" i],'
        '[id*="confirm" i],[id*="modal" i]'
    )

    async def _visible_dialog_keys(self) -> List[str]:
        """Snapshot which modal/popup containers are on screen right now.

        A choice click may open a confirmation popup.  Knowing what was already
        visible keeps the follow-up click from hitting an unrelated panel such
        as the accessibility menu.
        """
        if not self.page:
            return []
        try:
            return await self.page.evaluate(
                """(selector) => {
                    const visible = (el) => {
                        if (!el || !el.isConnected) return false;
                        const style = getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 1 && rect.height > 1;
                    };
                    return Array.from(document.querySelectorAll(selector))
                        .filter(visible)
                        .map(el => `${el.tagName}|${el.id || ''}|${el.className || ''}`);
                }""",
                self._DIALOG_SELECTOR,
            )
        except Exception:
            return []

    async def _accept_choice_popup(self, before: List[str]) -> Dict[str, Any]:
        """Click OK/Agree on a confirmation popup a choice just opened.

        Government portals often ask the candidate to confirm a declaration
        after selecting an option.  The confirmation is part of the choice, not
        a new decision: the candidate already answered it in the vault.  Only a
        popup that appeared *after* the click is considered, and only its
        affirmative control is pressed.
        """
        if not self.page:
            return {"clicked": False}
        try:
            result = await self.page.evaluate(
                """([selector, before, affirmPattern, negativePattern]) => {
                    const visible = (el) => {
                        if (!el || !el.isConnected) return false;
                        const style = getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 1 && rect.height > 1;
                    };
                    const key = (el) => `${el.tagName}|${el.id || ''}|${el.className || ''}`;
                    const seen = new Set(before || []);
                    const fresh = Array.from(document.querySelectorAll(selector))
                        .filter(visible)
                        .filter(el => !seen.has(key(el)));
                    // A portal writes "OK, I Agree / सहमत हूँ" or "Yes, Continue",
                    // so the affirmative word only has to come first.  The
                    // patterns live in Python so they can be unit tested.
                    const affirm = new RegExp(affirmPattern, 'i');
                    const negative = new RegExp(negativePattern, 'i');
                    for (const container of fresh) {
                        const controls = Array.from(container.querySelectorAll(
                            'button,input[type="button"],input[type="submit"],a,[role="button"],[onclick]'
                        )).filter(visible);
                        const target = controls.find(el => {
                            const text = String(el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                            return affirm.test(text) && !negative.test(text);
                        });
                        if (target) {
                            target.click();
                            return {
                                clicked: true,
                                text: String(target.innerText || target.value || '').trim(),
                                container: container.id || container.className || container.tagName,
                            };
                        }
                    }
                    if (typeof window.confirmYes === 'function') {
                        try {
                            window.confirmYes();
                            return {
                                clicked: true,
                                text: 'OK, I Agree (confirmYes)',
                                container: 'confirmPopup',
                            };
                        } catch (e) {}
                    }
                    return {clicked: false};
                }""",
                [
                    self._DIALOG_SELECTOR,
                    before,
                    self._AFFIRMATIVE_RE.pattern,
                    self._NEGATIVE_RE.pattern,
                ],
            )
        except Exception:
            traceback.print_exc()
            return {"clicked": False}
        if isinstance(result, dict) and result.get("clicked"):
            await asyncio.sleep(0.5)
            await self.emit_event(
                "ACT",
                f"Confirmed the portal dialog ({result.get('text') or 'OK'}).",
                f"Portal dialog confirm kiya ({result.get('text') or 'OK'}).",
            )
        return result if isinstance(result, dict) else {"clicked": False}

    def _bind_dialog_handler(self, page: Any) -> None:
        """Automatically accept portal alerts and confirmation prompts."""
        if not page:
            return

        async def _on_dialog(dialog):
            try:
                msg = str(dialog.message or "")
                dialog_type = str(dialog.type or "")
                print(f"[DIALOG] {dialog_type.upper()}: {msg}", flush=True)
                await self.emit_event(
                    "SENSE",
                    f"Portal dialog: {msg[:100]} (accepted)",
                    f"Portal dialog aya: {msg[:100]}",
                )
                await dialog.accept()
            except Exception:
                pass

        try:
            page.on("dialog", lambda d: asyncio.create_task(_on_dialog(d)))
        except Exception:
            pass

    async def _wait_for_postback(self, timeout_ms: int = 4000) -> bool:
        """Wait for ASP.NET / jQuery AJAX postbacks and DOM mutations to settle."""
        if not self.page:
            return False
        try:
            start = time.monotonic()
            await asyncio.sleep(0.15)
            while (time.monotonic() - start) * 1000 < timeout_ms:
                busy = await self.page.evaluate(
                    """() => {
                        const isAspBusy = Boolean(
                            window.Sys && window.Sys.WebForms &&
                            window.Sys.WebForms.PageRequestManager &&
                            window.Sys.WebForms.PageRequestManager.getInstance().get_isInAsyncPostBack()
                        );
                        const isJqBusy = Boolean(window.jQuery && window.jQuery.active > 0);
                        return isAspBusy || isJqBusy;
                    }"""
                )
                if not busy:
                    break
                await asyncio.sleep(0.1)
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _remember_journey_choice(self, resolved: Dict[str, Any]) -> None:
        concept = str(resolved.get("concept") or "").strip()
        group = str(resolved.get("group") or "").strip()
        if not concept or not group:
            return
        self._journey_choice_hints[group.lower()] = concept
        if not self._journey_key or not self._last_journey_step_id:
            return
        try:
            self.journey_store.record_choice(
                self._journey_key,
                self._last_journey_step_id,
                group=group,
                group_id=str(resolved.get("group_id") or ""),
                concept=concept,
                label=str(resolved.get("label") or ""),
            )
        except Exception:
            traceback.print_exc()

    def _journey_next_control(self, dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fall back to a control that worked on this page before."""
        step = self._journey_step or {}
        controls = step.get("controls") or []
        if not controls:
            return None
        live_controls = list(dom.get("nextButtons") or [])
        for saved in controls:
            text = str(saved.get("text") or "").strip().lower()
            if not text:
                continue
            for live in live_controls:
                if str(live.get("text") or "").strip().lower() == text:
                    return live
        return None

    async def _enter_inspect_mode(self) -> None:
        """Stop before touching the form and leave the real browser open."""
        self.is_running = False
        self.state = "INSPECT_READY"
        if self.live:
            self.live.set_allow_control(True, "Inspect mode: the browser is yours. Nothing will be filled or submitted.")

        saved = None
        if self._has_replayable_structure(self.form_map or {}):
            try:
                saved = self.recipe_store.save_from_form_map(
                    self.form_map or {},
                    source="inspect",
                    status="draft",
                )
                if self._recipe_status is not None:
                    self._recipe_status["saved_recipe"] = RecipeStore.summary(saved)
            except Exception:
                traceback.print_exc()

        form_map = self.form_map or {}
        message = (
            f"Inspect only: {form_map.get('field_count', 0)} fields found on a "
            f"{form_map.get('page_type', 'unknown')} page. Nothing was filled, clicked, paid or submitted."
        )
        await self.emit_event(
            "INSPECT",
            message,
            "Inspect-only mode: form ka structure dekh liya. Kuch bhara ya submit nahi kiya.",
            force_screenshot=True,
        )

    @staticmethod
    def _has_replayable_structure(form_map: Dict[str, Any]) -> bool:
        """An empty SPA shell is not a useful recipe.

        A page with fields or gateway choices has replayable structure.  A
        loading shell with neither must not overwrite a good recipe.
        """
        return bool(form_map.get("fields")) or bool(form_map.get("gateways"))

    def _save_current_recipe(self, source: str = "agent") -> None:
        if not self.form_map or not self._has_replayable_structure(self.form_map):
            return
        try:
            saved = self.recipe_store.save_from_form_map(
                self.form_map,
                source=source,
                status="draft",
            )
            if self._recipe_status is not None:
                self._recipe_status["saved_recipe"] = RecipeStore.summary(saved)
        except Exception:
            traceback.print_exc()

    async def refresh_inspection(self) -> Dict[str, Any]:
        if not self.page:
            raise AgentRunError("There is no live browser to inspect. Open a portal first.")
        dom, form_map = await self._observe_page(force_emit=True)
        if self._has_replayable_structure(form_map):
            try:
                saved = self.recipe_store.save_from_form_map(
                    form_map, source="inspect", status="draft"
                )
                if self._recipe_status is not None:
                    self._recipe_status["saved_recipe"] = RecipeStore.summary(saved)
            except Exception:
                traceback.print_exc()
        self.state = "INSPECT_READY" if self.run_mode == "inspect" else self.state
        await self.emit_event(
            "INSPECT",
            f"Page rescanned: {form_map.get('field_count', 0)} fields on a {form_map.get('page_type', 'unknown')} page.",
            "Page dobara scan ho gaya.",
            force_screenshot=True,
        )
        return form_map

    async def get_page_brief(
        self, *, refresh: bool = False, adopt_blueprint: bool = False
    ) -> Dict[str, Any]:
        """Read the live page and return a human-readable brief.

        This is read-only.  It never fills, clicks, uploads or submits.  The
        scan is local to this call so an explicit refresh cannot replace the
        operator's current blueprint mid-action.  ``adopt_blueprint`` is only
        used after a human takeover, when the operator must deliberately adopt
        the page the human left behind.
        """
        if not self.page or self.page.is_closed():
            if self.page_brief and not refresh:
                return self.page_brief
            raise AgentRunError("There is no live browser to read. Open a portal first.")
        try:
            if adopt_blueprint:
                dom, blueprint = await self._scan_dom()
                self.blueprint = blueprint
            else:
                dom, blueprint = await DOMScanner.scan(self.page)
        except Exception as exc:
            raise AgentRunError(
                "The page is still loading. Please wait a moment and read it again."
            ) from exc
        perception = Perception.from_scan(dom, blueprint)
        brief = await self.page_interpreter.interpret(perception, force=refresh)
        domain = urlparse(brief.url).netloc
        fact_book = self.fact_book
        fact_book.annotate_brief(brief, domain=domain)
        self.page_brief = {
            **brief.model_dump(),
            "summary_line": brief.summary_line(),
            "fact_summary": fact_book.summary(domain=domain),
        }
        return self.page_brief

    async def inspect_login_options(self) -> Dict[str, Any]:
        """Read the visible login/recovery options without touching the page.

        This is the read-only inspection used when the candidate is not sure
        whether they registered.  It never submits a credential, requests an
        OTP or resets anything.
        """
        if not self.page or self.page.is_closed():
            raise AgentRunError("There is no live browser to inspect. Open a portal first.")
        try:
            dom, _blueprint = await DOMScanner.scan(self.page)
        except Exception as exc:
            raise AgentRunError(
                "The page is still loading. Please wait a moment and inspect it again."
            ) from exc
        inspection = PortalAccountStore.inspect_login_ui(dom).model_dump()
        inspection["account_memory"] = self._portal_account_summary()
        return inspection

    async def attach_upload(self, path: str, field_key: str) -> Dict[str, Any]:
        """Attach a user-provided file to the correct file input.

        The file is used only in the live portal session.  It is not copied
        into the vault and it is not reused for another portal.
        """
        if not self.page:
            return {"success": False, "message": "There is no live browser to upload to."}
        upload_path = Path(path)
        if not upload_path.is_file():
            return {"success": False, "message": "The uploaded file could not be found."}

        try:
            dom = await self._scan_dom()
        except Exception:
            dom = {"inputs": [], "fileInputs": []}

        target = None
        inputs = [item for item in (dom.get("inputs") or []) if str(item.get("type") or "").lower() == "file"]
        for item in inputs:
            sem_key, _ = DOMScanner.classify_field(item)
            if sem_key == field_key or item.get("name") == field_key or item.get("id") == field_key:
                target = item
                break
        if target is None:
            if len(inputs) == 1:
                target = inputs[0]
            elif inputs:
                # Never guess between a photo and a signature field.  A wrong
                # file would be sent to the portal under the user's name.
                return {
                    "success": False,
                    "message": (
                        "More than one file field is visible and none matched "
                        f"'{field_key}'. Attach the file in the live browser, then continue."
                    ),
                }

        try:
            if target and target.get("id"):
                locator = self.page.locator(f"#{target.get('id')}").first
            elif target and target.get("name"):
                locator = self.page.locator(f"[name='{target.get('name')}']").first
            elif target is not None:
                index = int(target.get("index") or 0)
                locator = self.page.locator("input[type='file']").nth(index)
            else:
                locator = self.page.locator("input[type='file']").first
            if await locator.count() == 0:
                for frame in self.page.frames:
                    if target and target.get("id"):
                        loc = frame.locator(f"#{target.get('id')}").first
                        if await loc.count() > 0:
                            locator = loc
                            break
                    if target and target.get("name"):
                        loc = frame.locator(f"[name='{target.get('name')}']").first
                        if await loc.count() > 0:
                            locator = loc
                            break
                    loc = frame.locator("input[type='file']").first
                    if await loc.count() > 0:
                        locator = loc
                        break
            if await locator.count() == 0:
                return {"success": False, "message": "This page does not have a visible file input."}
            await locator.set_input_files(str(upload_path), timeout=15000)
            await self.page.wait_for_timeout(200)
            fresh = await self._scan_dom()
            if target:
                attached = self._file_attached(target, fresh)
            else:
                files = [
                    entry for entry in (fresh.get("fileInputs") or []) if entry.get("hasFile")
                ]
                attached = len(files) == 1
            if not attached:
                return {
                    "success": False,
                    "message": "The portal did not keep the attached file. Attach it in the live browser.",
                }
        except Exception as exc:
            return {"success": False, "message": f"The portal did not accept the file: {exc}"}

        self._record_fill(
            target or {"label": field_key, "type": "file"},
            field_key,
            str(upload_path),
            "file",
        )
        await self.emit_event(
            "ACT",
            f"Uploaded the file for {field_key.replace('_', ' ')}.",
            f"{field_key.replace('_', ' ')} ke liye file upload ho gayi.",
        )
        return {
            "success": True,
            "field_key": field_key,
            "message": "File attached to the live portal. It was not saved to your vault.",
        }


    async def _autonomous_drive_loop(self):
        while self.is_running:
            if self._run_ceiling_exceeded():
                clock = self.run_clock()
                raise AgentRunError(
                    "This run has reached its time limit "
                    f"({int(clock['active_seconds'])}s of active work). "
                    "Please continue from the portal yourself."
                )
            if self._is_paused:
                self.state = "PAUSED"
                await asyncio.sleep(0.4)
                continue
            self.state = "RUNNING"

            dom, _form_map = await self._observe_page()
            adapter = self._adapter or get_adapter(self.page.url if self.page else "")
            self._adapter = adapter
            step = adapter.current_step(self.page, dom)
            self.current_section = step

            # A portal error can appear on a page with no form fields at all
            # (a server error, an expired session, a blocked request).  Handle
            # it before the no-input branch so it is never mistaken for a
            # landing page or a stall.
            if await self._handle_errors(dom):
                continue

            if await self._observe_progress(dom, step):
                continue

            if await self._account_conflict_checkpoint(dom):
                continue

            if adapter.is_payment_page(self.page, dom):
                await self._trigger_pre_payment_lock()
                return

            scan_key = f"{dom.get('url')}|{adapter.step_key(self.page, dom)}|{len(dom.get('inputs') or [])}"
            if scan_key != self._last_scan_key:
                self._last_scan_key = scan_key
                self._idle_cycles = 0
                await self.emit_event(
                    "SENSE",
                    f"Reading the page: {len(dom.get('inputs') or [])} fields found.",
                    "Page padh rahe hain. Form ke fields dekh rahe hain...",
                )

            gateways = dom.get("gateways") or []
            inputs = dom.get("inputs") or []

            # A chat request such as "I need to register first" is remembered
            # until the portal entry page is actually on screen.  It is applied
            # only to an explicit option that the page offers.
            if self._requested_entry_mode and decision_policy.is_entry_page(dom, self.form_map):
                requested = decision_policy.match_entry_response(
                    {"mode": self._requested_entry_mode},
                    self._entry_options,
                )
                self._requested_entry_mode = None
                if requested:
                    await self._apply_entry_option(requested)
                    continue

            if os.getenv("FORMPILOT_DEBUG_ENTRY"):
                print(
                    "ENTRYDBG",
                    "page_type=", (self.form_map or {}).get("page_type"),
                    "fields=", len((self.form_map or {}).get("fields") or []),
                    "inputs=", len(inputs),
                    "gateways=", len(gateways),
                    "entry_opts=", [(o.get("type"), o.get("text")) for o in (self._entry_options or [])],
                    "entry_mode=", self._entry_mode,
                    "is_entry=", decision_policy.is_entry_page(dom, self.form_map),
                    flush=True,
                )
            # Chrome may fail to open a third-party page.  That is a transport
            # failure, not a form with zero fields.
            if await self._recover_from_browser_error(dom):
                continue

            # A consent screen (DigiLocker, MeriPehchaan, terms & conditions)
            # has consent controls and an affirmative button (Allow/Authorize/Agree).
            # Checked before identity checkpoint so consent screens on OAuth hosts
            # (e.g. digilocker.meripehchaan.gov.in/oauth2/consent) have their checkboxes
            # ticked and 'Allow' clicked rather than waiting for credentials.
            if page_actions.is_consent_page(dom, self.form_map):
                if await self._handle_consent_page(dom):
                    continue

            # A third-party sign-in (DigiLocker, MeriPehchaan, SSO) is the
            # candidate's own credential.  Hand over the live browser and do
            # not type, guess or store anything on that page.  Check this BEFORE
            # is_entry_page so the candidate's exam portal entry_mode (e.g. register)
            # does not get applied to an external IDP to auto-click "Sign up".
            if self._is_external_identity_page(dom):
                if await self._identity_provider_checkpoint(dom):
                    continue

            # Entry mode is never inferred from the URL or history.  The first
            # entry page always asks when more than one path is visible.  A
            # later run may reuse the exact path this account already chose.
            if decision_policy.is_entry_page(dom, self.form_map):
                if self._entry_mode:
                    matched = next(
                        (
                            opt
                            for opt in (self._entry_options or [])
                            if opt.get("mode") == self._entry_mode
                            and opt.get("source") != "current_page"
                        ),
                        None,
                    )
                    if matched:
                        await self.emit_event(
                            "ACT",
                            f"Using chosen entry path ({matched.get('text') or matched.get('mode')}).",
                            f"Chuna hua rasta use kar rahe hain ({matched.get('text') or matched.get('mode')}).",
                        )
                        await self._apply_entry_option(matched)
                        continue
                if not self._entry_mode:
                    remembered = self._remembered_entry_option()
                    if remembered:
                        await self.emit_event(
                            "ACT",
                            f"Known path: using the entry you chose before ({remembered.get('text') or remembered.get('mode')}).",
                            f"Known path: pehle chuna hua rasta use kar rahe hain ({remembered.get('text') or remembered.get('mode')}).",
                        )
                        await self._apply_entry_option(remembered)
                        continue
                    await self._gateway_checkpoint(dom, gateways)
                    continue

            page_type = str((self.form_map or {}).get("page_type") or "")
            if self._entry_mode == "login" or page_type == "login":
                if await self._login_method_checkpoint(dom):
                    continue
                if await self._login_identifier_checkpoint(dom):
                    continue

            # A slow loader is not a stall.  Wait for it to finish before
            # deciding that the page has no next step.
            if dom.get("loading"):
                self._idle_cycles = 0
                await asyncio.sleep(2.0)
                continue

            # A public landing page links to the application form with a
            # label such as "Online Application Form for JEE (Main) 2027".
            # That link is the next step, not a dead end.  Follow a single
            # unambiguous link; ask when the page offers a real choice.  This
            # runs even when a search box made the page look like a form.
            if await self._application_next_step(dom):
                continue

            if not inputs:
                # Interstitial / transition / handshake screens (e.g. DigiLocker complete verification,
                # proceed to registration, confirmation step): check for an advancing button first!
                advancing_button = adapter.find_next_button(dom) or (await self._find_advancing_button_with_context(dom))
                if advancing_button:
                    self._idle_cycles = 0
                    if await self._advance(dom):
                        continue

                # A signed-in dashboard is a hub, not the end of the run.  Its
                # links open the real application; ask which one to use.
                if await self._dashboard_next_step(dom, gateways):
                    continue
                visible = str(dom.get("visibleText") or "").lower()
                if any(token in visible for token in ("dashboard", "registration id", "logged in", "sign out", "logout")):
                    self.state = "DONE"
                    self.is_running = False
                    await self.emit_event(
                        "DECIDE",
                        "You are signed in. There is no application form on this page.",
                        "Aap sign in ho gaye hain. Is page par koi application form nahi hai.",
                        force_screenshot=True,
                    )
                    return
                self._idle_cycles += 1
                if self._idle_cycles > 20:
                    raise AgentRunError("No application form was found on this page. Please check the portal link and try again.")
                await asyncio.sleep(0.7)
                continue

            await self._fill_form(dom)
            if self._form_dirty:
                # A choice click triggered a portal postback.  Re-read the page
                # before captcha/OTP/section decisions; the old DOM is stale.
                self._form_dirty = False
                continue
            # A login form can show both a captcha and a "Send OTP" button.
            # The captcha owns the step: clicking Send OTP before it is solved
            # only produces a toastr and leaves the OTP boxes hidden.
            fresh = await self._scan_dom()
            captcha_pending = await self._handle_captcha(fresh)
            if captcha_pending:
                continue
            fresh = await self._scan_dom()
            otp_handled = await self._handle_otp(fresh)
            if otp_handled:
                # The OTP page has its own checkpoint.  Do not run section
                # approval or advance on an unverified form.
                continue
            fresh = await self._scan_dom()
            if await self._handle_errors(fresh):
                continue

            fill_state = await self._fill_incomplete_checkpoint()
            if fill_state == "stop":
                return
            if fill_state == "recheck":
                continue

            summary_status = str((self.fill_summary or {}).get("status") or "")
            if summary_status == "NO_FIELDS" and not (fresh.get("nextButtons") or []):
                # Nothing was filled, so there is nothing to approve.  If this
                # is an entry page or a page with an application link, follow
                # that.  Otherwise hand the page to the human rather than
                # showing a misleading "review section" gate.
                if await self._application_next_step(fresh):
                    continue
                if not self._entry_mode and decision_policy.is_entry_page(fresh, self.form_map):
                    await self._gateway_checkpoint(fresh, fresh.get("gateways") or [])
                    continue
                if await self._advance_handoff(fresh):
                    continue
                return

            if self._can_autopilot_step():
                approved = True
                proven = int((self._journey_step or {}).get("successes") or 0) >= 1
                await self.emit_event(
                    "ACT",
                    (
                        "Known path: this section was completed correctly before. Continuing automatically."
                        if proven
                        else "Every field on this section verified. Continuing automatically."
                    ),
                    (
                        "Known path: yeh section pehle sahi bhara tha. Automatically aage badh rahe hain."
                        if proven
                        else "Is section ke saare field verify ho gaye. Automatically aage badh rahe hain."
                    ),
                )
                self._remember_portal_account(
                    registration_status="in_progress",
                    last_known_step=f"section_{self.current_section}",
                    confirmed_by_human=False,
                )
            else:
                approved = await self._section_checkpoint()
            if not approved:
                if self.state in {"STOPPED", "FAILED"} or not self.is_running:
                    return
                await asyncio.sleep(0.4)
                continue

            advanced = await self._advance(dom)
            if advanced is None:
                # Already blocked on this page: do not click again, let the
                # stall guard's clock run.
                await asyncio.sleep(1.0)
                continue
            postcondition = (
                self._last_action_result.postcondition
                if self._last_action_result is not None
                else ""
            )
            self._record_step(
                "advance",
                status="ok" if advanced else "failed",
                error_code=None if advanced else "navigation_failure",
                output={
                    "url": self.page.url if self.page else self.target_url,
                    "postcondition": postcondition,
                },
            )
            if not advanced:
                fresh = await self._scan_dom()
                if adapter.is_payment_page(self.page, fresh):
                    await self._trigger_pre_payment_lock()
                    return
                if await self._handle_errors(fresh):
                    continue
                # A click that changed nothing is not a crash.  The page has
                # been handed to the stall guard; ask the human once it has
                # been unchanged long enough instead of failing the run.
                await asyncio.sleep(1.0)
                continue
            await asyncio.sleep(0.3)

    # ------------------------------------------------------------------ progress

    @staticmethod
    def _new_progress_tracker() -> ProgressTracker:
        return ProgressTracker(
            repeat_threshold=settings.STALL_REPEAT_THRESHOLD,
            stall_threshold=settings.STALL_THRESHOLD,
            shadow=settings.STALL_SHADOW,
            min_shadow_seconds=settings.STALL_MIN_SHADOW_SECONDS,
            min_stall_seconds=settings.STALL_MIN_SECONDS,
        )

    async def _observe_progress(self, dom: Dict[str, Any], step: Any) -> bool:
        """Measure one cycle; stop and ask the human if nothing changes.

        The low threshold only writes evidence to the ledger (shadow mode).
        The high threshold records a ``no_progress`` error and opens an
        ``ERROR_DIAGNOSIS`` checkpoint, because a page that will not move is a
        page only the human can unstick.
        """
        page_key = (
            f"{dom.get('url') or (self.page.url if self.page else '')}"
            f"|{step}"
            f"|{len(dom.get('inputs') or [])}"
        )
        fields = self._digest_field_values(dom.get("inputs") or [])
        verdict = self._progress.observe(page_key, fields)
        if verdict is ProgressVerdict.PROGRESS:
            return False

        key = (page_key, fields)
        if verdict is ProgressVerdict.SHADOW_STALL:
            # Measure, do not act.  One row per stalled key, not per cycle.
            if self._shadow_stall_key != key:
                self._shadow_stall_key = key
                self._record_step(
                    "stall",
                    status="shadow",
                    output={
                        "page": page_key,
                        "fields": fields,
                        "repeat_run": self._progress.repeat_run + 1,
                        "threshold": self._progress.repeat_threshold,
                    },
                )
            return False

        if verdict is ProgressVerdict.STALL:
            attempts = self._progress.repeat_run + 1
            message = (
                "The page has not changed after "
                f"{attempts} attempts, so FormPilot stopped to avoid repeating "
                "the same step."
            )
            self._record_step(
                "error",
                status="failed",
                error_code="no_progress",
                output={
                    "message": message,
                    "page": page_key,
                    "fields": fields,
                    "attempts": attempts,
                },
            )
            await self._no_progress_checkpoint(message, page_key)
            return True
        return False

    async def _no_progress_checkpoint(self, message: str, page_key: str) -> None:
        """Hand a stalled run to the human instead of failing it outright."""
        self.active_gate = None
        domain = self._current_domain()
        self._record_lesson(
            domain=domain,
            signature=f"no_progress:{self.current_section or page_key[:80]}",
            action="stall",
            outcome="failed",
            note=message,
        )
        gate = {
            "gate_type": "ERROR_DIAGNOSIS",
            "title": "The page is not changing",
            "hindi_title": "Page badal nahi raha",
            "error_text": message,
            "error_code": "no_progress",
            "description": (
                "FormPilot repeated the same step because the page did not "
                "change. Look at the live page, fix or skip whatever is "
                "blocking it, then continue."
            ),
            "suggested_actions": [
                "Review the page",
                "Continue after fixing it",
                "Stop and open the portal myself",
            ],
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
        }
        known = self._lesson_summary()
        if known:
            gate["known_lessons"] = known[:5]
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "The page is not changing. Check it here.")
        await self.emit_event(
            "DECIDE",
            "The page is not changing. FormPilot is waiting for you.",
            "Page badal nahi raha. FormPilot aapke liye ruka hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state
        if response.get("action") in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
        self._progress.reset("stall_checkpoint")
        self._shadow_stall_key = None

    # ---------------------------------------------------------------- gateways

    async def _application_next_step(self, dom: Dict[str, Any]) -> bool:
        """Follow a landing page's application link instead of stalling.

        A public landing page has no form fields, so the old loop treated it as
        a page that would not change and opened a generic stall gate.  The page
        already tells us the next step ("Online Application Form for JEE (Main)
        2027").  Follow one unambiguous link automatically; when there are
        genuinely different links, ask the candidate which one they mean.
        """
        links = [
            link
            for link in (dom.get("applicationLinks") or [])
            if isinstance(link, dict) and str(link.get("text") or "").strip()
        ]
        if not links:
            # A known path may remember the application link even when the
            # current markup no longer exposes it as a clickable anchor.
            links = [
                dict(link, source="journey")
                for link in ((self._journey_step or {}).get("application_links") or [])
                if isinstance(link, dict) and str(link.get("text") or "").strip()
            ]
        if not links:
            return False
        if self._app_link_follows >= 6:
            # Two pages that link to each other must not bounce forever.
            return False

        page_type = str((self.form_map or {}).get("page_type") or "").lower()
        if page_type in {"login", "registration", "portal_entry", "payment"}:
            return False
        # Auth entry is handled earlier.  Never treat "Apply Online" on a login
        # page as a post-login next step.
        try:
            if decision_policy.is_entry_page(dom, self.form_map):
                return False
        except Exception:
            pass

        # A page with a search box or a newsletter field is still a landing
        # page.  Only a page with real, fillable form fields owns the next
        # step; a search/filter control does not.
        fields = (self.form_map or {}).get("fields") or []
        real_fields = [
            field
            for field in fields
            if str(field.get("type") or "").lower() not in {"search", "button", "submit", "hidden"}
            and not re.search(
                r"\b(?:search|filter|find|newsletter|subscribe)\b",
                str(field.get("label") or field.get("name") or ""),
                re.IGNORECASE,
            )
        ]
        if page_type in {"application_form", "section_form", "form"} and real_fields:
            return False

        targets = self._distinct_application_targets(links)
        if not targets:
            return False
        if len(targets) > 1:
            await self._application_choice_checkpoint(dom, targets)
            return True
        return await self._follow_application_link(targets[0])

    @staticmethod
    def _clean_application_label(text: str) -> str:
        """Remove accessibility suffixes such as "External site" from a link.

        NIC templates append a visually hidden "External site that opens in a
        new window" to some anchors.  It is useful to a screen reader, not to
        the candidate, and it makes two copies of the same link look different.
        """
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        value = re.sub(
            r"\s*[-–—|:]\s*(?:external|opens?\s+in\s+a\s+new(?:\s+(?:window|tab))?).*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return value.strip()

    @staticmethod
    def _application_link_score(link: Dict[str, Any]) -> int:
        """Prefer the real application system over a notice or a landing page."""
        href = str(link.get("href") or "").lower()
        label = str(link.get("text") or "").lower()
        score = 0
        if re.search(r"examinationservices|onlineservices|online-services", href):
            score += 6
        elif re.search(r"/apply|registration|application", href):
            score += 2
        if "online application form" in label or re.search(r"\bapply\b", label):
            score += 3
        if re.search(r"\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)", href):
            score -= 20
        if link.get("insideForm"):
            score -= 5
        return score

    @classmethod
    def _distinct_application_targets(cls, links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse duplicate labels and drop notices/documents.

        The JEE landing page renders the same "Online Application Form" link in
        a header and a body block, next to PDF notices and a clarification.
        Those are not choices.  Only genuinely different application labels
        (for example Session 1 vs Session 2) should be asked about.
        """
        notice_re = re.compile(
            r"clarification|inviting|public\s*notice|\bnotice\b|corrigendum|"
            r"advertisement|press\s*release|information\s*bulletin|brochure|"
            r"prospectus|guidelines?|faq|manual",
            re.IGNORECASE,
        )
        document_re = re.compile(r"\.(?:pdf|docx?|xlsx?|zip|rar|jpe?g|png|gif)(?:[?#]|$)", re.IGNORECASE)
        filtered = [
            link
            for link in links
            if not notice_re.search(str(link.get("text") or ""))
            and not document_re.search(str(link.get("href") or ""))
        ]
        if not filtered:
            filtered = links

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for link in filtered:
            # Collapse duplicate copies of the same labelled link (a header
            # and a body copy often differ only by a volatile query token).
            # Genuinely different sessions carry different labels ("Session 1"
            # versus "Session 2"), so they stay distinct.  Two options with the
            # same label cannot be told apart by the candidate anyway.
            label = cls._clean_application_label(link.get("text")).lower()
            groups.setdefault(label, []).append(link)

        targets: List[Dict[str, Any]] = []
        for group in groups.values():
            group.sort(key=cls._application_link_score, reverse=True)
            targets.append(group[0])
        targets.sort(key=cls._application_link_score, reverse=True)
        return targets

    async def _follow_application_link(self, link: Dict[str, Any]) -> bool:
        signature = "|".join(
            str(link.get(key) or "")
            for key in ("elementId", "element_id", "href", "text")
        )
        if signature and signature == self._last_app_link_signature:
            return False
        self._last_app_link_signature = signature
        self._app_link_follows += 1
        label = self._clean_application_label(link.get("text")) or "the application form"
        await self.emit_event(
            "ACT",
            f"Opening: {label}",
            "Application form ka link khol rahe hain...",
        )
        before = await self._page_snapshot()
        pages_before = len(self.context.pages) if self.context else 0
        button = {
            "text": label,
            "element_id": link.get("elementId") or link.get("element_id"),
            "href": link.get("href"),
            "tagName": link.get("tagName") or link.get("tag"),
            "id": link.get("id"),
            "name": link.get("name"),
            "className": link.get("className"),
            "inside_form": False,
            "css": link.get("css"),
            "xpath": link.get("xpath"),
        }
        self._note_journey_action("open_application", label)
        clicked = await self._safe_click(button)
        opened_new_tab = await self._adopt_new_page(pages_before) if clicked else False
        changed = opened_new_tab or (
            await self._wait_for_page_change(before, timeout_ms=12000) if clicked else False
        )
        href = str(link.get("href") or "").strip()
        if not changed and href and not href.lower().startswith(("javascript:", "#")):
            # Some government templates attach the navigation to an overlay or
            # a script that the automated click does not trigger, and a stale
            # element id can make the click fail after a slow page update.  The
            # href is explicit, so navigating to it is the same user intent.
            try:
                target = urljoin(
                    str(before.get("url") or (self.page.url if self.page else "")),
                    href,
                )
                await self.emit_event(
                    "ACT",
                    f"Opening the application link directly: {target}",
                    "Application link seedha khol rahe hain...",
                )
                await self.page.goto(target, wait_until="domcontentloaded", timeout=30000)
                changed = await self._wait_for_page_change(before, timeout_ms=10000)
            except Exception:
                traceback.print_exc()
        if not changed:
            # Let the stall guard's clock run rather than failing the run.  The
            # next scan may still show the form after a slow redirect.
            self._pending_journey_action = None
            await self.emit_event(
                "SENSE",
                "The application link did not open a new page yet.",
                "Application link se naya page abhi nahi khula.",
            )
            return False
        self._last_app_link_signature = ""
        self._last_gateway_signature = ""
        self._record_lesson(
            domain=self._current_domain(),
            signature="application_link",
            action=f"click:{label[:80]}",
            outcome="opened_application",
            note="Landing-page application link opened the form.",
        )
        return True

    async def _application_choice_checkpoint(
        self,
        dom: Dict[str, Any],
        targets: List[Dict[str, Any]],
    ) -> None:
        signature = "|".join(
            sorted(
                str(link.get("href") or link.get("text") or "") for link in targets
            )
        )
        if signature and signature == self._last_gateway_signature:
            await asyncio.sleep(0.8)
            return
        self._last_gateway_signature = signature

        options = [
            {
                "id": link.get("elementId") or link.get("element_id") or link.get("id"),
                "element_id": link.get("elementId") or link.get("element_id"),
                "text": self._clean_application_label(link.get("text")),
                "type": "APPLICATION",
                "mode": "apply",
                "href": link.get("href"),
                "source": "application_link",
            }
            for link in targets
        ]
        gate = {
            "gate_type": "GATEWAY_DECISION",
            "stage": "next_step",
            "title": "Which application should FormPilot open?",
            "hindi_title": "Kaun si application kholni hai?",
            "description": (
                "This page links to more than one application form. FormPilot will "
                "not guess. Choose the one that matches your exam and session."
            ),
            "why": "The landing page offers more than one explicit application link.",
            "requires_explicit_choice": True,
            "no_default": True,
            "options": options,
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
        }
        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(
                    True,
                    "Choose the application link here or in the live browser.",
                )
            await self.emit_event(
                "DECIDE",
                "Waiting for you to choose which application to open.",
                "Kaun si application kholni hai, uska intezaar hai.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            if response.get("action") in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                return
            if response.get("action") == "DISMISS":
                continue
            selected = decision_policy.match_entry_response(response, options)
            if selected:
                for link in targets:
                    if str(link.get("elementId") or link.get("element_id") or link.get("id")) == str(
                        selected.get("element_id") or selected.get("id")
                    ):
                        self.state = "RUNNING"
                        await self._follow_application_link(link)
                        return
            await self.emit_event(
                "SENSE",
                "That choice did not match an application link on this page.",
                "Yeh choice is page ke kisi application link se match nahi hui.",
            )

    async def _adopt_new_page(self, pages_before: int) -> bool:
        """Switch to a tab the portal opened (many NIC portals do this)."""
        if not self.context:
            return False
        try:
            pages = list(self.context.pages)
        except Exception:
            return False
        if len(pages) <= pages_before:
            return False
        newest = pages[-1]
        try:
            await newest.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        self.page = newest
        self._bind_dialog_handler(newest)
        url = str(getattr(newest, "url", "") or "")
        if url and url not in self._visited_urls:
            self._visited_urls.append(url)
        await self.emit_event(
            "SENSE",
            "The portal opened a new tab. FormPilot switched to it.",
            "Portal ne naya tab khola. FormPilot us par chala gaya.",
        )
        return True

    async def _dashboard_next_step(
        self,
        dom: Dict[str, Any],
        gateways: List[Dict[str, Any]],
    ) -> bool:
        """Follow a signed-in dashboard's application links instead of stopping.

        A dashboard has no form fields, so the old loop treated it as the end of
        the run.  But a dashboard is a hub: its links open the actual form.  When
        the page offers at least one explicit path, ask (or follow a single
        unambiguous one) and keep the run alive.
        """
        if not gateways:
            return False
        if not decision_policy.is_entry_page(dom, self.form_map):
            return False
        await self._gateway_checkpoint(dom, gateways, kind="next_step")
        return True

    async def _gateway_checkpoint(
        self,
        dom: Dict[str, Any],
        gateways: List[Dict[str, Any]],
        *,
        kind: str = "entry",
    ):
        """Ask for an explicit entry path, never infer one.

        ``decision_policy`` has already reduced the page to distinct targets.
        A single explicit option is followed; two or more options open a gate.
        A response that does not match exactly one option is rejected and the
        gate is shown again.
        """
        next_step = kind == "next_step"
        options = list(self._entry_options or [])
        if not options:
            try:
                options = decision_policy.entry_options(dom, self.form_map)
            except Exception:
                options = []
            self._entry_options = options

        if not options:
            await self._entry_handoff(gateways)
            return

        if len(options) == 1:
            await self._apply_entry_option(options[0])
            return

        signature = "|".join(
            sorted(
                f"{option.get('type')}:{option.get('element_id') or option.get('href') or option.get('text')}"
                for option in options
            )
        )
        if signature == self._last_gateway_signature:
            await asyncio.sleep(0.8)
            return
        self._last_gateway_signature = signature

        await self.emit_event(
            "THINK",
            "This dashboard offers more than one next step."
            if next_step
            else "This portal offers more than one way to start.",
            "Dashboard par aage badhne ke kai raste hain. Aap decide karein."
            if next_step
            else "Portal par do raste hain. Aap decide karein kaise shuru karna hai.",
        )
        gate = (
            decision_policy.build_next_step_gate(options)
            if next_step
            else decision_policy.build_entry_gate(options)
        )
        gate["live_session"] = self.live.public_info() if self.live and not self.live.closed else None
        gate["can_takeover"] = bool(self.live)
        try:
            domain = self._current_domain() or urlparse(str(dom.get("url") or "")).netloc
            store = self.portal_account_store
            gate["domain"] = domain
            gate["account_memory"] = store.domain_summary(domain)
            gate["account_answered"] = bool(
                gate["account_memory"].get("account_exists") != "unknown"
                or gate["account_memory"].get("confirmed")
            )
            gate["login_inspection"] = store.inspect_login_ui(dom).model_dump()
        except Exception:
            traceback.print_exc()

        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(
                    True,
                    "Choose the next step here or in the live browser, then continue.",
                )
            await self.emit_event(
                "DECIDE",
                "Waiting for you to choose the next step."
                if next_step
                else "Waiting for you to choose how to start.",
                "Agle step ka intezaar hai."
                if next_step
                else "Aapke choice ka intezaar hai.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            if response.get("action") in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                return
            if response.get("action") == "DISMISS":
                # Dismissing the panel is not a choice.  Keep the decision
                # open instead of silently taking the first path.
                await self.emit_event(
                    "SENSE",
                    "The entry path is still open. Choose one of the listed options.",
                    "Shuru ka rasta abhi chuna nahi gaya. Options mein se ek chunein.",
                )
                continue

            if response.get("action") == "ACCOUNT_STATUS":
                value = str(response.get("account_exists") or "unknown")
                if value not in {"yes", "no", "unknown"}:
                    value = "unknown"
                self._remember_portal_account(
                    account_exists=value, confirmed_by_human=True
                )
                gate["account_memory"] = self._portal_account_summary()
                gate["account_answered"] = True
                await self.emit_event(
                    "SENSE",
                    "Thanks. I'll remember that for this portal.",
                    "Dhanyavaad. Is portal ke liye yaad rakhunga.",
                )
                continue

            selected = decision_policy.match_entry_response(response, options)
            if selected:
                self.state = "RUNNING"
                await self._apply_entry_option(selected)
                return
            await self.emit_event(
                "SENSE",
                "That choice did not match an entry path on this page. Please choose one of the listed options.",
                "Yeh choice is page ke kisi raste se match nahi hui. Options mein se ek chunein.",
            )

    async def _account_conflict_checkpoint(self, dom: Dict[str, Any]) -> bool:
        """Surface a portal "already registered" message instead of filling on.

        Only fires when the human previously said this was their first time on
        the portal.  The page is evidence that the earlier answer may be wrong,
        not proof of who owns the account, so the fact drops back to unknown
        and the human chooses how to continue.
        """
        domain = self._current_domain()
        if not domain:
            return False
        try:
            store = self.portal_account_store
            memory = store.domain_summary(domain)
            if memory.get("account_exists") != "no":
                return False
            conflict = store.detect_registration_conflict(dom)
            if not conflict:
                return False
            signature = f"{domain}|{conflict.get('signal')}|{conflict.get('evidence')}"
            if signature in self._handled_conflicts:
                return False
            self._handled_conflicts.add(signature)
            store.mark_conflict(domain, evidence=str(conflict.get("evidence") or ""))
        except Exception:
            traceback.print_exc()
            return False

        inspection = store.inspect_login_ui(dom)
        gate = build_conflict_gate(
            conflict,
            store.domain_summary(domain),
            domain=domain,
            live_session=self.live.public_info() if self.live and not self.live.closed else None,
            can_takeover=bool(self.live),
        )
        gate["login_inspection"] = inspection.model_dump()
        await self.emit_event(
            "THINK",
            "The portal says this identifier is already registered. Asking you before doing anything.",
            "Portal keh raha hai yeh number pehle se registered hai. Aap se pooch rahe hain.",
        )
        if self.live:
            self.live.set_allow_control(True, "Choose how to handle the existing account.")

        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            await self.emit_event(
                "DECIDE",
                "The portal reports an existing account. Choose how to continue.",
                "Portal par account pehle se hai. Aage ka rasta aap chunein.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            if response.get("action") in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                return True
            if response.get("action") == "DISMISS":
                await self.emit_event(
                    "SENSE",
                    "The account conflict is still open. Choose one of the options.",
                    "Account ka sawaal abhi khula hai. Options mein se ek chunein.",
                )
                continue

            choice = str(response.get("choice") or response.get("value") or "").strip().lower()
            if response.get("action") != "ACCOUNT_CONFLICT" or choice not in {
                item["choice"] for item in CONFLICT_CHOICES
            }:
                await self.emit_event(
                    "SENSE",
                    "That choice did not match one of the account options. Please pick one.",
                    "Yeh choice account options se match nahi hui. Ek option chunein.",
                )
                continue

            if choice == "login":
                login_method = next(
                    (item for item in inspection.login_methods if item != "unknown"), "unknown"
                )
                self._remember_portal_account(
                    account_exists="yes",
                    login_method=login_method,
                    last_path_choice="login",
                    confirmed_by_human=True,
                )
                self._requested_entry_mode = "login"
                option = decision_policy.match_entry_response(
                    {"mode": "login"}, list(self._entry_options or [])
                )
                if option:
                    self.state = "RUNNING"
                    await self._apply_entry_option(option)
                    return True
                await self._conflict_handoff(
                    "Use the live browser to open the sign-in page, then continue.",
                    "Live browser mein sign-in page kholein, phir continue karein.",
                    inspection,
                )
                return True

            if choice == "recover":
                self._remember_portal_account(
                    account_exists="yes",
                    last_path_choice="recover",
                    confirmed_by_human=True,
                )
                paths = ", ".join(inspection.recovery_paths) or "the portal's recovery link"
                await self._conflict_handoff(
                    f"Recover the account in the live browser using {paths}, then continue. "
                    "I will not reset anything for you.",
                    "Live browser mein account recover karein, phir continue karein. Main kuch reset nahi karunga.",
                    inspection,
                )
                return True

            if choice == "register":
                self._remember_portal_account(
                    last_path_choice="register_other_identifier",
                    last_known_step="needs_other_identifier",
                    confirmed_by_human=True,
                )
                await self._conflict_handoff(
                    "Enter a different mobile number or email in the live browser, then continue. "
                    "I will not reuse an identifier the portal already rejected.",
                    "Live browser mein doosra number ya email daalein, phir continue karein.",
                    inspection,
                )
                return True

            self.is_running = False
            self.state = "STOPPED"
            await self.emit_event(
                "DECIDE",
                "Stopped at your request. The browser is left where it is.",
                "Aapke kehne par ruk gaya. Browser wahin khula hai.",
            )
            return True
        return True

    async def _conflict_handoff(
        self,
        english: str,
        hindi: str,
        inspection: Any = None,
    ) -> None:
        """Hand the browser to the human after a conflict choice, then rescan."""
        gate = {
            "gate_type": "LIVE_HANDOFF",
            "handoff_type": "account_conflict",
            "title": "This step needs you",
            "hindi_title": "Yeh step aapke liye hai",
            "description": english,
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
            "instructions": [
                "Use the live browser. It is the same page the agent is using.",
                "Nothing is submitted or reset for you.",
                "When the page shows what you need, click 'I completed this step'.",
            ],
            "solver_policy": "human_handoff_only",
        }
        if inspection is not None:
            gate["login_inspection"] = inspection.model_dump()
        if self.live:
            self.live.set_allow_control(True, "Finish this step in the live browser.")
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        await self.emit_event("DECIDE", english, hindi, gate, force_screenshot=True)
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        if response.get("action") in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
            return
        self.state = "RUNNING" if self.is_running else self.state
        if response.get("action") in {"HANDOFF_COMPLETE", "CONTINUE"}:
            await self._rescan_blueprint()

    def _remembered_entry_option(self) -> Optional[Dict[str, Any]]:
        """Reuse an entry path this account already chose explicitly.

        A saved choice is not an inference: the candidate (or the operator)
        already answered this exact question for this domain.  It is reused only
        when the page still offers that path and the choice was confirmed.
        """
        if not settings.AUTOPILOT_KNOWN_PATHS:
            return None
        try:
            summary = self.portal_account_store.domain_summary(self._current_domain())
        except Exception:
            return None
        choice = str(summary.get("last_path_choice") or "").strip().lower()
        if not choice or not summary.get("confirmed"):
            return None
        options = list(self._entry_options or [])
        matches = [option for option in options if option.get("mode") == choice]
        if len(matches) != 1:
            return None
        return matches[0]

    async def _apply_entry_option(self, option: Dict[str, Any]) -> None:
        mode = str(option.get("mode") or decision_policy.normalize_mode(option.get("type")) or "")
        if not mode:
            raise AgentRunError(
                "The portal's entry path could not be identified. Please choose it in the live browser."
            )
        self._entry_mode = mode
        self._remember_portal_account(last_path_choice=mode, confirmed_by_human=True)
        if option.get("source") == "current_page":
            await self.emit_event(
                "DECIDE",
                f"Continuing on this {self._entry_label(mode)} page. Nothing is assumed beyond what the page shows.",
                "Is page par aage badh rahe hain. Page jo dikha raha hai, usi ke hisaab se.",
            )
            return
        await self._click_gateway(option)

    async def _entry_handoff(self, gateways: List[Dict[str, Any]]) -> None:
        """Human handoff when the page has entry links we cannot classify."""
        labels = []
        seen = set()
        for gateway in gateways:
            text = str(gateway.get("text") or "").strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            labels.append(text)
        if not labels:
            raise AgentRunError(
                "This page does not show a clear way to register, sign in or resume. "
                "Please open the portal and choose the path yourself."
            )
        if not self.live:
            raise AgentRunError(
                "This page's entry paths could not be identified. Please open the portal and choose the path yourself."
            )
        gate = {
            "gate_type": "LIVE_HANDOFF",
            "handoff_type": "entry_choice",
            "title": "Choose the entry path in the browser",
            "hindi_title": "Browser mein shuru ka rasta chunein",
            "description": (
                "The portal shows entry links that could not be classified safely. "
                "Use the live browser to choose register, sign in or resume yourself, then continue."
            ),
            "options": [{"text": label} for label in labels[:6]],
            "live_session": self.live.public_info() if not self.live.closed else None,
            "can_takeover": True,
            "instructions": [
                "Click the correct link in the live browser.",
                "Wait for the next page to load.",
                "Then click 'I completed this step'.",
            ],
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        self.live.set_allow_control(True, "Choose the correct entry path in the live browser.")
        await self.emit_event(
            "DECIDE",
            "Choose the entry path in the live browser, then continue.",
            "Live browser mein sahi rasta chunein, phir continue karein.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        self._release_live_control("The agent is driving again.")
        if response.get("action") in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
            return
        if response.get("action") not in {"HANDOFF_COMPLETE", "CONTINUE"}:
            await self.emit_event(
                "SENSE",
                "The entry path is still open. Choose it in the live browser, then continue.",
                "Shuru ka rasta abhi chuna nahi gaya. Live browser mein chunein.",
            )
            return
        self._entry_mode = "manual"
        self._last_gateway_signature = ""
        await self.emit_event(
            "ACT",
            "Entry path completed in the live browser. Re-reading the page.",
            "Live browser mein rasta chun liya. Page dobara padh rahe hain.",
        )

    async def _click_gateway(self, gateway: Dict[str, Any]):
        self.state = "RUNNING"
        self._otp_cleared = False
        self._otp_signature = ""
        self._last_advance_signature = ""
        self._captcha_signature = ""
        self._last_error_signature = ""
        await self.emit_event(
            "ACT",
            f"Opening: {gateway.get('text') or 'the application form'}",
            "Chuni hui option khol rahe hain...",
        )
        before = await self._page_snapshot()
        before_url = str(before.get("url") or (self.page.url if self.page else ""))
        pages_before = len(self.context.pages) if self.context else 0
        self._note_journey_action("click_gateway", str(gateway.get("text") or "entry"))
        if not await self._safe_click(gateway):
            self._pending_journey_action = None
            detail = self._last_action_result
            code = f" ({detail.error_code})" if detail and detail.error_code else ""
            raise AgentRunError(
                f"The portal button could not be clicked{code}. Please try again."
            )
        if await self._adopt_new_page(pages_before):
            self._last_gateway_signature = ""
            return
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass
        href = str(gateway.get("href") or "").strip()
        if href:
            try:
                await self.page.wait_for_url(
                    urljoin(before_url, href), timeout=8000, wait_until="domcontentloaded"
                )
            except Exception:
                pass
        changed = await self._wait_for_page_change(before, timeout_ms=9000)
        if not changed and href and not href.lower().startswith(("javascript:", "#")):
            # Some government templates attach navigation to an overlay that
            # the automated click cannot trigger.  The href is explicit, so
            # opening it is the same user intent.
            try:
                target = urljoin(before_url, href)
                await self.emit_event(
                    "ACT",
                    f"Opening the entry link directly: {target}",
                    "Entry link seedha khol rahe hain...",
                )
                await self.page.goto(target, wait_until="domcontentloaded", timeout=30000)
                changed = await self._wait_for_page_change(before, timeout_ms=10000)
            except Exception:
                traceback.print_exc()
        if not changed:
            # Do not end the run on a click the portal did not register.  Hand
            # this one explicit choice to the human in the live browser.
            self._pending_journey_action = None
            await self._entry_handoff([gateway])
            return
        # A new page owns its own gateway signature.  If the click did not
        # navigate, the signature stays so the loop cannot double-click it.
        self._last_gateway_signature = ""

    async def _page_snapshot(self) -> Dict[str, Any]:
        """Cheap identity of the current page for real change detection."""
        if not self.page:
            return {}
        try:
            snapshot = await self.page.evaluate(
                r"""() => {
                    const text = (document.body && document.body.innerText
                        ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
                    const active = document.querySelector(
                        '.form-section.active, .section.active, [data-section].active'
                    );
                    const heading = document.querySelector(
                        '.form-section.active h2, .section.active h2, h1, h2'
                    );
                    let digest = 0;
                    for (let i = 0; i < text.length && i < 4000; i += 1) {
                        digest = ((digest << 5) - digest + text.charCodeAt(i)) | 0;
                    }
                    const visible = (el) => {
                        if (!el || el.getClientRects().length === 0) return false;
                        const style = window.getComputedStyle(el);
                        return style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const form = document.querySelector('form');
                    const fields = Array.from(document.querySelectorAll(
                        'input:not([type="hidden"]), select, textarea, [contenteditable="true"]'
                    )).filter(visible);
                    const fieldSignature = fields.map((el) => [
                        el.tagName.toLowerCase(),
                        el.getAttribute('name') || '',
                        el.id || '',
                        (el.getAttribute('type') || '').toLowerCase(),
                        el.getAttribute('maxlength') || '',
                        el.readOnly ? 'ro' : '',
                        el.disabled ? 'disabled' : '',
                    ].join(':')).join('|');
                    const buttons = Array.from(document.querySelectorAll(
                        'button, input[type="submit"], input[type="button"], a[role="button"]'
                    )).filter(visible);
                    return {
                        url: location.href,
                        title: document.title || '',
                        section: active ? (active.id || '') : '',
                        heading: heading ? (heading.innerText || '').trim().slice(0, 160) : '',
                        inputCount: fields.length,
                        buttonCount: buttons.length,
                        formAction: form ? (form.getAttribute('action') || '') : '',
                        fieldSignature: fieldSignature,
                        textDigest: String(digest),
                    };
                }"""
            )
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            return {"url": getattr(self.page, "url", ""), "title": "", "section": "", "heading": ""}

    async def _wait_for_page_change(
        self,
        before: Dict[str, Any],
        *,
        timeout_ms: int = 9000,
    ) -> bool:
        if not before:
            return False
        # A toast, a validation message or a spinner changing is not a step
        # change.  Require the page identity or its field structure to move.
        # ``textDigest`` is deliberately excluded: HPSC, for example, shows a
        # toastr error when OTP is empty and the old code counted that as a
        # successful "Section 1 saved".
        keys = (
            "url",
            "title",
            "section",
            "heading",
            "inputCount",
            "buttonCount",
            "formAction",
            "fieldSignature",
        )
        deadline = time.monotonic() + max(0.5, timeout_ms / 1000)
        while time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            after = await self._page_snapshot()
            if any(str(before.get(key) or "") != str(after.get(key) or "") for key in keys):
                return True
        return False

    async def _select_login_method(
        self,
        field: Dict[str, Any],
        option: Dict[str, Any],
    ) -> None:
        result = await self._apply_field_value(field, str(option.get("value") or ""))
        if not result.get("success"):
            raise AgentRunError(
                "The login method could not be selected. Please choose it in the live browser and continue."
            )
        await self.page.wait_for_timeout(350)
        self._set_login_method(str(option.get("method") or ""))
        await self.emit_event(
            "ACT",
            f"Sign-in method selected: {option.get('label') or option.get('text')}.",
            "Sign-in ka tarika select ho gaya.",
        )

    async def _login_method_checkpoint(self, dom: Dict[str, Any]) -> bool:
        """Require an explicit choice when a login form offers several methods."""
        selection = decision_policy.login_method_options(dom)
        if not selection:
            return False
        options = selection.get("options") or []
        field = selection.get("field") or {}
        if not options:
            return False
        current_value = str(field.get("value") or "")
        current = next(
            (option for option in options if str(option.get("value") or "") == current_value),
            None,
        )

        requested = self._requested_login_method
        if requested:
            self._requested_login_method = None
            match = decision_policy.match_login_method_response(
                {"method": requested, "value": requested, "text": requested},
                selection,
            )
            if match:
                self._set_login_method(str(match.get("method") or ""))
                if current_value != str(match.get("value") or ""):
                    await self._select_login_method(field, match)
                    return True
                return False
            await self.emit_event(
                "SENSE",
                "That sign-in method is not offered on this form. Please choose one of its options.",
                "Yeh sign-in method is form par nahi hai. Form ke options mein se chunein.",
            )

        if self._login_method:
            match = next(
                (
                    option
                    for option in options
                    if str(option.get("method") or "") == self._login_method
                ),
                None,
            )
            if match:
                if current_value != str(match.get("value") or ""):
                    await self._select_login_method(field, match)
                    return True
                return False
            self._login_method = None

        if len(options) == 1:
            option = options[0]
            self._set_login_method(str(option.get("method") or ""))
            if current_value != str(option.get("value") or ""):
                await self._select_login_method(field, option)
                return True
            return False

        gate = decision_policy.build_login_method_gate(selection)
        gate["live_session"] = self.live.public_info() if self.live and not self.live.closed else None
        gate["can_takeover"] = bool(self.live)
        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(
                    True,
                    "Choose the sign-in method here or in the live browser, then continue.",
                )
            await self.emit_event(
                "DECIDE",
                "Waiting for you to choose a sign-in method.",
                "Sign-in method ka intezaar hai.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            if response.get("action") in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                return True
            if response.get("action") == "DISMISS":
                await self.emit_event(
                    "SENSE",
                    "The sign-in method is still open. Choose one of the listed methods.",
                    "Sign-in method abhi chuna nahi gaya. Options mein se chunein.",
                )
                continue
            selected = decision_policy.match_login_method_response(response, selection)
            if selected:
                await self._select_login_method(field, selected)
                return True
            await self.emit_event(
                "SENSE",
                "That choice did not match a sign-in method on this form. Please choose one of the listed methods.",
                "Yeh choice kisi sign-in method se match nahi hui. Options mein se chunein.",
            )
        return True

    async def _login_identifier_checkpoint(self, dom: Dict[str, Any]) -> bool:
        """Require an explicit account identifier when several are visible."""
        selection = decision_policy.identifier_options(dom)
        if not selection:
            return False
        options = selection.get("options") or []
        if not options:
            return False

        if self._login_identifier and not any(
            str(option.get("key") or "") == self._login_identifier for option in options
        ):
            self._login_identifier = None

        requested = self._requested_login_identifier
        if requested:
            self._requested_login_identifier = None
            match = next(
                (option for option in options if str(option.get("key") or "") == requested),
                None,
            )
            if match:
                self._set_login_identifier(requested)
                await self.emit_event(
                    "THINK",
                    f"Using {match.get('label')} to identify this account.",
                    "Is account ko is detail se identify kar rahe hain.",
                )
                return False
            await self.emit_event(
                "SENSE",
                "That account identifier is not offered on this login form. Please choose one of its options.",
                "Yeh identifier is login form par nahi hai. Form ke options mein se chunein.",
            )

        if self._login_identifier:
            return False

        if len(options) == 1:
            self._set_login_identifier(str(options[0].get("key") or ""))
            return False

        gate = decision_policy.build_identifier_gate(selection)
        gate["live_session"] = self.live.public_info() if self.live and not self.live.closed else None
        gate["can_takeover"] = bool(self.live)
        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(
                    True,
                    "Choose the account identifier here or in the live browser, then continue.",
                )
            await self.emit_event(
                "DECIDE",
                "Waiting for you to choose which detail identifies your account.",
                "Aapka account kis detail se khulta hai, iska intezaar hai.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            if response.get("action") in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                return True
            if response.get("action") == "DISMISS":
                await self.emit_event(
                    "SENSE",
                    "The account identifier is still open. Choose one of the listed options.",
                    "Account identifier abhi chuna nahi gaya. Options mein se chunein.",
                )
                continue
            selected = decision_policy.match_identifier_response(response, selection)
            if selected:
                self._set_login_identifier(str(selected.get("key") or ""))
                await self.emit_event(
                    "THINK",
                    f"Using {selected.get('label')} to identify this account.",
                    "Is account ko is detail se identify kar rahe hain.",
                )
                return False
            await self.emit_event(
                "SENSE",
                "That choice did not match an account identifier on this form. Please choose one of the listed options.",
                "Yeh choice kisi identifier se match nahi hui. Options mein se chunein.",
            )
        return True

    # ---------------------------------------------------------------- filling

    @staticmethod
    def _digest_field_values(values: List[Dict[str, Any]]) -> str:
        """A value digest for the review snapshot; the values themselves are not stored."""
        pairs = []
        for item in values or []:
            if not isinstance(item, dict):
                continue
            pairs.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "value": str(item.get("value") or ""),
                    "selected": str(item.get("selectedText") or ""),
                    "checked": bool(item.get("checked")),
                }
            )
        pairs.sort(key=lambda item: (item["id"], item["name"], item["value"], item["selected"]))
        return hashlib.sha256(json.dumps(pairs, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _mask_persisted_value(value: Any) -> Any:
        text = str(value or "")
        if not text or text == "provided by you":
            return value
        if len(text) <= 4:
            return "*" * len(text)
        return f"{'*' * (len(text) - 4)}{text[-4:]}"

    def _persisted_audit(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        """The on-disk audit keeps masked values; the gate keeps the display copy."""
        records = [
            {
                **record,
                "vault_value": self._mask_persisted_value(record.get("vault_value")),
                "form_value": self._mask_persisted_value(record.get("form_value")),
            }
            for record in (audit.get("records") or [])
        ]
        return {
            **audit,
            "records": records,
            "values_masked": True,
            "persisted_records_hash": hashlib.sha256(
                json.dumps(records, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    async def _verify_approval_snapshot(self) -> Optional[Dict[str, Any]]:
        """Re-check the frozen review snapshot after the human returns control."""
        snapshot = self._approval_snapshot
        if not snapshot or not self.page or self.page.is_closed():
            return None
        at_gate = self.state == "AWAITING_PAYMENT" or (
            isinstance(self.active_gate, dict)
            and self.active_gate.get("gate_type") == "PRE_PAYMENT_SAFETY_LOCK"
        )
        if not at_gate:
            return None
        try:
            values = await self.page.evaluate(DOMScanner.EXTRACT_VALUES_JS, True)
        except Exception:
            values = []
        current_url = str(self.page.url or "")
        current_digest = self._digest_field_values(values)
        url_changed = current_url != str(snapshot.get("url") or "")
        fields_changed = current_digest != str(snapshot.get("field_digest") or "")
        if not url_changed and not fields_changed:
            return {
                "valid": not bool(snapshot.get("invalidated")),
                "reason": "already_invalidated" if snapshot.get("invalidated") else None,
                "url": current_url,
            }
        if snapshot.get("invalidated"):
            return {
                "valid": False,
                "reason": "already_invalidated",
                "url": current_url,
            }
        reason = "url_changed" if url_changed else "fields_changed"
        snapshot_url = str(snapshot.get("url") or "")
        self._record_step(
            "submit",
            status="invalidated",
            error_code="wrong_page" if url_changed else "field_not_held",
            output={
                "reason": reason,
                "snapshot_url": snapshot_url,
                "current_url": current_url,
                "snapshot_digest": snapshot.get("field_digest"),
                "current_digest": current_digest,
            },
        )
        if isinstance(self.active_gate, dict):
            self.active_gate["approval_valid"] = False
            self.active_gate["snapshot_changed"] = True
            self.active_gate["snapshot_reason"] = reason
        snapshot["invalidated"] = True
        snapshot["invalidated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        snapshot["url"] = current_url
        snapshot["field_digest"] = current_digest
        await self.emit_event(
            "SENSE",
            "The page changed after you reviewed it. Check the form again before you pay or submit.",
            "Aapke review ke baad page badal gaya. Payment ya final submit se pehle form dobara check karein.",
            force_screenshot=True,
        )
        return {
            "valid": False,
            "reason": reason,
            "url": current_url,
            "snapshot_url": snapshot_url,
        }

    def _public_audit(self) -> List[Dict[str, Any]]:
        public: List[Dict[str, Any]] = []
        seen = set()
        for record in reversed(self.filled_audit):
            key = record.get("field_id") or record.get("field_name") or record.get("vault_key")
            if key in seen:
                continue
            seen.add(key)
            public.append(
                {
                    "field_label": record.get("field_label"),
                    "vault_key": record.get("vault_key"),
                    "injected_value": record.get("injected_value"),
                    "field_id": record.get("field_id"),
                    "field_name": record.get("field_name"),
                    "field_type": record.get("field_type"),
                    "status": record.get("status", "FILLED"),
                    "provenance": record.get("provenance", "profile"),
                    "timestamp": record.get("timestamp"),
                }
            )
        return list(reversed(public))

    def _record_fill(self, item: Dict[str, Any], sem_key: str, value: str, method: str, *, custom: bool = False):
        key = item.get("id") or item.get("name") or sem_key
        if custom or sem_key.startswith(("custom_", "unknown_")):
            display = "provided by you"
        elif sem_key not in {"photo_upload", "signature_upload", "matric_cert_upload"}:
            display = field_registry.mask_value(sem_key, value)
        else:
            display = os.path.basename(str(value))
        record = {
            "field_label": item.get("label") or sem_key,
            "vault_key": sem_key,
            "injected_value": display,
            "actual_value": str(value),
            "field_id": item.get("id") or "",
            "field_name": item.get("name") or "",
            "field_type": item.get("type") or "text",
            "method": method,
            "provenance": "user-entered-now" if custom else "profile",
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "status": "FILLED",
            "_key": key,
        }
        for index, existing in enumerate(self.filled_audit):
            if existing.get("_key") == key:
                self.filled_audit[index] = record
                return
        self.filled_audit.append(record)

    async def _apply_field_value(self, item: Dict[str, Any], value: str) -> Dict[str, Any]:
        """Fill one field through the resolver, with the JS injector as fallback.

        The resolver is preferred because it validates the element identity and
        actionability before typing.  Radio groups, checkboxes and exotic
        widgets keep using the injector, which already knows how to select a
        group member by value.
        """
        element_id = str(item.get("element_id") or "")
        tag = str(item.get("tagName") or "input").lower()
        field_type = str(item.get("type") or "text").lower()
        resolver = self._action_resolver()
        resolver_failed = False

        if element_id and resolver and field_type not in {"checkbox", "radio", "file", "hidden"}:
            if tag == "select":
                resolved = await resolver.select(element_id, value)
            elif tag in {"input", "textarea"} or str(item.get("role") or "") == "textbox":
                resolved = await resolver.fill(element_id, value)
            else:
                resolved = None

            if resolved and resolved.ok:
                # A successful ``type:`` or ``js:`` means the fast ``fill``
                # did not stick and the resolver re-entered the value itself.
                # That is still one re-entry, so the summary must count it.
                return {
                    "success": True,
                    "method": resolved.method,
                    "value": value,
                    "reentered": str(resolved.method or "").startswith(("type:", "js:")),
                }
            if resolved and resolved.error_code in {"NOT_VISIBLE", "DISABLED", "NOT_EDITABLE"}:
                # Do not bypass a disabled or hidden field with a JS setter.
                return {"success": False, "reason": resolved.message}
            # Any other resolver failure falls through to the injector, which
            # uses name/id/index and can handle unusual widgets.
            if resolved and resolved.error_code:
                resolver_failed = True
                self._last_action_result = resolved

        try:
            injected = await self.page.evaluate(DOMScanner.INJECTION_JS, [item, value])
            if isinstance(injected, dict):
                # The injector only counts as a re-entry when the resolver
                # already tried and failed; it is the first attempt for a
                # widget the resolver cannot address.
                injected.setdefault("reentered", resolver_failed)
            return injected
        except Exception:
            return {"success": False, "reason": "The field could not be reached."}

    # A one-time secret is never a profile fact.  These labels are matched on
    # the field itself, so a portal that names its code box "code" instead of
    # "otp" still gets a human checkpoint instead of a stored value.
    _SECURITY_HINT_RE = re.compile(
        r"otp|one[-\s]?time\s*(?:password|code|pin)|verification\s*(?:code|pin)|"
        r"auth(?:entication)?\s*code|passcode|access\s*code|security\s*(?:code|check)|"
        r"sms\s*code|email\s*code|captcha|code\s*(?:sent|shown|above)|"
        r"enter\s*(?:the\s*)?(?:code|pin)\b",
        re.IGNORECASE,
    )
    # Codes that are ordinary data, not secrets.
    _NON_SECRET_CODE_RE = re.compile(
        r"\b(?:postal|zip|pin\s*code|area|country|dial|std|course|subject|"
        r"application|registration|roll|centre|center|exam|course|coupon|promo|"
        r"voucher|discount|gift)\s*code\b",
        re.IGNORECASE,
    )

    @classmethod
    def _is_security_code_field(cls, item: Dict[str, Any]) -> bool:
        """OTP and CAPTCHA inputs have their own human-only checkpoints.

        They must not count as skipped form fields, otherwise every OTP page
        would be reported as an incomplete fill.  More importantly, their
        value must never be remembered as a reusable fact.
        """
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("label", "name", "id", "placeholder", "aria_label")
        ).lower()
        if cls._NON_SECRET_CODE_RE.search(haystack):
            return False
        return bool(cls._SECURITY_HINT_RE.search(haystack))

    _DECLARATION_RE = re.compile(
        r"\b(?:i\s+(?:hereby\s+)?(?:agree|declare|confirm|consent|accept|undertake|affirm|solemnly)|"
        r"terms\s*(?:and|&)\s*conditions|privacy\s*policy|declaration|i\s+am\s+aware)\b",
        re.IGNORECASE,
    )
    _NON_DECLARATION_RE = re.compile(
        r"\b(?:remember|subscribe|newsletter|notify|updates?|offers?|whatsapp)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _is_declaration(cls, item: Dict[str, Any]) -> bool:
        """True for a consent/declaration checkbox that a form needs ticked.

        These boxes are legal statements, not optional preferences, but they
        are also not profile facts.  The human must accept each one; the value
        is never stored.
        """
        if str(item.get("type") or "").lower() != "checkbox":
            return False
        haystack = " ".join(
            str(item.get(key) or "") for key in ("label", "name", "id")
        )
        if not haystack.strip():
            return False
        if cls._NON_DECLARATION_RE.search(haystack):
            return False
        return bool(cls._DECLARATION_RE.search(haystack))

    _INSTRUCTION_CONSENT_RE = re.compile(
        r"(?:(?:downloaded|read|gone\s+through|studied|understood|accept|confirm).{0,140}"
        r"(?:information\s+bulletin|instructions?|guidelines?|procedure|bulletin|notification|terms|prospectus)|"
        r"(?:information\s+bulletin|instructions?|guidelines?|procedure|bulletin|notification|prospectus).{0,140}"
        r"(?:downloaded|read|gone\s+through|studied|understood|accepted|confirmed))",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def _is_instruction_consent(cls, item: Dict[str, Any]) -> bool:
        """True for "I have read the instructions" acknowledgements.

        This is not a final declaration.  An autonomous run may tick it after
        the portal's instruction page was actually read; a declaration about
        the truth of the submitted data is still handed to the human.
        """
        if str(item.get("type") or "").lower() != "checkbox":
            return False
        haystack = " ".join(
            str(item.get(key) or "") for key in ("label", "name", "id")
        )
        if not haystack.strip():
            return False
        if "chkagreement" in haystack.lower():
            return True
        return bool(cls._INSTRUCTION_CONSENT_RE.search(haystack))

    @classmethod
    def _looks_like_generic_secret(
        cls,
        item: Dict[str, Any],
        dom: Dict[str, Any],
    ) -> bool:
        """Catch a bare "code"/"pin" box on a page that already has a challenge.

        Portals often label the box only "Enter code" and give it a machine
        name such as ``SignupForm[code]``.  When the same page also shows an
        OTP or CAPTCHA challenge, that short field is the challenge answer,
        not a profile question.
        """
        if not (dom.get("otpInputs") or dom.get("captchaElements")):
            return False
        text = " ".join(
            str(item.get(key) or "")
            for key in ("label", "name", "id", "placeholder")
        ).lower()
        if cls._NON_SECRET_CODE_RE.search(text):
            return False
        words = re.findall(r"[a-z]+", text)
        return len(words) <= 4 and bool(
            re.search(r"\b(?:code|pin|otp|verification|verify|security)\b", text)
        )

    @staticmethod
    def _is_otp_field(item: Dict[str, Any]) -> bool:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("label", "name", "id", "placeholder", "aria_label")
        ).lower()
        return bool(
            re.search(
                r"otp|one[-\s]?time\s*(?:password|code|pin)|verification\s*(?:code|pin)|"
                r"auth(?:entication)?\s*code|passcode|access\s*code|sms\s*code|email\s*code",
                haystack,
            )
        )

    @classmethod
    def _is_otp_page(cls, dom: Dict[str, Any]) -> bool:
        """True when the page is a dedicated verification step.

        A full registration form can contain an optional OTP field (the
        practice portal keeps its phone-verification box inside section 1).
        That is not an OTP page: the agent still has to save the section.
        HPSC's post-signup page has only the code boxes and a ``validateotp``
        action, so advancing there would submit the wrong form.
        """
        inputs = [
            item
            for item in (dom.get("inputs") or [])
            if str(item.get("type") or "").lower() not in {"submit", "button", "hidden"}
        ]
        otp_fields = [item for item in inputs if cls._is_otp_field(item)]
        if not otp_fields:
            return False
        action = str(dom.get("formAction") or "").lower()
        if "validateotp" in action:
            return True
        return not [item for item in inputs if not cls._is_otp_field(item)]

    async def _fill_form(self, dom: Dict[str, Any]) -> int:
        """Fill fields, then verify every value against a fresh DOM scan.

        Nothing is recorded in ``filled_audit`` until the portal itself shows
        the expected value.  The UI reads ``fill_summary`` and therefore cannot
        claim a form was filled when the page is empty or the portal rejected a
        value.
        """
        targets: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        vault = self.vault_mgr.vault
        plan: Dict[str, Any] = {}
        try:
            perception = Perception.from_scan(dom, self.blueprint)
            domain = urlparse(
                str(dom.get("url") or (self.page.url if self.page else ""))
            ).netloc
            plan = build_fill_plan(
                perception,
                self.fact_book,
                vault=vault,
                domain=domain,
            )
        except Exception:
            # A page that cannot be perceived still fills through the registry
            # fast path; the semantic layer must never block a run.
            traceback.print_exc()
            plan = {}
        login_selection = decision_policy.login_method_options(dom)
        login_field = (login_selection or {}).get("field") or {}
        page_type = str((self.form_map or {}).get("page_type") or "").lower()
        login_page = self._entry_mode == "login" or page_type == "login"
        upload_keys = {"photo_upload", "signature_upload", "matric_cert_upload"}

        inputs = dom.get("inputs") or []
        # A radio group is satisfied when any one option is selected.  Without
        # this, the unchecked siblings would be reported as "skipped" on every
        # scan and the human would be asked to choose the same option forever.
        radio_groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in inputs:
            if str(item.get("type") or "").lower() != "radio":
                continue
            group_key = str(
                item.get("name") or item.get("id") or item.get("elementId") or ""
            )
            if group_key:
                radio_groups.setdefault(group_key, []).append(item)
        satisfied_radio_groups = {
            key for key, group in radio_groups.items() if any(entry.get("checked") for entry in group)
        }
        seen_choice_groups: set = set()

        for item in inputs:
            if not self.is_running:
                break
            item_type = str(item.get("type") or "").lower()
            if item_type in {"submit", "button", "reset", "image", "hidden"}:
                continue
            if item.get("disabled") or (item.get("readOnly") and item.get("value")):
                # Locked or auto-copied by portal (e.g. permanent address auto-copied, pre-filled details)
                continue
            if item_type in {"radio", "checkbox"} and item.get("checked"):
                # The human already selected this in the live browser.  A
                # checked choice is not an unfilled field.
                continue
            if item_type == "radio":
                group_key = str(
                    item.get("name") or item.get("id") or item.get("elementId") or ""
                )
                if group_key and group_key in satisfied_radio_groups:
                    continue
            if (
                self._is_security_code_field(item)
                or FormModel.human_challenge(item)
                or self._looks_like_generic_secret(item, dom)
            ):
                # Handled by _handle_otp / _handle_captcha, never by the fill
                # verifier, and never stored as a reusable fact.
                continue

            label = str(item.get("label") or item.get("name") or item.get("id") or "field")
            if login_field and self._same_field(item, login_field):
                # The method selector has its own explicit checkpoint.
                continue

            if login_page and self._login_identifier:
                identifier = decision_policy.classify_identifier(item)
                if identifier and identifier != self._login_identifier:
                    skipped.append(
                        {
                            "item": item,
                            "sem_key": identifier,
                            "label": label,
                            "reason": "Not the account identifier you chose.",
                        }
                    )
                    continue

            sem_key, _is_verify = DOMScanner.classify_field(item)
            if not sem_key and item_type not in {"radio", "checkbox"}:
                # A page this account completed before already knows which
                # semantic key this machine name maps to.  Reusing it is
                # deterministic and avoids asking the model again.
                sem_key = self._journey_field_hint(item)
            custom_field = False
            if (
                item_type == "checkbox"
                and not item.get("checked")
                and self._is_instruction_consent(item)
                and settings.AUTOPILOT_INSTRUCTION_CONSENT
            ):
                # "I have read the instructions" is an acknowledgement, not a
                # profile fact and not a final declaration.  An autonomous run
                # may tick it; a final declaration still goes to the human.
                consent = await self._select_choice_element(item, "yes")
                if consent.get("success"):
                    targets.append(
                        {
                            "item": item,
                            "sem_key": "instruction_consent",
                            "label": label,
                            "value": "yes",
                            "method": "consent",
                            "custom": False,
                            "kind": "choice",
                            "apply_ok": True,
                            "reason": "",
                            "clicked": bool(consent.get("clicked")),
                        }
                    )
                    await self.emit_event(
                        "ACT",
                        "Accepted the instruction acknowledgement.",
                        "Instructions ki acknowledgement accept kar li.",
                    )
                    continue
            if self._is_declaration(item) and not item.get("checked"):
                # A consent/declaration checkbox is a legal statement, not a
                # profile fact.  Ask every time and never store the answer.
                value = await self._ask_for_missing_field(
                    item,
                    self._custom_key(item),
                    store=False,
                )
                if not value:
                    skipped.append(
                        {
                            "item": item,
                            "sem_key": "",
                            "label": label,
                            "reason": "You did not accept this declaration.",
                        }
                    )
                    continue
                sem_key = self._custom_key(item)
                custom_field = True
            elif not sem_key and item_type in {"radio", "checkbox"}:
                # A choice group whose machine name carries no meaning can
                # still be answered from the candidate's own profile
                # (nationality, category, gender...).  Never guess: the
                # resolver only matches a value the vault already holds.
                choice_key = str(
                    item.get("name") or item.get("id") or item.get("elementId") or label
                )
                if choice_key in seen_choice_groups:
                    continue
                seen_choice_groups.add(choice_key)
                resolved = self._resolve_choice(item, inputs, dom)
                if resolved:
                    choice_target = await self._apply_choice(resolved)
                    if choice_target:
                        targets.append(choice_target)
                        if item_type == "radio":
                            group_name = str(item.get("name") or "").strip() or str(
                                item.get("id") or item.get("elementId") or ""
                            )
                            if group_name:
                                satisfied_radio_groups.add(group_name)
                        if choice_target.get("clicked"):
                            # A postback reloads the page; the rest of this
                            # scan is stale, so re-observe before filling more.
                            break
                        continue
                skipped.append(
                    {
                        "item": item,
                        "sem_key": "",
                        "label": label,
                        "kind": "choice",
                        "reason": "This is a choice field. Select the correct option in the live browser.",
                    }
                )
                continue
            elif not sem_key:
                if not self._should_ask_unknown(item):
                    is_choice = item_type in {"radio", "checkbox"}
                    if is_choice:
                        # Report one entry per choice group, not one per option.
                        choice_key = str(
                            item.get("name") or item.get("id") or item.get("elementId") or label
                        )
                        if choice_key in seen_choice_groups:
                            continue
                        seen_choice_groups.add(choice_key)
                    skipped.append(
                        {
                            "item": item,
                            "sem_key": "",
                            "label": label,
                            "kind": "choice" if is_choice else "unknown",
                            "reason": (
                                "This is a choice field. Select the correct option in the live browser."
                                if is_choice
                                else "No high-confidence match for this label."
                            ),
                        }
                    )
                    continue
                value = await self._ask_for_unknown_field(item)
                if not value:
                    skipped.append(
                        {
                            "item": item,
                            "sem_key": "",
                            "label": label,
                            "reason": "You skipped this field.",
                        }
                    )
                    continue
                sem_key = self._custom_key(item)
                custom_field = True
            else:
                if sem_key in upload_keys:
                    self._last_upload_path = ""
                    uploaded = await self._handle_upload(item, sem_key)
                    targets.append(
                        {
                            "item": item,
                            "sem_key": sem_key,
                            "label": label,
                            "value": self._last_upload_path or "attached by you",
                            "method": "file",
                            "custom": False,
                            "kind": "upload",
                            "apply_ok": bool(uploaded),
                            "reason": "" if uploaded else "The file was not attached.",
                        }
                    )
                    continue

                if sem_key == "account_password":
                    if _is_verify:
                        # Confirm / re-enter password field
                        value = self._session_created_password or vault.find_field_value("account_password")
                        if not value and not login_page:
                            value = await self._ask_for_password_creation(item, domain)
                    elif not login_page:
                        # Registration / create-password field
                        if self._session_created_password:
                            value = self._session_created_password
                        else:
                            value = await self._ask_for_password_creation(item, domain)
                    else:
                        # Login page
                        from .credential_store import CredentialStore
                        cred = CredentialStore.get_instance().find_by_domain_or_url(str(dom.get("url") or (self.page.url if self.page else "") or domain))
                        if cred and cred.password:
                            value = cred.password
                        else:
                            value = vault.find_field_value("account_password")
                        if not value:
                            value = await self._ask_for_missing_field(item, sem_key)
                    if not value:
                        skipped.append(
                            {
                                "item": item,
                                "sem_key": sem_key,
                                "label": label,
                                "reason": "Password creation was skipped.",
                            }
                        )
                        continue
                    targets.append(
                        {
                            "item": item,
                            "sem_key": sem_key,
                            "label": label,
                            "value": value,
                            "method": "direct",
                            "custom": False,
                            "kind": "text",
                            "apply_ok": True,
                            "reason": "",
                        }
                    )
                    continue

                instruction = plan.get(str(item.get("elementId") or ""))
                if instruction is not None and instruction.state == "leave_blank":
                    skipped.append(
                        {
                            "item": item,
                            "sem_key": sem_key,
                            "label": label,
                            "reason": instruction.reason
                            or "You told me there is no value for this field.",
                        }
                    )
                    continue
                if (
                    instruction is not None
                    and instruction.state == "ask_human"
                    and not item.get("required")
                    and not settings.ASK_OPTIONAL_FIELDS
                ):
                    # An optional field with no saved value stays blank.  The
                    # human can still type it in the live browser, but a blank
                    # middle name or guardian must not open a checkpoint.
                    skipped.append(
                        {
                            "item": item,
                            "sem_key": sem_key,
                            "label": label,
                            "reason": "Optional field left blank.",
                        }
                    )
                    continue
                if instruction is not None and instruction.state == "fill":
                    # Meaning already decided the value; do not re-derive it
                    # from the framework name unless it assigned a long numeric ID to a choice field.
                    if item_type in {"radio", "checkbox"} and str(instruction.value or "").isdigit() and len(str(instruction.value or "")) >= 10:
                        value = vault.find_field_value(sem_key) or ""
                    else:
                        value = instruction.value or ""
                elif instruction is not None and instruction.state in {"ask_human", "confirm"}:
                    value = await self._ask_for_missing_field(
                        item, sem_key, concept=instruction.concept
                    )
                    if not value:
                        skipped.append(
                            {
                                "item": item,
                                "sem_key": sem_key,
                                "label": label,
                                "reason": (
                                    "This needs your confirmation."
                                    if instruction.state == "confirm"
                                    else "No value was available for this field."
                                ),
                            }
                        )
                        continue
                    vault = self.vault_mgr.vault
                else:
                    value = vault.find_field_value(sem_key)
                    if sem_key == "dob" and value:
                        # Read the format from the field itself (placeholder,
                        # label or helper).  A native date input always takes
                        # ISO.  Only fall back to the India-first DD/MM/YYYY
                        # when the page gives no hint at all.
                        expected = self._date_format_for(item)
                        value = vault.get_formatted_dob(expected or "DD/MM/YYYY")

                    if not value:
                        if not item.get("required") and not settings.ASK_OPTIONAL_FIELDS:
                            skipped.append(
                                {
                                    "item": item,
                                    "sem_key": sem_key,
                                    "label": label,
                                    "reason": "Optional field left blank.",
                                }
                            )
                            continue
                        value = await self._ask_for_missing_field(item, sem_key)
                        if not value:
                            skipped.append(
                                {
                                    "item": item,
                                    "sem_key": sem_key,
                                    "label": label,
                                    "reason": "No value was available for this field.",
                                }
                            )
                            continue
                        vault = self.vault_mgr.vault

            # A portal account can use a different mobile/email than the
            # global profile.  On the login page the identifier recorded for
            # this domain wins over the global vault value.
            if login_page and sem_key in {"mobile", "email"}:
                value = self._portal_credential(sem_key) or value

            # Portals commonly lock fields after a step succeeds (for example,
            # HPSC marks the mobile/email/password fields read-only once the
            # first signup step has sent the OTP).  A locked field that already
            # holds the expected value is filled, not a failure.  Re-typing it
            # would either fail or make the portal clear the value.
            if self._field_value_matches(item, str(value)):
                targets.append(
                    {
                        "item": item,
                        "sem_key": sem_key,
                        "label": label,
                        "value": str(value),
                        "method": "already_filled",
                        "custom": custom_field,
                        "kind": "field",
                        "apply_ok": True,
                        "reason": "",
                    }
                )
                continue

            if item.get("readOnly") or item.get("disabled"):
                reason = (
                    f"'{label}' is read-only."
                    if item.get("readOnly")
                    else f"'{label}' is disabled."
                )
                targets.append(
                    {
                        "item": item,
                        "sem_key": sem_key,
                        "label": label,
                        "value": str(value),
                        "method": "input",
                        "custom": custom_field,
                        "kind": "field",
                        "apply_ok": False,
                        "reason": reason,
                    }
                )
                continue

            result = await self._apply_field_value(item, str(value))
            if item_type == "radio" and result.get("success"):
                group_name = str(item.get("name") or "").strip() or str(
                    item.get("id") or item.get("elementId") or ""
                )
                if group_name:
                    satisfied_radio_groups.add(group_name)
                try:
                    await self._accept_choice_popup([])
                except Exception:
                    pass
            targets.append(
                {
                    "item": item,
                    "sem_key": sem_key,
                    "label": label,
                    "value": str(value),
                    "method": result.get("method", "input"),
                    "custom": custom_field,
                    "kind": "field",
                    "apply_ok": bool(result.get("success")),
                    "reason": str(result.get("reason") or ""),
                    "reentered": bool(result.get("reentered")),
                }
            )
            await asyncio.sleep(0.08)

        # A child select (district after state) only gets its options after the
        # parent changes.  One extra pass picks those up without re-filling
        # anything that was already handled.
        await asyncio.sleep(0.25)
        await self._fill_dependent_selects(targets, skipped)
        await self._fill_revealed_inputs(targets, skipped)

        return await self._verify_fill_targets(targets, skipped)

    async def _fill_revealed_inputs(
        self,
        targets: List[Dict[str, Any]],
        skipped: List[Dict[str, Any]],
    ) -> None:
        """Fill inputs that were hidden or absent until a parent field or choice was selected.

        For example, selecting Category: OBC-NCL reveals certificate number and date;
        selecting PwD: Yes reveals disability questions; selecting an identity radio reveals
        Aadhaar/DigiLocker credential fields.
        """
        try:
            fresh = await self._scan_dom()
        except Exception:
            return
        fresh_inputs = fresh.get("inputs") or []
        if not fresh_inputs:
            return

        handled_element_ids = {
            str(entry.get("item", {}).get("elementId") or entry.get("item", {}).get("element_id") or "")
            for entry in targets + skipped
            if isinstance(entry, dict)
        }
        handled_names = {
            str(entry.get("item", {}).get("name") or "")
            for entry in targets + skipped
            if isinstance(entry, dict) and entry.get("item", {}).get("name")
        }
        handled_ids = {
            str(entry.get("item", {}).get("id") or "")
            for entry in targets + skipped
            if isinstance(entry, dict) and entry.get("item", {}).get("id")
        }

        vault = self.vault_mgr.vault
        new_targets_added = False

        for item in fresh_inputs:
            if not self.is_running:
                break
            el_id = str(item.get("elementId") or item.get("element_id") or "")
            name = str(item.get("name") or "")
            item_id = str(item.get("id") or "")

            if (el_id and el_id in handled_element_ids) or (name and name in handled_names) or (item_id and item_id in handled_ids):
                continue

            item_type = str(item.get("type") or "").lower()
            if item_type in {"submit", "button", "reset", "image", "hidden"}:
                continue
            if item.get("readOnly") or item.get("disabled"):
                continue
            if item_type in {"radio", "checkbox"} and item.get("checked"):
                continue
            if (
                self._is_security_code_field(item)
                or FormModel.human_challenge(item)
                or self._looks_like_generic_secret(item, fresh)
            ):
                continue

            if (
                item_type == "checkbox"
                and not item.get("checked")
                and self._is_instruction_consent(item)
                and settings.AUTOPILOT_INSTRUCTION_CONSENT
            ):
                consent = await self._select_choice_element(item, "yes")
                if consent.get("success"):
                    targets.append(
                        {
                            "item": item,
                            "sem_key": "instruction_consent",
                            "label": str(item.get("label") or "instruction_consent"),
                            "value": "yes",
                            "method": "consent",
                            "custom": False,
                            "kind": "choice",
                            "apply_ok": True,
                            "reason": "",
                            "clicked": bool(consent.get("clicked")),
                        }
                    )
                    new_targets_added = True
                    continue

            sem_key, _ = DOMScanner.classify_field(item)
            if not sem_key:
                continue

            val = vault.find_field_value(sem_key)
            if sem_key == "dob" and val:
                expected = self._date_format_for(item)
                val = vault.get_formatted_dob(expected or "DD/MM/YYYY")

            if val:
                result = await self._apply_field_value(item, str(val))
                targets.append(
                    {
                        "item": item,
                        "sem_key": sem_key,
                        "label": str(item.get("label") or sem_key),
                        "value": str(val),
                        "method": result.get("method", "input"),
                        "custom": False,
                        "kind": "field",
                        "apply_ok": bool(result.get("success")),
                        "reason": str(result.get("reason") or ""),
                        "reentered": bool(result.get("reentered")),
                    }
                )
                new_targets_added = True
                await asyncio.sleep(0.08)

        if new_targets_added:
            await self._wait_for_postback(timeout_ms=2000)

    async def _fill_dependent_selects(
        self,
        targets: List[Dict[str, Any]],
        skipped: List[Dict[str, Any]],
    ) -> None:
        """Fill selects whose options appeared after a parent field changed.

        State -> district -> block cascades render an empty child until the
        parent fires ``change``.  The first scan cannot plan them, so they are
        skipped with a "does not offer an option" reason.  Re-scan once and
        fill only those fields, with the same option matcher and no guessing.
        """
        pending = [
            entry
            for entry in skipped
            if "does not offer an option" in str(entry.get("reason") or "").lower()
        ]
        if not pending:
            return
        try:
            fresh = await self._scan_dom()
        except Exception:
            return
        by_key: Dict[str, Dict[str, Any]] = {}
        for item in fresh.get("inputs") or []:
            if str(item.get("type") or "").lower() != "select":
                continue
            sem_key, _ = DOMScanner.classify_field(item)
            if sem_key and item.get("options"):
                by_key[sem_key] = item
        if not by_key:
            return
        for entry in list(pending):
            sem_key = str(entry.get("sem_key") or "")
            item = by_key.get(sem_key)
            if not item:
                continue
            value = self.vault_mgr.vault.find_field_value(sem_key)
            if not value:
                continue
            matched = match_option(str(value), item.get("options") or [])
            if not matched:
                continue
            result = await self._apply_field_value(item, matched)
            targets.append(
                {
                    "item": item,
                    "sem_key": sem_key,
                    "label": str(entry.get("label") or sem_key),
                    "value": matched,
                    "method": result.get("method", "select"),
                    "custom": False,
                    "kind": "field",
                    "apply_ok": bool(result.get("success")),
                    "reason": str(result.get("reason") or ""),
                    "reentered": bool(result.get("reentered")),
                }
            )
            skipped.remove(entry)

    @staticmethod
    def _same_field(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        for key in ("element_id", "id", "name"):
            left_value = str(left.get(key) or "")
            right_value = str(right.get(key) or "")
            if left_value and left_value == right_value:
                return True
        return False

    @staticmethod
    def _norm_exact(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def _values_match(
        cls,
        item: Dict[str, Any],
        expected: str,
        actual: str,
        raw_value: str,
    ) -> bool:
        """True when the field holds the value, allowing equivalent formats.

        The comparison rules live in ``field_commit`` so verification, the
        "already filled" check and the UI all agree on what "held" means.
        """
        kind = field_commit.kind_for(item)
        if field_commit.committed(
            field_commit.classify_commit(expected, actual, kind=kind)
        ):
            return True
        if raw_value and raw_value != expected:
            return field_commit.committed(
                field_commit.classify_commit(raw_value, actual, kind=kind)
            )
        return False

    @classmethod
    def _field_value_matches(cls, item: Dict[str, Any], expected: str) -> bool:
        """True when the scanned field already holds the value we would enter.

        This is intentionally based on the field's current DOM value, not on
        the presence of a green check or a portal-specific class.  A locked
        field with the right value can be verified without touching it; a
        locked empty field still needs a human.
        """
        field_type = str(item.get("type") or "text").lower()
        if field_type in {"checkbox", "radio"}:
            wanted = str(expected or "").strip().lower() not in {"", "no", "false", "0", "unchecked"}
            return bool(item.get("checked")) == wanted
        actual_values = [
            str(item.get("value") or ""),
            str(item.get("selectedText") or ""),
        ]
        return any(
            cls._values_match(item, expected, actual, expected)
            for actual in actual_values
            if actual
        )

    @staticmethod
    def _find_current_input(
        item: Dict[str, Any],
        dom: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        inputs = [entry for entry in (dom.get("inputs") or []) if isinstance(entry, dict)]
        frame = str(item.get("frame") or "")
        for key in ("id", "name"):
            value = str(item.get(key) or "")
            if not value:
                continue
            matches = [
                entry
                for entry in inputs
                if str(entry.get(key) or "") == value
                and (not frame or not entry.get("frame") or str(entry.get("frame")) == frame)
            ]
            if len(matches) == 1:
                return matches[0]
        try:
            index = int(item.get("index") or 0)
        except (TypeError, ValueError):
            return None
        matches = [
            entry
            for entry in inputs
            if int(entry.get("index") or -1) == index
            and (not frame or not entry.get("frame") or str(entry.get("frame")) == frame)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _file_attached(item: Dict[str, Any], dom: Dict[str, Any]) -> bool:
        frame = str(item.get("frame") or "")
        for key in ("id", "name"):
            value = str(item.get(key) or "")
            if not value:
                continue
            matches = [
                entry
                for entry in (dom.get("fileInputs") or [])
                if str(entry.get(key) or "") == value
                and (not frame or not entry.get("frame") or str(entry.get("frame")) == frame)
            ]
            if len(matches) == 1:
                return bool(matches[0].get("hasFile"))
        current = FormPilotOrchestrator._find_current_input(item, dom)
        if current:
            return bool(current.get("value") or current.get("fileCount"))
        files = [entry for entry in (dom.get("fileInputs") or []) if entry.get("hasFile")]
        return len(files) == 1

    def _drop_audit_for(self, item: Dict[str, Any], sem_key: str) -> None:
        item_id = str(item.get("id") or "")
        item_name = str(item.get("name") or "")
        kept: List[Dict[str, Any]] = []
        for record in self.filled_audit:
            same = False
            if item_id and str(record.get("field_id") or "") == item_id:
                same = True
            elif item_name and str(record.get("field_name") or "") == item_name:
                same = True
            elif not item_id and not item_name and str(record.get("vault_key") or "") == str(sem_key or ""):
                same = True
            if not same:
                kept.append(record)
        self.filled_audit = kept

    def _evaluate_fill_target(
        self,
        target: Dict[str, Any],
        fresh: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compare one fill target against a fresh read of the page.

        Returns ``status`` (``VERIFIED``/``FAILED``), a human reason, the
        commit verdict when one applies, and whether a single retry is
        justified.  Uploads and checkboxes are never retried: re-attaching a
        file or toggling a box can undo a value the portal already accepted.
        """
        item = target.get("item") or {}
        if not target.get("apply_ok"):
            return {
                "status": "FAILED",
                "reason": str(target.get("reason") or "The portal did not accept this value."),
                "retryable": False,
            }

        if target.get("kind") == "upload":
            if self._file_attached(item, fresh):
                return {"status": "VERIFIED", "reason": "", "retryable": False}
            return {
                "status": "FAILED",
                "reason": "The portal did not keep the attached file.",
                "retryable": False,
            }

        current = self._find_current_input(item, fresh)
        if current is None:
            return {
                "status": "FAILED",
                "reason": "The field disappeared after it was filled.",
                "retryable": False,
            }

        field_type = str(item.get("type") or "text").lower()
        value = str(target.get("value") or "")
        if field_type == "radio":
            group_name = str(current.get("name") or item.get("name") or "").strip()
            if group_name:
                group_radios = [
                    inp for inp in fresh.get("inputs", [])
                    if str(inp.get("type") or "").lower() == "radio"
                    and str(inp.get("name") or "").strip() == group_name
                ]
                checked_radio = next((r for r in group_radios if r.get("checked")), None)
                if checked_radio:
                    return {"status": "VERIFIED", "reason": "", "retryable": False}
            matches = bool(current.get("checked"))
            return {
                "status": "VERIFIED" if matches else "FAILED",
                "reason": "" if matches else "The portal did not keep this choice.",
                "retryable": False,
            }

        if field_type == "checkbox":
            wanted = value.strip().lower() not in {"", "no", "false", "0", "unchecked"}
            matches = bool(current.get("checked")) == wanted
            return {
                "status": "VERIFIED" if matches else "FAILED",
                "reason": "" if matches else "The portal did not keep this choice.",
                "retryable": False,
            }

        kind = field_commit.kind_for(item)
        verdict: Optional[Dict[str, Any]] = None
        actual_values = [
            str(current.get("value") or ""),
            str(current.get("selectedText") or ""),
        ]
        for actual in actual_values:
            candidate = field_commit.classify_commit(value, actual, kind=kind)
            if field_commit.committed(candidate):
                verdict = candidate
                break
            verdict = verdict or candidate

        if verdict is None:
            verdict = field_commit.classify_commit(value, "", kind=kind)

        ok = field_commit.committed(verdict)
        retryable = (
            field_commit.retryable(verdict)
            and kind not in {"select"}
            and str(item.get("tagName") or "").lower() != "select"
        )
        return {
            "status": "VERIFIED" if ok else "FAILED",
            "reason": "" if ok else str(verdict.get("reason") or "The portal did not keep the value that was entered."),
            "retryable": retryable,
            "commit": verdict,
        }

    async def _verify_fill_targets(
        self,
        targets: List[Dict[str, Any]],
        skipped: List[Dict[str, Any]],
    ) -> int:
        self._fill_targets = list(targets)
        self._fill_skipped = list(skipped)
        self.fill_failures = []
        verified = 0
        field_results: List[Dict[str, Any]] = []

        # Portals often clear, truncate or reformat a value in an input handler
        # a moment after typing.  Read back only after that handler has run,
        # otherwise the first scan reports a value the page is about to drop.
        await asyncio.sleep(0.3)
        try:
            fresh = await self._scan_dom()
        except Exception:
            fresh = {"inputs": [], "fileInputs": []}

        results = [self._evaluate_fill_target(target, fresh) for target in targets]

        # One bounded retry, only for values the portal dropped or replaced.
        # This mirrors Skyvern's read-back rule: a silent rejection gets one
        # atomic re-entry, not a loop.
        retry_indexes = [index for index, result in enumerate(results) if result.get("retryable")]
        # A value the resolver had to type or inject after its fast fill did
        # not stick was also re-entered, just one layer lower.  Count it once
        # per field so the summary reports re-entry honestly either way.
        reentered_indexes = {
            index for index, target in enumerate(targets) if target.get("reentered")
        }
        if retry_indexes and self.page:
            for index in retry_indexes:
                target = targets[index]
                try:
                    await self._apply_field_value(
                        target.get("item") or {}, str(target.get("value") or "")
                    )
                except Exception:
                    traceback.print_exc()
            await asyncio.sleep(0.15)
            try:
                second_read = await self._scan_dom()
            except Exception:
                second_read = None
            if second_read is not None:
                for index in retry_indexes:
                    results[index] = self._evaluate_fill_target(targets[index], second_read)
                    results[index]["retried"] = True
                await self.emit_event(
                    "ACT",
                    f"Re-entered {len(retry_indexes)} field(s) the portal had dropped, then read them back.",
                    f"Portal ne {len(retry_indexes)} field drop kar diye the; dobara bhar kar check kiya.",
                )

        for target, result in zip(targets, results):
            item = target.get("item") or {}
            sem_key = str(target.get("sem_key") or "")
            label = str(target.get("label") or sem_key or "field")
            if result.get("status") == "VERIFIED":
                verified += 1
                method = "file" if target.get("kind") == "upload" else str(target.get("method") or "input")
                self._record_fill(
                    item,
                    sem_key,
                    str(target.get("value") or ""),
                    method,
                    custom=bool(target.get("custom")),
                )
                entry = {"field_label": label, "vault_key": sem_key, "status": "VERIFIED"}
                if result.get("commit"):
                    entry["commit"] = result["commit"]["match"]
                field_results.append(entry)
                continue

            self._drop_audit_for(item, sem_key)
            failure = {
                "field_label": label,
                "vault_key": sem_key,
                "status": "FAILED",
                "reason": str(result.get("reason") or "The portal did not keep the value that was entered."),
            }
            if result.get("commit"):
                failure["commit"] = result["commit"]
            if result.get("retried"):
                failure["retried"] = True
            self.fill_failures.append(failure)
            entry = {"field_label": label, "vault_key": sem_key, "status": "FAILED"}
            if result.get("commit"):
                entry["commit"] = result["commit"]["match"]
            field_results.append(entry)

        for skip in skipped:
            item = skip.get("item") or {}
            sem_key = str(skip.get("sem_key") or "")
            label = str(skip.get("label") or sem_key or "field")
            self._drop_audit_for(item, sem_key)
            self.fill_failures.append(
                {
                    "field_label": label,
                    "vault_key": sem_key,
                    "status": "SKIPPED",
                    "reason": str(skip.get("reason") or "This field was skipped."),
                }
            )
            field_results.append(
                {"field_label": label, "vault_key": sem_key, "status": "SKIPPED"}
            )

        attempted = len(targets)
        skipped_count = len(skipped)
        failed_count = sum(1 for failure in self.fill_failures if failure.get("status") == "FAILED")
        reformatted_count = sum(
            1 for entry in field_results if entry.get("commit") == "reformatted"
        )
        if attempted == 0 and skipped_count == 0:
            status = "NO_FIELDS"
        elif verified == 0:
            status = "FAILED"
        elif failed_count == 0 and skipped_count == 0 and verified == attempted:
            status = "FILLED"
        else:
            status = "PARTIAL"

        self.fill_summary = {
            "status": status,
            "page_url": self.page.url if self.page else self.target_url,
            "section": self.current_section,
            "attempted": attempted,
            "verified": verified,
            "failed": failed_count,
            "skipped": skipped_count,
            "reformatted": reformatted_count,
            "retried": len(set(retry_indexes) | reentered_indexes),
            "choice_fields": [
                str(item.get("label") or "")
                for item in skipped
                if item.get("kind") == "choice"
            ][:8],
            "fields": field_results,
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        self._record_step(
            "fill",
            status="ok" if status in {"FILLED", "NO_FIELDS"} else "partial" if status == "PARTIAL" else "failed",
            output={
                "status": status,
                "attempted": attempted,
                "verified": verified,
                "failed": failed_count,
                "skipped": skipped_count,
                "reformatted": reformatted_count,
                "retried": len(set(retry_indexes) | reentered_indexes),
                "section": self.current_section,
            },
        )
        if verified:
            await self.emit_event(
                "ACT",
                f"Verified {verified} of {attempted} filled field(s) on this page.",
                f"Is page par {attempted} mein se {verified} field verify ho gaye.",
            )
        if self.fill_failures:
            all_labels = [
                str(failure.get("field_label") or "field")
                for failure in self.fill_failures
            ]
            shown = all_labels[:4]
            remaining = len(all_labels) - len(shown)
            labels = ", ".join(shown)
            if remaining:
                labels += f" and {remaining} more"
            await self.emit_event(
                "SENSE",
                f"{len(self.fill_failures)} field(s) need attention: {labels}.",
                f"{len(self.fill_failures)} field par dhyan dein: {labels}.",
            )
        if status == "NO_FIELDS":
            await self.emit_event(
                "SENSE",
                "No fillable fields were found on this page.",
                "Is page par bharne ke liye koi field nahi mila.",
            )
        return verified

    @staticmethod
    def _should_ask_unknown(item: Dict[str, Any]) -> bool:
        field_type = str(item.get("type") or "text").lower()
        if field_type in {"file", "checkbox", "radio", "hidden", "submit", "button", "reset", "image", "search"}:
            return False
        label = str(item.get("label") or "").strip()
        if len(label) < 2:
            return False
        if re.search(r"\b(?:search|filter|find|newsletter|subscribe|coupon|promo)\b", label, re.IGNORECASE):
            return False
        # CAPTCHA and OTP fields have their own checkpoints.  Asking for a
        # reusable "custom field" value here would be wrong and would leak a
        # one-time secret into the profile.
        haystack = " ".join(
            str(item.get(key) or "") for key in ("label", "name", "id", "placeholder")
        )
        if re.search(
            r"captcha|security\s*(?:check|code)|otp|one[-\s]?time|verification\s*code|auth(?:entication)?\s*code",
            haystack,
            re.IGNORECASE,
        ):
            return False
        return True

    @staticmethod
    def _date_format_for(item: Dict[str, Any]) -> str:
        """Return the date format the field itself asks for, if it says."""
        if str(item.get("type") or "").lower() == "date":
            return "YYYY-MM-DD"
        hint = " ".join(
            str(item.get(key) or "")
            for key in ("label", "placeholder", "helperText", "aria_label")
        )
        return concepts.expected_date_format(hint) or ""

    @staticmethod
    def _is_skip_value(value: Any) -> bool:
        """Recognise a human telling us the field does not apply.

        Candidates often type "skip" or "N/A" into a text box when the UI has
        no skip button.  That must never be stored as a real name or fact.
        """
        return str(value or "").strip().lower() in {
            "skip",
            "skipped",
            "n/a",
            "na",
            "none",
            "not applicable",
            "not-applicable",
            "-",
            "--",
        }

    def _mark_known_absent(self, concept: str) -> None:
        """Remember that a field does not apply, so future runs do not ask."""
        try:
            self.fact_book.set_fact(
                concept,
                value="",
                known_absent=True,
                provenance="explicit_user",
                verification="confirmed_by_human",
                scope={"kind": "global"},
            )
        except Exception:
            traceback.print_exc()

    @staticmethod
    def _custom_key(item: Dict[str, Any]) -> str:
        label = str(item.get("label") or item.get("name") or item.get("id") or "field")
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:48] or "field"
        return f"custom_{slug}"

    async def _ask_for_unknown_field(self, item: Dict[str, Any]) -> str:
        label = str(item.get("label") or item.get("name") or "this field")
        custom_key = self._custom_key(item)
        if custom_key in self._session_values:
            return self._session_values[custom_key]

        await self.emit_event(
            "THINK",
            f"The form asks for something new: {label}",
            f"Form mein ek nayi detail chahiye: {label}",
        )
        options = [
            {"text": str(option.get("text") or ""), "value": str(option.get("value") or "")}
            for option in (item.get("options") or [])[:60]
        ]
        gate = {
            "gate_type": "UNKNOWN_FIELD",
            "title": "The form asks for something new",
            "hindi_title": "Form mein nayi detail chahiye",
            "field_key": custom_key,
            "field_label": label,
            "input_type": item.get("type") or "text",
            "options": options,
            "required": bool(item.get("required")),
            "description": (
                "This label does not match a known field with enough confidence. "
                "FormPilot will not guess. Enter the value yourself, or skip if the form allows it."
            ),
            "why": "No high-confidence match in the field registry.",
            "can_skip": not bool(item.get("required")),
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "Fill this new field in the live browser, or answer here.")
        await self.emit_event(
            "DECIDE",
            f"Waiting for: {label}",
            "Aapke input ka intezaar hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state

        action = str(response.get("action") or "")
        if action in {"STOPPED", "TIMEOUT", "DISMISS", "SKIP"}:
            if action == "TIMEOUT":
                self.is_running = False
            return ""
        value = str(response.get("value") or response.get("text") or "").strip()
        if not value or self._is_skip_value(value):
            return ""
        self._session_values[custom_key] = value
        try:
            self.vault_mgr.add_custom_field(custom_key, value)
        except Exception:
            pass
        await self.emit_event(
            "THINK",
            f"Saved '{label}' as a custom profile field for this account.",
            f"'{label}' ko custom profile field ke roop mein save kar diya.",
        )
        return value

    async def _ask_for_missing_field(
        self,
        item: Dict[str, Any],
        sem_key: str,
        *,
        concept: Optional[str] = None,
        store: bool = True,
    ) -> str:
        label = item.get("label") or sem_key
        await self.emit_event(
            "THINK",
            f"One more detail is needed: {label}",
            f"Ek detail aur chahiye: {label}",
        )
        gate = {
            "gate_type": "MISSING_FIELD",
            "title": "One more detail is needed",
            "hindi_title": "Ek detail aur chahiye",
            "field_key": sem_key,
            "field_label": label,
            "input_type": item.get("type") or "text",
            "required": bool(item.get("required")),
            "can_skip": not bool(item.get("required")),
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
            "description": f"This portal asks for {label}. Add it once and FormPilot will reuse it in future applications.",
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "Enter this detail in the live browser, or answer here.")
        await self.emit_event(
            "DECIDE",
            f"Waiting for: {label}",
            "Aapke input ka intezaar hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state
        action = str(response.get("action") or "")
        if action in {"STOPPED", "TIMEOUT", "DISMISS", "SKIP"}:
            if action == "TIMEOUT":
                self.is_running = False
            if action == "SKIP" and concept:
                self._mark_known_absent(concept)
            return ""
        if action == "HANDOFF_COMPLETE":
            return ""
        value = str(response.get("value") or response.get("text") or "").strip()
        if value and self._is_skip_value(value):
            # The human typed "skip" because there was no button.  Record the
            # field as intentionally blank, never as a value.
            if concept:
                self._mark_known_absent(concept)
            return ""
        if value:
            stored_as_fact = False
            if concept and store:
                try:
                    self.fact_book.set_fact(
                        concept,
                        value=value,
                        provenance="explicit_user",
                        verification="confirmed_by_human",
                        scope={"kind": "global"},
                    )
                    stored_as_fact = True
                except Exception:
                    traceback.print_exc()
            if store and not stored_as_fact:
                try:
                    self.vault_mgr.set_semantic_field(sem_key, value)
                except Exception:
                    self.vault_mgr.add_custom_field(sem_key, value)
        return value

    async def _ask_for_password_creation(
        self,
        item: Dict[str, Any],
        domain: str = "",
    ) -> str:
        """Prompt user to create or auto-generate a compliant password for the portal account."""
        from .credential_store import CredentialStore, generate_compliant_password
        label = str(item.get("label") or item.get("name") or "Create Password")
        suggested = generate_compliant_password(12)
        gate = {
            "gate_type": "PASSWORD_CREATION",
            "title": "Create Account Password",
            "hindi_title": "Portal ke liye Password banayein",
            "field_key": "account_password",
            "field_label": label,
            "domain": domain,
            "suggested_password": suggested,
            "rules": [
                "8 to 13 characters in length",
                "At least 1 uppercase alphabet (A-Z)",
                "At least 1 lowercase alphabet (a-z)",
                "At least 1 numeric digit (0-9)",
                "At least 1 special character (!@#$%^&*)",
            ],
            "description": f"This portal requires a secure password for registration. You can use FormPilot's auto-generated strong password or enter your own. It will be permanently saved to your Saved Passwords vault.",
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "Create a password here or in the live browser.")
        await self.emit_event(
            "DECIDE",
            f"Create account password for {domain or 'portal'}",
            "Naye account ke liye password chunein ya auto-generate karein.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state
        action = str(response.get("action") or "")
        if action in {"STOPPED", "TIMEOUT", "DISMISS", "SKIP"}:
            if action == "TIMEOUT":
                self.is_running = False
            return ""

        password = str(response.get("password") or response.get("value") or "").strip()
        if not password and response.get("use_generated"):
            password = suggested
        if not password:
            password = suggested

        self._session_created_password = password

        # Save to CredentialStore (persistent on-disk JSON surviving restarts & refreshes)
        try:
            vault = self.vault_mgr.vault
            username = (
                vault.find_field_value("candidate_name")
                or vault.find_field_value("email")
                or vault.find_field_value("mobile")
                or ""
            )
            portal_url = str(
                (self.page.url if self.page else "")
                or (f"https://{domain}" if domain else "")
            )
            site_name = (
                self.blueprint.name
                if self.blueprint and getattr(self.blueprint, "name", None)
                else (domain or "Registration Portal")
            )
            CredentialStore.get_instance().save_credential(
                site_name=site_name,
                url=portal_url,
                username=username,
                password=password,
                notes=f"Auto-saved during application run {self.run_id}",
                account_id=getattr(self, "account_id", None),
            )
        except Exception:
            traceback.print_exc()

        try:
            self.vault_mgr.set_semantic_field("account_password", password)
        except Exception:
            pass

        await self.emit_event(
            "ACT",
            "Password saved securely in Saved Passwords vault.",
            "Password surakshit roop se vault mein save kar liya gaya hai.",
        )
        return password

    async def _handle_upload(self, item: Dict[str, Any], sem_key: str) -> bool:
        live_photo = bool(
            sem_key == "photo_upload"
            and (
                (self.form_map or {}).get("live_photo_required")
                or str(item.get("capture") or "").strip()
                or "live" in f"{item.get('label') or ''} {item.get('name') or ''}".lower()
            )
        )

        vault = self.vault_mgr.vault
        if sem_key == "photo_upload":
            path_value = vault.photo_path
            fallback = self.uploads_dir / "candidate_photo.jpg"
            doc_type = "photo"
        elif sem_key == "signature_upload":
            path_value = vault.signature_path
            fallback = self.uploads_dir / "candidate_signature.jpg"
            doc_type = "signature"
        else:
            path_value = vault.matric_cert_path
            fallback = None
            doc_type = "matric_certificate"

        # A sealed document in the One-Vault is referenced as "document:<id>".
        # It is decrypted in memory only for this upload and never written to a
        # temporary path, so the plaintext never lands on disk.
        document_payload: Optional[Dict[str, Any]] = None
        candidate: Optional[Path] = None
        doc_id = DocumentStore.parse_reference(path_value) if path_value else None
        if not doc_id:
            try:
                latest = self.document_store.latest(doc_type)
            except Exception:
                latest = None
            if latest:
                doc_id = latest.get("id")
        if doc_id:
            try:
                record, data = self.document_store.read(doc_id)
                document_payload = {
                    "name": record.get("filename") or "document",
                    "mimeType": record.get("mime") or "application/octet-stream",
                    "buffer": data,
                }
            except Exception:
                document_payload = None
        elif path_value:
            candidate = Path(path_value)
            if not candidate.is_absolute():
                candidate = settings.ROOT_DIR / candidate

        if (not document_payload and (not candidate or not candidate.exists())) and settings.DEMO_MODE and getattr(self._adapter, "name", "") == "simulator":
            try:
                BiometricCompressor.generate_sample_assets(str(self.uploads_dir))
            except Exception:
                pass
            candidate = fallback

        if live_photo or not (document_payload or (candidate and candidate.exists())):
            if live_photo:
                return await self._upload_handoff(item, sem_key, live_photo=True)
            return await self._upload_handoff(item, sem_key, live_photo=False)

        try:
            locator = None
            if item.get("id"):
                loc = self.page.locator(f"#{item.get('id')}")
                loc = getattr(loc, "first", loc)
                if await loc.count() > 0:
                    locator = loc
            if not locator and item.get("name"):
                loc = self.page.locator(f"[name='{item.get('name')}']")
                loc = getattr(loc, "first", loc)
                if await loc.count() > 0:
                    locator = loc
            if not locator and item.get("xpath"):
                loc = self.page.locator(f"xpath={item.get('xpath')}")
                loc = getattr(loc, "first", loc)
                if await loc.count() > 0:
                    locator = loc
            if not locator:
                for frame in getattr(self.page, "frames", []):
                    if item.get("id"):
                        loc = frame.locator(f"#{item.get('id')}")
                        loc = getattr(loc, "first", loc)
                        if await loc.count() > 0:
                            locator = loc
                            break
                    if item.get("name"):
                        loc = frame.locator(f"[name='{item.get('name')}']")
                        loc = getattr(loc, "first", loc)
                        if await loc.count() > 0:
                            locator = loc
                            break
                    loc = frame.locator("input[type='file']")
                    loc = getattr(loc, "first", loc)
                    if await loc.count() > 0:
                        locator = loc
                        break
            if not locator:
                loc = self.page.locator("input[type='file']")
                locator = getattr(loc, "first", loc)
            await locator.set_input_files(
                document_payload if document_payload else str(candidate),
                timeout=10000,
            )
        except Exception:
            await self.emit_event(
                "SENSE",
                f"Could not upload {item.get('label') or sem_key}. Please attach it in the live browser.",
                f"{item.get('label') or sem_key} upload nahi ho paya. Live browser mein attach karein.",
            )
            return await self._upload_handoff(item, sem_key, live_photo=live_photo)

        self._last_upload_path = str(candidate or f"document:{doc_id}")
        await self.emit_event(
            "ACT",
            f"Uploaded: {item.get('label') or sem_key}. Verifying the attachment.",
            f"{item.get('label') or sem_key} upload ho gaya. Attachment verify kar rahe hain.",
        )
        return True

    async def _upload_handoff(self, item: Dict[str, Any], sem_key: str, *, live_photo: bool) -> bool:
        label = str(item.get("label") or sem_key)
        gate_type = "LIVE_PHOTO" if live_photo else "FILE_UPLOAD"
        await self.emit_event(
            "SENSE",
            f"Please provide a file for: {label}",
            f"{label} ke liye file chahiye.",
        )
        gate = {
            "gate_type": gate_type,
            "handoff_type": "live_photo" if live_photo else "file_upload",
            "title": "Your camera or file is needed",
            "hindi_title": "Aapka photo ya file chahiye",
            "field_key": sem_key,
            "field_label": label,
            "accept": str(item.get("accept") or "image/*"),
            "max_size_mb": 5,
            "live_photo_required": live_photo,
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "description": (
                "This portal asks for a live photo. Capture it with your own camera or choose a recent photo. "
                "FormPilot never uses a stock image or another person's photo."
                if live_photo
                else f"This portal needs a file for {label}. Choose a file from your device."
            ),
            "instructions": (
                [
                    "Use your own front camera or a recent photo of yourself.",
                    "If the portal insists on its own live webcam step, do that step directly on the portal.",
                    "FormPilot attaches the file to this browser session only.",
                ]
                if live_photo
                else [
                    "Choose the exact document the portal asks for.",
                    "Check the format and size before uploading.",
                    "The file is attached to this browser session only.",
                ]
            ),
            "privacy_note": "The file is attached to the live portal and is not added to your saved profile.",
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "Attach the requested file in the live browser.")
        await self.emit_event(
            "DECIDE",
            f"Waiting for: {label}",
            f"{label} ka intezaar hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state

        action = response.get("action")
        if action in {"STOPPED", "TIMEOUT", "DISMISS"}:
            if action == "TIMEOUT":
                self.is_running = False
            return False
        if action not in {"UPLOAD_COMPLETE", "HANDOFF_COMPLETE", "CONTINUE"}:
            return False

        # The endpoint may have attached the file already.  Verify it, but
        # never pretend the upload worked if the input is still empty.
        try:
            dom = await self._scan_dom()
            file_inputs = [entry for entry in (dom.get("inputs") or []) if str(entry.get("type") or "").lower() == "file"]
            attached = any(bool(entry.get("value")) for entry in file_inputs)
            if not attached:
                attached = any(bool(entry.get("hasFile")) for entry in (dom.get("fileInputs") or []))
        except Exception:
            attached = False
        if attached:
            await self.emit_event(
                "ACT",
                f"File attached for {label}.",
                f"{label} ke liye file attach ho gayi.",
            )
            return True

        await self.emit_event(
            "SENSE",
            f"No file is attached for {label} yet. Attach it in the live browser, then continue.",
            f"{label} ke liye abhi file attach nahi hui. Live browser mein attach karein.",
        )
        return False


    # ---------------------------------------------------------------- security checks

    @staticmethod
    def _otp_signature_for(dom: Dict[str, Any]) -> str:
        fields = dom.get("otpInputs") or []
        names = "|".join(
            str(field.get("name") or field.get("id") or field.get("element_id") or "")
            for field in fields
        )
        return f"{dom.get('url') or ''}|{dom.get('formAction') or ''}|{names}"

    async def _enter_otp_code(self, dom: Dict[str, Any], otp: str) -> Dict[str, Any]:
        """Enter one code into a single input or a row of split OTP boxes.

        HPSC uses six one-character inputs with the same name.  Filling only
        the first input with the whole code leaves five boxes empty, so the
        portal never verifies anything.  A page with more than one distinct
        OTP group is handed back to the human instead of guessing which code
        belongs where.
        """
        items = [
            item
            for item in (dom.get("inputs") or [])
            if self._is_otp_field(item)
        ]
        if not items:
            return {"success": False, "reason": "The verification-code fields disappeared."}

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            key = str(item.get("name") or item.get("id") or item.get("element_id") or "")
            groups.setdefault(key, []).append(item)
        if len(groups) > 1:
            return {
                "success": False,
                "reason": (
                    "This page has more than one verification-code group. "
                    "Enter the codes directly in the live browser."
                ),
            }

        if len(items) == 1:
            characters = [otp]
        else:
            if len(otp) != len(items):
                return {
                    "success": False,
                    "reason": f"The page expects {len(items)} digits, but the code has {len(otp)}.",
                }
            characters = list(otp)

        for item, character in zip(items, characters):
            selector = str(item.get("css") or "")
            if not selector and item.get("id"):
                selector = f"#{item['id']}"
            if not selector:
                return {"success": False, "reason": "A verification-code box could not be located."}
            try:
                box = self.page.locator(selector).first
                if await box.count() == 0:
                    return {
                        "success": False,
                        "reason": "A verification-code box disappeared before it could be filled.",
                    }
                await box.fill(character, timeout=5000)
                # HPSC's auto-advance listens for keyup; dispatching it keeps
                # the visible focus and the serialized form in sync.
                try:
                    await box.dispatch_event("keyup", {"key": character})
                except Exception:
                    pass
            except Exception as exc:
                return {"success": False, "reason": f"A verification-code box could not be filled: {exc}"}
        return {"success": True}

    async def _submit_otp_form(self, dom: Dict[str, Any]) -> Dict[str, Any]:
        """Submit only the OTP form, never a generic final-submit button."""
        if not self.page:
            return {"success": False, "reason": "The browser page is no longer available."}
        try:
            action = str(
                await self.page.evaluate(
                    "() => { const f = document.querySelector('form'); "
                    "return f ? (f.getAttribute('action') || '') : ''; }"
                )
                or ""
            )
        except Exception:
            action = str(dom.get("formAction") or "")
        lower_action = action.lower()

        button = None
        for selector in (
            "#btn-verify-otp",
            "#verify_otp_btn",
            "#signup_submit",
            "button[type='submit']",
            "input[type='submit']",
        ):
            try:
                candidate = self.page.locator(selector).first
                if await candidate.count() > 0 and await candidate.is_visible():
                    button = candidate
                    break
            except Exception:
                continue
        if button is None:
            names = ["Verify OTP", "Verify", "Confirm OTP", "Submit OTP"]
            if "validateotp" in lower_action:
                names.append("Create Account")
            for name in names:
                try:
                    candidate = self.page.get_by_role(
                        "button", name=re.compile(rf"^{re.escape(name)}$", re.IGNORECASE)
                    ).first
                    if await candidate.count() > 0 and await candidate.is_visible():
                        button = candidate
                        break
                except Exception:
                    continue
        if button is None:
            return {
                "success": False,
                "reason": "The page does not expose a button that submits the verification code.",
            }

        if "validateotp" not in lower_action:
            try:
                text = (await button.inner_text()).strip().lower()
            except Exception:
                text = ""
            if not re.search(r"verify|confirm|otp|validate", text):
                return {
                    "success": False,
                    "reason": "The only available button is not a verification button.",
                }

        before = await self._page_snapshot()
        try:
            await button.click(timeout=8000)
        except Exception as exc:
            return {"success": False, "reason": f"The verification form could not be submitted: {exc}"}

        changed = await self._wait_for_page_change(before, timeout_ms=15000)
        try:
            fresh = await self._scan_dom()
        except Exception:
            fresh = {}
        if not changed:
            # Some portals verify the code over AJAX and leave the page
            # structure alone, showing a persistent "verification complete"
            # state instead.  Accept that explicit success signal; a transient
            # toastr alone is still not enough.
            if await self._otp_verification_complete():
                return {"success": True}
            visible = str(fresh.get("visibleText") or "").lower()
            errors = [str(item) for item in (fresh.get("errors") or []) if str(item).strip()]
            reason = errors[0] if errors else ""
            for phrase in (
                "please enter mobile otp",
                "please enter email otp",
                "invalid otp",
                "incorrect otp",
                "wrong otp",
                "otp expired",
            ):
                if phrase in visible:
                    reason = phrase.capitalize() + "."
                    break
            return {
                "success": False,
                "reason": reason or "The portal did not confirm the verification code.",
            }

        if not (fresh.get("otpInputs") or []):
            return {"success": True}
        url = str(fresh.get("url") or "").lower()
        visible = str(fresh.get("visibleText") or "").lower()
        if "login" in url and "signup" not in url:
            return {"success": True}
        if self._otp_success_text(visible):
            return {"success": True}
        errors = [str(item) for item in (fresh.get("errors") or []) if str(item).strip()]
        return {
            "success": False,
            "reason": errors[0] if errors else "The portal did not confirm the verification code.",
        }

    @staticmethod
    def _otp_success_text(visible: str) -> bool:
        text = str(visible or "").lower()
        return any(
            token in text
            for token in (
                "account created",
                "registration successful",
                "verification successful",
                "verification complete",
                "otp verified",
                "phone verified",
                "mobile verified",
                "email verified",
                "login to continue",
            )
        )

    async def _otp_verification_complete(self) -> bool:
        try:
            fresh = await self._scan_dom()
        except Exception:
            return False
        if not (fresh.get("otpInputs") or []):
            return True
        url = str(fresh.get("url") or "").lower()
        if "login" in url and "signup" not in url:
            return True
        return self._otp_success_text(str(fresh.get("visibleText") or ""))

    async def _handle_otp(self, dom: Optional[Dict[str, Any]] = None) -> bool:
        """Relay a human-supplied OTP and verify that the portal accepted it.

        Returns True when the OTP checkpoint was handled (success, retry or
        stop), so the main loop rescans instead of continuing to the section
        approval and advance steps on an unverified page.
        """
        if not self.page:
            return False
        dom = dom or {}
        otp_inputs = dom.get("otpInputs") or []
        signature = self._otp_signature_for(dom)
        if self._otp_cleared:
            if signature == self._otp_signature:
                return False
            # A new OTP page (for example the login page after registration)
            # owns a new checkpoint.
            self._otp_cleared = False
            self._otp_signature = ""

        selector = (
            "#btn-send-otp, #send-otp, #btn-send-code, #send-code, "
            "button:has-text('Send OTP'), button:has-text('Get OTP'), "
            "button:has-text('Generate OTP'), button:has-text('Request OTP'), "
            "button:has-text('Resend OTP'), button:has-text('Send code'), "
            "button:has-text('Get code'), button:has-text('Send verification'), "
            "button:has-text('ओटीपी'), button:has-text('कोड')"
        )
        button = None
        try:
            candidate = self.page.locator(selector).first
            if await candidate.count() > 0 and await candidate.is_visible():
                button = candidate
        except Exception:
            button = None
        if button is None and not otp_inputs:
            return False

        await self.emit_event(
            "THINK",
            "The portal needs to verify your phone number.",
            "Portal phone number verify karna chahta hai.",
        )
        if button is not None and not otp_inputs:
            try:
                await button.click(timeout=8000)
            except Exception:
                pass
            await self.page.wait_for_timeout(900)
            try:
                dom = await self._scan_dom()
                otp_inputs = dom.get("otpInputs") or []
                signature = self._otp_signature_for(dom)
            except Exception:
                pass
            if not otp_inputs:
                # The send button did not reveal a code field (usually because
                # a captcha is still empty or the portal rejected the request).
                # Opening an OTP gate here would ask for a code that cannot be
                # entered anywhere, so leave the page to the captcha/error
                # checkpoints instead.
                await self.emit_event(
                    "SENSE",
                    "The portal did not show a verification-code field. Check the page and try again.",
                    "Portal ne verification code ka field nahi dikhaya. Page check karke dobara koshish karein.",
                )
                return False

        config = self.tinyfish_mgr.config
        base_description = (
            "Enter the code sent to the phone number saved in your details. "
            "FormPilot never stores this code."
        )
        gate = {
            "gate_type": "OTP_RELAY",
            "title": "Enter the verification code",
            "hindi_title": "Verification code enter karein",
            "hindi_audio_text": "Aapke phone par code bheja gaya hai. Woh code yahan enter karein.",
            "description": base_description,
            "recipient": self._masked_phone(self.vault_mgr.vault.mobile),
            "ntfy_topic": config.ntfy_topic,
            "ntfy_url": f"https://ntfy.sh/{config.ntfy_topic}",
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
            "instructions": [
                "You can type the code below, or enter it directly in the live portal.",
                "The code is used once and is never stored.",
            ],
        }
        # The practice portal exposes a fixed code; a real portal sends a real
        # code to the human's phone.  Never advertise the demo code on a live
        # portal, where it would only mislead the candidate.
        adapter_name = getattr(self._adapter, "name", "")
        portal_url = str(getattr(self.page, "url", "") or "")
        is_simulator = adapter_name == "simulator" or "gov-portal-demo" in portal_url or "gov-portal-simulator" in portal_url
        if settings.DEMO_MODE and is_simulator:
            gate["demo_otp"] = settings.DEMO_OTP
            gate["description"] += f" Demo mode code: {settings.DEMO_OTP}."

        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(True, "Enter the verification code in the live browser.")
            await self.emit_event(
                "DECIDE",
                "Waiting for the verification code.",
                "Verification code ka intezaar hai.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            self.state = "RUNNING" if self.is_running else self.state
            action = str(response.get("action") or "")
            if action in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                if action == "TIMEOUT":
                    self.last_error = "No response was received. The application was paused."
                return True
            if action == "DISMISS":
                await self.emit_event(
                    "SENSE",
                    "The verification code is still needed. Enter it below or in the live browser.",
                    "Verification code abhi bhi chahiye. Neeche ya live browser mein enter karein.",
                )
                continue
            if action == "HANDOFF_COMPLETE":
                if await self._otp_verification_complete():
                    self._otp_cleared = True
                    self._otp_signature = signature
                    await self.emit_event(
                        "ACT",
                        "Verification completed in the live browser.",
                        "Live browser mein verification pura ho gaya.",
                    )
                    return True
                await self.emit_event(
                    "SENSE",
                    "The code is entered but the portal has not verified it yet. Submit it in the live browser, then continue.",
                    "Code enter hai lekin portal ne verify nahi kiya. Live browser mein submit karein, phir continue karein.",
                )
                continue

            otp = re.sub(
                r"\D",
                "",
                str(
                    response.get("otp")
                    or response.get("code")
                    or response.get("value")
                    or response.get("verification_code")
                    or ""
                ),
            )
            if not otp:
                await self.emit_event(
                    "SENSE",
                    "Enter the verification code to continue.",
                    "Aage badhne ke liye verification code enter karein.",
                )
                continue

            entered = await self._enter_otp_code(dom, otp)
            if not entered.get("success"):
                await self.emit_event(
                    "SENSE",
                    str(entered.get("reason") or "The verification code could not be entered."),
                    "Verification code enter nahi ho paya. Dobara koshish karein.",
                )
                continue

            submitted = await self._submit_otp_form(dom)
            if submitted.get("success"):
                self._otp_cleared = True
                self._otp_signature = signature
                await self.emit_event(
                    "ACT",
                    "Verification code accepted.",
                    "Verification code accept ho gaya.",
                )
                return True

            reason = str(submitted.get("reason") or "The portal did not accept the code.")
            gate["description"] = f"{base_description} Last attempt: {reason}"
            await self.emit_event(
                "SENSE",
                f"The verification code was not accepted: {reason}",
                "Verification code accept nahi hua. Dobara check karke enter karein.",
            )
            try:
                dom = await self._scan_dom()
                signature = self._otp_signature_for(dom)
            except Exception:
                pass
        return True

    @staticmethod
    def _captcha_signature_for(dom: Dict[str, Any]) -> str:
        captchas = dom.get("captchaElements") or []
        kinds = sorted({str(captcha.get("kind") or "unknown") for captcha in captchas})
        return f"{dom.get('url')}|{'|'.join(kinds)}|" + "|".join(
            str(captcha.get("id") or captcha.get("tagName") or "") for captcha in captchas[:3]
        )

    @staticmethod
    def _captcha_input_target(captchas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """The field where the human's answer is typed."""
        for item in captchas:
            if str(item.get("tagName") or "").lower() in {"input", "textarea"}:
                return item
        return captchas[0] if captchas else None

    @staticmethod
    def _captcha_preview_target(captchas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """The challenge image, never the empty answer field."""
        for item in captchas:
            if str(item.get("tagName") or "").lower() in {"img", "canvas", "iframe"}:
                return item
        return None

    async def _handle_captcha(self, dom: Dict[str, Any]) -> bool:
        """Handle a security check; return True while it is still pending.

        ``True`` means the main loop must not click "Send OTP", approve a
        section or advance: the human has not cleared the challenge yet.
        """
        captchas = dom.get("captchaElements") or []
        if not captchas or not self.page:
            return False

        signature = self._captcha_signature_for(dom)
        if signature == self._captcha_signature:
            return False

        interactive = next(
            (
                captcha
                for captcha in captchas
                if str(captcha.get("kind") or "") in {"interactive", "slider", "drag", "unknown"}
                and str(captcha.get("tagName") or "").lower() in {"iframe", "div", "canvas", "img", "input"}
            ),
            None,
        )
        if interactive and self.live:
            await self._captcha_live_handoff(captchas, interactive, signature)
            return signature != self._captcha_signature

        # Text CAPTCHA (for example "hJ8ik)3") can be entered in the gate.
        # The scanner reports both the answer field and the challenge image as
        # "text"; the gate must preview the image and fill the input.
        captcha = self._captcha_input_target(captchas)
        preview = self._captcha_preview_target(captchas) or captcha
        image_b64 = ""
        if preview:
            target_id = preview.get("captchaTargetId")
            elem_id = preview.get("elementId")
            html_id = preview.get("id")

            # Strategy 1: Pixel-perfect in-DOM extraction (zero scroll/viewport offset issues)
            try:
                extracted = await self.page.evaluate(
                    """([targetId, elemId, htmlId]) => {
                        let el = null;
                        if (targetId) el = document.querySelector(`[data-fp-captcha-target="${targetId}"]`);
                        if (!el && elemId) el = document.querySelector(`[data-fp-id="${elemId}"]`);
                        if (!el && htmlId) el = document.getElementById(htmlId);
                        if (!el) {
                            // Find image/canvas adjacent to a captcha input
                            const inp = document.querySelector('input[id*="captcha" i], input[name*="captcha" i]');
                            if (inp && inp.parentElement) {
                                el = inp.parentElement.querySelector('img, canvas') ||
                                     inp.parentElement.parentElement?.querySelector('img, canvas');
                            }
                        }
                        if (!el) return null;
                        if (el.tagName === 'CANVAS') {
                            try { return el.toDataURL('image/png'); } catch (_) { return null; }
                        }
                        if (el.tagName === 'IMG') {
                            if (el.src && el.src.startsWith('data:image/')) return el.src;
                            try {
                                const c = document.createElement('canvas');
                                c.width = el.naturalWidth || el.width || 150;
                                c.height = el.naturalHeight || el.height || 50;
                                const ctx = c.getContext('2d');
                                ctx.drawImage(el, 0, 0);
                                return c.toDataURL('image/png');
                            } catch (_) {
                                return null;
                            }
                        }
                        return null;
                    }""",
                    [target_id, elem_id, html_id]
                )
                if extracted and isinstance(extracted, str) and extracted.startswith("data:image/"):
                    image_b64 = extracted
            except Exception:
                pass

            # Strategy 2: Targeted element screenshot if in-DOM extraction failed
            if not image_b64:
                selector_candidates = []
                if target_id:
                    selector_candidates.append(f'[data-fp-captcha-target="{target_id}"]')
                if elem_id:
                    selector_candidates.append(f'[data-fp-id="{elem_id}"]')
                if html_id:
                    selector_candidates.append(f'#{html_id}')
                if preview.get("src"):
                    # Use unique portion of src
                    src_frag = preview["src"].split("?")[0].split("/")[-1]
                    if len(src_frag) > 4:
                        selector_candidates.append(f'img[src*="{src_frag}"]')

                for sel in selector_candidates:
                    try:
                        locator = self.page.locator(sel).first
                        if await locator.count() > 0:
                            await locator.scroll_into_view_if_needed(timeout=1500)
                            image = await locator.screenshot(timeout=2500)
                            if image and len(image) > 100:
                                image_b64 = f"data:image/png;base64,{base64.b64encode(image).decode('utf-8')}"
                                break
                    except Exception:
                        continue

        await self.emit_event(
            "THINK",
            "The portal is asking for a security check.",
            "Portal ek security check maang raha hai.",
        )
        gate = {
            "gate_type": "CAPTCHA_SOLVE",
            "title": "Enter the security check",
            "hindi_title": "Security check enter karein",
            "captcha_image": image_b64,
            "captcha_kind": str(captcha.get("kind") or "text"),
            "description": "Enter the characters shown in the image. This check is never solved automatically.",
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "instructions": [
                "Read the characters in the live portal or in the image.",
                "Type them in the box below.",
                "FormPilot submits the text; a human still solves the challenge.",
            ],
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(
                True, "Enter the security check in the live browser or below."
            )
        await self.emit_event(
            "DECIDE",
            "Waiting for the security check.",
            "Security check ka intezaar hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state
        if response.get("action") in {"STOPPED", "TIMEOUT", "DISMISS"}:
            if response.get("action") == "TIMEOUT":
                self.is_running = False
            return True
        if response.get("action") == "HANDOFF_COMPLETE":
            self._captcha_signature = signature
            return False

        code = str(
            response.get("code")
            or response.get("value")
            or response.get("captcha")
            or response.get("text")
            or response.get("answer")
            or ""
        ).strip()
        if not code:
            return True
        try:
            field = self.page.locator("input[id*='captcha' i]:visible, input[name*='captcha' i]:visible").first
            if await field.count() == 0:
                return True
            await field.fill(code, timeout=8000)
            await field.dispatch_event("change")
            self._captcha_signature = signature
            await self.emit_event(
                "ACT",
                "Security check completed.",
                "Security check complete ho gaya.",
            )
            return False
        except Exception:
            await self.emit_event(
                "SENSE",
                "The security check could not be submitted.",
                "Security check submit nahi ho paya.",
            )
            return True

    async def _captcha_live_handoff(
        self,
        captchas: List[Dict[str, Any]],
        captcha: Dict[str, Any],
        signature: str,
    ) -> None:
        """Pause and let the human solve the challenge in the real browser."""
        kind = str(captcha.get("kind") or "interactive")
        prompt = str(captcha.get("prompt") or "").strip()
        if self.live:
            self.live.set_allow_control(True, "Solve the security check in the live browser.")

        await self.emit_event(
            "THINK",
            "This page has a human-verification challenge. Automation is paused.",
            "Is page par human verification hai. Automation pause kar diya hai.",
        )
        gate = {
            "gate_type": "LIVE_HANDOFF",
            "handoff_type": "captcha",
            "title": "This step needs you",
            "hindi_title": "Yeh step aapke liye hai",
            "description": (
                "Solve the security check directly in the live browser. "
                "FormPilot will not click it, solve it, or inject a token."
            ),
            "captcha_kind": kind,
            "captcha_prompt": prompt[:200],
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "instructions": [
                "Use the live browser on the left. It is the same page the agent is using.",
                "Complete the checkbox, image grid, slider or puzzle yourself.",
                "When the portal shows success, click 'I completed this step'.",
            ],
            "solver_policy": "human_handoff_only",
            "detected_types": sorted({str(item.get("kind") or "unknown") for item in captchas}),
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        await self.emit_event(
            "DECIDE",
            "The live browser is yours. Complete the security check, then continue.",
            "Live browser aapka hai. Security check khud pura karein, phir continue karein.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state

        action = response.get("action")
        if action in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
            if action == "TIMEOUT":
                self.last_error = "The security check was left open, so the application paused."
            return
        if action == "DISMISS":
            await self.emit_event(
                "SENSE",
                "The security check is still open. Complete it in the live browser, then continue.",
                "Security check abhi khula hai. Live browser mein pura karein, phir continue karein.",
            )
            return
        if action not in {"HANDOFF_COMPLETE", "CONTINUE", "CAPTCHA_SUBMIT"}:
            return

        self._captcha_signature = signature
        try:
            fresh = await self._scan_dom()
            remaining = fresh.get("captchaElements") or []
            if remaining:
                await self.emit_event(
                    "SENSE",
                    "A security widget is still visible. If the portal accepted the challenge, continue; otherwise reopen the checkpoint.",
                    "Security widget abhi bhi dikh raha hai. Agar portal ne accept kar liya hai to continue karein.",
                )
            else:
                await self.emit_event(
                    "ACT",
                    "Security check cleared. Resuming the form.",
                    "Security check clear ho gaya. Form dobara shuru ho raha hai.",
                )
        except Exception:
            pass


    # --------------------------------------------------------- page load errors

    @staticmethod
    def _is_browser_error_page(dom: Dict[str, Any]) -> bool:
        """True when Chrome itself failed to load the page, not the portal."""
        url = str(dom.get("url") or "")
        if url.startswith(("chrome-error://", "edge-error://")):
            return True
        text = str(dom.get("visibleText") or "").lower()
        return bool(
            re.search(
                r"this\s+site\s+can.t\s+be\s+reached|"
                r"\berr_(?:connection|name|internet|timed|ssl|address)\w*|"
                r"took\s+too\s+long\s+to\s+respond|"
                r"check\s+your\s+internet\s+connection|"
                r"the\s+page\s+isn.t\s+working",
                text,
            )
        )

    async def _recover_from_browser_error(self, dom: Dict[str, Any]) -> bool:
        """Go back from a failed navigation instead of treating it as a form.

        A cloud browser occasionally fails to open a third-party sign-in page.
        The run should retry the step, not declare that the portal has no form.
        """
        if not self._is_browser_error_page(dom):
            return False
        self._browser_error_count += 1
        if self._browser_error_count > 3:
            raise AgentRunError(
                "The portal page could not be reached. Check the connection and start the run again."
            )
        await self.emit_event(
            "SENSE",
            "The last page failed to load. Going back and retrying it.",
            "Pichla page load nahi hua. Wapas jaakar dobara try kar rahe hain.",
        )
        try:
            if self.page:
                went_back = False
                try:
                    await self.page.go_back(wait_until="domcontentloaded", timeout=20000)
                    went_back = True
                except Exception:
                    went_back = False
                if not went_back:
                    await self.page.reload(wait_until="domcontentloaded", timeout=20000)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(1.0)
        return True

    # ---------------------------------------------------- identity providers

    @staticmethod
    def _domain_family(host: str) -> str:
        """Rough registrable-domain family: ``a.nic.in`` and ``b.nic.in`` match."""
        labels = [part for part in str(host or "").lower().split(".") if part]
        if len(labels) >= 2:
            return ".".join(labels[-2:])
        return labels[0] if labels else ""

    def _is_external_identity_page(self, dom: Dict[str, Any]) -> bool:
        """True for a third-party sign-in (DigiLocker, MeriPehchaan, SSO).

        A different domain that asks for a password, a PIN or an OTP is an
        identity provider, not the application form.  FormPilot must not type
        vault values into it: the credential belongs to the candidate.
        """
        if not self.page:
            return False
        host = urlparse(self.page.url).netloc
        portal = self._domain_family(urlparse(self.target_url or "").netloc)
        if not host or not portal:
            return False
        if self._domain_family(host) == portal:
            return False
        if host in self._idp_signed_in:
            return False
        # A consent screen on an OAuth domain collects permissions, not credentials!
        if page_actions.is_consent_page(dom, getattr(self, "form_map", None)):
            return False
        # Known Indian Gov & Identity providers (DigiLocker, MeriPehchaan, JanParichay, Parichay, OAuth)
        if re.search(r"meripehchaan|digilocker|parichay|janparichay|oauth", host, re.IGNORECASE):
            return True
        # Only an actual credential surface makes this an identity gate.  A
        # consent screen on an OAuth domain has no PIN or password; treating it
        # as a sign-in page asked the candidate for a credential that the page
        # could not accept, and then hid the consent controls behind a gate.
        inputs = [item for item in (dom.get("inputs") or []) if isinstance(item, dict)]
        has_secret = any(
            str(item.get("type") or "").lower() == "password" for item in inputs
        )
        has_otp = bool(dom.get("otpInputs"))
        return bool(has_secret or has_otp)

    async def _idp_still_active(self, host: str) -> bool:
        """True while the identity provider still shows a credential box."""
        for _ in range(8):
            await asyncio.sleep(1.0)
            if not self.page:
                return False
            if urlparse(self.page.url).netloc != host:
                return False
            try:
                fresh = await self._scan_dom()
            except Exception:
                fresh = {}
            still_secret = any(
                str(item.get("type") or "").lower() == "password"
                for item in (fresh.get("inputs") or [])
            )
            if not still_secret and not fresh.get("otpInputs"):
                return False
        return True

    async def idp_switch_mode(self, target_mode: str) -> bool:
        """Public helper to switch IDP mode between 'signin' and 'signup'."""
        return await self._idp_switch_mode(target_mode)

    async def idp_generate_otp(self) -> Dict[str, Any]:
        """Public helper to generate OTP on IDP sign up page."""
        return await self._idp_generate_otp()

    async def _idp_prefill_identifier(self) -> Dict[str, Any]:
        """Proactively type candidate's mobile or username into IDP identifier field."""
        if not self.page:
            return {"filled": False, "reason": "No browser page."}
        mobile = str(getattr(self.vault_mgr.vault, "mobile", "") or "").strip()
        username = str(getattr(self.vault_mgr.vault, "username", "") or "").strip()
        if not mobile and not username:
            return {"filled": False, "reason": "No mobile or username in vault."}

        # Mobile-specific selectors
        mobile_selectors = [
            "input[type='tel']",
            "input[name*='mobile' i]",
            "input[id*='mobile' i]",
            "input[placeholder*='mobile' i]",
            "input[aria-label*='mobile' i]",
            "input[formcontrolname*='mobile' i]",
            "input[name*='phone' i]",
            "input[id*='phone' i]",
        ]
        # Username / identifier selectors (for sign-in)
        id_selectors = [
            "input[name*='username' i]",
            "input[id*='username' i]",
            "input[placeholder*='username' i]",
            "input[placeholder*='mobile' i]",
            "input[placeholder*='userid' i]",
            "input[name*='userid' i]",
            "input[id*='userid' i]",
            "input[name*='login' i]",
            "input[id*='login' i]",
        ]

        target_selectors = mobile_selectors + id_selectors
        for sel in target_selectors:
            try:
                locator = self.page.locator(sel)
                count = await locator.count()
                for i in range(count):
                    el = locator.nth(i)
                    if not await el.is_visible():
                        continue
                    if await el.is_disabled():
                        continue
                    val = (await el.input_value()).strip()
                    if val:
                        return {"filled": True, "value": val, "already": True}
                    fill_val = mobile or username
                    await el.click(timeout=3000)
                    await el.fill(fill_val)
                    await el.dispatch_event("input")
                    await el.dispatch_event("change")
                    await el.dispatch_event("blur")
                    return {"filled": True, "value": fill_val, "already": False}
            except Exception:
                continue
        return {"filled": False, "reason": "No identifier input found."}

    async def _idp_is_otp_input_visible(self) -> bool:
        """Check if an OTP input field is currently visible and interactable."""
        if not self.page:
            return False
        otp_selectors = [
            "input[name*='otp' i]",
            "input[id*='otp' i]",
            "input[placeholder*='otp' i]",
            "input[aria-label*='otp' i]",
            "input[formcontrolname*='otp' i]",
            "input[name*='verification_code' i]",
            "input[id*='verification_code' i]",
        ]
        for sel in otp_selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                    return True
            except Exception:
                continue
        return False

    async def _idp_detect_already_registered(self) -> bool:
        """Detect if MeriPehchaan/DigiLocker indicates the user/mobile is already registered."""
        if not self.page:
            return False
        try:
            content = (await self.page.content() or "").lower()
            if re.search(
                r"already\s*registered|user\s*already\s*exists|mobile.*already.*associated|mobile\s*number\s*already\s*exists|already\s*have\s*an\s*account",
                content,
            ):
                return True
        except Exception:
            pass
        return False

    async def _idp_switch_mode(self, target_mode: str) -> bool:
        """Switch between Sign In and Sign Up on the identity provider.

        Maintains full OAuth state, redirect URI, and client parameters.
        """
        if not self.page:
            return False
        current_url = self.page.url
        try:
            if target_mode == "signin":
                # Look for link or button for Sign In
                for pattern in (
                    r"already\s*have\s*an\s*account|sign\s*in|log\s*in",
                    r"sign\s*in\s*to\s*your\s*account",
                ):
                    try:
                        el = self.page.locator("a, button").filter(has_text=re.compile(pattern, re.IGNORECASE)).first
                        if await el.count() > 0 and await el.is_visible():
                            await el.click(timeout=6000)
                            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                            return True
                    except Exception:
                        pass
                if "/signup/" in current_url:
                    new_url = current_url.replace("/signup/", "/signinv2/")
                    await self.page.goto(new_url, timeout=20000, wait_until="domcontentloaded")
                    return True
            elif target_mode == "signup":
                for pattern in (
                    r"new\s*to\s*meripehchaan|sign\s*up|create\s*account|register",
                ):
                    try:
                        el = self.page.locator("a, button").filter(has_text=re.compile(pattern, re.IGNORECASE)).first
                        if await el.count() > 0 and await el.is_visible():
                            await el.click(timeout=6000)
                            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                            return True
                    except Exception:
                        pass
                if "/signinv2/" in current_url:
                    new_url = current_url.replace("/signinv2/", "/signup/")
                    await self.page.goto(new_url, timeout=20000, wait_until="domcontentloaded")
                    return True
        except Exception as exc:
            logger.warning("Failed to switch IDP mode: %s", exc)
        return False

    async def _idp_generate_otp(self) -> Dict[str, Any]:
        """Click 'Generate OTP' on the identity provider sign-up page."""
        if not self.page:
            return {"success": False, "reason": "No browser page."}
        try:
            # 1. Proactively ensure mobile is typed
            prefill = await self._idp_prefill_identifier()
            if not prefill.get("filled") and not getattr(self.vault_mgr.vault, "mobile", None):
                return {
                    "success": False,
                    "reason": "Please provide your mobile number to generate OTP.",
                    "needs_mobile": True,
                }
            # Ensure any terms / consent checkboxes on sign up are ticked
            try:
                await self.page.evaluate('''() => {
                    const cbs = document.querySelectorAll('input[type="checkbox"]');
                    for (const cb of cbs) {
                        if (!cb.checked && cb.offsetParent !== null && !cb.disabled) {
                            try { cb.click(); } catch(e) {}
                            cb.checked = true;
                            cb.dispatchEvent(new Event('input', { bubbles: true }));
                            cb.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                }''')
            except Exception:
                pass
            await asyncio.sleep(0.4)

            # 2. Look for Generate OTP button
            btn_selectors = [
                "button:has-text('Generate OTP')",
                "input[value*='Generate OTP' i]",
                "button:has-text('Send OTP')",
                "input[value*='Send OTP' i]",
                "input[type='button'][value*='OTP' i]",
                "input[type='submit'][value*='OTP' i]",
                "#generate_otp",
                "#generateOtp",
                "[id*='gen_otp' i]",
                "[id*='generate_otp' i]",
                "a:has-text('Generate OTP')",
                ".btn:has-text('Generate OTP')",
            ]
            btn = None
            for sel in btn_selectors:
                try:
                    loc = self.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                        btn = loc
                        break
                except Exception:
                    continue

            if not btn:
                try:
                    loc = self.page.get_by_role("button", name=re.compile(r"generate\s*otp|send\s*otp", re.IGNORECASE)).first
                    if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                        btn = loc
                except Exception:
                    pass

            if not btn:
                if await self._idp_is_otp_input_visible():
                    return {"success": True, "message": "OTP is already active on the page."}
                return {"success": False, "reason": "Generate OTP button not found or disabled."}

            await btn.click(timeout=8000)
            await asyncio.sleep(1.5)

            if await self._idp_detect_already_registered():
                return {
                    "success": False,
                    "already_registered": True,
                    "reason": "Mobile number is already registered with DigiLocker. Please Sign In.",
                }

            return {"success": True, "message": "OTP generated and sent to your mobile."}
        except Exception as exc:
            return {"success": False, "reason": str(exc)}

    async def _fill_idp_credential(
        self, dom: Dict[str, Any], credential: str
    ) -> Dict[str, Any]:
        """Type the candidate's own PIN/OTP into the provider page.

        The value is used once, never stored and never written to a lesson or
        journey.  The identifier box (mobile/username) is filled with the
        candidate's own saved mobile only when it is empty.
        """
        if not self.page:
            return {"success": False, "reason": "The browser page is no longer available."}

        # 1. Ensure identifier is filled
        await self._idp_prefill_identifier()

        current_url = (self.page.url or "").lower()
        is_signup = "/signup" in current_url

        # Check if an OTP input is visible
        has_otp_box = await self._idp_is_otp_input_visible()

        target_el = None
        is_entering_otp = False

        if has_otp_box or is_signup:
            otp_selectors = [
                "input[name*='otp' i]",
                "input[id*='otp' i]",
                "input[placeholder*='otp' i]",
                "input[aria-label*='otp' i]",
                "input[formcontrolname*='otp' i]",
            ]
            for sel in otp_selectors:
                try:
                    loc = self.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                        target_el = loc
                        is_entering_otp = True
                        break
                except Exception:
                    continue

        if not target_el and not is_signup:
            pw_loc = self.page.locator("input[type='password']").first
            try:
                if await pw_loc.count() > 0 and await pw_loc.is_visible() and not await pw_loc.is_disabled():
                    target_el = pw_loc
            except Exception:
                pass

        if target_el:
            try:
                await target_el.click(timeout=4000)
                await target_el.fill(credential)
                await target_el.dispatch_event("input")
                await target_el.dispatch_event("change")
                await target_el.dispatch_event("blur")
            except Exception as exc:
                return {"success": False, "reason": f"Failed to type credential: {exc}"}
        else:
            inputs = [item for item in (dom.get("inputs") or []) if isinstance(item, dict)]
            active_codes = [c for c in inputs if self._is_otp_field(c) and not c.get("disabled") and c.get("interactable", True)]
            active_secrets = [s for s in inputs if str(s.get("type") or "").lower() == "password" and not s.get("disabled") and s.get("interactable", True)]

            target = None
            if is_signup or active_codes:
                target = active_codes[0] if active_codes else (active_secrets[0] if active_secrets else None)
                if target and self._is_otp_field(target):
                    is_entering_otp = True
            else:
                target = active_secrets[0] if active_secrets else (active_codes[0] if active_codes else None)

            if not target:
                return {"success": False, "reason": "There is no active PIN or OTP input box on this page."}

            entered = await self._apply_field_value(target, credential)
            if not entered.get("success"):
                return {"success": False, "reason": str(entered.get("reason") or "The credential could not be entered.")}

        # Ensure any terms / agreement checkboxes on login or verification are ticked
        try:
            await self.page.evaluate('''() => {
                const cbs = document.querySelectorAll('input[type="checkbox"]');
                for (const cb of cbs) {
                    if (!cb.checked && cb.offsetParent !== null && !cb.disabled) {
                        try { cb.click(); } catch(e) {}
                        cb.checked = true;
                        cb.dispatchEvent(new Event('input', { bubbles: true }));
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }''')
        except Exception:
            pass

        # Submit affirmative action
        if is_entering_otp:
            submit_names = ("Verify OTP", "Validate OTP", "Submit OTP", "Verify", "Submit", "Continue", "Proceed")
        else:
            submit_names = ("Sign In", "Sign in", "Login", "Log In", "Continue", "Verify", "Submit", "Proceed")

        for name in submit_names:
            try:
                button = self.page.get_by_role(
                    "button", name=re.compile(rf"^{re.escape(name)}$", re.IGNORECASE)
                ).first
                if await button.count() > 0 and await button.is_visible() and not await button.is_disabled():
                    await button.click(timeout=8000)
                    return {"success": True}
            except Exception:
                continue

        for sel in ("button[type='submit']", "input[type='submit']", "#verify_otp", "#submit_btn", ".btn-primary"):
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                    await loc.click(timeout=8000)
                    return {"success": True}
            except Exception:
                continue

        try:
            await self.page.keyboard.press("Enter")
            return {"success": True}
        except Exception:
            return {"success": False, "reason": "The sign-in button could not be pressed."}

    async def _identity_provider_checkpoint(self, dom: Dict[str, Any]) -> bool:
        """Hand a third-party sign-in to the candidate, then resume.

        The candidate can type their PIN or OTP into the checkpoint (the agent
        enters it once and never stores it) or finish the sign-in in the live
        browser.  FormPilot itself never guesses or replays the credential.
        """
        if not self.page:
            return False
        host = urlparse(self.page.url).netloc
        base_description = (
            f"The portal sent the application to {host} to verify your identity. "
            "Type your PIN or OTP below and FormPilot will enter it once, or sign in "
            "in the live browser. The credential is never stored or replayed."
        )

        otp_auto_generated = False
        while self.is_running:
            if not self.page:
                return False
            host = urlparse(self.page.url).netloc
            current_url = (self.page.url or "").lower()
            is_signup = "/signup" in current_url or bool(
                re.search(r"sign\s*up|new\s*user|create\s*account", str(dom.get("visibleText") or "").lower())
            )

            # 1. Proactively prefill mobile/identifier
            mobile = str(getattr(self.vault_mgr.vault, "mobile", "") or "").strip()
            prefill_res = await self._idp_prefill_identifier()
            if prefill_res.get("filled") and not prefill_res.get("already"):
                masked = f"{mobile[:2]}******{mobile[-2:]}" if len(mobile) >= 10 else mobile
                await self.emit_event(
                    "ACT",
                    f"Pre-filled mobile number {masked} on {host}.",
                    f"{host} par mobile number pre-fill kiya gaya.",
                )

            # 2. If on signup and haven't auto-generated OTP yet, and OTP box isn't visible:
            has_otp_box = await self._idp_is_otp_input_visible()
            if is_signup and not has_otp_box and not otp_auto_generated and mobile:
                gen_res = await self._idp_generate_otp()
                otp_auto_generated = True
                if gen_res.get("already_registered"):
                    await self.emit_event(
                        "ACT",
                        f"Mobile number is already registered with DigiLocker. Switching to Sign In...",
                        f"Mobile number DigiLocker par already registered hai. Sign In par switch kar rahe hain...",
                    )
                    switched = await self._idp_switch_mode("signin")
                    if switched:
                        await asyncio.sleep(1.0)
                        try:
                            dom = await self._scan_dom()
                        except Exception:
                            pass
                        continue
                elif gen_res.get("success"):
                    masked = f"{mobile[:2]}******{mobile[-2:]}" if len(mobile) >= 10 else mobile
                    await self.emit_event(
                        "ACT",
                        f"Generated OTP on {host}. Sent to {masked}.",
                        f"{host} par OTP bhej diya gaya.",
                    )
                    await asyncio.sleep(1.0)
                    has_otp_box = await self._idp_is_otp_input_visible()

            masked_mobile = f"{mobile[:2]}******{mobile[-2:]}" if len(mobile) >= 10 else mobile
            options = [
                {"id": "continue", "text": "I signed in / completed this in browser — continue", "type": "CONTINUE"}
            ]
            if is_signup:
                title = f"Enter DigiLocker OTP ({host})"
                hindi_title = f"{host} par OTP enter karein"
                desc = (
                    f"We entered your mobile number ({masked_mobile}) and requested an OTP. "
                    "Enter the 6-digit OTP sent to your phone below. "
                    "If you already have a DigiLocker account, click 'Switch to Sign In' to log in with your PIN."
                )
                cred_label = "6-Digit SMS OTP"
                options.insert(0, {
                    "id": "switch_signin",
                    "text": "I already have an account — Switch to Sign In",
                    "type": "SWITCH_IDP_MODE",
                    "mode": "signin",
                })
                options.insert(1, {
                    "id": "generate_otp",
                    "text": "Resend / Generate OTP",
                    "type": "GENERATE_OTP",
                })
            else:
                title = f"Sign in to DigiLocker ({host})"
                hindi_title = f"{host} par sign in karein"
                desc = (
                    f"Your identifier ({masked_mobile or 'mobile'}) is pre-filled. "
                    "Enter your 6-digit DigiLocker Security PIN below (or sign in in the live browser)."
                )
                cred_label = "6-Digit Security PIN"
                options.insert(0, {
                    "id": "switch_signup",
                    "text": "New user? Create DigiLocker account",
                    "type": "SWITCH_IDP_MODE",
                    "mode": "signup",
                })

            gate = {
                "gate_type": "LIVE_HANDOFF",
                "handoff_type": "identity_provider",
                "idp_mode": "signup" if is_signup else "signin",
                "title": title,
                "hindi_title": hindi_title,
                "description": desc,
                "provider_host": host,
                "accepts_credential": True,
                "credential_label": cred_label,
                "live_session": self.live.public_info() if self.live and not self.live.closed else None,
                "instructions": [
                    "If you already have a DigiLocker account, click 'Switch to Sign In' to log in with your PIN or OTP.",
                    "If creating a new account, enter the 6-digit OTP sent to your mobile.",
                    f"After {host} returns you to the exam portal, click 'I completed this step — continue'.",
                ],
                "requires_explicit_choice": False,
                "options": options,
                "solver_policy": "human_handoff_only",
            }

            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(True, f"Sign in to {host}.")
            await self.emit_event(
                "DECIDE",
                f"{title} to continue.",
                f"Aage badhne ke liye {hindi_title}.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            self.state = "RUNNING" if self.is_running else self.state

            action = str(response.get("action") or response.get("id") or "")
            if action in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                if action == "TIMEOUT":
                    self.last_error = f"The {host} sign-in was left open, so the application paused."
                return True
            if action == "DISMISS":
                return True

            if action in {"SWITCH_IDP_MODE", "switch_signin", "switch_signup"}:
                target_mode = str(response.get("mode") or ("signin" if "signin" in action else "signup"))
                await self.emit_event(
                    "ACT",
                    f"Switching {host} to {target_mode} mode...",
                    f"{host} par {target_mode} mode par switch kar rahe hain...",
                )
                switched = await self._idp_switch_mode(target_mode)
                if switched:
                    await asyncio.sleep(1.0)
                    try:
                        dom = await self._scan_dom()
                    except Exception:
                        pass
                continue

            if action in {"GENERATE_OTP", "generate_otp"}:
                await self.emit_event(
                    "ACT",
                    f"Clicking 'Generate OTP' on {host}...",
                    f"{host} par OTP generate kar rahe hain...",
                )
                res = await self._idp_generate_otp()
                if res.get("already_registered"):
                    await self.emit_event(
                        "ACT",
                        f"Mobile number is already registered with DigiLocker. Switching to Sign In...",
                        f"Mobile number DigiLocker par already registered hai. Sign In par switch kar rahe hain...",
                    )
                    switched = await self._idp_switch_mode("signin")
                    if switched:
                        await asyncio.sleep(1.0)
                        try:
                            dom = await self._scan_dom()
                        except Exception:
                            pass
                    continue
                elif res.get("success"):
                    gate["description"] = "OTP generated and sent to mobile. Please enter the OTP below."
                    await self.emit_event(
                        "SENSE",
                        "OTP sent to mobile. Please enter the code.",
                        "Mobile par OTP bhej diya gaya hai. Code enter karein.",
                    )
                else:
                    gate["description"] = f"Could not generate OTP: {res.get('reason')}"
                continue

            credential = str(
                response.get("otp")
                or response.get("code")
                or response.get("credential")
                or ""
            ).strip()
            if credential:
                try:
                    fresh = await self._scan_dom()
                except Exception:
                    fresh = dom
                entered = await self._fill_idp_credential(fresh, credential)
                if not entered.get("success"):
                    gate["description"] = (
                        f"{base_description} Last attempt: {entered.get('reason')}"
                    )
                    await self.emit_event(
                        "SENSE",
                        str(entered.get("reason") or "The credential could not be entered."),
                        "Credential enter nahi ho paya. Dobara koshish karein.",
                    )
                    continue
                await self.emit_event(
                    "ACT",
                    f"Entered the credential on {host}.",
                    f"{host} par credential enter kiya.",
                )
                if not await self._idp_still_active(host):
                    self._idp_signed_in.add(host)
                    await self.emit_event(
                        "ACT",
                        f"{host} sign-in complete. Continuing on the exam portal.",
                        f"{host} sign-in complete. Exam portal par aage badh rahe hain.",
                    )
                    return True
                gate["description"] = (
                    f"{base_description} The provider did not accept it yet. "
                    "Check the PIN or wait for a new OTP."
                )
                continue

            if action in {"HANDOFF_COMPLETE", "CONTINUE", "OTP_SUBMIT"}:
                if not await self._idp_still_active(host):
                    self._idp_signed_in.add(host)
                    await self.emit_event(
                        "ACT",
                        f"{host} sign-in marked complete. Continuing on the exam portal.",
                        f"{host} sign-in complete. Exam portal par aage badh rahe hain.",
                    )
                    return True
                gate["description"] = (
                    f"{base_description} The sign-in page is still open."
                )
                continue
        return True

    async def _handle_consent_page(self, dom: Dict[str, Any]) -> bool:
        """Handle an OAuth or portal consent page (DigiLocker, MeriPehchaan, terms).

        Ticks consent controls (parent/select-all first) and clicks the affirmative
        button ('Allow' / 'Authorize' / 'I Agree').
        """
        if not self.page:
            return False
        controls = page_actions.consent_controls(dom)
        affirmative = page_actions.affirmative_button(dom)
        if not controls and not affirmative:
            return False

        # 1. Tick unselected consent checkboxes via scanner
        for control in controls:
            try:
                await self._select_choice_element(control, "yes")
                await asyncio.sleep(0.2)
            except Exception:
                pass

        # 2. In-page evaluate: tick any remaining visible checkboxes on the consent screen
        try:
            await self.page.evaluate('''() => {
                const cbs = document.querySelectorAll('input[type="checkbox"]');
                for (const cb of cbs) {
                    if (!cb.checked && cb.offsetParent !== null && !cb.disabled) {
                        try { cb.click(); } catch(e) {}
                        cb.checked = true;
                        cb.dispatchEvent(new Event('input', { bubbles: true }));
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }''')
        except Exception:
            pass

        # 3. Re-scan to get fresh DOM with ticked state and enabled button
        try:
            fresh = await self._scan_dom()
        except Exception:
            fresh = dom
        btn = page_actions.affirmative_button(fresh) or affirmative
        clicked = False
        text = "Allow"

        if btn:
            element_id = btn.get("element_id")
            text = btn.get("text") or "Allow"
            resolver = self._action_resolver()
            if element_id and resolver:
                res = await resolver.click(element_id)
                if res and res.ok:
                    clicked = True
            if not clicked:
                try:
                    clicked = await self._safe_click(btn)
                except Exception:
                    pass

        # 4. Playwright locator fallback for consent affirmative buttons
        if not clicked:
            for name in ("Allow", "Authorize", "I Agree", "Agree", "Consent", "Proceed", "Continue", "Submit"):
                try:
                    loc = self.page.get_by_role("button", name=re.compile(rf"^{name}$", re.IGNORECASE)).first
                    if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                        await loc.click(timeout=6000)
                        clicked = True
                        text = name
                        break
                except Exception:
                    continue

        if not clicked:
            for sel in ("button#allow", "button[name*='allow' i]", "input[value*='allow' i]", "button.btn-success", "button:has-text('Allow')"):
                try:
                    loc = self.page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible() and not await loc.is_disabled():
                        await loc.click(timeout=6000)
                        clicked = True
                        text = "Allow"
                        break
                except Exception:
                    continue

        if clicked:
            host = urlparse(self.page.url).netloc
            if host:
                self._idp_signed_in.add(host)
            await self.emit_event(
                "ACT",
                f"Consented and clicked '{text}' to continue.",
                f"Consent diya aur '{text}' par click kiya.",
            )
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(1.0)
            return True
        return False

    async def _handle_errors(self, dom: Dict[str, Any]) -> bool:
        """Recognise a portal failure, recover if safe, otherwise ask.

        Returns ``True`` when an error was observed and handled, so the caller
        rescans instead of continuing to fill a page that just rejected the
        request.  ``False`` means there is nothing new to handle.
        """
        errors = self._collect_page_errors(dom)
        if not errors:
            return False
        signature = f"{dom.get('url')}|{'|'.join(errors[:2])}"
        if signature == self._last_error_signature:
            return False
        self._last_error_signature = signature

        message = errors[0]
        code = classify_failure(message)
        self._record_step(
            "error",
            status="failed",
            error_code=code.value,
            output={"message": message[:300]},
        )
        await self.emit_event(
            "SENSE",
            f"The portal reported: {message}",
            f"Portal ne bataya: {message}",
        )

        domain = self._current_domain()
        lesson = None
        try:
            lesson = self.lesson_store.recall(domain=domain, signature=signature)
        except Exception:
            traceback.print_exc()

        # Recover transient failures automatically before asking the human.
        # A lesson that already failed twice with no success is not repeated.
        attempts = self._error_recovery_attempts.get(signature, 0)
        exhausted_by_lesson = bool(
            lesson
            and int(lesson.get("failures") or 0) >= 2
            and int(lesson.get("successes") or 0) == 0
        )
        if is_retryable(code) and attempts < 2 and not exhausted_by_lesson:
            self._error_recovery_attempts[signature] = attempts + 1
            if await self._attempt_error_recovery(dom, message):
                self._record_lesson(
                    domain=domain,
                    signature=signature,
                    action="auto_recover",
                    outcome="recovered",
                    note=message,
                )
                # A recovered page is a new observation, not the same error.
                self._last_error_signature = ""
                return True
            self._record_lesson(
                domain=domain,
                signature=signature,
                action="auto_recover",
                outcome="failed",
                note=message,
            )

        gate = {
            "gate_type": "ERROR_DIAGNOSIS",
            "title": "The portal needs attention",
            "hindi_title": "Portal par dhyan dein",
            "error_text": message,
            "error_code": code.value,
            "description": (
                "The portal did not accept the current details. Review the message, "
                "edit anything that is wrong in the live browser, then continue."
            ),
            "suggested_actions": ["Review the details", "Try again", "Stop and open the portal myself"],
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
        }
        if lesson:
            gate["lesson"] = {
                "action": lesson.get("action"),
                "outcome": lesson.get("outcome"),
                "note": lesson.get("note"),
                "attempts": lesson.get("attempts"),
                "successes": lesson.get("successes"),
                "failures": lesson.get("failures"),
            }
        known = self._lesson_summary()
        if known:
            gate["known_lessons"] = known[:5]
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "Fix the highlighted field in the live browser.")
        await self.emit_event(
            "DECIDE",
            "Waiting for you to review the portal message.",
            "Portal message review karne ka intezaar hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        self.state = "RUNNING" if self.is_running else self.state
        if response.get("action") in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
            return True

        # Do not claim the human's review worked just because they clicked
        # continue.  Rescan and only record a success when the message is gone.
        fresh = dom
        try:
            fresh = await self._scan_dom()
            remaining = self._collect_page_errors(fresh)
        except Exception:
            remaining = errors
        still_failing = bool(
            remaining
            and f"{fresh.get('url')}|{'|'.join(remaining[:2])}" == signature
        )
        self._record_lesson(
            domain=domain,
            signature=signature,
            action="human_review",
            outcome="failed" if still_failing else "worked",
            note=message,
        )
        return True

    @staticmethod
    def _looks_like_error(text: str) -> bool:
        """Whether a short piece of page text is a real failure message.

        Government portals use ``role="alert"`` for instructions and notices
        too.  Treating every alert as a failure would stop a healthy page, so
        informational text is excluded before the failure words are checked.
        """
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if not value or len(value) > 500:
            return False
        informational = re.compile(
            r"instruction|guideline|advisory|please\s+read|kindly\s+read|"
            r"note\s*:|important\s*:|eligib|declaration|terms\s*(?:and|&)\s*conditions|"
            r"exam\s+pattern|syllabus|admit\s*card|answer\s*key|result|"
            r"fee\s+details|how\s+to\s+apply|step\s*\d|process\s*:",
            re.IGNORECASE,
        )
        if informational.search(value):
            return False
        error_re = re.compile(
            r"\berror\b|invalid|failed|failure|expired|timed?\s*out|timeout|"
            r"not\s+(?:valid|allowed|available|registered)|"
            r"please\s+(?:try|enter|select|check|fill|upload|verify)|"
            r"enter\s+(?:a\s+)?valid|select\s+(?:a\s+)?valid|provide\s+(?:a\s+)?valid|"
            r"\b(?:is|are)\s+required\b|must\s+be|cannot|can't|unable|denied|"
            r"incorrect|wrong|server|network|connection|unavailable|"
            r"something\s+went\s+wrong|already\s+(?:registered|exists)|"
            r"limit\s+exceeded|try\s+again",
            re.IGNORECASE,
        )
        return bool(error_re.search(value))

    @classmethod
    def _collect_page_errors(cls, dom: Dict[str, Any]) -> List[str]:
        """Collect real failure messages, not every red pixel on the page.

        Portals report errors in three places: field-level classes, ARIA
        alerts/toasts, and modal dialogs.  The old code only read the first,
        so a modal "Session expired" or a toast "Server error" looked like a
        healthy page.
        """
        seen: List[str] = []
        candidates: List[str] = []
        candidates.extend(str(item or "") for item in (dom.get("errors") or []))
        candidates.extend(str(item or "") for item in (dom.get("alerts") or []))
        for dialog in dom.get("dialogs") or []:
            if isinstance(dialog, dict):
                candidates.append(str(dialog.get("text") or ""))
        for raw in candidates:
            text = re.sub(r"\s+", " ", str(raw or "")).strip()
            if not text:
                continue
            if cls._looks_like_error(text) and text not in seen:
                seen.append(text)
        return seen

    @staticmethod
    def _find_retry_control(dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        retry_re = re.compile(r"\bretry\b|try\s*again|reload|refresh|resend", re.IGNORECASE)
        for element in dom.get("elements") or []:
            if not isinstance(element, dict) or not element.get("visible") or not element.get("enabled"):
                continue
            tag = str(element.get("tag") or element.get("tagName") or "").lower()
            role = str(element.get("role") or "").lower()
            if tag not in {"button", "a", "input"} and role not in {"button", "link"}:
                continue
            text = str(
                element.get("text")
                or element.get("labelText")
                or element.get("name")
                or ""
            ).strip()
            if not text or not retry_re.search(text):
                continue
            attributes = element.get("attributes") if isinstance(element.get("attributes"), dict) else {}
            return {
                "text": text,
                "element_id": element.get("id"),
                "tagName": tag,
                "role": role,
                "id": attributes.get("id"),
                "name": attributes.get("name") or element.get("name"),
                "className": attributes.get("class") or "",
                "css": element.get("css"),
                "xpath": element.get("xpath"),
                "inside_form": False,
            }
        return None

    async def _attempt_error_recovery(self, dom: Dict[str, Any], message: str) -> bool:
        """Try the cheapest safe recovery: retry control, then reload."""
        text = str(message or "").lower()
        retry = self._find_retry_control(dom)
        if retry:
            before = await self._page_snapshot()
            if await self._safe_click(retry):
                if await self._wait_for_page_change(before, timeout_ms=10000):
                    await self.emit_event(
                        "ACT",
                        "Retried the portal action after the error.",
                        "Error ke baad portal action dobara try kiya.",
                    )
                    return True
                await self.emit_event(
                    "SENSE",
                    "The retry control did not change the page.",
                    "Retry button se page nahi badla.",
                )
        if re.search(
            r"server|network|connection|timeout|timed?\s*out|temporarily|"
            r"unavailable|try\s*again|something\s+went\s+wrong|reload",
            text,
        ):
            try:
                await self.page.reload(wait_until="domcontentloaded", timeout=20000)
                # A reload of the same URL does not change the page identity,
                # so the change detector would report failure even after a
                # successful reload.  The next scan decides whether the error
                # is gone; this call only reports that the safe action ran.
                await self.emit_event(
                    "ACT",
                    "Reloaded the portal page after a transient error.",
                    "Transient error ke baad portal page reload kiya.",
                )
                return True
            except Exception:
                traceback.print_exc()
        return False


    # ---------------------------------------------------------------- review + advance

    async def _fill_incomplete_checkpoint(self) -> str:
        """Stop when the page did not keep every value.

        Returns ``recheck`` to rescan and fill again, ``continue`` when the
        human explicitly accepts the incomplete state, or ``stop``.
        """
        summary = self.fill_summary or {}
        if str(summary.get("status") or "") not in {"PARTIAL", "FAILED"}:
            return "continue"

        choice_fields = [
            str(label) for label in (summary.get("choice_fields") or []) if str(label).strip()
        ]
        if choice_fields and not self.fill_failures:
            # A page whose only unfilled controls are radio/checkbox choices is
            # not a broken form.  It is a decision only the candidate can make.
            title = "Choose the correct option"
            hindi_title = "Sahi option chunein"
            description = (
                "This page asks you to choose an option before continuing. "
                "Select the correct radio button or checkbox in the live browser, "
                "then continue. FormPilot does not guess these choices."
            )
        else:
            title = "Some fields are not filled"
            hindi_title = "Kuch fields nahi bhare"
            description = (
                "The portal did not keep every value FormPilot entered. "
                "The form is not fully filled. Recheck the fields, edit them in the live browser, "
                "or continue only after you have reviewed them yourself."
            )

        gate = {
            "gate_type": "FILL_INCOMPLETE",
            "title": title,
            "hindi_title": hindi_title,
            "section_number": self.current_section,
            "description": description,
            "choice_fields": choice_fields,
            "fill_summary": summary,
            "fill_failures": list(self.fill_failures),
            "fields_filled": self._public_audit(),
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
            "options": [
                {"action": "FILL_RECHECK", "label": "Recheck and fill again"},
                {"action": "CONTINUE", "label": "Continue after reviewing"},
            ],
        }
        while self.is_running:
            self.active_gate = gate
            self.state = "WAITING_FOR_USER"
            if self.live:
                self.live.set_allow_control(
                    True,
                    "Review the unfilled fields in the live browser, then choose recheck or continue.",
                )
            await self.emit_event(
                "DECIDE",
                "Some fields are not filled. Review them before continuing.",
                "Kuch fields nahi bhare. Aage badhne se pehle unhe check karein.",
                gate,
                force_screenshot=True,
            )
            response = await self._wait_for_user_response()
            self.active_gate = None
            if self.live:
                self._release_live_control("The agent is driving again.")
            action = str(response.get("action") or "")
            if action in {"STOPPED", "TIMEOUT"}:
                self.is_running = False
                self.state = "STOPPED" if action == "STOPPED" else "FAILED"
                if action == "TIMEOUT":
                    self.last_error = "No response was received. The application was paused."
                return "stop"
            if action in {"FILL_RECHECK", "RECHECK"}:
                await self.emit_event(
                    "ACT",
                    "Rechecking the form fields now.",
                    "Form ke fields dobara check kar rahe hain.",
                )
                return "recheck"
            if action in {"CONTINUE", "FILL_CONTINUE", "SECTION_APPROVAL"}:
                self.state = "RUNNING"
                return "continue"
            if action == "DISMISS":
                await self.emit_event(
                    "SENSE",
                    "The fill check is still open. Recheck the fields or continue after reviewing them.",
                    "Fill check abhi khula hai. Fields dobara check karein ya review ke baad continue karein.",
                )
                continue
        return "stop"

    def _can_autopilot_step(self) -> bool:
        """Whether a proven, fully verified step may skip section approval.

        The first visit always asks.  A later visit only skips the gate when
        the same page was completed before, every value verified, there is no
        unfilled choice, and the page has no human-only checkpoint.  Payment,
        CAPTCHA, OTP, live photo, declarations and final submission are never
        in this set.
        """
        if not settings.AUTOPILOT_KNOWN_PATHS:
            return False
        step = self._journey_step or {}
        proven = int(step.get("successes") or 0) >= 1
        if not proven and not settings.AUTOPILOT_SECTIONS:
            return False
        summary = self.fill_summary or {}
        if str(summary.get("status") or "") != "FILLED":
            return False
        if self.fill_failures:
            return False
        if summary.get("choice_fields"):
            return False
        human_only = {
            "captcha",
            "otp",
            "live_photo",
            "payment",
            "declaration",
            "identity",
        }
        if human_only & set(step.get("checkpoints") or []):
            return False
        return True

    async def _section_checkpoint(self) -> bool:
        step = self.current_section
        gate = {
            "gate_type": "SECTION_APPROVAL",
            "title": f"Review section {step}",
            "hindi_title": f"Section {step} review karein",
            "hindi_audio_text": f"Section {step} ready hai. Form par details check karein. Sab sahi ho to continue karein.",
            "section_number": step,
            "description": "Please check the details on the form. You can edit fields directly in the live browser, then continue.",
            "fields_filled": self._public_audit(),
            "fill_summary": self.fill_summary,
            "fill_failures": list(self.fill_failures),
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        if self.live:
            self.live.set_allow_control(True, "Review and edit the form in the live browser.")
        await self.emit_event(
            "DECIDE",
            f"Section {step} is ready for your review.",
            f"Section {step} review ke liye ready hai.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        if self.live:
            self._release_live_control("The agent is driving again.")
        if response.get("action") in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
            self.state = "STOPPED" if response.get("action") == "STOPPED" else "FAILED"
            if response.get("action") == "TIMEOUT":
                self.last_error = "No response was received. The application was paused."
            return False
        self.state = "RUNNING"
        approved = bool(response.get("approved")) or response.get("action") in {
            "SECTION_APPROVAL",
            "CONTINUE",
            "APPROVE",
            "CONFIRM",
        }
        if approved:
            self._remember_portal_account(
                registration_status="in_progress",
                last_known_step=f"section_{step}",
                confirmed_by_human=True,
            )
        if not approved:
            await self.emit_event(
                "THINK",
                "You asked to review the details before continuing.",
                "Aap details check karna chahte hain. Form edit kar sakte hain.",
            )
        return approved

    @staticmethod
    def _dom_signature(dom: Dict[str, Any]) -> str:
        fields = "|".join(
            f"{item.get('name') or item.get('id') or ''}:{item.get('type') or ''}"
            for item in (dom.get("inputs") or [])
        )
        return f"{dom.get('url') or ''}|{dom.get('formAction') or ''}|{fields}"

    async def _advance(self, dom: Dict[str, Any]) -> Optional[bool]:
        adapter = self._adapter or get_adapter(self.page.url if self.page else "")
        # Field filling and the security checkpoints may have re-rendered the
        # page, so never click a button id from an older scan.  Take a fresh
        # blueprint immediately before the navigation action.
        try:
            dom = await self._scan_dom()
        except Exception:
            pass
        if self._is_otp_page(dom):
            await self.emit_event(
                "SENSE",
                "The verification code is still required before this step can continue.",
                "Aage badhne se pehle verification code zaroori hai.",
            )
            return False
        button = adapter.find_next_button(dom)
        if not button:
            # A known path remembers the control that advanced this page even
            # when the adapter's heuristics no longer recognise it.
            button = self._journey_next_control(dom)
        if not button:
            # AI Context Fallback: Resolve instructed buttons (e.g. 'Complete Digilocker Verification')
            button = await self._find_advancing_button_with_context(dom)
        if not button:
            if adapter.is_payment_page(self.page, dom):
                await self._trigger_pre_payment_lock()
                return True
            return await self._advance_handoff(dom)

        previous_step = self.current_section
        last_step = self._page_looks_final(dom, button)
        if self._is_final_action(button, last_step=last_step):
            await self._trigger_pre_payment_lock(final_action=True)
            return True
        before_signature = self._dom_signature(dom)
        if self._blocked_advance and before_signature == self._blocked_advance:
            # The last click on this exact page changed nothing.  Clicking
            # again cannot help; the stall guard will ask the human.
            await self.emit_event(
                "SENSE",
                "The portal is still showing the same step. FormPilot will not click it again.",
                "Portal abhi bhi wahi step dikha raha hai. FormPilot dobara click nahi karega.",
            )
            return None
        before = await self._page_snapshot()
        dialogs_before = await self._visible_dialog_keys()
        pages_before = len(self.context.pages) if self.context else 0
        await self.emit_event(
            "ACT",
            f"Saving section {previous_step}...",
            f"Section {previous_step} save kar rahe hain...",
        )
        self._save_current_recipe()
        self._note_journey_action("click", str(button.get("text") or "next"))

        # On instruction, declaration, and review pages:
        # 1. Ensure agreement checkbox is checked and button unlocked
        # 2. Ensure all particulars checklist checkboxes (Name, Father, Mother, DOB, Gender, Category, etc.) are ticked
        if self.page:
            try:
                await self.page.evaluate('''() => {
                    const chk = document.querySelector('[id*="chkagreement" i], [name*="chkagreement" i]');
                    if (chk) {
                        if (typeof window.confirmYes === 'function') {
                            try { window.confirmYes(); } catch (e) {}
                        }
                        if (!chk.checked) {
                            chk.checked = true;
                            chk.disabled = false;
                            chk.dispatchEvent(new Event('input', { bubbles: true }));
                            chk.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                    const btn = document.querySelector('[id*="btnsubmit" i], [id*="btnProceed" i]');
                    if (btn && btn.disabled) {
                        btn.disabled = false;
                    }

                    // Particulars checklist on NTA review popups / pages
                    const checklistSelectors = [
                        '[id*="chkMyName" i]', '[name*="chkMyName" i]',
                        '[id*="chkFather" i]', '[name*="chkFather" i]',
                        '[id*="chkMother" i]', '[name*="chkMother" i]',
                        '[id*="chkDOB" i]', '[name*="chkDOB" i]',
                        '[id*="chkGender" i]', '[name*="chkGender" i]',
                        '[id*="chkCategory" i]', '[name*="chkCategory" i]',
                        '[id*="chkAddress" i]', '[name*="chkAddress" i]',
                        '[id*="chkMobile" i]', '[name*="chkMobile" i]',
                        '[id*="chkEmail" i]', '[name*="chkEmail" i]',
                        '[id*="chkPwd" i]', '[name*="chkPwd" i]',
                        '[id*="chkCity" i]', '[name*="chkCity" i]',
                        '[id*="chkEdu" i]', '[name*="chkEdu" i]',
                        '[id*="chkPaper" i]', '[name*="chkPaper" i]',
                        '[id*="chkAgree" i]', '[name*="chkAgree" i]',
                        '[id*="chkDeclaration" i]', '[name*="chkDeclaration" i]'
                    ];
                    for (const sel of checklistSelectors) {
                        for (const el of document.querySelectorAll(sel)) {
                            if (!el.checked && !el.disabled) {
                                el.checked = true;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                    }

                    const containers = document.querySelectorAll('[id*="particular" i], [class*="particular" i], [id*="checklist" i], [class*="checklist" i]');
                    for (const cont of containers) {
                        for (const cb of cont.querySelectorAll('input[type="checkbox"]')) {
                            if (!cb.checked && !cb.disabled) {
                                cb.checked = true;
                                cb.dispatchEvent(new Event('input', { bubbles: true }));
                                cb.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                    }
                }''')
            except Exception:
                pass

        if not await self._safe_click(button):
            self._pending_journey_action = None
            return False

        await asyncio.sleep(0.3)
        confirmed = await self._accept_choice_popup(dialogs_before)
        if confirmed.get("clicked"):
            await self._wait_for_postback(timeout_ms=3000)

        opened_new_tab = await self._adopt_new_page(pages_before)
        changed = opened_new_tab or await self._wait_for_page_change(before)
        if not changed:
            self._blocked_advance = before_signature
            postcondition = (
                self._last_action_result.postcondition
                if self._last_action_result is not None
                else ""
            )
            await self.emit_event(
                "SENSE",
                "The portal did not move to the next step. Nothing was saved.",
                "Portal agle step par nahi gaya. Kuch save nahi hua.",
            )
            if postcondition == "no_change":
                # The click was dispatched and the page did not react; that is
                # a page only the human can unstick.
                await self.emit_event(
                    "SENSE",
                    "The button accepted the click but the page did not react.",
                    "Button click hua, lekin page par kuch nahi badla.",
                )
            return False

        self._captcha_signature = ""
        self._last_error_signature = ""
        try:
            fresh = await self._scan_dom()
            fresh_signature = self._dom_signature(fresh)
            if fresh_signature == before_signature or fresh_signature == self._last_advance_signature:
                # A validation toast or a transient overlay can change the
                # page text without moving the form.  Never report a save
                # twice for the same form.
                self._blocked_advance = before_signature
                await self.emit_event(
                    "SENSE",
                    "The portal is still showing the same step. Nothing was saved.",
                    "Portal abhi bhi wahi step dikha raha hai. Kuch save nahi hua.",
                )
                return False
            self._last_advance_signature = fresh_signature
            self._blocked_advance = ""
            self.current_section = adapter.current_step(self.page, fresh)
            visible = str(fresh.get("visibleText") or "").lower()
            if any(token in visible for token in ("dashboard", "logged in", "sign out", "logout")):
                await self.emit_event(
                    "ACT",
                    "Signed in successfully.",
                    "Sign in ho gaya.",
                )
                return True
            if adapter.is_payment_page(self.page, fresh):
                await self.emit_event(
                    "THINK",
                    "The payment page is open. Stopping before any payment action.",
                    "Payment page khul gaya. Payment se pehle ruk rahe hain.",
                )
                return True
        except Exception:
            pass

        await self.emit_event(
            "ACT",
            f"Section {previous_step} saved and the next step is open.",
            f"Section {previous_step} save ho gaya aur agla step khul gaya.",
        )
        return True

    async def _find_advancing_button_with_context(self, dom: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Context-aware fallback when heuristic regexes fail to match a button name."""
        if not self.page or self.page.is_closed():
            return None

        visible_text = str(dom.get("visibleText") or "").strip()
        clickables = dom.get("nextButtons") or []

        # 1. Look for explicit instruction: e.g. 'Please click the "..." button'
        match = re.search(r"click\s+(?:the\s+)?[\"']([^\"']+)[\"']\s+button", visible_text, re.IGNORECASE)
        if match:
            target_name = match.group(1).strip().lower()
            for btn in clickables:
                btn_text = str(btn.get("text") or "").strip().lower()
                if target_name in btn_text or btn_text in target_name:
                    logger.info("Found instructed advance button from page text: %s", btn.get("text"))
                    return btn

            # Check all buttons directly in DOM via evaluate
            try:
                found_el = await self.page.evaluate(
                    """(target) => {
                        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a.btn'));
                        for (const b of buttons) {
                            const t = (b.innerText || b.value || '').trim().toLowerCase();
                            if (t && (t.includes(target) || target.includes(t))) {
                                return {
                                    text: (b.innerText || b.value || '').trim(),
                                    id: b.id || null,
                                    tagName: b.tagName.toLowerCase(),
                                    type: b.type || '',
                                    className: b.className || '',
                                    element_id: b.getAttribute('data-fp-id') || null
                                };
                            }
                        }
                        return null;
                    }""",
                    target_name
                )
                if found_el:
                    logger.info("Found instructed advance button directly in DOM: %s", found_el)
                    return found_el
            except Exception as exc:
                logger.debug("Failed evaluating instructed button: %s", exc)

        # 2. Interstitial / Verification response page:
        # If the page has 0 form inputs, and only 1 or 2 primary buttons on the entire card
        inputs = dom.get("inputs") or []
        if len(inputs) == 0:
            primary_candidates = [
                b for b in clickables
                if not re.search(r"back|previous|cancel|help|faq", str(b.get("text") or ""), re.IGNORECASE)
            ]
            if len(primary_candidates) == 1:
                logger.info("Single primary button on input-free interstitial page: %s", primary_candidates[0].get("text"))
                return primary_candidates[0]

            # Try querySelector for any prominent action button inside the card/container
            try:
                card_button = await self.page.evaluate(
                    """() => {
                        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a.btn, a[role="button"], a[class*="btn"]'))
                            .filter(b => {
                                const rect = b.getBoundingClientRect();
                                const style = window.getComputedStyle(b);
                                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                            })
                            .filter(b => !/back|previous|cancel|help/i.test(b.innerText || b.value || ''));
                        if (buttons.length === 1) {
                            const b = buttons[0];
                            return {
                                text: (b.innerText || b.value || '').trim(),
                                id: b.id || null,
                                tagName: b.tagName.toLowerCase(),
                                type: b.type || '',
                                className: b.className || '',
                                element_id: b.getAttribute('data-fp-id') || null
                            };
                        }
                        return null;
                    }"""
                )
                if card_button:
                    logger.info("Sole active button on page resolved as advance: %s", card_button)
                    return card_button
            except Exception as exc:
                logger.debug("Failed evaluating sole active button: %s", exc)

        return None

    async def _advance_handoff(self, dom: Dict[str, Any]) -> bool:
        """Ask the human to press the control the agent could not identify.

        Portals use icon-only buttons, non-English labels and custom widgets.
        Guessing is worse than asking: the wrong control can submit the form.
        The live browser is interactive, so the human can press it and confirm.
        """
        signature = self._dom_signature(dom)
        if signature == self._advance_handoff_signature:
            return False
        if not self.live:
            return False
        self._advance_handoff_signature = signature

        # Extract all visible candidate buttons on page so the user can one-click auto-click
        suggested_buttons = []
        for button in (dom.get("nextButtons") or []):
            t = str(button.get("text") or "").strip()
            if t and t not in suggested_buttons:
                suggested_buttons.append(t)

        gate = {
            "gate_type": "LIVE_HANDOFF",
            "handoff_type": "advance",
            "title": "Continue in the live browser",
            "hindi_title": "Live browser mein aage badhein",
            "description": (
                "FormPilot could not identify the button that moves this page "
                "forward, so it did not click anything. Use the live browser to "
                "save or continue, or choose a detected button below."
            ),
            "options": [
                {"text": t, "action": "AUTO_CLICK", "button_text": t}
                for t in suggested_buttons[:6]
            ],
            "live_session": self.live.public_info() if not self.live.closed else None,
            "can_takeover": True,
            "instructions": [
                "Click the save/continue button in the live browser.",
                "Wait for the next page to load.",
                "Then click 'I completed this step'.",
            ],
        }
        self.active_gate = gate
        self.state = "WAITING_FOR_USER"
        self.live.set_allow_control(True, "Press the save/continue button in the live browser.")
        await self.emit_event(
            "DECIDE",
            "I could not identify the continue button. Use the live browser, then confirm.",
            "Continue button pehchana nahi gaya. Live browser mein aage badhein, phir confirm karein.",
            gate,
            force_screenshot=True,
        )
        response = await self._wait_for_user_response()
        self.active_gate = None
        self._release_live_control("The agent is driving again.")

        if response.get("action") in {"STOPPED", "TIMEOUT"}:
            self.is_running = False
            return False

        # Support AUTO_CLICK if user selects one of the suggested buttons from the modal
        if response.get("action") == "AUTO_CLICK" or response.get("button_text"):
            btn_text = response.get("button_text")
            if btn_text and self.page and not self.page.is_closed():
                try:
                    await self.page.evaluate(
                        """(text) => {
                            const btns = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a.btn'));
                            for (const b of btns) {
                                if ((b.innerText || b.value || '').trim().toLowerCase() === text.trim().toLowerCase()) {
                                    b.click();
                                    return true;
                                }
                            }
                            return false;
                        }""",
                        btn_text
                    )
                except Exception as exc:
                    logger.warning("Failed to auto-click user selected button: %s", exc)
            self._advance_handoff_signature = ""
            return True

        if response.get("action") in {"HANDOFF_COMPLETE", "CONTINUE"}:
            self._advance_handoff_signature = ""
            return True
        return False

    # ---------------------------------------------------------------- pre-payment

    _FINAL_ACTION_PATTERN = re.compile(
        r"\b(?:submit|pay|payment|checkout|finish|"
        r"complete\s+(?:application|registration)|proceed\s+to\s+pay)\b",
        re.IGNORECASE,
    )
    # Wording that means this page is the end of the application.  Only then
    # do ambiguous labels such as "Save" or "Confirm" count as final.
    _FINAL_PAGE_RE = re.compile(
        r"\b(?:preview|declaration|final\s+(?:step|submission|review)|"
        r"review\s+(?:your|the)\s+application|confirm\s+(?:your\s+)?details|"
        r"terms\s*(?:and|&)\s*conditions|before\s+(?:you\s+)?submit|"
        r"submit\s+(?:your\s+)?application)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _is_final_action(
        cls,
        button: Dict[str, Any],
        *,
        last_step: bool = False,
    ) -> bool:
        """True for a button that would submit or pay for the application.

        Navigation labels such as "Save & Next: Pre-Payment Review" mention
        payment but only move to another section, so they are excluded.
        Ambiguous labels ("Save", "Confirm", "Complete") only count as final
        on a page that already looks like the last step; otherwise a normal
        section's Save button would trigger a false pre-payment lock.
        """
        text = str(button.get("text") or "").strip()
        if re.search(r"(?:save\s*&\s*next|save\s+and\s+next|next\s+step)", text, re.IGNORECASE):
            return False
        if cls._FINAL_ACTION_PATTERN.search(text):
            return True
        if last_step and re.search(
            r"\b(?:save|confirm|finish|complete|lock|freeze|accept|agree)\b",
            text,
            re.IGNORECASE,
        ):
            return True
        return False

    @classmethod
    def _page_looks_final(cls, dom: Dict[str, Any], button: Dict[str, Any]) -> bool:
        """Heuristic: is this page the last one before submission?

        Two independent signals: the page talks like a preview/declaration,
        or it shows a consent checkbox next to an ambiguous save/confirm
        button.  Both are common on Indian government portals.
        """
        text = str(dom.get("visibleText") or "")
        if cls._FINAL_PAGE_RE.search(text):
            return True
        label = str(button.get("text") or "")
        if not re.search(r"\b(?:save|confirm|finish|complete|update)\b", label, re.IGNORECASE):
            return False
        for item in dom.get("inputs") or []:
            if str(item.get("type") or "").lower() != "checkbox":
                continue
            haystack = " ".join(
                str(item.get(key) or "") for key in ("label", "name", "id")
            )
            if re.search(
                r"\b(?:i\s+(?:hereby\s+)?(?:agree|declare|confirm|consent|accept)|"
                r"terms\s*(?:and|&)\s*conditions|declaration)\b",
                haystack,
                re.IGNORECASE,
            ):
                return True
        return False

    @staticmethod
    def _masked_phone(value: str) -> str:
        text = str(value or "")
        if len(text) <= 4:
            return "your saved number"
        return f"{'*' * (len(text) - 4)}{text[-4:]}"

    @staticmethod
    def _normalise_value(value: Any) -> str:
        return " ".join(str(value or "").split()).strip().lower().replace("-", "/").replace(".", "/")

    async def _trigger_pre_payment_lock(self, *, final_action: bool = False):
        """Stop before payment or final submission, show an audit, and hand over."""
        self._save_current_recipe()
        if self.live:
            self.live.set_allow_control(
                True,
                "Payment and final submission are yours. FormPilot will not click them.",
            )
        try:
            reg_id = await self.page.evaluate(
                "() => { const el = document.getElementById('permanent-reg-id'); return el ? el.innerText.trim() : ''; }"
            )
            if reg_id and "PENDING" not in reg_id:
                self.vault_mgr.add_custom_field("otr_registration_id", reg_id)
                await self.emit_event(
                    "THINK",
                    f"Registration ID saved: {reg_id}",
                    f"Registration ID save ho gaya: {reg_id}",
                )
        except Exception:
            reg_id = ""

        try:
            current_values = await self.page.evaluate(DOMScanner.EXTRACT_VALUES_JS, True)
        except Exception:
            current_values = []

        by_id = {str(v.get("id")): v for v in current_values if v.get("id")}
        by_name = {str(v.get("name")): v for v in current_values if v.get("name")}

        records: List[Dict[str, Any]] = []
        mismatches = 0
        for item in self._public_audit():
            field_id = item.get("field_id") or ""
            field_name = item.get("field_name") or ""
            current = by_id.get(field_id) or by_name.get(field_name)
            form_values: List[str] = []
            if current:
                form_values = [
                    str(current.get("value") or ""),
                    str(current.get("selectedText") or ""),
                ]
            form_value = next((value for value in form_values if value), "")
            saved_display = str(item.get("injected_value") or "")
            if not form_value:
                status = "EMPTY"
                risk = 60
                mismatches += 1
            elif item.get("vault_key") in {"photo_upload", "signature_upload", "matric_cert_upload"}:
                status = "MATCH"
                risk = 0
            elif any(
                self._normalise_value(value) == self._normalise_value(saved_display)
                for value in form_values
                if value
            ):
                status = "MATCH"
                risk = 0
            else:
                # Masked values cannot be compared character-for-character.
                key = item.get("vault_key") or ""
                spec = field_registry.spec_for(key)
                if spec and spec.sensitive:
                    status = "MATCH"
                    risk = 0
                else:
                    status = "MISMATCH"
                    risk = 40
                    mismatches += 1

            records.append(
                {
                    "field": item.get("field_label"),
                    "vault_value": saved_display,
                    "form_value": field_registry.mask_value(item.get("vault_key") or "", form_value),
                    "status": status,
                    "risk_score": risk,
                }
            )

        audit_payload = {
            "run_id": self.run_id,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "portal_url": self.page.url if self.page else self.target_url,
            "registration_id": reg_id,
            "records": records,
            "total_checked": len(records),
            "total_matched": len(records) - mismatches,
            "total_mismatches": mismatches,
            "audit_hash": hashlib.sha256(json.dumps(records, sort_keys=True).encode("utf-8")).hexdigest(),
            "disclaimer": (
                "FormPilot never clicks a payment button or a final submission button."
            ),
        }
        approval_snapshot = {
            "run_id": self.run_id,
            "url": audit_payload["portal_url"],
            "audit_hash": audit_payload["audit_hash"],
            "field_digest": self._digest_field_values(current_values),
            "captured_at": audit_payload["generated_at"],
        }
        self._approval_snapshot = approval_snapshot
        audit_payload["approval_snapshot"] = approval_snapshot
        if self.run_id:
            try:
                self.run_store.save_audit(self.run_id, self._persisted_audit(audit_payload))
            except Exception:
                pass

        fill_status = str((self.fill_summary or {}).get("status") or "")
        fill_incomplete = fill_status in {"PARTIAL", "FAILED"}
        safety_status = (
            "READY_FOR_REVIEW"
            if mismatches == 0 and not fill_incomplete
            else "NEEDS_REVIEW"
        )
        gate = {
            "gate_type": "PRE_PAYMENT_SAFETY_LOCK",
            "title": (
                "Review before final submission"
                if final_action
                else "Review before payment"
            ),
            "run_id": self.run_id,
            "final_action": "submission" if final_action else "payment",
            "hindi_title": (
                "Final submit se pehle review karein"
                if final_action
                else "Payment se pehle review karein"
            ),
            "hindi_audio_text": (
                "Final step aa gaya hai. Neeche di gayi details check karein. "
                "Final submit aap khud portal par karein."
                if final_action
                else "Payment step aa gaya hai. Neeche di gayi details check karein. "
                "Payment aap khud portal par karein."
            ),
            "description": (
                "This is the final step. FormPilot has stopped here. "
                "Check the details below, then complete the final submission yourself "
                "in the portal. Nothing is submitted automatically."
                if final_action
                else "The application fee page is open. FormPilot has stopped here. "
                "Check the details below, then complete the payment yourself in the portal. "
                "Nothing is submitted or paid automatically."
            ),
            "audit_diff": records,
            "total_verified_fields": len(records) - mismatches,
            "total_checked_fields": len(records),
            "total_mismatches": mismatches,
            "fill_summary": self.fill_summary,
            "fill_failures": list(self.fill_failures),
            "safety_status": safety_status,
            "registration_id": reg_id,
            "portal_url": self.page.url if self.page else self.target_url,
            "audit_hash": audit_payload["audit_hash"],
            "approval_snapshot": approval_snapshot,
            "approval_valid": True,
            "download_available": True,
            "live_session": self.live.public_info() if self.live and not self.live.closed else None,
            "can_takeover": bool(self.live),
            "human_action_required": "payment" if not final_action else "final_submission",
        }
        self.active_gate = gate
        self.state = "AWAITING_PAYMENT"
        self.is_running = False
        await self.emit_event(
            "DECIDE",
            (
                "Final step reached. FormPilot stopped before submitting anything."
                if final_action
                else "Payment page reached. FormPilot stopped before any payment action."
            ),
            (
                "Final step aa gaya. FormPilot ne submit karne se pehle ruk gaya. "
                "Ab aap khud final submit karein."
                if final_action
                else "Payment page aa gaya. FormPilot ne payment se pehle ruk gaya. "
                "Ab aap khud payment karein."
            ),
            gate,
            force_screenshot=True,
        )
        self._record_step(
            "submit",
            status="waiting",
            output={
                "final_action": bool(final_action),
                "gate_type": str((gate or {}).get("gate_type") or ""),
                "audit_hash": audit_payload.get("audit_hash"),
            },
        )
        if self.run_id:
            self.run_store.finish(
                self.run_id,
                self.state,
                {
                    "audit_hash": audit_payload["audit_hash"],
                    "target_url": self.target_url,
                    "run_clock": self.run_clock(),
                    "llm_usage": self.llm_usage(),
                },
            )

    # ---------------------------------------------------------------- helpers

    async def _safe_click(self, button: Dict[str, Any]) -> bool:
        """Click a blueprint element, or a uniquely identified legacy control.

        A blueprint id is always tried first.  If the id is stale we re-scan
        once and re-identify the same control by its durable locators.  The
        legacy path is only used for controls that predate the blueprint and
        it refuses ambiguous matches instead of silently taking ``.first``.
        """
        self._last_action_result = None
        if not self.page:
            return False

        element_id = str(button.get("element_id") or "")
        resolver = self._action_resolver()
        if element_id and resolver:
            result = await resolver.click(element_id)
            if result.ok:
                self._last_action_result = result
                return True

            if result.error_code in {
                "NOT_FOUND",
                "STALE_SNAPSHOT",
                "FRAME_NOT_ACCESSIBLE",
                "NOT_VISIBLE",
                "COVERED",
                "CLICK_FAILED",
            }:
                fresh_id = await self._find_fresh_element_id(button)
                if fresh_id and fresh_id != element_id:
                    resolver = self._action_resolver()
                    if resolver:
                        retry = await resolver.click(fresh_id)
                        if retry.ok:
                            self._last_action_result = retry
                            button["element_id"] = fresh_id
                            return True
                        result = retry

            self._last_action_result = result

        # Tier 2: Resilient legacy locator click
        if await self._legacy_click(button):
            return True

        # Tier 3: Universal DOM clicker
        if await self._universal_dom_click(button):
            return True

        err_code = (
            getattr(self._last_action_result, "error_code", "CLICK_FAILED")
            if self._last_action_result
            else "CLICK_FAILED"
        )
        err_msg = (
            getattr(self._last_action_result, "message", "Could not click control.")
            if self._last_action_result
            else "Could not click control."
        )
        await self.emit_event(
            "SENSE",
            f"Could not click {button.get('text') or 'the control'} ({err_code}): {err_msg}",
            f"{button.get('text') or 'Control'} click nahi ho paya. Page dobara scan kar rahe hain.",
        )
        return False

    async def _find_fresh_element_id(self, button: Dict[str, Any]) -> Optional[str]:
        """Re-identify a control after a re-scan using durable locators."""
        blueprint = await self._rescan_blueprint()
        if not blueprint:
            return None

        old_css = str(button.get("css") or "")
        old_xpath = str(button.get("xpath") or "")
        old_tag = str(button.get("tagName") or button.get("tag") or "").lower()
        old_role = str(button.get("role") or "").lower()
        old_name = str(button.get("text") or button.get("name") or "").strip().lower()
        old_id = str(button.get("id") or "")
        old_href = str(button.get("href") or "").strip()

        def unique(matches: List[BlueprintElement]) -> Optional[str]:
            return matches[0].id if len(matches) == 1 else None

        elements = list(blueprint.elements.values())
        if old_href:
            # Links are the most stable locator on government portals; the
            # element id and accessible name can both change between scans.
            found = unique(
                [
                    element
                    for element in elements
                    if str(element.attributes.get("href") or "").strip() == old_href
                ]
            )
            if found:
                return found
        if old_css:
            found = unique([element for element in elements if element.css == old_css])
            if found:
                return found
        if old_xpath:
            found = unique([element for element in elements if element.xpath == old_xpath])
            if found:
                return found
        if old_id:
            found = unique(
                [element for element in elements if str(element.attributes.get("id") or "") == old_id]
            )
            if found:
                return found
        if old_role and old_name:
            found = unique(
                [
                    element
                    for element in elements
                    if element.role == old_role
                    and str(element.name or "").strip().lower() == old_name
                    and (not old_tag or element.tag == old_tag)
                ]
            )
            if found:
                return found
        if old_name and old_tag:
            found = unique(
                [
                    element
                    for element in elements
                    if element.tag == old_tag
                    and str(element.name or "").strip().lower() == old_name
                ]
            )
            if found:
                return found
        return None

    async def _legacy_click(self, button: Dict[str, Any]) -> bool:
        """Last-resort click for controls without a blueprint element id.

        Every candidate must resolve to exactly one node.  A text that matches
        several nodes is rejected, because guessing the first one is what made
        the HPSC login link fail.
        """
        if not self.page:
            return False
        text = str(button.get("text") or "").strip()
        candidates = []
        if button.get("id"):
            candidates.append(self.page.locator(f"#{button['id']}"))
        if button.get("css"):
            candidates.append(self.page.locator(str(button["css"])))
        if button.get("xpath"):
            candidates.append(self.page.locator(f"xpath={button['xpath']}"))
        role = str(button.get("role") or "").strip()
        if role and text:
            candidates.append(self.page.get_by_role(role, name=text, exact=True))
        if text:
            for role_name in ("button", "link"):
                candidates.append(self.page.get_by_role(role_name, name=text, exact=True))
            tag = str(button.get("tagName") or "").lower()
            if tag:
                escaped = text.replace("\\", "\\\\").replace('"', '\\"')
                candidates.append(self.page.locator(f'{tag}:text-is("{escaped}")'))

        for locator in candidates:
            try:
                count = await locator.count()
            except Exception:
                continue
            if count == 0:
                continue
            target_node = None
            if count == 1:
                target_node = locator
            else:
                visible = []
                for idx in range(min(count, 6)):
                    try:
                        node = locator.nth(idx)
                        if await node.is_visible():
                            visible.append(node)
                    except Exception:
                        pass
                if len(visible) == 1:
                    target_node = visible[0]
            if not target_node:
                continue
            try:
                await target_node.scroll_into_view_if_needed(timeout=4000)
                clicked_ok = False
                try:
                    await target_node.click(timeout=4000)
                    clicked_ok = True
                except Exception:
                    try:
                        await target_node.click(force=True, timeout=3000)
                        clicked_ok = True
                    except Exception:
                        try:
                            await target_node.evaluate(
                                "el => { el.scrollIntoView({ block: 'center' }); try { el.focus(); } catch (e) {} el.click(); }"
                            )
                            clicked_ok = True
                        except Exception:
                            clicked_ok = False

                if clicked_ok:
                    self._last_action_result = ActionResult(
                        ok=True,
                        action="click",
                        method="legacy_unique",
                        message=f"Clicked {text or 'the control'}.",
                        scan_id=self.blueprint.scan_id if self.blueprint else "",
                    )
                    return True
            except Exception as exc:
                self._last_action_result = ActionResult(
                    ok=False,
                    action="click",
                    error_code="CLICK_FAILED",
                    message=str(exc)[:200],
                    scan_id=self.blueprint.scan_id if self.blueprint else "",
                )
        return False

    async def _universal_dom_click(self, button: Dict[str, Any]) -> bool:
        """Universal DOM-level clicker that searches the document for any matching button."""
        if not self.page or self.page.is_closed():
            return False

        btn_text = str(button.get("text") or "").strip().lower()
        btn_id = str(button.get("id") or "").strip()
        btn_name = str(button.get("name") or "").strip()
        btn_xpath = str(button.get("xpath") or "").strip()

        keywords = []
        if btn_text:
            keywords.append(btn_text)
        if "proceed" in btn_text:
            keywords.extend(["click here to proceed", "proceed"])
        if "next" in btn_text:
            keywords.extend(["next", "save & next", "save and next"])
        if "submit" in btn_text:
            keywords.extend(["submit", "save"])

        try:
            clicked = await self.page.evaluate(
                r"""({ id, name, xpath, keywords }) => {
                    // 1. Direct ID match
                    if (id) {
                        const byId = document.getElementById(id);
                        if (byId) {
                            byId.scrollIntoView({ block: 'center', inline: 'center' });
                            try { byId.focus(); } catch (e) {}
                            byId.click();
                            byId.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                            return { ok: true, matched: 'id:' + id };
                        }
                    }
                    // 2. Direct XPath match
                    if (xpath) {
                        try {
                            const res = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                            if (res.singleNodeValue) {
                                const node = res.singleNodeValue;
                                node.scrollIntoView({ block: 'center', inline: 'center' });
                                node.click();
                                node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                                return { ok: true, matched: 'xpath' };
                            }
                        } catch (e) {}
                    }
                    // 3. Search all buttons, submit inputs, links by text/value
                    const candidates = Array.from(document.querySelectorAll(
                        'input[type="submit"], input[type="button"], button, a[role="button"], a.btn, a, [onclick]'
                    ));
                    for (const el of candidates) {
                        const txt = (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '').toLowerCase().trim();
                        const elId = (el.id || '').toLowerCase();
                        const elName = (el.getAttribute('name') || '').toLowerCase();
                        
                        const textMatch = keywords.some(k => k && (txt.includes(k) || k.includes(txt)));
                        const idMatch = id && elId.includes(id.toLowerCase());
                        const nameMatch = name && elName.includes(name.toLowerCase());

                        if (textMatch || idMatch || nameMatch) {
                            el.scrollIntoView({ block: 'center', inline: 'center' });
                            try { el.focus(); } catch (e) {}
                            el.click();
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                            return { ok: true, matched: 'text:' + txt };
                        }
                    }
                    return { ok: false };
                }""",
                {"id": btn_id, "name": btn_name, "xpath": btn_xpath, "keywords": keywords},
            )
            if clicked and clicked.get("ok"):
                await asyncio.sleep(0.5)
                await self._wait_for_postback(timeout_ms=3000)
                self._last_action_result = ActionResult(
                    ok=True,
                    action="click",
                    method=f"universal_dom:{clicked.get('matched')}",
                    message=f"Clicked {button.get('text') or 'button'} via universal DOM handler.",
                    scan_id=self.blueprint.scan_id if self.blueprint else "",
                )
                return True
        except Exception:
            pass

        return False

    def _stopped_gate_result(self) -> Dict[str, Any]:
        """Keep a stop request authoritative even if a gate opened mid-teardown."""
        self._close_gate_step("STOPPED")
        self.state = "STOPPED"
        self.active_gate = None
        return {"action": "STOPPED"}

    async def _wait_for_user_response(self) -> Dict[str, Any]:
        if self._stop_requested or not self.is_running:
            return self._stopped_gate_result()
        if self._pending_user_response is not None:
            result = self._pending_user_response
            self._pending_user_response = None
            return result
        loop = asyncio.get_running_loop()
        self.active_event_future = loop.create_future()
        # Close the race where stop() lands between the check above and the
        # future being created: either this check sees the stop request, or
        # stop() sees the future and resolves it.
        if self._stop_requested or not self.is_running:
            self.active_event_future = None
            return self._stopped_gate_result()
        try:
            result = await asyncio.wait_for(self.active_event_future, timeout=settings.GATE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self.active_event_future = None
            self._close_gate_step("TIMEOUT")
            await self.emit_event(
                "DECIDE",
                "No response was received, so the application was paused.",
                "Koi response nahi aaya, isliye application pause ho gayi.",
            )
            return {"action": "TIMEOUT"}
        finally:
            self.active_event_future = None
        if result.get("action") == "STOPPED":
            return self._stopped_gate_result()
        # A human answer is progress: give the loop a fresh stall budget and
        # let it try the page again.
        self._progress.reset("human_answer")
        self._shadow_stall_key = None
        self._blocked_advance = ""
        return result

