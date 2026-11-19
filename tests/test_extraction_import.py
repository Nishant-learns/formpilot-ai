"""The BYOK extraction contract: prompt, validation, mapping, and safe apply."""

from __future__ import annotations

import json

import pytest

from backend.core.extraction_contract import (
    EXTRACTION_PROMPT,
    SCHEMA,
    SCHEMA_VERSION,
    apply_import,
    build_import_plan,
    normalize_date,
    normalize_phone,
    split_full_name,
    strip_honorific,
)
from backend.core.vault import CandidateVault, VaultManager


@pytest.fixture()
def vault(tmp_path):
    manager = VaultManager(str(tmp_path / "candidate_vault.json"))
    manager.reset_defaults()
    return manager


def verdicts(plan):
    return {field.key: field.verdict for field in plan.fields}


def values(plan):
    return {field.key: field.value for field in plan.fields}


def test_prompt_is_self_contained_and_asks_for_json_only():
    assert SCHEMA_VERSION in EXTRACTION_PROMPT
    assert "JSON" in EXTRACTION_PROMPT
    assert "Never guess" in EXTRACTION_PROMPT
    assert SCHEMA["schema_version"] == SCHEMA_VERSION
    assert "education" in EXTRACTION_PROMPT
    assert "extras" in EXTRACTION_PROMPT
    assert "Field guide:" in EXTRACTION_PROMPT
    assert "Requirements:" in EXTRACTION_PROMPT


def _leaf_values(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "schema_version":
                continue
            yield from _leaf_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _leaf_values(item)
    else:
        yield node


def test_schema_is_placeholder_only_and_has_no_prefilled_values():
    # The user copies this prompt into ChatGPT/Gemini.  A sample name, date or
    # format token in the template can be copied back as if it were real data.
    assert all(value == "" for value in _leaf_values(SCHEMA))
    template = EXTRACTION_PROMPT.split("Field guide:")[0]
    assert '"full_name": ""' in template
    assert "as printed on the document" not in template
    assert "YYYY-MM-DD" not in template
    assert "Demo" not in template
    assert "Nishant" not in template


def test_normalize_date_accepts_real_formats_and_rejects_impossible_dates():
    assert normalize_date("2005-08-03") == "2005-08-03"
    assert normalize_date("03/08/2005") == "2005-08-03"
    assert normalize_date("3-8-2005") == "2005-08-03"
    assert normalize_date("03 Aug 2005") == "2005-08-03"
    assert normalize_date("31/02/2005") is None
    assert normalize_date("not a date") is None
    assert normalize_date("") is None


def test_normalize_phone_handles_country_codes():
    assert normalize_phone("+91 98765 43210") == "9876543210"
    assert normalize_phone("09876543210") == "9876543210"
    assert normalize_phone("9876543210") == "9876543210"
    assert normalize_phone("123") is None


def test_names_lose_titles_and_split_sensibly():
    assert strip_honorific("Mr. Nishant Kumar") == "Nishant Kumar"
    assert split_full_name("Mr. Nishant Kumar") == {
        "first": "Nishant",
        "middle": None,
        "last": "Kumar",
        "middle_known_absent": True,
    }
    assert split_full_name("Aman Kumar Sharma")["middle"] == "Kumar"
    assert split_full_name("Nishant")["last"] is None


def test_name_parts_are_composed_when_the_model_returns_them_separately(vault):
    plan = build_import_plan(
        {"first_name": "Nishant", "last_name": "Kumar"},
        vault.vault,
    )

    assert values(plan)["full_name"] == "Nishant Kumar"


def test_full_profile_maps_onto_the_same_registry_the_fill_loop_uses(vault):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "full_name": "Mr. Nishant Kumar",
            "father_name": "Rajesh Kumar",
            "dob": "03/08/2005",
            "gender": "M",
        },
        "contact": {
            "mobile": "+91 98765 43210",
            "address": {"city": "Patna", "pincode": "800001"},
        },
        "education": [
            {
                "level": "10th",
                "board": "CBSE",
                "roll_number": "24108842",
                "passing_year": "2019",
                "percentage": "88.4%",
                "school_or_college": "Demo School",
            },
            {
                "level": "12th",
                "board": "BSEB",
                "roll_number": "21030045",
                "percentage": "83",
                "college": "Demo College",
            },
        ],
        "identity": {"aadhaar_number": "1234 5678 9012"},
    }
    plan = build_import_plan(payload, vault.vault)
    result = values(plan)

    assert result["full_name"] == "Nishant Kumar"
    assert result["dob"] == "2005-08-03"
    assert result["gender"] == "Male"
    assert result["mobile"] == "9876543210"
    assert result["village_town_city"] == "Patna"
    assert result["matric_board"] == "CBSE"
    assert result["matric_roll_number"] == "24108842"
    assert result["matric_school_name"] == "Demo School"
    assert result["intermediate_college_name"] == "Demo College"
    assert result["aadhaar_number"] == "123456789012"
    assert not plan.errors


def test_same_value_is_not_reported_as_a_conflict(vault):
    payload = {"profile": {"full_name": "Aman  Kumar Sharma", "dob": "15/08/2003"}}
    plan = build_import_plan(payload, vault.vault)

    assert verdicts(plan)["full_name"] == "same"
    assert verdicts(plan)["dob"] == "same"


def test_numeric_spellings_are_equivalent(vault):
    plan = build_import_plan(
        {"education": [{"level": "10th", "percentage": "88.4%"}]},
        vault.vault,
    )

    assert verdicts(plan)["matric_percentage"] == "same"


