"""Unit tests for Set-of-Marks extractor, page state validator, and smart agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.core.som_extractor import IndexedElement, SetOfMarksExtractor
from backend.core.page_validator import PageStateValidator, ValidationState, PageValidationResult
from backend.core.smart_agent import SmartFormAgent, AgentAction


def test_indexed_element_summary():
    el = IndexedElement(
        index=1,
        tag="input",
        element_type="text",
        label="Candidate's Name",
        placeholder="Enter name as per 10th marksheet",
        value="",
        required=True,
    )
    summary = el.summary_line()
    assert "[1] INPUT" in summary
    assert "label='Candidate\'s Name'" in summary
    assert "REQUIRED" in summary


def test_format_for_prompt():
    elements = [
        IndexedElement(index=1, tag="input", element_type="text", label="Candidate Name"),
        IndexedElement(index=2, tag="select", element_type="select", label="Gender", options=["Male", "Female"]),
    ]
    prompt_str = SetOfMarksExtractor.format_for_prompt(elements)
    assert "[1] INPUT" in prompt_str
    assert "[2] SELECT" in prompt_str
    assert "options=['Male', 'Female']" in prompt_str


@pytest.mark.anyio
async def test_page_validator_detects_errors():
    validator = PageStateValidator(max_retries_per_step=2)
    fake_page = MagicMock()
    fake_page.url = "https://example.com/step1"
    fake_page.evaluate = AsyncMock(return_value={
        "errors": ["Candidate Name is required", "Invalid PIN code"],
        "invalidIndices": [1, 5],
        "stepTitle": "Personal Details"
    })

    result = await validator.validate_state(fake_page)
    assert result.state == ValidationState.VALIDATION_ERROR
    assert result.success is False
    assert len(result.error_messages) == 2
    assert 1 in result.invalid_element_indices


@pytest.mark.anyio
async def test_page_validator_circuit_breaker():
    validator = PageStateValidator(max_retries_per_step=2)
    fake_page = MagicMock()
    fake_page.url = "https://example.com/step1"
    fake_page.evaluate = AsyncMock(return_value={
        "errors": ["Invalid PIN code"],
        "invalidIndices": [5],
        "stepTitle": "Personal Details"
    })

    # First attempt -> validation error
    res1 = await validator.validate_state(fake_page)
    assert res1.state == ValidationState.VALIDATION_ERROR

    # Second attempt -> validation error
    res2 = await validator.validate_state(fake_page)
    assert res2.state == ValidationState.VALIDATION_ERROR

    # Third attempt -> Circuit breaker trips!
    res3 = await validator.validate_state(fake_page)
    assert res3.state == ValidationState.STUCK_LOOP
    assert res3.needs_human_intervention is True
    assert "Pausing for candidate review" in res3.intervention_reason


def test_smart_agent_offline_matching():
    agent = SmartFormAgent()
    elements = [
        IndexedElement(index=1, tag="input", element_type="text", label="Candidate's Full Name"),
        IndexedElement(index=2, tag="input", element_type="text", label="Father's Name"),
        IndexedElement(index=3, tag="select", element_type="select", label="Category", options=["General", "OBC-NCL", "SC", "ST"]),
        IndexedElement(index=4, tag="input", element_type="checkbox", label="I agree to terms"),
    ]
    profile = {
        "candidate_name": "Nishant Kumar",
        "father_name": "Rajesh Kumar",
        "category": "OBC-NCL",
        "agree": True,
    }

    actions = agent.match_fields_offline(elements, profile)
    assert len(actions) >= 3

    # Check that candidate name matches index 1
    name_act = next(a for a in actions if a.index == 1)
    assert name_act.value == "Nishant Kumar"

    # Check father's name matches index 2
    father_act = next(a for a in actions if a.index == 2)
    assert father_act.value == "Rajesh Kumar"

    # Check category select matches index 3
    cat_act = next(a for a in actions if a.index == 3)
    assert cat_act.value == "OBC-NCL"
