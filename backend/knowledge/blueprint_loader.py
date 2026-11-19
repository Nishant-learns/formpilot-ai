"""Exam Blueprint Loader and Registry.

Loads, indexes, and resolves certified examination blueprints (Pydantic models)
from `backend/knowledge/blueprints/` for deterministic runtime form execution.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .schemas.exam_blueprint_schema import ExamBlueprint, FieldSpec

logger = logging.getLogger("formpilot.blueprint_loader")

BLUEPRINTS_DIR = Path(__file__).resolve().parent / "blueprints"

# Canonical domain to Exam ID routing table
DOMAIN_EXAM_MAPPING: Dict[str, str] = {
    "examinationservices.nic.in": "NTA_JEE_MAIN_2027",
    "jeemain.nta.nic.in": "NTA_JEE_MAIN_2027",
    "jeemain.ntaonline.in": "NTA_JEE_MAIN_2027",
    "neet.ntaonline.in": "NTA_NEET_UG_2027",
    "upsconline.nic.in": "UPSC_OTR_2027",
    "ssc.gov.in": "SSC_OTR_2027",
}


class BlueprintRegistry:
    """Singleton registry holding compiled ExamBlueprints in memory."""

    _instance: Optional[BlueprintRegistry] = None

    def __init__(self, blueprints_dir: Optional[Path] = None):
        self.blueprints_dir = blueprints_dir or BLUEPRINTS_DIR
        self._blueprints: Dict[str, ExamBlueprint] = {}
        self.load_all()

    @classmethod
    def get_instance(cls) -> BlueprintRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_all(self) -> None:
        """Scan blueprints directory and load all verified JSON specifications."""
        self._blueprints.clear()
        if not self.blueprints_dir.exists():
            logger.warning("Blueprints directory does not exist: %s", self.blueprints_dir)
            return

        for json_file in self.blueprints_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                bp = ExamBlueprint.model_validate(data)
                bp.compile_indexes()
                self._blueprints[bp.exam_id] = bp
                logger.info("Loaded certified exam blueprint: %s (v%s, %d fields)", bp.exam_id, bp.version, len(bp.all_fields_by_id))
            except Exception as exc:
                logger.error("Failed to load blueprint from %s: %s", json_file.name, exc)

    def get_by_id(self, exam_id: str) -> Optional[ExamBlueprint]:
        """Look up an exam blueprint directly by its canonical ID."""
        return self._blueprints.get(exam_id)

    def get_blueprint(self, exam_id: str) -> Optional[ExamBlueprint]:
        """Alias for get_by_id."""
        return self.get_by_id(exam_id)

    def find_by_url_or_domain(self, url: str) -> Optional[ExamBlueprint]:
        """Determine the active ExamBlueprint from a portal URL or hostname."""
        if not url:
            return None
        domain = urlparse(url).netloc.lower() if "://" in url else url.lower().split("/")[0]
        # Clean port if present
        domain = domain.split(":")[0]

        exam_id = DOMAIN_EXAM_MAPPING.get(domain)
        if exam_id and exam_id in self._blueprints:
            return self._blueprints[exam_id]

        # Subdomain / partial match
        for mapped_domain, mapped_id in DOMAIN_EXAM_MAPPING.items():
            if mapped_domain in domain or domain in mapped_domain:
                if mapped_id in self._blueprints:
                    return self._blueprints[mapped_id]

        return None

    def list_available_exams(self) -> List[Dict[str, Any]]:
        """List all loaded examination blueprints for cockpit UI display."""
        return [
            {
                "exam_id": bp.exam_id,
                "exam_title": bp.exam_title,
                "authority_name": bp.authority_name,
                "cycle_year": bp.cycle_year,
                "version": bp.version,
                "field_count": len(bp.all_fields_by_id),
                "document_types": list(bp.documents.keys()),
                "source_bulletin": bp.source_pdf_filename,
            }
            for bp in self._blueprints.values()
        ]

    def resolve_field(
        self,
        blueprint: ExamBlueprint,
        concept: str,
        section_id: Optional[str] = None,
    ) -> Optional[FieldSpec]:
        """Resolve a canonical concept to its exact FieldSpec in the blueprint."""
        field_ids = blueprint.all_fields_by_concept.get(concept) or []
        if not field_ids:
            return None

        if section_id:
            # Filter by matching section
            for fid in field_ids:
                spec = blueprint.all_fields_by_id.get(fid)
                if spec:
                    return spec

        # Default to first matching field spec
        return blueprint.all_fields_by_id.get(field_ids[0])