def test_a_real_difference_is_a_conflict_and_is_never_applied_silently(vault):
    plan = build_import_plan(
        {"profile": {"full_name": "Aman Kumar Verma"}},
        vault.vault,
    )
    field = next(item for item in plan.fields if item.key == "full_name")
    assert field.verdict == "conflict"
    assert field.current == "Aman Kumar Sharma"

    result = apply_import(plan, vault)
    assert "full_name" not in result["applied"]
    assert vault.vault.full_name == "Aman Kumar Sharma"


def test_conflict_is_applied_when_the_candidate_explicitly_accepts_it(vault):
    plan = build_import_plan({"profile": {"full_name": "Aman Kumar Verma"}}, vault.vault)

    result = apply_import(plan, vault, accept=["full_name"])

    assert result["applied"] == ["full_name"]
    assert vault.vault.full_name == "Aman Kumar Verma"
    # The "verify" field is kept in sync so a portal that asks for the name
    # twice does not fail.
    assert vault.vault.verify_full_name == "Aman Kumar Verma"


def test_invalid_values_are_reported_and_not_written(vault):
    plan = build_import_plan({"profile": {"dob": "31/02/2005"}}, vault.vault)
    field = next(item for item in plan.fields if item.key == "dob")

    assert field.verdict == "invalid"
    assert field.note == "Not a valid date."
    assert apply_import(plan, vault)["applied"] == []
    assert vault.vault.dob == "2003-08-15"


def test_uncertain_values_need_a_human(vault):
    plan = build_import_plan(
        {"profile": {"gender": {"value": "M", "uncertain": True}}},
        vault.vault,
    )

    assert verdicts(plan)["gender"] == "uncertain"
    assert "gender" not in apply_import(plan, vault)["applied"]


def test_unknown_details_are_kept_as_extras_not_guessed(vault):
    plan = build_import_plan(
        {
            "profile": {"full_name": "Aman Kumar Sharma"},
            "extras": {"apaar_id": "1234-5678-9012", "blood_group": "B+"},
        },
        vault.vault,
    )

    assert plan.extras["apaar_id"] == "1234-5678-9012"
    apply_import(plan, vault)
    assert vault.vault.custom_fields["apaar_id"] == "1234-5678-9012"
    assert vault.vault.custom_fields["blood_group"] == "B+"


def test_a_recognised_concept_without_a_column_becomes_an_extra(vault):
    plan = build_import_plan({"identity": {"pan_number": "ABCDE1234F"}}, vault.vault)

    assert "pan_number" in plan.extras
    assert "pan_number" not in verdicts(plan)


def test_bad_json_is_explained_not_raised(vault):
    plan = build_import_plan("{not json", vault.vault)

    assert plan.errors
    assert "not valid JSON" in plan.errors[0]


def test_non_object_payload_is_rejected(vault):
    assert build_import_plan("[1, 2, 3]", vault.vault).errors
    assert build_import_plan({"schema_version": SCHEMA_VERSION}, vault.vault).errors


def test_older_schema_still_imports_with_a_warning(vault):
    plan = build_import_plan(
        {"schema_version": "formpilot_profile_v0", "profile": {"full_name": "Aman Kumar Sharma"}},
        vault.vault,
    )

    assert plan.warnings and "formpilot_profile_v0" in plan.warnings[0]
    assert values(plan)["full_name"] == "Aman Kumar Sharma"


def test_imported_values_resolve_through_the_fill_loop(vault):
    plan = build_import_plan(
        {
            "education": [
                {"level": "10th", "board": "CBSE", "roll_number": "24108842"},
            ],
            "profile": {"father_name": "Rajesh Kumar"},
        },
        vault.vault,
    )
    apply_import(plan, vault, accept=[field.key for field in plan.fields])

    assert vault.vault.find_field_value("matric_roll_number") == "24108842"
    assert vault.vault.find_field_value("father_name") == "Rajesh Kumar"


def test_api_prompt_and_import_round_trip(client):
    prompt = client.get("/api/vault/extraction-prompt").json()
    assert prompt["schema_version"] == SCHEMA_VERSION
    assert prompt["prompt_version"]
    assert "education" in prompt["prompt"]
    assert len(prompt["steps"]) >= 4
    assert prompt["field_guide"]
    assert prompt["schema"]["profile"]["full_name"] == ""

    review = client.post(
        "/api/vault/import-extraction",
        json={"payload": {"profile": {"father_name": "Suresh Prasad"}}, "apply": False},
    )
    assert review.status_code == 200
    plan = review.json()["plan"]
    assert plan["summary"]["conflict"] == 1
    # Nothing is written during review, and the demo value is untouched.
    assert client.get("/api/vault").json()["father_name"] == "Rajesh Kumar Sharma"

    applied = client.post(
        "/api/vault/import-extraction",
        json={
            "payload": {"profile": {"father_name": "Suresh Prasad"}},
            "apply": True,
            "accept": ["father_name"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"]["applied"] == ["father_name"]
    assert client.get("/api/vault").json()["father_name"] == "Suresh Prasad"


def test_api_rejects_unreadable_json(client):
    response = client.post(
        "/api/vault/import-extraction",
        json={"payload": "{not json", "apply": False},
    )

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert response.json()["errors"]


def test_api_accepts_the_raw_pasted_text(client):
    response = client.post(
        "/api/vault/import-extraction",
        json={"payload": json.dumps({"profile": {"mother_name": "Sunita Sharma"}})},
    )

    assert response.status_code == 200
    assert response.json()["plan"]["summary"]["conflict"] == 1
