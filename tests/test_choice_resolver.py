"""Choice groups are answered from the candidate's own vault, never guessed."""

from __future__ import annotations

from types import SimpleNamespace

from backend.core import choice_resolver


def _group(*labels, name="rblOption", field_type="radio"):
    return [
        {
            "id": f"{name}_{index}",
            "name": name,
            "type": field_type,
            "label": label,
            "value": str(index),
        }
        for index, label in enumerate(labels)
    ]


def _resolve(group, vault, learned=None, page_text=""):
    return choice_resolver.resolve_group(
        group, group[0], vault, page_text=page_text, learned=learned or {}
    )


def test_jee_nationality_options_resolve_from_vault():
    group = _group(
        "Indian Nationals (including NRIs who have Aadhaar): Candidates who are "
        "citizens of India. भारतीय नागरिक (एनआरआई सहित जिनके पास आधार कार्ड है)",
        "Foreign Nationals (including OCI Cardholders): Candidates who are not "
        "citizens of India.",
        "NRIs (Having NO Aadhaar): Non-Resident Indians holding Indian Passport.",
    )
    resolved = _resolve(group, SimpleNamespace(nationality="Indian"))

    assert resolved is not None
    assert resolved["concept"] == "nationality"
    assert resolved["item"]["value"] == "0"
    assert resolved["label"].startswith("Indian Nationals")


def test_category_ews_is_matched_exactly():
    group = _group("General", "Gen-EWS", "OBC(NCL)", "SC", "ST")
    resolved = _resolve(group, SimpleNamespace(category="EWS"))

    assert resolved is not None
    assert resolved["item"]["label"] == "Gen-EWS"


def test_gender_male_never_matches_female():
    group = _group("Female", "Male", "Transgender")
    resolved = _resolve(group, SimpleNamespace(gender="Male"))

    assert resolved is not None
    assert resolved["item"]["label"] == "Male"

    missing = _resolve(group, SimpleNamespace(gender="Other"))
    assert missing is None


def test_missing_vault_value_returns_none():
    group = _group("General", "OBC", "SC", "ST")
    assert _resolve(group, SimpleNamespace(category="")) is None
    assert _resolve(group, SimpleNamespace()) is None


def test_learned_concept_is_used_when_option_text_is_ambiguous():
    group = _group("Yes", "No", name="rblChoice")
    vault = SimpleNamespace(has_aadhaar="Yes")

    assert _resolve(group, vault) is None
    resolved = _resolve(group, vault, learned={"rblchoice": "has_aadhaar"})
    assert resolved is not None
    assert resolved["item"]["label"] == "Yes"


def test_no_inference_from_page_text_for_bare_yes_no():
    group = _group("Yes", "No", name="rblOption")
    resolved = _resolve(
        group,
        SimpleNamespace(is_differently_abled="No"),
        page_text="Aadhaar disability ex-serviceman declaration",
    )
    assert resolved is None
