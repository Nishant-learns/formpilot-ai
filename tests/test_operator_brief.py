"""The operator brief and real page navigation the chat assistant relies on."""

from __future__ import annotations

import asyncio

from backend.core.action_resolver import ActionResult
from backend.core.blueprint import BlueprintElement, PageBlueprint
from backend.core.chat_assistant import FormPilotChatAssistant
from backend.core.orchestrator import FormPilotOrchestrator


class FakePage:
    def __init__(self, closed=False):
        self._closed = closed
        self.url = "https://hpsc.gov.in/apply/step-2"
        self.went_back = 0

    def is_closed(self):
        return self._closed

    async def go_back(self, **kwargs):
        self.went_back += 1
        self.url = "https://hpsc.gov.in/apply/step-1"


class FakeResolver:
    def __init__(self, *, changed=True, click_ok=True):
        self.changed = changed
        self.click_ok = click_ok
        self.clicked = []

    async def _page_state(self):
        return {"url": "https://hpsc.gov.in/apply/step-2", "textDigest": "same"}

    async def click(self, element_id):
        self.clicked.append(element_id)
        return ActionResult(
            ok=self.click_ok,
            action="click",
            element_id=element_id,
            postcondition="changed" if self.changed else "no_change",
            message="Clicked the Back control." if self.click_ok else "The control is disabled.",
        )


def _blueprint(*labels):
    elements = [
        BlueprintElement(
            id=f"el-{index}",
            tag="button",
            role="button",
            name=label,
            text=label,
            visible=True,
            interactable=True,
        )
        for index, label in enumerate(labels)
    ]
    return PageBlueprint(
        scan_id="scan-test",
        url="https://hpsc.gov.in/apply/step-2",
        title="Application",
        elements=elements,
    )


class FakeAdapter:
    name = "simulator"

    def find_next_button(self, dom):
        return {"id": "final-submit", "label": "Final Submit"}


def _orchestrator():
    orchestrator = FormPilotOrchestrator()
    orchestrator.run_id = "run-test"
    orchestrator.state = "RUNNING"
    orchestrator.is_running = True
    return orchestrator


def _silence_events(orchestrator):
    async def emit_event(*args, **kwargs):
        return None

    orchestrator.emit_event = emit_event


def test_operator_brief_is_compact_and_honest_without_a_browser():
    brief = _orchestrator().operator_brief()

    assert brief["engine"]["driver"] == "none"
    assert brief["can_go_back"] is False
    assert brief["recent_events"] == []
    assert "saved_details" in brief


def test_operator_brief_reports_the_pending_gate_and_inputs():
    orchestrator = _orchestrator()
    orchestrator.active_gate = {
        "gate_type": "OTP_RELAY",
        "title": "Enter the OTP",
        "reason": "OTP_REQUIRED",
    }
    orchestrator.form_map = {
        "page_type": "otp",
        "title": "Verify mobile",
        "fields": [
            {"label": "Aadhaar Number", "needs_user_input": True},
            {"label": "Full Name", "needs_user_input": False},
        ],
    }

    brief = orchestrator.operator_brief()

    assert brief["open_gate"]["type"] == "OTP_RELAY"
    assert brief["open_gate"]["human_only"] is True
    assert brief["pending_inputs"] == ["Aadhaar Number"]
    assert brief["page_type"] == "otp"


def test_recent_events_are_bounded_and_ordered():
    orchestrator = _orchestrator()
    for index in range(30):
        orchestrator.recent_events.append({"at": "10:00", "phase": "ACT", "message": f"step {index}"})

    brief = orchestrator.operator_brief()

    assert len(orchestrator.recent_events) == 12
    assert brief["recent_events"][-1]["message"] == "step 29"


def test_engine_label_never_lets_a_local_fallback_look_cloud():
    orchestrator = _orchestrator()
    orchestrator._session = type(
        "Session",
        (),
        {
            "session_id": "abc",
            "is_cloud": False,
            "proxy_node": None,
            "country_code": None,
            "fallback_reason": "INSUFFICIENT_CREDITS",
        },
    )()

    label = orchestrator._engine_label()

    assert label["driver"] == "local-playwright"
    assert label["is_cloud"] is False
    assert label["fallback_reason"] == "INSUFFICIENT_CREDITS"


def test_engine_label_names_tinyfish_when_it_is_driving():
    orchestrator = _orchestrator()
    orchestrator._session = type(
        "Session",
        (),
        {
            "session_id": "abc",
            "is_cloud": True,
            "proxy_node": "us-east",
            "country_code": "US",
            "fallback_reason": None,
        },
    )()

    label = orchestrator._engine_label()

    assert label["driver"] == "tinyfish-cloud"
    assert label["label"] == "TinyFish cloud browser"


def test_go_back_moves_real_history_and_rescans(monkeypatch):
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator._visited_urls = [
        "https://hpsc.gov.in/apply/step-1",
        "https://hpsc.gov.in/apply/step-2",
    ]
    _silence_events(orchestrator)
    rescans = {"count": 0}

    async def fake_scan():
        return {"buttons": []}

    async def fake_observe(**kwargs):
        rescans["count"] += 1
        return {}, {"title": "Education details", "page_type": "form", "fields": []}

    orchestrator._scan_dom = fake_scan
    orchestrator._observe_page = fake_observe

    result = asyncio.run(orchestrator.go_back())

    assert result["success"] is True
    assert result["method"] == "history"
    assert orchestrator.page.went_back == 1
    assert rescans["count"] == 1
    assert result["title"] == "Education details"
    assert orchestrator.form_map["title"] == "Education details"


