"""Encrypted-at-rest storage for the documents a candidate uploads.

Aadhaar scans, photographs, signatures and certificates are the most sensitive
artefacts FormPilot ever holds.  They are therefore handled differently from
ordinary uploads:

* every file is sealed with AES-256-GCM before it touches the disk;
* the index (names, types, hashes) is sealed with the same cipher, so the
  directory itself does not reveal what a candidate submitted;
* nothing is served from a static directory - downloads go through an API
  route that checks the document id;
* the key comes from ``FORMPILOT_VAULT_KEY`` when set, otherwise a random
  key is generated once at ``<data>/.formpilot.key`` with mode 0600.

Deleting a record removes the sealed file and rewrites the sealed index.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import settings
from .vault_crypto import VaultCipher, VaultCryptoError, decode_envelope, document_cipher

# What a candidate is allowed to attach.  Aadhaar and PAN scans are commonly
# PDFs; photographs and signatures are images.  Anything else is refused so a
# mislabelled executable or an HTML file can never enter the store.
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024

_MIME_RULES: Dict[str, Tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "application/pdf": (b"%PDF-",),
}

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

# Document kinds the cockpit offers.  The key is what the API stores; the
# label is what the candidate sees.
DOC_TYPES: Dict[str, str] = {
    "photo": "Passport photograph",
    "signature": "Signature",
    "aadhaar_front": "Aadhaar (front)",
    "aadhaar_back": "Aadhaar (back)",
    "pan_card": "PAN card",
    "matric_certificate": "10th / Matric certificate",
    "intermediate_certificate": "12th / Intermediate certificate",
    "graduation_certificate": "Graduation certificate",
    "caste_certificate": "Caste certificate",
    "domicile_certificate": "Domicile certificate",
    "other": "Other document",
}

# Document kinds that back a vault path, so the fill loop can attach them.
_VAULT_PATHS = {
    "photo": "photo_path",
    "signature": "signature_path",
    "matric_certificate": "matric_cert_path",
}


def _documents_root() -> Path:
    override = os.getenv("FORMPILOT_DOCUMENTS_DIR", "").strip()
    root = Path(override) if override else settings.DATA_DIR / "documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(filename: str) -> str:
    """Keep a display name only.  It is never used to build a path."""
    name = Path(str(filename or "document")).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" ._")
    return (name or "document")[:120]


def sniff_mime(data: bytes) -> Optional[str]:
    """Return the real media type from the file's magic bytes."""
    if not data:
        return None
    for mime, prefixes in _MIME_RULES.items():
        if mime == "image/webp":
            if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                return mime
            continue
        if data.startswith(prefixes[0]):
            return mime
    return None


class DocumentError(ValueError):
    """A rejected upload, with a message a candidate can act on."""


