"""Pre-Flight Vault Readiness and Eligibility Validator.

Evaluates a candidate's profile and documents against an official ExamBlueprint
BEFORE launching the browser session, preventing late-stage failures and timeouts.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..knowledge.schemas.exam_blueprint_schema import DocumentFormat, ExamBlueprint, FieldSpec


@dataclass
class PreFlightIssue:
    field_id: str
    label_en: str
    label_hi: str = ""
    issue_type: str = "missing"  # "missing" | "invalid_format" | "out_of_bounds" | "ineligible"
    message: str = ""
    clause_reference: str = ""
    suggested_fix: str = ""


@dataclass
class PreFlightResult:
    ready: bool
    readiness_score: int  # 0 to 100
    exam_id: str
    exam_title: str
    authority_name: str
    eligibility_verdict: str  # "ELIGIBLE" | "INELIGIBLE" | "CONDITIONAL"
    eligibility_reason: str = ""
    issues: List[PreFlightIssue] = field(default_factory=list)
    document_issues: List[PreFlightIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    actionable_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data


class PreFlightValidator:
    """Pre-flight inspection engine grounding candidate data against official exam rules."""

    @classmethod
    def validate(
        cls,
        vault: Any,
        blueprint: ExamBlueprint,
        uploads_dir: Optional[Path] = None,
    ) -> PreFlightResult:
        """Validate candidate vault and documents against the official blueprint."""
        issues: List[PreFlightIssue] = []
        doc_issues: List[PreFlightIssue] = []
        warnings: List[str] = []
        eligibility_verdict = "ELIGIBLE"
        eligibility_reason = ""

        # Extract vault facts helper
        def get_fact(key: str) -> str:
            if hasattr(vault, "find_field_value"):
                return str(vault.find_field_value(key) or "").strip()
            if isinstance(vault, dict):
                return str(vault.get(key) or "").strip()
            return str(getattr(vault, key, "") or "").strip()

        # 1. Eligibility Check (Class 12 Passing Year Invariant from Clause 3.3)
        passing_year_str = get_fact("intermediate_year") or get_fact("passing_year_12") or ""
        if not passing_year_str and hasattr(vault, "intermediate"):
            inter = getattr(vault, "intermediate") or {}
            if isinstance(inter, dict):
                passing_year_str = str(inter.get("passing_year") or inter.get("year_of_passing") or "")
            else:
                passing_year_str = str(getattr(inter, "passing_year", "") or getattr(inter, "year_of_passing", "") or "")

        if passing_year_str.isdigit():
            year = int(passing_year_str)
            if blueprint.cycle_year == 2027 and year <= 2024:
                eligibility_verdict = "INELIGIBLE"
                eligibility_reason = (
                    f"Clause 3.3 (Page 22) states: Candidates who passed Class 12 in 2024 or earlier "
                    f"are NOT eligible to appear in JEE (Main) - 2027."
                )
                issues.append(
                    PreFlightIssue(
                        field_id="intermediate_year",
                        label_en="Class 12 Passing Year",
                        issue_type="ineligible",
                        message=eligibility_reason,
                        clause_reference="Clause 3.3, Page 22",
                        suggested_fix="Candidate is not eligible under official NTA 2027 criteria.",
                    )
                )

        # 2. Mandatory Blueprint Fields Check
        total_mandatory_fields = 0
        satisfied_mandatory_fields = 0

        for field_id, spec in blueprint.all_fields_by_id.items():
            if not spec.required:
                continue
            # Skip password / confirmation fields as they are handled in registration
            if spec.canonical_concept in {"account_password", "verify_password"}:
                continue

            total_mandatory_fields += 1
            vault_key = spec.vault_key or spec.canonical_concept
            val = get_fact(vault_key) or get_fact(spec.canonical_concept)

            if not val:
                issues.append(
                    PreFlightIssue(
                        field_id=field_id,
                        label_en=spec.label_en,
                        label_hi=spec.label_hi,
                        issue_type="missing",
                        message=f"Mandatory detail '{spec.label_en}' is missing in identity profile.",
                        suggested_fix=f"Add {spec.label_en} in Vault before starting application.",
                    )
                )
            else:
                satisfied_mandatory_fields += 1

                # Length validations
                if spec.exact_length and len(val) != spec.exact_length:
                    issues.append(
                        PreFlightIssue(
                            field_id=field_id,
                            label_en=spec.label_en,
                            label_hi=spec.label_hi,
                            issue_type="invalid_format",
                            message=f"'{spec.label_en}' must be exactly {spec.exact_length} digits (currently {len(val)}).",
                            suggested_fix=f"Correct {spec.label_en} to be {spec.exact_length} digits.",
                        )
                    )

        # 3. Category-Specific Conditional Validations
        category = get_fact("category").upper()
        if any(cat in category for cat in ["OBC", "SC", "ST"]):
            cert_no = get_fact("caste_certificate_number")
            cert_date = get_fact("caste_cert_issue_date")
            cert_auth = get_fact("caste_cert_authority")
            if not cert_no or not cert_date:
                warnings.append(
                    f"Category is '{category}', which requires valid Category Certificate ID, Issue Date, "
                    f"and Issuing Authority (Screen 8 / Page 76). Please ensure these are saved."
                )

        # 4. Document Upload Constraints Check
        for doc_key, doc_spec in blueprint.documents.items():
            if not doc_spec.mandatory:
                continue

            # Locate document path in vault
            doc_path_val = ""
            if hasattr(vault, "photo_path") and doc_key == "photo":
                doc_path_val = vault.photo_path
            elif hasattr(vault, "signature_path") and doc_key == "signature":
                doc_path_val = vault.signature_path
            elif hasattr(vault, "matric_cert_path") and "matric" in doc_key:
                doc_path_val = vault.matric_cert_path

            if not doc_path_val:
                doc_issues.append(
                    PreFlightIssue(
                        field_id=doc_key,
                        label_en=doc_spec.title_en,
                        label_hi=doc_spec.title_hi,
                        issue_type="missing",
                        message=f"Mandatory document '{doc_spec.title_en}' is not attached in Vault.",
                        clause_reference=doc_spec.clause_reference,
                        suggested_fix=f"Upload {doc_spec.title_en} ({doc_spec.min_size_kb}-{doc_spec.max_size_kb} KB).",
                    )
                )
                continue

            # Check physical file if it exists locally
            doc_file = Path(doc_path_val)
            if doc_file.exists() and doc_file.is_file():
                size_kb = doc_file.stat().st_size / 1024.0
                if size_kb < doc_spec.min_size_kb or size_kb > doc_spec.max_size_kb:
                    doc_issues.append(
                        PreFlightIssue(
                            field_id=doc_key,
                            label_en=doc_spec.title_en,
                            label_hi=doc_spec.title_hi,
                            issue_type="out_of_bounds",
                            message=(
                                f"Document '{doc_spec.title_en}' is {size_kb:.1f} KB, but {blueprint.exam_title} "
                                f"strictly mandates {doc_spec.min_size_kb} KB to {doc_spec.max_size_kb} KB."
                            ),
                            clause_reference=doc_spec.clause_reference,
                            suggested_fix="Use FormPilot Smart Document Optimizer to auto-compress.",
                        )
                    )

        # Compute Readiness Score
        total_items = max(1, total_mandatory_fields + len(blueprint.documents))
        total_satisfied = satisfied_mandatory_fields + (len(blueprint.documents) - len(doc_issues))
        readiness_score = max(0, min(100, int((total_satisfied / total_items) * 100)))

        is_ready = len(issues) == 0 and len(doc_issues) == 0 and eligibility_verdict == "ELIGIBLE"

        # Construct Actionable Summary
        if is_ready:
            actionable_summary = f"100% Ready for {blueprint.exam_title}. All mandatory fields and document constraints satisfied."
        elif eligibility_verdict == "INELIGIBLE":
            actionable_summary = f"Candidate is ineligible for {blueprint.exam_title}: {eligibility_reason}"
        else:
            missing_count = len([i for i in issues if i.issue_type == "missing"])
            doc_count = len(doc_issues)
            actionable_summary = f"{readiness_score}% Profile Readiness: {missing_count} fields and {doc_count} documents need attention before launch."

        return PreFlightResult(
            ready=is_ready,
            readiness_score=readiness_score,
            exam_id=blueprint.exam_id,
            exam_title=blueprint.exam_title,
            authority_name=blueprint.authority_name,
            eligibility_verdict=eligibility_verdict,
            eligibility_reason=eligibility_reason,
            issues=issues,
            document_issues=doc_issues,
            warnings=warnings,
            actionable_summary=actionable_summary,
        )
