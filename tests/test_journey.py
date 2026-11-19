"""Known-path memory: structural, redacted and reusable across visits."""

from __future__ import annotations

import json

from backend.core import settings
from backend.core.journey import JourneyStore, journey_key
from backend.core.orchestrator import FormPilotOrchestrator


def _dom(url="https://jeemain.nta.nic.in/", **extra):
    dom = {
        "url": url,
        "title": "JEE (Main) 2027",
        "stepHeading": "Online Application Form",
        "visibleText": "Apply online for JEE (Main) 2027. Candidate Nishant Kumar.",
        "inputs": [],
        "gateways": [],
        "applicationLinks": [],
        "nextButtons": [],
        "captchaElements": [],
        "otpInputs": [],
        "livePhotoRequired": False,
        "hasPaymentButton": False,
        "formCount": 0,
        "formAction": "",
        "frameworks": [],
        "elements": [],
        "loading": False,
    }
    dom.update(extra)
    return dom


def _form_map(page_type="portal_entry", fingerprint="fp-1", fields=None):
    return {
        "url": "https://jeemain.nta.nic.in/",
        "page_type": page_type,
        "fingerprint": fingerprint,
        "fields": fields or [],
    }


def test_journey_key_aliases_the_same_exam():
    assert journey_key("JEE") == "exam_jee"
    assert journey_key("JEE Main") == "exam_jee"
    assert journey_key("JEE Main 2027 Session 1") == "exam_jee"
    assert journey_key("JEE Advanced") == "exam_jee_advanced"
    assert journey_key("https://jeemain.nta.nic.in/") == "portal_jeemain_nta_nic_in"


def test_observe_page_stores_structure_and_redacts_vault_values(tmp_path):
    store = JourneyStore(tmp_path)
    dom = _dom(
        applicationLinks=[
            {
                "text": "Online Application Form for JEE (Main) 2027 - Session 1",
                "href": "https://examinationservices.nic.in/root/Home.aspx?enc=abc",
                "tagName": "a",
                "id": "apply",
            }
        ]
    )
    form_map = _form_map(
        fields=[
            {
                "semantic_key": "full_name",
                "label": "Candidate Name",
                "name": "txtName",
                "id": "txtName",
                "type": "text",
                "required": True,
            }
        ]
    )

    step = store.observe_page(
        "exam_jee",
        dom,
        form_map,
        secrets=["Nishant Kumar"],
    )

    assert step["step_id"] == "fp-1"
    assert step["fields"][0]["semantic_key"] == "full_name"
    assert step["application_links"][0]["href"].endswith("Home.aspx?enc=abc")
    assert "<redacted>" in step["dom_snapshot"]["visible_text"]

    saved = json.loads((tmp_path / "exam_jee.json").read_text(encoding="utf-8"))
    serialized = json.dumps(saved)
    assert "Nishant Kumar" not in serialized
    assert "txtName" in serialized


def test_loading_and_empty_pages_are_not_stored(tmp_path):
    store = JourneyStore(tmp_path)

    assert store.observe_page("exam_jee", _dom(loading=True), _form_map()) is None
    assert store.observe_page(
        "exam_jee",
        _dom(visibleText="", inputs=[]),
        _form_map(fingerprint=""),
    ) is None
    assert store.load("exam_jee") is None


def test_match_step_by_fingerprint_and_url_path(tmp_path):
    store = JourneyStore(tmp_path)
    store.observe_page(
        "exam_jee",
        _dom(url="https://jeemain.nta.nic.in/registration/step-1"),
        _form_map(page_type="application_form", fingerprint="fp-registration"),
    )

    exact = store.match_step(
        "exam_jee",
        _dom(url="https://jeemain.nta.nic.in/registration/step-1"),
        _form_map(page_type="application_form", fingerprint="fp-registration"),
    )
    assert exact is not None
    assert exact["step_id"] == "fp-registration"

    by_path = store.match_step(
        "exam_jee",
        _dom(url="https://jeemain.nta.nic.in/registration/step-1?fresh=1"),
        _form_map(page_type="application_form", fingerprint="different"),
    )
    assert by_path is not None
    assert by_path["step_id"] == "fp-registration"


def test_transitions_and_proven_steps_are_recorded(tmp_path):
    store = JourneyStore(tmp_path)
    store.observe_page("exam_jee", _dom(), _form_map(fingerprint="fp-entry"))
    store.observe_page(
        "exam_jee",
        _dom(url="https://examinationservices.nic.in/root/Home.aspx"),
        _form_map(page_type="portal_entry", fingerprint="fp-home"),
    )

    store.record_transition(
        "exam_jee",
        from_step="fp-entry",
        action="open_application",
        target="Online Application Form",
        to_step="fp-home",
    )
    store.mark_step_success("exam_jee", "fp-entry")

    journey = store.load("exam_jee")
    assert journey["transitions"][0]["successes"] == 1
    entry = next(step for step in journey["steps"] if step["step_id"] == "fp-entry")
    assert entry["successes"] == 1
    assert store.summary("exam_jee")["proven_steps"] == 1


