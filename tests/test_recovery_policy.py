"""Error recognition, safe recovery and application-link ranking."""

from __future__ import annotations

from backend.core.orchestrator import FormPilotOrchestrator


def test_error_collection_ignores_instructions_but_keeps_real_failures():
    dom = {
        "url": "https://jeemain.nta.nic.in/",
        "errors": [
            "Please read the instructions carefully before applying.",
            "Enter a valid date of birth.",
        ],
        "alerts": ["Server error. Please try again."],
        "dialogs": [{"text": "Session expired. Please sign in again."}],
    }

    errors = FormPilotOrchestrator._collect_page_errors(dom)

    assert "Enter a valid date of birth." in errors
    assert "Server error. Please try again." in errors
    assert "Session expired. Please sign in again." in errors
    assert all("instructions carefully" not in item for item in errors)


def test_retry_control_is_found_by_its_label():
    dom = {
        "elements": [
            {"visible": True, "enabled": True, "tag": "button", "text": "Save & Next"},
            {"visible": True, "enabled": True, "tag": "button", "text": "Try again"},
        ]
    }

    retry = FormPilotOrchestrator._find_retry_control(dom)

    assert retry is not None
    assert retry["text"] == "Try again"
    assert retry["element_id"] is None


def test_application_targets_drop_notices_and_keep_distinct_destinations():
    links = [
        {
            "text": "Online Application Form for JEE (Main) 2027",
            "href": "https://examinationservices.nic.in/JeeMaink2027/root/Home.aspx?enc=1",
        },
        {
            "text": "Online Application Form for JEE (Main) 2027",
            "href": "https://examinationservices.nic.in/JeeMaink2027/root/Home.aspx?enc=1",
        },
        {
            "text": "Public Notice regarding JEE (Main) 2027",
            "href": "https://jeemain.nta.nic.in/notice.pdf",
        },
        {
            "text": "Apply Online",
            "href": "https://examinationservices.nic.in/session-1",
        },
        {
            "text": "Apply Online",
            "href": "https://examinationservices.nic.in/session-2",
        },
    ]

    targets = FormPilotOrchestrator._distinct_application_targets(links)

    # Two links with the same label cannot be told apart by the candidate, so
    # they collapse to the higher-scored one.  Different labels stay distinct.
    assert len(targets) == 2
    hrefs = {link["href"] for link in targets}
    assert "https://examinationservices.nic.in/JeeMaink2027/root/Home.aspx?enc=1" in hrefs
    assert any(
        href in {"https://examinationservices.nic.in/session-1", "https://examinationservices.nic.in/session-2"}
        for href in hrefs
    )
    assert all("notice.pdf" not in href for href in hrefs)


def test_application_link_score_prefers_the_real_application_system():
    real = FormPilotOrchestrator._application_link_score(
        {
            "text": "Online Application Form for JEE (Main) 2027",
            "href": "https://examinationservices.nic.in/JeeMaink2027/root/Home.aspx",
        }
    )
    notice = FormPilotOrchestrator._application_link_score(
        {"text": "Notice", "href": "https://jeemain.nta.nic.in/notice.pdf"}
    )

    assert real > notice
