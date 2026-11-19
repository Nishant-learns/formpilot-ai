"""FormPilot app accounts: signup, sessions, and per-account isolation."""

from __future__ import annotations

import json

import pytest

import backend.main as main_module
from backend.core import settings
from backend.core.accounts import AccountError, AccountStore


PASSWORD = "CorrectHorse9"


def signup(client, email, name="Test Candidate", password=PASSWORD):
    response = client.post(
        "/api/account/signup",
        json={"email": email, "password": password, "name": name},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert payload["token"]
    return payload["token"], payload["account"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- signup


def test_signup_creates_an_account_and_a_live_session(client):
    token, account = signup(client, "Asha@Example.com", "Asha")

    assert account["email"] == "asha@example.com"
    assert account["name"] == "Asha"
    me = client.get("/api/account/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["account"]["id"] == account["id"]


def test_duplicate_email_is_rejected_case_insensitively(client):
    signup(client, "asha@example.com")
    response = client.post(
        "/api/account/signup",
        json={"email": "ASHA@example.com", "password": PASSWORD},
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_short_password_is_rejected(client):
    response = client.post(
        "/api/account/signup",
        json={"email": "asha@example.com", "password": "short"},
    )

    assert response.status_code == 400
    assert "at least" in response.json()["detail"]


def test_invalid_email_is_rejected(client):
    response = client.post(
        "/api/account/signup",
        json={"email": "not-an-email", "password": PASSWORD},
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------- login


def test_login_with_the_right_password_returns_a_new_token(client):
    first_token, account = signup(client, "asha@example.com")
    response = client.post(
        "/api/account/login",
        json={"email": "asha@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    second_token = response.json()["token"]
    assert second_token != first_token
    assert response.json()["account"]["id"] == account["id"]


def test_login_with_a_wrong_password_is_generic(client):
    signup(client, "asha@example.com")
    response = client.post(
        "/api/account/login",
        json={"email": "asha@example.com", "password": "WrongPassword9"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect."


def test_login_for_an_unknown_email_is_the_same_generic_error(client):
    response = client.post(
        "/api/account/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect."


# ------------------------------------------------------------------- sessions


def test_logout_invalidates_the_token(client):
    token, _ = signup(client, "asha@example.com")
    assert client.post("/api/account/logout", headers=auth(token)).status_code == 200
    assert client.get("/api/account/me", headers=auth(token)).status_code == 401


def test_an_expired_session_is_refused(client):
    token, account = signup(client, "asha@example.com")
    store = AccountStore.get_instance()

    from backend.core.accounts import _token_digest

    with store._lock:
        store._data["sessions"][_token_digest(token)]["expires_at"] = "2000-01-01T00:00:00+00:00"
        store._write()

    assert store.resolve(token) is None
    assert client.get("/api/account/me", headers=auth(token)).status_code == 401


def test_accounts_file_never_contains_a_plaintext_password_or_token(client):
    token, _ = signup(client, "asha@example.com")
    raw = (settings.ACCOUNTS_DIR / "accounts.json").read_text(encoding="utf-8")

    assert PASSWORD not in raw
    assert token not in raw
    assert "password_hash" in raw
    assert "salt" in raw


def test_signing_in_is_required_when_accounts_are_required(client, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNTS_REQUIRED", True)

    blocked = client.get("/api/vault")
    assert blocked.status_code == 401
    assert blocked.json()["code"] == "account_required"

    token, _ = signup(client, "asha@example.com")
    allowed = client.get("/api/vault", headers=auth(token))
    assert allowed.status_code == 200


def test_a_bogus_token_cannot_reach_an_account_workspace(client, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNTS_REQUIRED", True)

    response = client.get("/api/vault", headers=auth("not-a-real-token"))
    assert response.status_code == 401


# ------------------------------------------------------------------ isolation


def test_two_accounts_do_not_share_a_vault(client):
    token_a, account_a = signup(client, "asha@example.com")
    token_b, account_b = signup(client, "ravi@example.com")

    assert account_a["id"] != account_b["id"]
    saved = client.post(
        "/api/vault",
        headers=auth(token_a),
        json={"full_name": "Asha Verma", "mobile": "9000000001"},
    )
    assert saved.status_code == 200

    a_vault = client.get("/api/vault", headers=auth(token_a)).json()
    b_vault = client.get("/api/vault", headers=auth(token_b)).json()

    assert a_vault["full_name"] == "Asha Verma"
    assert b_vault["full_name"] == ""
    assert b_vault["mobile"] == ""


def test_a_new_account_starts_with_a_blank_vault(client):
    token, _ = signup(client, "asha@example.com")

    vault = client.get("/api/vault", headers=auth(token)).json()

    assert vault["full_name"] == ""
    assert vault["dob"] == ""
    assert vault["matric"]["roll_number"] == ""
    assert vault["intermediate"]["board"] == ""
    assert vault["custom_fields"] == {}


def test_workspaces_have_separate_directories(client):
    _, account_a = signup(client, "asha@example.com")
    _, account_b = signup(client, "ravi@example.com")

    dir_a = settings.ACCOUNTS_DIR / account_a["id"]
    dir_b = settings.ACCOUNTS_DIR / account_b["id"]

    assert dir_a != dir_b
    assert (dir_a / "candidate_vault.json").is_file()
    assert (dir_b / "candidate_vault.json").is_file()
    assert (dir_a / "documents").is_dir()
    assert (dir_a / "runs").is_dir()


def test_documents_are_isolated_and_not_downloadable_across_accounts(client):
    token_a, _ = signup(client, "asha@example.com")
    token_b, _ = signup(client, "ravi@example.com")

    # A tiny, real PNG (magic bytes are what the store validates).
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    uploaded = client.post(
        "/api/vault/documents",
        headers=auth(token_a),
        data={"doc_type": "photo"},
        files={"file": ("photo.png", png, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    doc_id = uploaded.json()["document"]["id"]

    a_docs = client.get("/api/vault/documents", headers=auth(token_a)).json()["documents"]
    b_docs = client.get("/api/vault/documents", headers=auth(token_b)).json()["documents"]
    assert [doc["id"] for doc in a_docs] == [doc_id]
    assert b_docs == []

    assert client.get(f"/api/vault/documents/{doc_id}", headers=auth(token_a)).status_code == 200
    assert client.get(f"/api/vault/documents/{doc_id}", headers=auth(token_b)).status_code == 404


def test_runs_are_isolated(client):
    token_a, account_a = signup(client, "asha@example.com")
    token_b, _ = signup(client, "ravi@example.com")

    workspace_a = main_module.workspaces.get(
        main_module.accounts.get(account_a["id"])
    )
    workspace_a.run_store.start("run-account-a", {"query": "practice portal", "mode": "fill"})

    a_runs = client.get("/api/runs", headers=auth(token_a)).json()
    b_runs = client.get("/api/runs", headers=auth(token_b)).json()

    assert any(run.get("run_id") == "run-account-a" for run in a_runs["runs"])
    assert all(run.get("run_id") != "run-account-a" for run in b_runs["runs"])
    assert client.get("/api/runs/run-account-a", headers=auth(token_b)).status_code == 404


def test_facts_are_isolated(client):
    token_a, _ = signup(client, "asha@example.com")
    token_b, _ = signup(client, "ravi@example.com")

    saved = client.put(
        "/api/facts/first_name",
        headers=auth(token_a),
        json={"value": "Asha"},
    )
    assert saved.status_code == 200

    a_fact = client.get(
        "/api/facts/resolve",
        headers=auth(token_a),
        params={"concept": "first_name"},
    ).json()
    b_fact = client.get(
        "/api/facts/resolve",
        headers=auth(token_b),
        params={"concept": "first_name"},
    ).json()

    assert a_fact["value"] == "Asha"
    assert b_fact["value"] != "Asha"


def test_portal_account_memory_is_isolated(client):
    token_a, _ = signup(client, "asha@example.com")
    token_b, _ = signup(client, "ravi@example.com")

    saved = client.put(
        "/api/portal-accounts/example.gov.in",
        headers=auth(token_a),
        json={
            "identifier_type": "registration_id",
            "identifier_value": "REG-12345",
            "account_exists": "yes",
        },
    )
    assert saved.status_code == 200

    a_accounts = client.get(
        "/api/portal-accounts", headers=auth(token_a)
    ).json()["accounts"]
    b_accounts = client.get(
        "/api/portal-accounts", headers=auth(token_b)
    ).json()["accounts"]

    assert [item["identifier_value"] for item in a_accounts] == ["*****2345"]
    assert b_accounts == []


def test_chat_history_is_per_account(client):
    token_a, _ = signup(client, "asha@example.com")
    token_b, _ = signup(client, "ravi@example.com")

    sent = client.post(
        "/api/chat/message",
        headers=auth(token_a),
        json={"message": "hello"},
    )
    assert sent.status_code == 200

    a_history = client.get("/api/chat/history", headers=auth(token_a)).json()
    b_history = client.get("/api/chat/history", headers=auth(token_b)).json()

    assert a_history
    assert b_history == []


def test_account_status_reports_the_signed_in_user(client):
    status = client.get("/api/account/status").json()
    assert status["accounts_enabled"] is True
    assert status["signed_in"] is False

    token, account = signup(client, "asha@example.com")
    status = client.get("/api/account/status", headers=auth(token)).json()
    assert status["signed_in"] is True
    assert status["account"]["id"] == account["id"]


def test_demo_login_issues_valid_session(client):
    res = client.post("/api/account/demo-login")
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["account"]["email"] == "demo@formpilot.local"
    assert data["account"]["name"] == "Candidate Nishant"

    status = client.get("/api/account/status", headers=auth(data["token"])).json()
    assert status["signed_in"] is True
    assert status["account"]["email"] == "demo@formpilot.local"


def test_google_login_via_store(client):
    store = AccountStore.get_instance()
    # 1. New Google user
    account, token = store.google_login("google.candidate@gmail.com", "Google Candidate", "sub_98765")
    assert account.email == "google.candidate@gmail.com"
    assert account.name == "Google Candidate"
    assert store.resolve(token).id == account.id

    # 2. Existing Google user signs in again -> same account, new session
    account2, token2 = store.google_login("google.candidate@gmail.com", "Google Candidate", "sub_98765")
    assert account2.id == account.id
    assert token2 != token
    assert store.resolve(token2).id == account.id


def test_google_login_endpoint_simulated(client):
    res = client.post(
        "/api/account/google",
        json={"simulated": True, "simulated_email": "candidate.test@gmail.com", "simulated_name": "Test User"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["account"]["email"] == "candidate.test@gmail.com"
    assert data["account"]["name"] == "Test User"
    assert "token" in data

    # Verify session is accepted
    me = client.get("/api/account/me", headers=auth(data["token"]))
    assert me.status_code == 200
    assert me.json()["account"]["email"] == "candidate.test@gmail.com"


def test_google_login_endpoint_verified_token(client, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "_verify_google_token",
        lambda cred: {
            "email": "verified.user@gmail.com",
            "name": "Verified Candidate",
            "sub": "sub_google_12345",
            "picture": "https://lh3.googleusercontent.com/avatar",
        },
    )
    res = client.post("/api/account/google", json={"credential": "valid_mock_token"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["account"]["email"] == "verified.user@gmail.com"
    assert data["account"]["name"] == "Verified Candidate"


def test_google_login_endpoint_rejects_missing_credential(client):
    res = client.post("/api/account/google", json={})
    assert res.status_code == 400
    assert "Missing Google credential" in res.json()["detail"]