class DocumentStore:
    """Sealed document store with an atomic, sealed index."""

    _instance: Optional["DocumentStore"] = None
    _instance_root: Optional[str] = None

    def __init__(self, root: Optional[Path] = None, *, cipher: Optional[VaultCipher] = None):
        self.root = Path(root) if root else _documents_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self._cipher = cipher or document_cipher()

    # ------------------------------------------------------------- lifecycle

    @classmethod
    def get_instance(cls) -> "DocumentStore":
        root = str(_documents_root())
        if cls._instance is None or cls._instance_root != root:
            cls._instance = DocumentStore(Path(root))
            cls._instance_root = root
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None
        cls._instance_root = None

    # ---------------------------------------------------------------- index

    def _read_index(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            raw = self.index_path.read_text(encoding="utf-8")
            is_encrypted, payload = decode_envelope(raw)
            if is_encrypted:
                plaintext = self._cipher.decrypt_bytes(payload)  # type: ignore[arg-type]
                data = json.loads(plaintext)
            else:
                data = json.loads(raw)
            documents = data.get("documents") if isinstance(data, dict) else None
            return list(documents or [])
        except VaultCryptoError:
            raise
        except Exception:
            # A corrupt index must not silently look like "no documents": the
            # files are still on disk and a human should know.
            raise DocumentError(
                "The document index could not be read. Check FORMPILOT_VAULT_KEY."
            )

    def _write_index(self, documents: List[Dict[str, Any]]) -> None:
        body = json.dumps({"version": 1, "documents": documents}, indent=2).encode("utf-8")
        envelope = self._cipher.encrypt_bytes(body)
        output = json.dumps(envelope, indent=2).encode("utf-8")

        fd, tmp_name = tempfile.mkstemp(
            prefix=".index.", suffix=".tmp", dir=str(self.root)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(output)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.index_path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # --------------------------------------------------------------- writes

    def save(
        self,
        doc_type: str,
        filename: str,
        data: bytes,
        *,
        declared_mime: str = "",
    ) -> Dict[str, Any]:
        doc_type = str(doc_type or "").strip().lower()
        if doc_type not in DOC_TYPES:
            raise DocumentError(
                "Unknown document type. Choose one of: " + ", ".join(sorted(DOC_TYPES))
            )
        if not data:
            raise DocumentError("The uploaded file is empty.")
        if len(data) > MAX_DOCUMENT_BYTES:
            raise DocumentError("The file must be 8 MB or smaller.")

        mime = sniff_mime(data)
        if not mime:
            raise DocumentError(
                "That file is not a JPEG, PNG, WebP or PDF. Please upload a real scan or photo."
            )
        declared = str(declared_mime or "").split(";")[0].strip().lower()
        if declared and declared not in {mime, "application/octet-stream"}:
            # The extension can lie; the bytes cannot.
            if not (declared == "image/jpg" and mime == "image/jpeg"):
                raise DocumentError(
                    "The file's contents do not match its type. Please re-export it and try again."
                )

        doc_id = uuid.uuid4().hex
        sealed = self._cipher.encrypt_bytes(data)
        sealed_path = self.root / f"{doc_id}.enc"
        fd = os.open(sealed_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(sealed, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            sealed_path.unlink(missing_ok=True)
            raise

        record = {
            "id": doc_id,
            "doc_type": doc_type,
            "label": DOC_TYPES[doc_type],
            "filename": _safe_name(filename),
            "mime": mime,
            "extension": _EXTENSIONS.get(mime, ""),
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "encrypted": True,
            "algorithm": "AES-256-GCM",
        }
        documents = self._read_index()
        documents.append(record)
        self._write_index(documents)
        return record

    # ---------------------------------------------------------------- reads

    def list(self, doc_type: Optional[str] = None) -> List[Dict[str, Any]]:
        documents = self._read_index()
        if doc_type:
            documents = [item for item in documents if item.get("doc_type") == doc_type]
        return sorted(documents, key=lambda item: item.get("created_at") or "", reverse=True)

    def metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        for record in self._read_index():
            if record.get("id") == doc_id:
                return record
        return None

    def latest(self, doc_type: str) -> Optional[Dict[str, Any]]:
        matches = self.list(doc_type)
        return matches[0] if matches else None

    def read(self, doc_id: str) -> Tuple[Dict[str, Any], bytes]:
        record = self.metadata(doc_id)
        if not record:
            raise DocumentError("That document does not exist.")
        path = self.root / f"{doc_id}.enc"
        if not path.exists():
            raise DocumentError("That document's file is missing from the vault.")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            payload = self._cipher.decrypt_bytes(envelope)
        except VaultCryptoError:
            raise
        except Exception as exc:
            raise DocumentError("That document could not be decrypted.") from exc
        return record, payload

    # --------------------------------------------------------------- delete

    def delete(self, doc_id: str) -> bool:
        documents = self._read_index()
        remaining = [item for item in documents if item.get("id") != doc_id]
        if len(remaining) == len(documents):
            return False
        (self.root / f"{doc_id}.enc").unlink(missing_ok=True)
        self._write_index(remaining)
        return True

    # ---------------------------------------------------------------- helper

    def vault_path_for(self, record: Dict[str, Any]) -> Optional[str]:
        """The vault pointer for a record, when it backs a form field."""
        attribute = _VAULT_PATHS.get(str(record.get("doc_type") or ""))
        return f"document:{record['id']}" if attribute else None

    @staticmethod
    def parse_reference(value: str) -> Optional[str]:
        """Return the document id from a ``document:<id>`` vault pointer."""
        text = str(value or "")
        if not text.startswith("document:"):
            return None
        doc_id = text.split(":", 1)[1].strip()
        return doc_id or None

    def public(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Metadata safe to send to the cockpit (never the bytes)."""
        return {
            key: record.get(key)
            for key in (
                "id",
                "doc_type",
                "label",
                "filename",
                "mime",
                "size",
                "sha256",
                "created_at",
                "encrypted",
                "algorithm",
            )
        }
