"""Unit and contract tests for the Ground-Truth Exam Intelligence System.

Tests BlueprintRegistry, PreFlightValidator, DocumentProcessor, and DOMScanner grounding.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from PIL import Image
import pytest

from backend.knowledge.blueprint_loader import BlueprintRegistry
from backend.knowledge.schemas.exam_blueprint_schema import DocumentFormat, ExamBlueprint
from backend.core.preflight_validator import PreFlightValidator
from backend.core.document_processor import DocumentProcessor
from backend.core.dom_scanner import DOMScanner


def test_blueprint_registry_loads_jee_2027():
    registry = BlueprintRegistry.get_instance()
    exams = registry.list_available_exams()
    assert len(exams) >= 1
    
    jee_meta = next((e for e in exams if e["exam_id"] == "NTA_JEE_MAIN_2027"), None)
    assert jee_meta is not None
    assert jee_meta["cycle_year"] == 2027
    assert jee_meta["field_count"] >= 40
    assert "photo" in jee_meta["document_types"]
    assert "signature" in jee_meta["document_types"]

    # Test lookup by domain
    bp_domain = registry.find_by_url_or_domain("https://examinationservices.nic.in/jeemain2027/root/home.aspx")
    assert bp_domain is not None
    assert bp_domain.exam_id == "NTA_JEE_MAIN_2027"

    # Test lookup by ID
    bp_id = registry.get_blueprint("NTA_JEE_MAIN_2027")
    assert bp_id is not None
    assert len(bp_id.phases) == 2
    assert bp_id.password_policy.min_length == 8
    assert bp_id.password_policy.max_length == 13


def test_preflight_validator_class_12_passing_year_invariant():
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint("NTA_JEE_MAIN_2027")

    # Ineligible case: Passing year <= 2024
    ineligible_vault = {
        "full_name": "Aman Sharma",
        "intermediate_year": "2023",
        "category": "GEN",
    }
    res_ineligible = PreFlightValidator.validate(ineligible_vault, bp)
    assert res_ineligible.eligibility_verdict == "INELIGIBLE"
    assert any("Clause 3.3" in i.clause_reference for i in res_ineligible.issues)
    assert not res_ineligible.ready

    # Eligible case: Passing year 2025
    eligible_vault = {
        "full_name": "Aman Sharma",
        "intermediate_year": "2025",
        "category": "GEN",
    }
    res_eligible = PreFlightValidator.validate(eligible_vault, bp)
    assert res_eligible.eligibility_verdict == "ELIGIBLE"


def test_preflight_validator_category_warning():
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint("NTA_JEE_MAIN_2027")

    vault = {
        "full_name": "Aman Sharma",
        "category": "OBC-NCL",
        "intermediate_year": "2025",
    }
    res = PreFlightValidator.validate(vault, bp)
    assert any("Category is 'OBC-NCL'" in w for w in res.warnings)


def test_document_processor_photo_and_signature_constraints():
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint("NTA_JEE_MAIN_2027")
    photo_spec = bp.documents["photo"]
    sig_spec = bp.documents["signature"]

    with tempfile.TemporaryDirectory() as td:
        # Create test photo
        photo_path = Path(td) / "photo.png"
        Image.new("RGBA", (1000, 1400), color=(255, 255, 255, 255)).save(photo_path)
        
        photo_res = DocumentProcessor.optimize_for_spec(photo_path, photo_spec)
        assert photo_res.success
        assert photo_spec.min_size_kb <= photo_res.optimized_size_kb <= photo_spec.max_size_kb
        assert photo_res.target_format == "jpg"

        # Create tiny signature (needs padding to reach 10 KB)
        sig_path = Path(td) / "sig.jpg"
        Image.new("RGB", (200, 100), color=(255, 255, 255)).save(sig_path)

        sig_res = DocumentProcessor.optimize_for_spec(sig_path, sig_spec)
        assert sig_res.success
        assert sig_spec.min_size_kb <= sig_res.optimized_size_kb <= sig_spec.max_size_kb
        assert sig_res.target_format == "jpg"


def test_document_processor_pdf_conversion_constraints():
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint("NTA_JEE_MAIN_2027")
    matric_spec = bp.documents["matric_certificate"]

    with tempfile.TemporaryDirectory() as td:
        cert_img_path = Path(td) / "marksheet.jpg"
        Image.new("RGB", (800, 1200), color=(245, 245, 245)).save(cert_img_path)

        res = DocumentProcessor.optimize_for_spec(cert_img_path, matric_spec)
        assert res.success
        assert matric_spec.min_size_kb <= res.optimized_size_kb <= matric_spec.max_size_kb
        assert res.target_format == "pdf"


def test_dom_scanner_grounded_field_matching():
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint("NTA_JEE_MAIN_2027")

    # Set active blueprint in DOMScanner
    DOMScanner.set_active_blueprint(bp)

    # Test exact element ID match for Father Name
    field_father = {
        "id": "father_name",
        "name": "father_name",
        "label": "पिता / अभिभावक का नाम (Father / Guardian Name)",
    }
    concept, is_verify = DOMScanner.classify_field(field_father)
    assert concept == "father_name"

    # Test Mother Name disambiguation
    field_mother = {
        "id": "mother_name",
        "name": "mother_name",
        "label": "माता / अभिभावक का नाम (Mother / Guardian Name)",
    }
    concept_m, _ = DOMScanner.classify_field(field_mother)
    assert concept_m == "mother_name"

    # Reset active blueprint
    DOMScanner.set_active_blueprint(None)