def test_go_back_prefers_an_in_page_control_on_a_single_page_wizard():
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator.blueprint = _blueprint("← Back to Personal")
    orchestrator._visited_urls = ["https://hpsc.gov.in/apply"]
    _silence_events(orchestrator)
    resolver = FakeResolver(changed=True)

    async def fake_scan():
        return {"buttons": []}

    async def fake_observe(**kwargs):
        return {}, {"title": "Personal details", "page_type": "form", "fields": []}

    orchestrator._scan_dom = fake_scan
    orchestrator._observe_page = fake_observe
    orchestrator._action_resolver = lambda: resolver

    result = asyncio.run(orchestrator.go_back())

    assert result["success"] is True
    assert result["method"] == "in_page_control"
    assert resolver.clicked == ["el-0"]
    assert orchestrator.page.went_back == 0
    assert result["title"] == "Personal details"


def test_go_back_does_not_treat_logout_or_cancel_as_back():
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator.blueprint = _blueprint("Log Out Session", "Cancel application", "Back to login")
    orchestrator._visited_urls = ["https://hpsc.gov.in/apply"]
    _silence_events(orchestrator)

    async def fake_scan():
        return {"buttons": []}

    orchestrator._scan_dom = fake_scan

    result = asyncio.run(orchestrator.go_back())

    assert result["success"] is False
    assert "does not show a Previous/Back control" in result["message"]
    assert orchestrator.page.went_back == 0


def test_go_back_refuses_history_when_only_one_url_was_seen():
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator._visited_urls = ["https://hpsc.gov.in/apply"]
    _silence_events(orchestrator)

    async def fake_scan():
        return {"buttons": []}

    orchestrator._scan_dom = fake_scan

    result = asyncio.run(orchestrator.go_back())

    assert result["success"] is False
    assert orchestrator.page.went_back == 0
    assert "could leave the portal" in result["message"]


def test_go_back_reports_when_the_back_control_does_not_move_the_page():
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator.blueprint = _blueprint("Previous step")
    orchestrator._visited_urls = ["https://hpsc.gov.in/apply"]
    _silence_events(orchestrator)
    resolver = FakeResolver(changed=False)

    async def fake_scan():
        return {"buttons": []}

    orchestrator._scan_dom = fake_scan
    orchestrator._action_resolver = lambda: resolver

    result = asyncio.run(orchestrator.go_back())

    assert result["success"] is False
    assert resolver.clicked == ["el-0"]
    assert "did not move the page" in result["message"]
    assert orchestrator.page.went_back == 0


def test_go_back_is_refused_on_the_final_declaration_page(monkeypatch):
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator._adapter = FakeAdapter()
    _silence_events(orchestrator)

    async def fake_scan():
        return {"buttons": [{"id": "final-submit"}]}

    orchestrator._scan_dom = fake_scan
    orchestrator._page_looks_final = lambda dom, button: True

    result = asyncio.run(orchestrator.go_back())

    assert result["success"] is False
    assert "final declaration" in result["message"].lower()
    assert orchestrator.page.went_back == 0


def test_go_back_without_a_browser_is_a_clear_refusal():
    result = asyncio.run(_orchestrator().go_back())

    assert result["success"] is False
    assert "no live page" in result["message"].lower()


def test_chat_rules_route_go_back_to_the_orchestrator():
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    orchestrator._visited_urls = [
        "https://hpsc.gov.in/apply/step-1",
        "https://hpsc.gov.in/apply/step-2",
    ]
    _silence_events(orchestrator)

    async def fake_scan():
        return {"buttons": []}

    async def fake_observe(**kwargs):
        return {}, {"title": "Personal details", "page_type": "form", "fields": []}

    orchestrator._scan_dom = fake_scan
    orchestrator._observe_page = fake_observe
    assistant = FormPilotChatAssistant(orchestrator=orchestrator)

    reply = asyncio.run(assistant._try_navigation_action("please go back to the previous page"))

    assert reply["action_taken"] == "NAVIGATION_BACK"
    assert orchestrator.page.went_back == 1
    assert "Personal details" in reply["reply"]


def test_chat_does_not_treat_portal_logout_as_go_back():
    assistant = FormPilotChatAssistant(orchestrator=_orchestrator())

    result = asyncio.run(assistant._try_navigation_action("click the back button of the portal to sign out"))

    assert result is None


def test_chat_reports_a_refused_go_back_instead_of_claiming_success():
    orchestrator = _orchestrator()
    orchestrator.page = FakePage()
    assistant = FormPilotChatAssistant(orchestrator=orchestrator)

    async def refuse(**kwargs):
        return {"success": False, "message": "This looks like the final declaration step."}

    orchestrator.go_back = refuse

    reply = asyncio.run(assistant._try_navigation_action("go back"))

    assert reply["action_taken"] == "NAVIGATION_BLOCKED"
    assert "final declaration" in reply["reply"]


def test_chat_operator_context_includes_the_live_brief():
    orchestrator = _orchestrator()
    orchestrator.active_gate = {"gate_type": "CAPTCHA_SOLVE", "title": "Solve the CAPTCHA"}
    assistant = FormPilotChatAssistant(orchestrator=orchestrator)

    context = assistant._state_context()

    assert context["operator"]["open_gate"]["human_only"] is True
    assert context["operator"]["engine"]["driver"] == "none"
