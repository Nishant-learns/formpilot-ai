"""Single source of truth for portal fields.

The DOM scanner emits semantic keys.  The vault resolves those keys to values.
Before this module existed the two sides drifted (e.g. `matric_board` vs
`10th_board`), which produced false "missing field" prompts.  Every key emitted
by `DOMScanner.classify_field` must be present here, and a contract test
enforces that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class FieldSpec:
    key: str
    path: str
    label: str
    kind: str = "text"
    sensitive: bool = False


def _spec(key: str, path: str, label: str, kind: str = "text", sensitive: bool = False) -> FieldSpec:
    return FieldSpec(key=key, path=path, label=label, kind=kind, sensitive=sensitive)


FIELD_SPECS: dict[str, FieldSpec] = {
    # Identity
    "full_name": _spec("full_name", "full_name", "Candidate Full Name"),
    "verify_full_name": _spec("verify_full_name", "verify_full_name", "Verify Candidate Full Name"),
    "first_name": _spec("first_name", "first_name", "Candidate First Name"),
    "middle_name": _spec("middle_name", "middle_name", "Candidate Middle Name"),
    "last_name": _spec("last_name", "last_name", "Candidate Last Name"),
    "verify_first_name": _spec("verify_first_name", "verify_first_name", "Verify First Name"),
    "verify_middle_name": _spec("verify_middle_name", "verify_middle_name", "Verify Middle Name"),
    "verify_last_name": _spec("verify_last_name", "verify_last_name", "Verify Last Name"),
    "father_name": _spec("father_name", "father_name", "Father's Name"),
    "verify_father_name": _spec("verify_father_name", "verify_father_name", "Verify Father's Name"),
    "mother_name": _spec("mother_name", "mother_name", "Mother's Name"),
    "verify_mother_name": _spec("verify_mother_name", "verify_mother_name", "Verify Mother's Name"),
    "dob": _spec("dob", "dob", "Date of Birth", "date"),
    "dob_day": _spec("dob_day", "dob_day", "Date of Birth - Day", "select"),
    "dob_month": _spec("dob_month", "dob_month", "Date of Birth - Month", "select"),
    "dob_year": _spec("dob_year", "dob_year", "Date of Birth - Year", "select"),
    "verify_dob_day": _spec("verify_dob_day", "verify_dob_day", "Verify DOB - Day", "select"),
    "verify_dob_month": _spec("verify_dob_month", "verify_dob_month", "Verify DOB - Month", "select"),
    "verify_dob_year": _spec("verify_dob_year", "verify_dob_year", "Verify DOB - Year", "select"),
    "gender": _spec("gender", "gender", "Gender", "select"),
    "marital_status": _spec("marital_status", "marital_status", "Marital Status", "select"),
    "religion": _spec("religion", "religion", "Religion", "select"),
    "nationality": _spec("nationality", "nationality", "Nationality"),
    "category": _spec("category", "category", "Social Category", "select"),
    "sub_caste": _spec("sub_caste", "sub_caste", "Sub Caste"),
    "caste_certificate_number": _spec("caste_certificate_number", "caste_certificate_number", "Caste Certificate Number"),
    "caste_cert_issue_date": _spec("caste_cert_issue_date", "caste_cert_issue_date", "Caste Certificate Issue Date", "date"),
    "caste_cert_authority": _spec("caste_cert_authority", "caste_cert_authority", "Caste Certificate Authority"),
    "domicile_state": _spec("domicile_state", "domicile_state", "Domicile State", "select"),
    "domicile_certificate_number": _spec("domicile_certificate_number", "domicile_certificate_number", "Domicile Certificate Number"),
    "is_differently_abled": _spec("is_differently_abled", "is_differently_abled", "Differently Abled", "select"),
    "disability_type": _spec("disability_type", "disability_type", "Disability Type"),
    "disability_percentage": _spec("disability_percentage", "disability_percentage", "Disability Percentage"),
    "is_ex_serviceman": _spec("is_ex_serviceman", "is_ex_serviceman", "Ex-Serviceman", "select"),

    # Identifiers
    "registration_id": _spec("registration_id", "registration_id", "Registration / OTR ID"),
    "account_password": _spec("account_password", "account_password", "Account Password", "password", sensitive=True),
    "aadhaar_number": _spec("aadhaar_number", "aadhaar_number", "Aadhaar Number", sensitive=True),
    "aadhaar_part1": _spec("aadhaar_part1", "aadhaar_part1", "Aadhaar First 4 Digits", sensitive=True),
    "aadhaar_part2": _spec("aadhaar_part2", "aadhaar_part2", "Aadhaar Middle 4 Digits", sensitive=True),
    "aadhaar_part3": _spec("aadhaar_part3", "aadhaar_part3", "Aadhaar Last 4 Digits", sensitive=True),
    "has_aadhaar": _spec("has_aadhaar", "has_aadhaar", "Has Aadhaar", "select"),
    "identification_mark_1": _spec("identification_mark_1", "identification_mark_1", "Identification Mark 1"),
    "identification_mark_2": _spec("identification_mark_2", "identification_mark_2", "Identification Mark 2"),

    # Contact
    "mobile": _spec("mobile", "mobile", "Mobile Number", "tel", sensitive=True),
    "alternate_mobile": _spec("alternate_mobile", "alternate_mobile", "Alternate Mobile", "tel", sensitive=True),
    "email": _spec("email", "email", "Email Address", "email"),
    "alternate_email": _spec("alternate_email", "alternate_email", "Alternate Email Address", "email"),
    "confirm_email": _spec("confirm_email", "confirm_email", "Confirm Email Address", "email"),
    "guardian_name": _spec("guardian_name", "guardian_name", "Guardian's Name"),
    "spouse_name": _spec("spouse_name", "spouse_name", "Spouse / Husband Name"),

    # Address
    "address_line_1": _spec("address_line_1", "address_line_1", "Address Line 1"),
    "address_line_2": _spec("address_line_2", "address_line_2", "Address Line 2"),
    "village_town_city": _spec("village_town_city", "village_town_city", "Village / Town / City"),
    "district": _spec("district", "district", "District"),
    "state": _spec("state", "state", "State"),
    "pincode": _spec("pincode", "pincode", "PIN Code", "tel"),
    "same_as_permanent": _spec("same_as_permanent", "same_as_permanent", "Same As Permanent", "checkbox"),
    "present_address_line_1": _spec("present_address_line_1", "present_address_line_1", "Present Address"),
    "present_address_line_2": _spec("present_address_line_2", "present_address_line_2", "Present Address Line 2"),
    "present_district": _spec("present_district", "present_district", "Present District"),
    "present_state": _spec("present_state", "present_state", "Present State"),
    "present_pincode": _spec("present_pincode", "present_pincode", "Present PIN Code"),

    # Matric / 10th
    "matric_board": _spec("matric_board", "matric.board", "10th / Matric Board", "select"),
    "matric_roll_number": _spec("matric_roll_number", "matric.roll_number", "10th / Matric Roll Number"),
    "matric_roll_code": _spec("matric_roll_code", "matric.roll_code", "10th / Matric Roll Code"),
    "matric_passing_year": _spec("matric_passing_year", "matric.passing_year", "Matric Passing Year"),
    "matric_total_marks": _spec("matric_total_marks", "matric.total_marks", "Matric Total Marks"),
    "matric_obtained_marks": _spec("matric_obtained_marks", "matric.obtained_marks", "Matric Obtained Marks"),
    "matric_percentage": _spec("matric_percentage", "matric.percentage", "Matric Percentage"),
    "matric_cgpa": _spec("matric_cgpa", "matric.cgpa", "Matric CGPA"),
    "matric_school_name": _spec("matric_school_name", "matric.school_name", "Matric School Name"),
    "matric_certificate_number": _spec("matric_certificate_number", "matric.certificate_number", "Matric Certificate Number"),

    # Intermediate / 12th
    "intermediate_board": _spec("intermediate_board", "intermediate.board", "12th / Intermediate Board", "select"),
    "intermediate_stream": _spec("intermediate_stream", "intermediate.stream", "Intermediate Stream"),
    "intermediate_roll_number": _spec("intermediate_roll_number", "intermediate.roll_number", "Intermediate Roll Number"),
    "intermediate_roll_code": _spec("intermediate_roll_code", "intermediate.roll_code", "Intermediate Roll Code"),
    "intermediate_passing_year": _spec("intermediate_passing_year", "intermediate.passing_year", "Intermediate Passing Year"),
    "intermediate_total_marks": _spec("intermediate_total_marks", "intermediate.total_marks", "Intermediate Total Marks"),
    "intermediate_obtained_marks": _spec("intermediate_obtained_marks", "intermediate.obtained_marks", "Intermediate Obtained Marks"),
    "intermediate_percentage": _spec("intermediate_percentage", "intermediate.percentage", "Intermediate Percentage"),
    "intermediate_college_name": _spec("intermediate_college_name", "intermediate.college_name", "Intermediate College Name"),
    "intermediate_certificate_number": _spec("intermediate_certificate_number", "intermediate.certificate_number", "Intermediate Certificate Number"),

    # Graduation
    "graduation_degree_name": _spec("graduation_degree_name", "graduation.degree_name", "Graduation Degree"),
    "graduation_university": _spec("graduation_university", "graduation.university", "Graduation University"),
    "graduation_passing_year": _spec("graduation_passing_year", "graduation.passing_year", "Graduation Passing Year"),
    "graduation_roll_number": _spec("graduation_roll_number", "graduation.roll_number", "Graduation Roll Number"),
    "graduation_cgpa": _spec("graduation_cgpa", "graduation.cgpa", "Graduation CGPA"),
    "graduation_percentage": _spec("graduation_percentage", "graduation.percentage", "Graduation Percentage"),

    # Uploads
    "photo_upload": _spec("photo_upload", "photo_path", "Passport Photograph", "file"),
    "signature_upload": _spec("signature_upload", "signature_path", "Digital Signature", "file"),
    "matric_cert_upload": _spec("matric_cert_upload", "matric_cert_path", "Matric Certificate", "file"),

    # Extensible / custom fields
    "apaar_id": _spec("apaar_id", "custom_fields.apaar_id", "APAAR ID"),
    "digilocker_id": _spec("digilocker_id", "custom_fields.digilocker_id", "DigiLocker ID"),
    "height_cm": _spec("height_cm", "custom_fields.height_cm", "Height (cm)"),
    "chest_cm": _spec("chest_cm", "custom_fields.chest_cm", "Chest (cm)"),
    "mother_tongue": _spec("mother_tongue", "custom_fields.mother_tongue", "Mother Tongue"),
    "employment_status": _spec("employment_status", "custom_fields.employment_status", "Employment Status"),
    "criminal_case_pending": _spec("criminal_case_pending", "custom_fields.criminal_case_pending", "Criminal Case Pending", "select"),
    "debarred_from_exam": _spec("debarred_from_exam", "custom_fields.debarred_from_exam", "Debarred From Exam", "select"),
}

# Portal labels are messy.  These aliases keep the resolver tolerant without
# scattering portal-specific strings across the orchestrator.
ALIASES: dict[str, str] = {
    "name": "full_name",
    "candidate_name": "full_name",
    "applicant_name": "full_name",
    "student_name": "full_name",
    "father": "father_name",
    "mother": "mother_name",
    "phone": "mobile",
    "mobile_no": "mobile",
    "mobile_number": "mobile",
    "contact_no": "mobile",
    "mail": "email",
    "email_id": "email",
    "email_address": "email",
    "caste": "category",
    "community": "category",
    "social_category": "category",
    "social_status": "category",
    "id_mark": "identification_mark_1",
    "identification_mark": "identification_mark_1",
    "pin": "pincode",
    "pin_code": "pincode",
    "postal_code": "pincode",
    "zip": "pincode",
    "city": "village_town_city",
    "town": "village_town_city",
    "village": "village_town_city",
    "address": "address_line_1",
    "permanent_address": "address_line_1",
    "same_as_present": "same_as_permanent",
    "same_as_present_address": "same_as_permanent",
    "same_as_correspondence": "same_as_permanent",
    "permanent_same_as_present": "same_as_permanent",
    "present_same_as_permanent": "same_as_permanent",
    "aadhaar": "aadhaar_number",
    "aadhar": "aadhaar_number",
    "uidai": "aadhaar_number",
    "10th_board": "matric_board",
    "10th_roll": "matric_roll_number",
    "matric_roll": "matric_roll_number",
    "birth_day": "dob_day",
    "day": "dob_day",
    "dob_date": "dob_day",
    "birth_month": "dob_month",
    "month": "dob_month",
    "birth_year": "dob_year",
    "year": "dob_year",
    "verify_day": "verify_dob_day",
    "verify_month": "verify_dob_month",
    "verify_year": "verify_dob_year",
    "10th_year": "matric_passing_year",
    "10th_marks": "matric_obtained_marks",
    "10th_percentage": "matric_percentage",
    "12th_board": "intermediate_board",
    "12th_roll": "intermediate_roll_number",
    "inter_roll": "intermediate_roll_number",
    "12th_year": "intermediate_passing_year",
    "12th_percentage": "intermediate_percentage",
    "grad_roll": "graduation_roll_number",
    "grad_university": "graduation_university",
    "grad_percentage": "graduation_percentage",
    "password": "account_password",
    "login_password": "account_password",
    "login_reg_id": "registration_id",
    "firstname": "first_name",
    "f_name": "first_name",
    "fname": "first_name",
    "first": "first_name",
    "given_name": "first_name",
    "middlename": "middle_name",
    "m_name": "middle_name",
    "mname": "middle_name",
    "lastname": "last_name",
    "surname": "last_name",
    "l_name": "last_name",
    "lname": "last_name",
    "family_name": "last_name",
    "verify_firstname": "verify_first_name",
    "verify_lastname": "verify_last_name",
    "verify_surname": "verify_last_name",
    "aadhaar_1": "aadhaar_part1",
    "aadhaar_2": "aadhaar_part2",
    "aadhaar_3": "aadhaar_part3",
    "aadhar_1": "aadhaar_part1",
    "aadhar_2": "aadhaar_part2",
    "aadhar_3": "aadhaar_part3",
}


def normalize_key(key: str) -> str:
    return (key or "").strip().lower().replace("-", "_").replace(" ", "_")


def canonical_key(key: str) -> str:
    key = normalize_key(key)
    return ALIASES.get(key, key)


def spec_for(key: str) -> Optional[FieldSpec]:
    return FIELD_SPECS.get(canonical_key(key))


def resolve_value(vault: Any, key: str) -> Optional[str]:
    """Resolve a semantic key against a CandidateVault instance.

    Supports direct attributes, dotted paths (`matric.roll_number`), custom
    fields, aliases, and derived fields (split names, split DOB, split Aadhaar).
    Returns None for genuinely missing values so the orchestrator can open a
    Missing Field gate.
    """
    canonical = canonical_key(key)
    spec = FIELD_SPECS.get(canonical)

    candidates: list[str] = []
    if spec:
        candidates.append(spec.path)
    candidates.append(canonical)
    candidates.append(f"custom_fields.{canonical}")

    for path in candidates:
        value = _resolve_dotted(vault, path)
        if value is not None and value != "":
            if isinstance(value, bool):
                return "Yes" if value else "No"
            val_str = str(value).strip()
            # Clean mobile numbers if required (10 digits for Indian portals)
            if canonical in {"mobile", "alternate_mobile"}:
                digits = re.sub(r"[^\d]", "", val_str)
                if len(digits) == 12 and digits.startswith("91"):
                    return digits[2:]
                elif len(digits) == 11 and digits.startswith("0"):
                    return digits[1:]
                elif len(digits) == 10:
                    return digits
            # Clean Aadhaar numbers (12 digits, strip spaces/hyphens)
            if canonical == "aadhaar_number":
                digits = re.sub(r"[^\d]", "", val_str)
                if len(digits) == 12:
                    return digits
            return val_str

    # Derived fallbacks when direct path is not in vault
    # 1. Split Names
    if canonical in {
        "first_name", "verify_first_name",
        "middle_name", "verify_middle_name",
        "last_name", "verify_last_name", "surname"
    }:
        raw_name = (
            getattr(vault, "verify_full_name", None)
            if "verify" in canonical
            else getattr(vault, "full_name", None)
        ) or getattr(vault, "full_name", "") or ""
        tokens = str(raw_name).strip().split()
        if tokens:
            if "first" in canonical:
                return tokens[0]
            elif "middle" in canonical:
                return " ".join(tokens[1:-1]) if len(tokens) > 2 else ""
            elif "last" in canonical or "surname" in canonical:
                return tokens[-1] if len(tokens) > 1 else tokens[0]

    # 2. Split Date of Birth (Day, Month, Year)
    if canonical in {
        "dob_day", "verify_dob_day",
        "dob_month", "verify_dob_month",
        "dob_year", "verify_dob_year",
    }:
        dob_val = str(getattr(vault, "dob", "") or "").strip()
        if dob_val:
            m_iso = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$", dob_val)
            if m_iso:
                y, mo, d = m_iso.group(1), m_iso.group(2).zfill(2), m_iso.group(3).zfill(2)
            else:
                m_in = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", dob_val)
                if m_in:
                    d, mo, y = m_in.group(1).zfill(2), m_in.group(2).zfill(2), m_in.group(3)
                else:
                    d, mo, y = None, None, None
            if d and mo and y:
                if "day" in canonical:
                    return d
                elif "month" in canonical:
                    return mo
                elif "year" in canonical:
                    return y

    # 3. Split Aadhaar (4-4-4 chunks)
    if canonical in {"aadhaar_part1", "aadhaar_part2", "aadhaar_part3"}:
        raw_aadhaar = str(getattr(vault, "aadhaar_number", "") or "")
        digits = re.sub(r"[^\d]", "", raw_aadhaar)
        if len(digits) == 12:
            if canonical == "aadhaar_part1":
                return digits[:4]
            elif canonical == "aadhaar_part2":
                return digits[4:8]
            elif canonical == "aadhaar_part3":
                return digits[8:12]

    return None


def _resolve_dotted(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def mask_value(key: str, value: Optional[str]) -> Optional[str]:
    """Mask sensitive values for logs, audit exports and public API views."""
    spec = spec_for(key)
    if value is None:
        return None
    if not spec or not spec.sensitive:
        return value
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * (len(text) - 4)}{text[-4:]}"


def known_keys() -> set[str]:
    return set(FIELD_SPECS)
