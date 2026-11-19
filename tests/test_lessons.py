"""Per-account portal lessons: bounded, scoped and privacy-safe."""

from __future__ import annotations

import json

from backend.core.lessons import LessonStore, normalize_domain, normalize_signature


def test_lessons_are_scoped_to_domain_and_normalized_signature(tmp_path):
    store = LessonStore(str(tmp_path / "lessons.json"))

    store.record(
        domain="https://jeemain.nta.nic.in/registration",
        signature="Server Error 503 while saving",
        action="auto_recover",
        outcome="recovered",
        note="Reload worked once.",
    )

    # Numbers and ids change between attempts; the lesson must still match.
    recalled = store.recall(
        domain="jeemain.nta.nic.in",
        signature="Server Error 504 while saving",
    )
    assert recalled is not None
    assert recalled["attempts"] == 1
    assert recalled["successes"] == 1
    assert recalled["action"] == "auto_recover"

    # A different portal is a different account context.
    assert store.recall(domain="ssc.gov.in", signature="Server Error 504 while saving") is None


def test_repeat_failures_merge_into_one_lesson(tmp_path):
    store = LessonStore(str(tmp_path / "lessons.json"))

    for _ in range(2):
        store.record(
            domain="example.gov.in",
            signature="The page has not changed",
            action="auto_recover",
            outcome="failed",
        )

    recalled = store.recall(domain="example.gov.in", signature="The page has not changed")
    assert recalled["attempts"] == 2
    assert recalled["failures"] == 2
    assert len(store.for_domain("example.gov.in")) == 1


def test_summary_is_a_small_public_view(tmp_path):
    store = LessonStore(str(tmp_path / "lessons.json"))
    store.record(
        domain="example.gov.in",
        signature="Session expired",
        action="human_review",
        outcome="worked",
    )

    summary = store.summary("example.gov.in")
    assert summary == [
        {
            "action": "human_review",
            "outcome": "worked",
            "successes": 1,
            "failures": 0,
            "note": "",
        }
    ]


def test_corrupt_lesson_file_never_stops_a_run(tmp_path):
    path = tmp_path / "lessons.json"
    path.write_text("{not json", encoding="utf-8")

    store = LessonStore(str(path))
    assert store.for_domain("example.gov.in") == []

    store.record(
        domain="example.gov.in",
        signature="Server error",
        action="auto_recover",
        outcome="failed",
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["lessons"][0]["domain"] == "example.gov.in"


def test_normalizers_are_stable():
    assert normalize_domain("https://JEEAdv.ac.in/path") == "jeeadv.ac.in"
    assert normalize_domain("example.gov.in") == "example.gov.in"
    assert normalize_signature("Error 12345 at 2026-01-01") == "error <n> at <n>-<n>-<n>"
