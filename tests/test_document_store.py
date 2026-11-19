"""The sealed document vault: encryption at rest, validation, and API access."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from backend.core.document_store import (
    DOC_TYPES,
    DocumentError,
    DocumentStore,
    sniff_mime,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 240
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 240
PDF = b"%PDF-1.7\n" + b"\x00" * 240


@pytest.fixture()
def store(tmp_path):
    DocumentStore.reset_instance()
    instance = DocumentStore(tmp_path / "documents")
    yield instance
    DocumentStore.reset_instance()


def test_every_document_is_sealed_on_disk(store):
    record = store.save("aadhaar_front", "aadhaar.png", PNG, declared_mime="image/png")

    sealed = Path(store.root) / f"{record['id']}.enc"
    assert sealed.exists()
    raw = sealed.read_bytes()
    # The plaintext must not be recoverable from the file, and the record says
    # how it was sealed.
    assert b"\x89PNG" not in raw
    assert record["encrypted"] is True
    assert record["algorithm"] == "AES-256-GCM"

    metadata, payload = store.read(record["id"])
    assert payload == PNG
    assert metadata["sha256"] == record["sha256"]


def test_index_does_not_leak_filenames(store):
    store.save("photo", "my-passport-photo.png", PNG)
    raw = Path(store.index_path).read_text(encoding="utf-8")

    assert "my-passport-photo" not in raw
    assert "passport" not in raw.lower()
    assert json.loads(raw)["encrypted"] is True


def test_files_and_key_are_private(store):
    record = store.save("signature", "sign.png", PNG)
    sealed = Path(store.root) / f"{record['id']}.enc"

    assert stat.S_IMODE(sealed.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(store.index_path).stat().st_mode) == 0o600


def test_key_file_is_created_once_with_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("FORMPILOT_VAULT_KEY", raising=False)
    monkeypatch.setenv("FORMPILOT_KEY_FILE", str(tmp_path / "key.bin"))
    monkeypatch.setenv("FORMPILOT_DATA_DIR", str(tmp_path))

    from backend.core.vault_crypto import load_or_create_key

    first = load_or_create_key()
    second = load_or_create_key()

    assert first == second
    assert len(first) > 20
    key_file = tmp_path / "key.bin"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_rejects_non_documents(store):
    with pytest.raises(DocumentError):
        store.save("other", "resume.html", b"<html><script>alert(1)</script></html>")
    with pytest.raises(DocumentError):
        store.save("other", "setup.exe", b"MZ\x90\x00\x03")


def test_rejects_a_lying_extension(store):
    # A PNG named .pdf is a mislabel; the bytes win.
    with pytest.raises(DocumentError):
        store.save("other", "scan.pdf", PNG, declared_mime="application/pdf")


def test_rejects_oversized_files(store):
    with pytest.raises(DocumentError):
        store.save("other", "huge.png", PNG + b"\x00" * (8 * 1024 * 1024))


def test_rejects_unknown_type(store):
    with pytest.raises(DocumentError):
        store.save("not_a_doc_type", "x.png", PNG)


def test_sniff_mime_reads_magic_bytes():
    assert sniff_mime(JPEG) == "image/jpeg"
    assert sniff_mime(PNG) == "image/png"
    assert sniff_mime(PDF) == "application/pdf"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_mime(b"hello") is None


def test_filename_is_sanitised_and_never_used_as_a_path(store):
    record = store.save("other", "../../etc/passwd.png", PNG)

    assert record["filename"] == "passwd.png"
    assert not (store.root / "../../etc/passwd.png").exists()
    assert list(store.root.glob("*.png")) == []


def test_latest_and_delete(store):
    first = store.save("photo", "one.png", PNG)
    second = store.save("photo", "two.png", PNG)

    assert store.latest("photo")["id"] == second["id"]
    assert store.delete(first["id"]) is True
    assert [item["id"] for item in store.list("photo")] == [second["id"]]
    assert store.delete(first["id"]) is False
    assert not (Path(store.root) / f"{first['id']}.enc").exists()


def test_vault_pointer_round_trip(store):
    record = store.save("photo", "face.png", PNG)

    pointer = store.vault_path_for(record)
    assert pointer == f"document:{record['id']}"
    assert DocumentStore.parse_reference(pointer) == record["id"]
    assert DocumentStore.parse_reference("/tmp/plain.jpg") is None
    # Aadhaar has no vault column, so it is never attached to a form by accident.
    assert store.vault_path_for({"id": "abc", "doc_type": "aadhaar_front"}) is None


def test_document_types_cover_the_required_uploads():
    for required in ("photo", "signature", "aadhaar_front", "aadhaar_back"):
        assert required in DOC_TYPES


def test_api_upload_list_download_delete(client):
    response = client.post(
        "/api/vault/documents",
        data={"doc_type": "signature"},
        files={"file": ("sign.png", PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    record = response.json()["document"]
    assert record["encrypted"] is True

    listing = client.get("/api/vault/documents").json()
    assert record["id"] in [item["id"] for item in listing["documents"]]
    assert "signature" in listing["doc_types"]

    download = client.get(f"/api/vault/documents/{record['id']}")
    assert download.status_code == 200
    assert download.content == PNG
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in download.headers["content-disposition"]

    assert client.delete(f"/api/vault/documents/{record['id']}").status_code == 200
    assert client.get(f"/api/vault/documents/{record['id']}").status_code == 404


def test_api_rejects_bad_id_and_bad_file(client):
    assert client.get("/api/vault/documents/not-an-id").status_code == 422
    response = client.post(
        "/api/vault/documents",
        data={"doc_type": "other"},
        files={"file": ("page.html", b"<html>hi</html>", "text/html")},
    )
    assert response.status_code == 422
    assert "JPEG" in response.json()["detail"]


def test_photo_upload_points_the_vault_at_the_sealed_document(client):
    response = client.post(
        "/api/vault/documents",
        data={"doc_type": "photo"},
        files={"file": ("face.png", PNG, "image/png")},
    )
    assert response.status_code == 200
    doc_id = response.json()["document"]["id"]

    vault = client.get("/api/vault").json()
    assert vault["photo_path"] == f"document:{doc_id}"


def test_upload_hands_playwright_the_decrypted_bytes_not_a_path(store, monkeypatch, tmp_path):
    """The plaintext must exist only in memory during an upload."""
    import asyncio

    from backend.core.orchestrator import FormPilotOrchestrator
    from backend.core.vault import VaultManager

    record = store.save("photo", "face.png", PNG)
    monkeypatch.setattr(DocumentStore, "get_instance", classmethod(lambda cls: store))

    captured = {}

    class Locator:
        async def count(self):
            return 1

        async def set_input_files(self, value, timeout=None):
            captured["value"] = value

    class Page:
        def is_closed(self):
            return False

        def locator(self, selector):
            return Locator()

    orchestrator = FormPilotOrchestrator()
    orchestrator.vault_mgr = VaultManager(str(tmp_path / "vault.json"))
    orchestrator.vault_mgr.vault.photo_path = f"document:{record['id']}"
    orchestrator.page = Page()

    async def emit_event(*args, **kwargs):
        return None

    orchestrator.emit_event = emit_event

    ok = asyncio.run(orchestrator._handle_upload({"id": "photo", "name": "photo"}, "photo_upload"))

    assert ok is True
    payload = captured["value"]
    assert isinstance(payload, dict)
    assert payload["buffer"] == PNG
    assert payload["mimeType"] == "image/png"
    assert payload["name"] == "face.png"
    # Nothing decrypted was written back to the documents directory.
    assert list(Path(store.root).glob("*.png")) == []