def test_autopilot_requires_a_clean_step(monkeypatch):
    orchestrator = object.__new__(FormPilotOrchestrator)
    orchestrator._journey_step = {"successes": 1, "checkpoints": []}
    orchestrator.fill_summary = {"status": "FILLED", "choice_fields": []}
    orchestrator.fill_failures = []

    assert orchestrator._can_autopilot_step() is True

    # A first visit may continue without a review click when every field
    # verified, but only while section autopilot is enabled.
    orchestrator._journey_step = {"successes": 0, "checkpoints": []}
    assert orchestrator._can_autopilot_step() is True
    monkeypatch.setattr(settings, "AUTOPILOT_SECTIONS", False)
    assert orchestrator._can_autopilot_step() is False
    monkeypatch.setattr(settings, "AUTOPILOT_SECTIONS", True)

    orchestrator._journey_step = {"successes": 1, "checkpoints": ["captcha"]}
    assert orchestrator._can_autopilot_step() is False

    orchestrator._journey_step = {"successes": 1, "checkpoints": []}
    orchestrator.fill_summary = {"status": "PARTIAL", "choice_fields": []}
    assert orchestrator._can_autopilot_step() is False


def test_journey_field_hint_reuses_a_learned_mapping():
    orchestrator = object.__new__(FormPilotOrchestrator)
    orchestrator._journey_field_hints = {"txtcandidatename": "full_name"}

    assert orchestrator._journey_field_hint({"name": "txtCandidateName"}) == "full_name"
    assert orchestrator._journey_field_hint({"name": "other"}) == ""


def test_affirmative_pattern_matches_portal_confirm_buttons():
    from backend.core.orchestrator import FormPilotOrchestrator as O

    assert O._AFFIRMATIVE_RE.search("OK, I Agree / सहमत हूँ")
    assert O._AFFIRMATIVE_RE.search("Yes")
    assert O._AFFIRMATIVE_RE.search("Confirm")
    assert not O._AFFIRMATIVE_RE.search("Cancel")
    assert O._NEGATIVE_RE.search("Cancel")
    assert O._NEGATIVE_RE.search("No, go back")


def test_identity_provider_page_is_detected_and_never_filled():
    from types import SimpleNamespace
    from backend.core.orchestrator import FormPilotOrchestrator as O

    orchestrator = object.__new__(O)
    orchestrator.target_url = "https://jeemain.nta.nic.in/"
    orchestrator._idp_signed_in = set()
    orchestrator.page = SimpleNamespace(
        url="https://digilocker.meripehchaan.gov.in/signinv2/oauth_partner/abc"
    )
    dom = {
        "inputs": [
            {"type": "text", "id": "mobilenumber", "name": "mobilenumber"},
            {"type": "password", "id": "passwordmobile", "name": "pin"},
        ]
    }

    assert orchestrator._is_external_identity_page(dom) is True

    orchestrator.page = SimpleNamespace(
        url="https://examinationservices.nic.in/JeeMaink2027/Registration/Form.aspx"
    )
    assert orchestrator._is_external_identity_page(dom) is False


def test_password_box_is_never_mapped_to_a_contact_field():
    from backend.core.dom_scanner import DOMScanner

    assert DOMScanner.classify_field(
        {"type": "password", "id": "passwordmobile", "name": "pin", "label": "pin"}
    ) == (None, False)
    assert DOMScanner.classify_field(
        {"type": "password", "id": "password", "name": "password", "label": "Password"}
    ) == ("account_password", False)


def test_journey_ignores_browser_error_pages(tmp_path):
    store = JourneyStore(root=str(tmp_path))
    dom = {"url": "chrome-error://chromewebdata/", "visibleText": "This site can't be reached"}
    assert store.observe_page("exam_jee", dom, {"fields": []}) is None


def test_journey_marks_oauth_password_page_as_identity_checkpoint(tmp_path):
    store = JourneyStore(root=str(tmp_path))
    dom = {
        "url": "https://digilocker.meripehchaan.gov.in/signinv2/oauth_partner/abc",
        "visibleText": "Sign In",
        "inputs": [{"type": "password", "id": "pin", "name": "pin"}],
    }
    step = store.observe_page("exam_jee", dom, {"fields": [], "page_type": "login"})
    assert step is not None
    assert "identity" in step["checkpoints"]
