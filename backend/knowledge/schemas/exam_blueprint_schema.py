"""Structured Pydantic Schema for Official Examination Blueprints.

Represents ground truth extracted and verified line-by-line from official
examination documentation (e.g. NTA Information Bulletins).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class InputKind(str, Enum):
    TEXT = "text"
    PASSWORD = "password"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    DATE = "date"
    FILE = "file"
    LIVE_PHOTO = "live_photo"
    OTP = "otp"
    CAPTCHA = "captcha"


class DocumentFormat(str, Enum):
    JPG = "jpg"
    JPEG = "jpeg"
    PDF = "pdf"


class DocumentSpec(BaseModel):
    document_key: str
    title_en: str
    title_hi: str = ""
    formats: List[DocumentFormat]
    min_size_kb: int
    max_size_kb: int
    aspect_ratio: Optional[str] = None
    face_coverage_percent: Optional[int] = None
    background_color: Optional[str] = None
    mandatory: bool = True
    page_reference: int = 0
    clause_reference: str = ""


class FieldOption(BaseModel):
    value: str
    label_en: str
    label_hi: str = ""


class ConditionalRule(BaseModel):
    trigger_field: str
    trigger_values: List[str]
    action: str = "show"  # "show" | "hide" | "require"
    target_fields: List[str]
    description: str = ""


class FieldSpec(BaseModel):
    field_id: str
    canonical_concept: str
    label_en: str
    label_hi: str = ""
    input_kind: InputKind = InputKind.TEXT
    required: bool = True
    vault_key: Optional[str] = None
    placeholder: str = ""
    options: List[FieldOption] = Field(default_factory=list)
    validation_regex: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    exact_length: Optional[int] = None
    auto_reused_from: Optional[str] = None  # e.g. verify_father_name reused from father_name
    page_reference: int = 0
    screenshot_evidence_id: Optional[str] = None


class SectionSpec(BaseModel):
    section_index: int
    section_id: str
    title_en: str
    title_hi: str = ""
    page_number_in_bulletin: int
    screenshot_ids: List[str] = Field(default_factory=list)
    fields: List[FieldSpec] = Field(default_factory=list)
    conditional_rules: List[ConditionalRule] = Field(default_factory=list)
    submit_button_text_en: str = "Save & Next"
    submit_button_text_hi: str = "सुरक्षित करें और आगे बढ़ें"
    is_human_gate: bool = False
    human_gate_type: Optional[str] = None


class WorkflowPhase(BaseModel):
    phase_order: int
    phase_id: str
    title_en: str
    title_hi: str = ""
    sections: List[SectionSpec] = Field(default_factory=list)


class PasswordPolicy(BaseModel):
    min_length: int = 8
    max_length: int = 13
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special_char: bool = True
    allowed_special_chars: str = "!@#$%^&*-"
    clause_reference: str = "Clause 8 / Page 10"


class ExamBlueprint(BaseModel):
    exam_id: str  # e.g. "NTA_JEE_MAIN_2027"
    authority_name: str  # e.g. "National Testing Agency (NTA)"
    exam_title: str  # e.g. "Joint Entrance Examination (Main) – 2027"
    cycle_year: int = 2027
    version: str = "1.0.0"
    source_pdf_filename: str = "JEE-info_bulletein.pdf"
    total_pages_in_pdf: int = 93
    verification_date: str = "2026-11-17"
    verified_by: str = "FormPilot Lead Systems Engineering"
    
    password_policy: PasswordPolicy = Field(default_factory=PasswordPolicy)
    documents: Dict[str, DocumentSpec] = Field(default_factory=dict)
    phases: List[WorkflowPhase] = Field(default_factory=list)
    
    # Fast lookup indexes
    all_fields_by_id: Dict[str, FieldSpec] = Field(default_factory=dict)
    all_fields_by_concept: Dict[str, List[str]] = Field(default_factory=dict)
    
    def compile_indexes(self) -> None:
        """Build instant microsecond lookups across all sections."""
        self.all_fields_by_id.clear()
        self.all_fields_by_concept.clear()
        for phase in self.phases:
            for section in phase.sections:
                for field in section.fields:
                    self.all_fields_by_id[field.field_id] = field
                    self.all_fields_by_concept.setdefault(field.canonical_concept, []).append(field.field_id)
