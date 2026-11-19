"""Tests for live portal hardening: postback handling, dialogs, cascading inputs, and advance."""

from __future__ import annotations

import re
import pytest
from backend.core.portal_adapter import BasePortalAdapter
from backend.core.orchestrator import FormPilotOrchestrator


def test_next_candidates_ranks_save_and_next_above_bare_next():
    adapter = BasePortalAdapter()
    dom = {
        "nextButtons": [
            {"text": "Next", "element_id": "btn-next", "type": "submit", "insideForm": True},
            {"text": "Save & Next", "element_id": "btn-save-next", "type": "submit", "insideForm": True},
        ]
    }
    button = adapter.find_next_button(dom)
    assert button is not None
    assert button["text"] == "Save & Next"
    assert button["element_id"] == "btn-save-next"


def test_next_candidates_ranks_save_and_proceed_above_next():
    adapter = BasePortalAdapter()
    dom = {
        "nextButtons": [
            {"text": "Next Step", "element_id": "btn-step", "type": "submit", "insideForm": True},
            {"text": "Save and Proceed", "element_id": "btn-save-proceed", "type": "submit", "insideForm": True},
        ]
    }
    button = adapter.find_next_button(dom)
    assert button is not None
    assert button["text"] == "Save and Proceed"


def test_instruction_consent_matches_both_word_orders():
    # Word order 1: downloaded/read first
    item1 = {
        "type": "checkbox",
        "label": "I have downloaded the Information Bulletin of JEE Main 2025 and read all instructions",
    }
    assert FormPilotOrchestrator._is_instruction_consent(item1) is True

    # Word order 2: information bulletin first
    item2 = {
        "type": "checkbox",
        "label": "Information Bulletin and instructions have been downloaded and read by me",
    }
    assert FormPilotOrchestrator._is_instruction_consent(item2) is True

    # Checkbox by machine ID (JEE Main style)
    item3 = {
        "type": "checkbox",
        "id": "chkagreement",
        "name": "chkagreement",
        "label": "Declaration",
    }
    assert FormPilotOrchestrator._is_instruction_consent(item3) is True


def test_instruction_consent_rejects_unrelated_checkbox():
    item = {
        "type": "checkbox",
        "label": "Send me SMS updates and notification offers",
    }
    assert FormPilotOrchestrator._is_instruction_consent(item) is False


@pytest.mark.anyio
async def test_safe_click_falls_back_to_universal_dom_when_resolver_fails_not_visible():
    orchestrator = FormPilotOrchestrator()
    orchestrator.target_url = "https://example.com"

    class FakeLocator:
        async def count(self):
            return 0

    class FakePage:
        url = "https://example.com"
        def is_closed(self):
            return False
        def locator(self, *args, **kwargs):
            return FakeLocator()
        def get_by_role(self, *args, **kwargs):
            return FakeLocator()
        async def evaluate(self, script, args=None):
            return {"ok": True, "matched": "text:click here to proceed"}

    orchestrator.page = FakePage()

    class FailingResolver:
        async def click(self, el_id):
            class FailedRes:
                ok = False
                error_code = "NOT_VISIBLE"
                message = "Element is not visible."
                postcondition = "no_change"
            return FailedRes()

    orchestrator._action_resolver = lambda: FailingResolver()

    button = {"element_id": "btn-proceed", "text": "Click here to Proceed", "id": "btnProceed"}

    clicked = await orchestrator._safe_click(button)
    assert clicked is True
    assert orchestrator._last_action_result.ok is True
    assert "universal_dom" in orchestrator._last_action_result.method


def test_is_external_identity_page_recognizes_meripehchaan():
    orch = FormPilotOrchestrator()
    orch.target_url = "https://examinationservices.nic.in/JeeMain2025/Registration/Instruction.aspx"

    class FakePage:
        url = "https://digilocker.meripehchaan.gov.in/signinv2/oauth_partner/123"

    orch.page = FakePage()
    dom = {"inputs": [{"type": "text", "name": "mobile"}], "otpInputs": []}
    assert orch._is_external_identity_page(dom) is True


def test_chat_assistant_switches_digilocker_mode():
    from backend.core.chat_assistant import FormPilotChatAssistant

    class MockOrchestrator:
        def __init__(self):
            self.active_gate = {
                "gate_type": "LIVE_HANDOFF",
                "handoff_type": "identity_provider",
                "provider_host": "digilocker.meripehchaan.gov.in",
            }
            self.submitted = []
            self.page = None

        def submit_user_response(self, data):
            self.submitted.append(data)

    async def _run():
        orch = MockOrchestrator()
        assistant = FormPilotChatAssistant(orchestrator=orch)

        # 1. User asks to sign in instead of signup
        res = await assistant.handle_message("I need to sign in for digilocker, not signup")
        assert res["action_taken"] == "IDP_SWITCH_SIGNIN"
        assert orch.submitted[-1] == {"action": "SWITCH_IDP_MODE", "mode": "signin"}

        # 2. User asks to generate OTP
        res2 = await assistant.handle_message("Generate OTP")
        assert res2["action_taken"] == "IDP_GENERATE_OTP"
        assert orch.submitted[-1] == {"action": "GENERATE_OTP"}

        # 3. User provides PIN directly
        res3 = await assistant.handle_message("My PIN is 123456")
        assert res3["action_taken"] == "IDP_ENTER_CODE"
        assert orch.submitted[-1] == {"action": "OTP_SUBMIT", "credential": "123456"}

    import asyncio
    asyncio.run(_run())


def test_idp_detects_already_registered():
    from backend.core.orchestrator import FormPilotOrchestrator
    import asyncio

    class MockPage:
        async def content(self):
            return "<div>Error: Mobile number is already registered with MeriPehchaan. Please Sign In.</div>"

    orch = object.__new__(FormPilotOrchestrator)
    orch.page = MockPage()

    async def _test():
        res = await orch._idp_detect_already_registered()
        assert res is True

        class MockPageNew:
            async def content(self):
                return "<div>Please enter your mobile number and click Generate OTP.</div>"

        orch.page = MockPageNew()
        res2 = await orch._idp_detect_already_registered()
        assert res2 is False

    asyncio.run(_test())


def test_fill_idp_credential_targets_active_otp_over_disabled_pin():
    from backend.core.orchestrator import FormPilotOrchestrator
    import asyncio

    class MockVault:
        mobile = "9876543210"

    class MockVaultMgr:
        vault = MockVault()

    class MockLocator:
        def __init__(self, visible=True, disabled=False):
            self._visible = visible
            self._disabled = disabled
            self.value = ""

        async def count(self):
            return 1 if self._visible else 0

        async def is_visible(self):
            return self._visible

        async def is_disabled(self):
            return self._disabled

        @property
        def first(self):
            return self

        async def click(self, timeout=None):
            pass

        async def fill(self, val):
            self.value = val

        async def dispatch_event(self, ev):
            pass

    class MockPage:
        url = "https://digilocker.meripehchaan.gov.in/signup/oauth_partner/123"

        def __init__(self):
            self.otp_loc = MockLocator(visible=True, disabled=False)
            self.pin_loc = MockLocator(visible=False, disabled=True)

        def locator(self, sel):
            if "otp" in sel:
                return self.otp_loc
            if "password" in sel:
                return self.pin_loc
            return MockLocator(visible=False)

        def get_by_role(self, role, name=None):
            return MockLocator(visible=True)

    orch = object.__new__(FormPilotOrchestrator)
    orch.page = MockPage()
    orch.vault_mgr = MockVaultMgr()

    async def _test():
        dom = {
            "inputs": [
                {"name": "mobilenumber", "type": "text", "value": "9876543210"},
                {"name": "otp", "id": "otp", "type": "text", "interactable": True, "disabled": False},
                {"name": "pin", "id": "pin", "type": "password", "interactable": False, "disabled": True},
            ]
        }
        res = await orch._fill_idp_credential(dom, "654321")
        assert res.get("success") is True
        assert orch.page.otp_loc.value == "654321"

    asyncio.run(_test())


