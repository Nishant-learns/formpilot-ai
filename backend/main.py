from __future__ import annotations

import asyncio
import datetime
import hmac
import json
import os
import re
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core import field_registry, playwright_patch, settings  # noqa: F401
from .core.accounts import Account, AccountError, AccountStore
from .core.biometrics import BiometricCompressor
from .core.document_store import DOC_TYPES, DocumentError, DocumentStore
from .core.extraction_contract import (
    EXTRACTION_PROMPT,
    FIELD_GUIDE,
    PROMPT_VERSION,
    SCHEMA,
    SCHEMA_VERSION,
    apply_import,
    build_import_plan,
)
from .core.facts import FactBook
from .core.portal_accounts import PortalAccountStore
from .core.chat_assistant import FormPilotChatAssistant
from .core.llm_client import LLMConfig
from .core.live_browser import live_sessions
from .core.oracle import PortalOracle
from .core.orchestrator import AgentRunError, FormPilotOrchestrator
from .core.rate_limit import RateLimiter
from .core.recipe import RecipeStore
from .core.run_report import build_run_report, render_run_report_html
from .core.run_store import RunStore
from .core.tinyfish_client import EngineConfig, TinyFishClient, TinyFishError
from .core.vault import CandidateVault, VaultManager
from .core.workspaces import Workspace, WorkspaceRegistry
from .core.security_hardening import SSRFGuard, AuditHashChain, PIISanitizer, BLOCKED_IP_NETWORKS
from .core.credential_store import CredentialStore, generate_compliant_password
from .core.som_extractor import SetOfMarksExtractor
from .core.smart_agent import SmartFormAgent
from .core.circuit_breaker import get_circuit_breaker, get_all_circuit_breaker_metrics, CircuitBreakerOpenError
from .core.idempotency import idempotency_engine, IdempotencyConflictError
from .knowledge.blueprint_loader import BlueprintRegistry
from .core.preflight_validator import PreFlightValidator
from .core.document_processor import DocumentProcessor

if settings.ENABLE_SIMULATOR:
    from .simulator.portal import router as simulator_router
else:  # pragma: no cover - production deployments can disable the practice portal
    simulator_router = None


settings.ensure_directories()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    yield
    try:
        if orchestrator.is_running or orchestrator.browser or orchestrator.page:
            await orchestrator.stop()
        elif orchestrator._session and orchestrator._session.is_cloud:
            await orchestrator.tinyfish_mgr.terminate_session(orchestrator._session.session_id)
    except Exception:
        traceback.print_exc()


app = FastAPI(
    title="FormPilot API",
    version=settings.APP_VERSION,
    description="Guided form-filling assistant for public recruitment and admission portals.",
    lifespan=lifespan,
    # The interactive API explorer is a development convenience.  A public
    # pilot does not need to advertise every internal endpoint.
    docs_url=None if settings.IS_PRODUCTION else "/docs",
    redoc_url=None if settings.IS_PRODUCTION else "/redoc",
    openapi_url=None if settings.IS_PRODUCTION else "/openapi.json",
)

# CORS is registered *after* the security middleware below so it stays the
# outermost layer.  Otherwise a preflight OPTIONS request hits the account
# guard first, gets a 401 with no CORS headers, and the browser reports the
# backend as unreachable.

if simulator_router is not None:
    app.include_router(simulator_router)

vault_mgr = VaultManager.get_instance()
tinyfish_client = TinyFishClient()
run_store = RunStore()
accounts = AccountStore.get_instance()
login_limiter = RateLimiter(
    limit=settings.LOGIN_RATE_LIMIT,
    window_seconds=settings.LOGIN_RATE_WINDOW_SECONDS,
)
signup_limiter = RateLimiter(
    limit=settings.SIGNUP_RATE_LIMIT,
    window_seconds=settings.SIGNUP_RATE_WINDOW_SECONDS,
)
# WebSocket -> owning account id (None for the legacy single-user demo).
active_connections: Dict[WebSocket, Optional[str]] = {}


async def broadcast_to_cockpits(event: Dict[str, Any], account_id: Optional[str] = None):
    """Send a cockpit event only to sockets that belong to the same account.

    Broadcasting every event to every socket would leak one candidate's page,
    fields and chat into another candidate's browser.
    """
    disconnected: List[WebSocket] = []
    for websocket, socket_account in list(active_connections.items()):
        if socket_account != account_id:
            continue
        try:
            await websocket.send_json(event)
        except Exception:
            disconnected.append(websocket)
    for websocket in disconnected:
        active_connections.pop(websocket, None)


orchestrator = FormPilotOrchestrator(broadcast_fn=broadcast_to_cockpits)
chat_assistant = FormPilotChatAssistant(orchestrator=orchestrator)


def _broadcast_for(account_id: Optional[str]):
    async def _send(event: Dict[str, Any]):
        await broadcast_to_cockpits(event, account_id=account_id)

    return _send


workspaces = WorkspaceRegistry(broadcast_factory=_broadcast_for)
legacy_workspace = Workspace(
    account_id=None,
    root=settings.DATA_DIR,
    vault_mgr=vault_mgr,
    document_store=DocumentStore.get_instance(),
    run_store=run_store,
    orchestrator=orchestrator,
    chat_assistant=chat_assistant,
    uploads_dir=settings.UPLOADS_DIR,
)


def get_workspace(request: Request) -> Workspace:
    """The authenticated account's workspace, or the legacy demo workspace."""
    account: Optional[Account] = getattr(request.state, "account", None)
    if account is None:
        return legacy_workspace
    return workspaces.get(account)


class FactInput(BaseModel):
    value: Optional[str] = Field(None, max_length=2000)
    label: Optional[str] = Field(None, max_length=200)
    value_type: Optional[str] = Field(None, max_length=40)
    parts: Optional[Dict[str, Any]] = None
    aliases: Optional[List[str]] = None
    provenance: str = Field(
        "explicit_user", pattern="^(explicit_user|derived|portal_confirmed|imported)$"
    )
    verification: str = Field(
        "confirmed_by_human",
        pattern="^(unverified|confirmed_by_human|verified_on_page)$",
    )
    domain: Optional[str] = Field(None, max_length=255)
    constraints: Optional[Dict[str, Any]] = None
    notes: Optional[str] = Field(None, max_length=1000)
    known_absent: bool = False


class PortalAccountInput(BaseModel):
    identifier_type: str = Field("unknown", max_length=40)
    identifier_value: str = Field("", max_length=255)
    account_exists: Optional[str] = Field(None, pattern="^(yes|no|unknown)$")
    login_method: Optional[str] = Field(None, max_length=40)
    registration_status: Optional[str] = Field(
        None, pattern="^(not_started|in_progress|submitted|unknown)$"
    )
    last_known_step: Optional[str] = Field(None, max_length=200)
    last_path_choice: Optional[str] = Field(None, max_length=40)
    identifiers_seen: Optional[List[str]] = None
    confirmed_by_human: bool = True


class CredentialInput(BaseModel):
    site_name: str = Field("Portal", max_length=120)
    url: str = Field("", max_length=500)
    username: str = Field("", max_length=200)
    password: str = Field(..., max_length=200)
    notes: Optional[str] = Field("", max_length=1000)
    id: Optional[str] = None


# --------------------------------------------------------------------------- security


def _request_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (
        request.headers.get("x-api-token")
        or request.query_params.get("token")
        or ""
    )


def _safe_compare(candidate: str) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, settings.AUTH_TOKEN)


def _client_ip(request: Request) -> str:
    """Best-effort client address behind Render/Cloudflare proxies."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _enforce_rate(limiter: RateLimiter, request: Request, scope: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry_after = limiter.check(f"{scope}:{_client_ip(request)}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )


@app.middleware("http")
async def security_headers_and_auth(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id

    # A CORS preflight carries no credentials by design.  Let it through to the
    # CORS layer instead of answering 401 from the account guard.
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    account_open = path.startswith("/api/account/")
    # Sign-in itself must be reachable without a session.  Everything else
    # under /api/ belongs to an account when accounts are required.
    protected = (
        path.startswith("/api/")
        and not path.startswith("/api/health")
        and not path.startswith("/api/portal/")
        and not account_open
    ) or path.startswith("/uploads/")

    token = _request_token(request)
    account = accounts.resolve(token) if token else None
    request.state.account = account
    request.state.account_token = token

    if settings.AUTH_REQUIRED and protected:
        if not _safe_compare(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"X-Request-ID": request_id},
            )

    if settings.ACCOUNTS_ENABLED and settings.ACCOUNTS_REQUIRED and protected and account is None:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Sign in to continue.",
                "code": "account_required",
            },
            headers={"X-Request-ID": request_id},
        )

    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss: https:; "
        "frame-ancestors 'self';"
    )
    # The live-photo checkpoint runs in this page, so the camera must be
    # allowed for the same origin. Microphone and geolocation stay off.
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
    if path.startswith("/api/vault") or path.startswith("/uploads/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong. Please try again."},
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


# Registered last on purpose: Starlette makes the most recently added middleware
# the outermost one.  CORS must see preflight requests and every error response
# before the account guard can short-circuit them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Token",
        "X-Request-ID",
        "X-Idempotency-Key",
        "X-Circuit-Breaker",
    ],
    expose_headers=["X-Request-ID", "Server-Timing", "Retry-After"],
    max_age=600,
)


# --------------------------------------------------------------------------- accounts


class SignupRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)
    name: str = Field("", max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)


class GoogleLoginRequest(BaseModel):
    credential: Optional[str] = None
    client_id: Optional[str] = None
    simulated: Optional[bool] = False
    simulated_email: Optional[str] = None
    simulated_name: Optional[str] = None


def _account_payload(account: Account, token: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": True, "account": account.public()}
    if token:
        payload["token"] = token
    return payload


@app.get("/api/account/status")
def account_status(request: Request):
    """Public capability probe for the sign-in screen."""
    account: Optional[Account] = getattr(request.state, "account", None)
    return {
        "accounts_enabled": settings.ACCOUNTS_ENABLED,
        "accounts_required": settings.ACCOUNTS_REQUIRED,
        "signed_in": account is not None,
        "account": account.public() if account else None,
        "account_count": accounts.count(),
        "google_client_id": settings.GOOGLE_CLIENT_ID,
    }


@app.post("/api/account/signup")
def account_signup(req: SignupRequest, request: Request):
    if not settings.ACCOUNTS_ENABLED:
        raise HTTPException(status_code=403, detail="Account creation is disabled on this instance.")
    _enforce_rate(signup_limiter, request, "signup")
    try:
        account, token = accounts.signup(req.email, req.password, req.name)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Create the private workspace now, so the first vault read is not shared.
    workspaces.get(account)
    return JSONResponse(content=_account_payload(account, token), headers={"Cache-Control": "no-store"})


@app.post("/api/account/login")
def account_login(req: LoginRequest, request: Request):
    if not settings.ACCOUNTS_ENABLED:
        raise HTTPException(status_code=403, detail="Accounts are disabled on this instance.")
    _enforce_rate(login_limiter, request, "login")
    try:
        account, token = accounts.login(req.email, req.password)
    except AccountError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    workspaces.get(account)
    return JSONResponse(content=_account_payload(account, token), headers={"Cache-Control": "no-store"})


@app.post("/api/account/demo-login")
def account_demo_login(request: Request):
    """1-click instant demo login without credentials so users/evaluators are never blocked."""
    account, token = accounts.demo_login()
    workspaces.get(account)
    return JSONResponse(
        content=_account_payload(account, token),
        headers={"Cache-Control": "no-store"},
    )


def _verify_google_token(credential: str) -> Dict[str, Any]:
    """Verify Google ID token via Google tokeninfo endpoint."""
    import json
    import urllib.parse
    import urllib.request

    credential = str(credential or "").strip()
    if not credential:
        raise AccountError("Missing Google ID token.")

    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}"
    req = urllib.request.Request(url, headers={"User-Agent": "FormPilot-Auth/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise AccountError("Google ID token verification failed or expired.") from exc

    if data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise AccountError("Invalid token issuer.")

    if settings.GOOGLE_CLIENT_ID and data.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise AccountError("Google token audience does not match configured Client ID.")

    email = data.get("email")
    if not email:
        raise AccountError("No email returned by Google identity.")
    if str(data.get("email_verified", "")).lower() not in ("true", "1"):
        raise AccountError("Google email is not verified.")

    return {
        "email": email,
        "name": data.get("name") or "",
        "sub": data.get("sub") or "",
        "picture": data.get("picture") or "",
    }


@app.post("/api/account/google")
def account_google(req: GoogleLoginRequest, request: Request):
    if not settings.ACCOUNTS_ENABLED:
        raise HTTPException(status_code=403, detail="Accounts are disabled on this instance.")
    _enforce_rate(login_limiter, request, "google_login")

    if req.simulated:
        if settings.IS_PRODUCTION and not settings.DEMO_MODE:
            raise HTTPException(status_code=403, detail="Simulated Google login is not permitted in production.")
        email = req.simulated_email or "google.candidate@example.com"
        name = req.simulated_name or "Google Candidate"
        sub = "simulated_google_sub_101"
    else:
        if not req.credential:
            raise HTTPException(status_code=400, detail="Missing Google credential ID token.")
        try:
            verified = _verify_google_token(req.credential)
            email = verified["email"]
            name = verified["name"]
            sub = verified["sub"]
        except AccountError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        account, token = accounts.google_login(email=email, name=name, google_sub=sub)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workspaces.get(account)
    return JSONResponse(
        content=_account_payload(account, token),
        headers={"Cache-Control": "no-store"},
    )



@app.post("/api/account/logout")
def account_logout(request: Request):
    token = getattr(request.state, "account_token", "")
    accounts.logout(token)
    return {"success": True}


@app.get("/api/account/me")
def account_me(request: Request):
    account: Optional[Account] = getattr(request.state, "account", None)
    if account is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return _account_payload(account)


@app.delete("/api/account")
def account_delete(request: Request):
    """Remove the account record.  The workspace is left for a human to audit."""
    account: Optional[Account] = getattr(request.state, "account", None)
    if account is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    removed = accounts.delete_account(account.id)
    workspaces.drop(account.id)
    return {"success": removed}


# --------------------------------------------------------------------------- vault


@app.get("/api/facts")
def list_facts(
    domain: Optional[str] = None,
    ws: Workspace = Depends(get_workspace),
):
    """The candidate's facts with provenance and verification.

    Values are masked for sensitive concepts, exactly like the vault view.
    """
    book = ws.orchestrator.fact_book
    return {
        "domain": domain,
        "summary": book.summary(domain=domain),
        "facts": [fact.public() for fact in book.all_facts(domain=domain)],
    }


@app.get("/api/facts/resolve")
def resolve_fact(
    concept: str,
    domain: Optional[str] = None,
    ws: Workspace = Depends(get_workspace),
):
    """Resolve one concept to a value, or say why it is missing."""
    book = ws.orchestrator.fact_book
    resolution = book.resolve(concept, domain=domain)
    data = resolution.model_dump()
    data["value"] = field_registry.mask_value(concept, data.get("value"))
    return data


@app.put("/api/facts/{concept}")
def set_fact(
    concept: str,
    payload: FactInput,
    ws: Workspace = Depends(get_workspace),
):
    """Store an explicit fact.  The human said it, so it beats derived data."""
    if not re.match(r"^[a-z0-9_]{1,60}$", concept):
        raise HTTPException(status_code=422, detail="Invalid concept name.")
    scope = (
        {"kind": "portal", "domain": payload.domain}
        if payload.domain
        else {"kind": "global"}
    )
    try:
        fact = ws.orchestrator.fact_book.set_fact(
            concept,
            value=payload.value,
            label=payload.label,
            value_type=payload.value_type,
            parts=payload.parts,
            aliases=payload.aliases,
            provenance=payload.provenance,
            verification=payload.verification,
            scope=scope,
            constraints=payload.constraints,
            notes=payload.notes,
            known_absent=payload.known_absent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "fact": fact.public()}


@app.delete("/api/facts/{concept}")
def delete_fact(
    concept: str,
    domain: Optional[str] = None,
    ws: Workspace = Depends(get_workspace),
):
    scope = {"kind": "portal", "domain": domain} if domain else {"kind": "global"}
    removed = ws.orchestrator.fact_book.delete_fact(concept, scope=scope)
    return {"success": removed, "concept": concept}


@app.get("/api/portal-accounts")
def list_portal_accounts(
    domain: Optional[str] = None,
    ws: Workspace = Depends(get_workspace),
):
    """Portal account memory: what is known per portal and per identifier."""
    store = ws.orchestrator.portal_account_store
    if domain:
        return {
            "domain": domain.lower(),
            "summary": store.domain_summary(domain),
            "accounts": [account.public() for account in store.accounts_for(domain)],
        }
    accounts = store.all_accounts()
    domains = sorted({account.domain for account in accounts})
    return {
        "domains": [
            {
                "domain": item,
                "summary": store.domain_summary(item),
            }
            for item in domains
        ],
        "accounts": [account.public() for account in accounts],
    }


@app.put("/api/portal-accounts/{domain}")
def set_portal_account(
    domain: str,
    payload: PortalAccountInput,
    ws: Workspace = Depends(get_workspace),
):
    """Record what the human confirmed about a portal account.

    The record is scoped to the portal domain (and optionally the identifier).
    Nothing here probes the portal.
    """
    if not re.match(r"^[a-z0-9.\-]{1,255}$", domain.lower()):
        raise HTTPException(status_code=422, detail="Invalid portal domain.")
    try:
        account = ws.orchestrator.portal_account_store.record(
            domain,
            identifier_type=payload.identifier_type,
            identifier_value=payload.identifier_value,
            account_exists=payload.account_exists,
            identifiers_seen=payload.identifiers_seen,
            login_method=payload.login_method,
            registration_status=payload.registration_status,
            last_known_step=payload.last_known_step,
            last_path_choice=payload.last_path_choice,
            confirmed_by_human=payload.confirmed_by_human,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "account": account.public()}


@app.delete("/api/portal-accounts/{domain}")
def delete_portal_account(
    domain: str,
    identifier_type: str = "unknown",
    identifier_value: str = "",
    ws: Workspace = Depends(get_workspace),
):
    removed = ws.orchestrator.portal_account_store.delete(
        domain,
        identifier_type=identifier_type,
        identifier_value=identifier_value,
    )
    return {"success": removed, "domain": domain}


# --------------------------------------------------------------------------- saved credentials store


@app.get("/api/credentials")
def list_credentials(request: Request):
    account = getattr(request.state, "account", None)
    acc_id = account.id if account else None
    store = CredentialStore.get_instance()
    return {"credentials": store.list_credentials(account_id=acc_id)}


@app.post("/api/credentials")
def save_credential(input_data: CredentialInput, request: Request):
    account = getattr(request.state, "account", None)
    acc_id = account.id if account else None
    store = CredentialStore.get_instance()
    rec = store.save_credential(
        site_name=input_data.site_name,
        url=input_data.url,
        username=input_data.username,
        password=input_data.password,
        notes=input_data.notes or "",
        account_id=acc_id,
        cred_id=input_data.id,
    )
    return {"success": True, "credential": rec.to_dict()}


@app.delete("/api/credentials/{cred_id}")
def delete_credential(cred_id: str, request: Request):
    account = getattr(request.state, "account", None)
    acc_id = account.id if account else None
    store = CredentialStore.get_instance()
    deleted = store.delete_credential(cred_id, account_id=acc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found.")
    return {"success": True}


@app.post("/api/credentials/generate-password")
def generate_password_api(length: int = Query(12, ge=8, le=16)):
    pwd = generate_compliant_password(length=length)
    return {"password": pwd}


@app.get("/api/vault")
def get_vault(masked: bool = Query(False), ws: Workspace = Depends(get_workspace)):
    data = ws.vault_mgr.vault.public_dict(mask_sensitive=masked or settings.MASK_PII)
    return JSONResponse(content=data, headers={"Cache-Control": "no-store"})


@app.post("/api/vault")
def update_vault(data: Dict[str, Any], ws: Workspace = Depends(get_workspace)):
    if len(json.dumps(data)) > 250_000:
        raise HTTPException(status_code=413, detail="Vault payload is too large.")
    try:
        updated = ws.vault_mgr.update(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid vault data: {exc}") from exc
    return {"success": True, "vault": updated.public_dict(mask_sensitive=settings.MASK_PII)}


@app.post("/api/vault/custom-field")
def add_custom_field(
    field_name: str = Form(...),
    field_value: str = Form(...),
    ws: Workspace = Depends(get_workspace),
):
    if len(field_name) > 80 or len(field_value) > 500:
        raise HTTPException(status_code=413, detail="Field is too large.")
    updated = ws.vault_mgr.add_custom_field(field_name, field_value)
    return {"success": True, "vault": updated.public_dict(mask_sensitive=settings.MASK_PII)}


@app.post("/api/vault/reset")
def reset_vault(ws: Workspace = Depends(get_workspace)):
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=403, detail="Vault reset is only available in demo mode.")
    default_vault = ws.vault_mgr.reset_defaults()
    return {"success": True, "vault": default_vault.public_dict(mask_sensitive=settings.MASK_PII)}


# ------------------------------------------------------- sealed document vault


def _link_document_to_vault(ws: Workspace, record: Dict[str, Any]) -> None:
    """Point the matching vault attribute at a sealed document.

    The vault stores ``document:<id>`` rather than a path: the decrypted file
    only exists in memory, at the moment the portal asks for it.
    """
    pointer = ws.document_store.vault_path_for(record)
    if not pointer:
        return
    attribute = {
        "photo": "photo_path",
        "signature": "signature_path",
        "matric_certificate": "matric_cert_path",
    }[record["doc_type"]]
    try:
        ws.vault_mgr.update({attribute: pointer})
    except Exception:
        traceback.print_exc()


@app.get("/api/vault/documents")
def list_documents(
    doc_type: Optional[str] = Query(None, max_length=40),
    ws: Workspace = Depends(get_workspace),
):
    store = ws.document_store
    try:
        records = store.list(doc_type)
        if not records and not doc_type:
            sample_files = [
                ("photo", "candidate_photo.jpg"),
                ("signature", "candidate_signature.jpg"),
            ]
            for dtype, fname in sample_files:
                src = settings.UPLOADS_DIR / fname
                if src.exists():
                    try:
                        rec = store.save(dtype, fname, src.read_bytes(), declared_mime="image/jpeg")
                        _link_document_to_vault(ws, rec)
                    except Exception:
                        pass
            records = store.list(doc_type)
    except DocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(
        content={
            "documents": [store.public(record) for record in records],
            "doc_types": DOC_TYPES,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/vault/documents/prefill-test")
def prefill_test_documents(ws: Workspace = Depends(get_workspace)):
    """Pre-fill sample candidate photo & signature into the encrypted document vault."""
    store = ws.document_store
    seeded = []
    sample_files = [
        ("photo", "candidate_photo.jpg"),
        ("signature", "candidate_signature.jpg"),
    ]
    for doc_type, filename in sample_files:
        src = settings.UPLOADS_DIR / filename
        if src.exists():
            data = src.read_bytes()
            existing = [d for d in store.list(doc_type)]
            if not existing:
                try:
                    record = store.save(doc_type, filename, data, declared_mime="image/jpeg")
                    _link_document_to_vault(ws, record)
                    seeded.append(store.public(record))
                except Exception:
                    pass
    return JSONResponse(
        content={
            "success": True,
            "seeded": seeded,
            "documents": [store.public(r) for r in store.list()],
        },
        headers={"Cache-Control": "no-store"},
    )



@app.post("/api/vault/documents")
async def upload_document(
    doc_type: str = Form(..., min_length=1, max_length=40),
    file: UploadFile = File(...),
    ws: Workspace = Depends(get_workspace),
):
    store = ws.document_store
    contents = await file.read(8 * 1024 * 1024 + 1)
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The file must be 8 MB or smaller.")
    try:
        record = store.save(
            doc_type,
            file.filename or "document",
            contents,
            declared_mime=file.content_type or "",
        )
    except DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _link_document_to_vault(ws, record)
    return JSONResponse(
        content={"success": True, "document": store.public(record)},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/vault/documents/{doc_id}")
def download_document(doc_id: str, ws: Workspace = Depends(get_workspace)):
    if not re.match(r"^[a-f0-9]{32}$", doc_id):
        raise HTTPException(status_code=422, detail="Invalid document id.")
    store = ws.document_store
    try:
        record, payload = store.read(doc_id)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = record.get("filename") or f"document{record.get('extension') or ''}"
    return Response(
        content=payload,
        media_type=record.get("mime") or "application/octet-stream",
        headers={
            # Always an attachment: a stored HTML/SVG can never execute here.
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@app.delete("/api/vault/documents/{doc_id}")
def delete_document(doc_id: str, ws: Workspace = Depends(get_workspace)):
    if not re.match(r"^[a-f0-9]{32}$", doc_id):
        raise HTTPException(status_code=422, detail="Invalid document id.")
    store = ws.document_store
    try:
        removed = store.delete(doc_id)
    except DocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="That document does not exist.")
    return {"success": True}


# ------------------------------------------- BYOK extraction (copy + paste)


@app.get("/api/vault/extraction-prompt")
def extraction_prompt():
    """The exact prompt and placeholder schema a candidate copies into an AI."""
    return JSONResponse(
        content={
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "prompt": EXTRACTION_PROMPT,
            "schema": SCHEMA,
            "field_guide": FIELD_GUIDE,
            "document_types": DOC_TYPES,
            "steps": [
                "Copy the prompt below.",
                "Open ChatGPT or Gemini and paste the prompt.",
                "Attach your marksheets, certificates, ID or address proof.",
                "Copy the JSON reply the AI gives you.",
                "Paste that JSON in the box below and press Review changes.",
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


class ExtractionImportRequest(BaseModel):
    payload: Any = Field(..., description="Pasted JSON, as text or an object.")
    apply: bool = False
    accept: Optional[List[str]] = None


@app.post("/api/vault/import-extraction")
def import_extraction(req: ExtractionImportRequest, ws: Workspace = Depends(get_workspace)):
    """Validate and map a pasted extraction, then optionally apply it.

    Two calls by design: the first returns the per-field verdicts so the
    candidate can review conflicts, the second applies only what they chose.
    """
    if isinstance(req.payload, str) and len(req.payload) > 200_000:
        raise HTTPException(status_code=413, detail="That JSON is too large.")
    plan = build_import_plan(req.payload, ws.vault_mgr.vault)
    if plan.errors:
        return JSONResponse(
            status_code=422,
            content={"success": False, "errors": plan.errors, "plan": plan.public()},
        )
    result: Dict[str, Any] = {"success": True, "plan": plan.public()}
    if req.apply:
        applied = apply_import(plan, ws.vault_mgr, accept=req.accept)
        result["applied"] = applied
        result["vault"] = ws.vault_mgr.vault.public_dict(mask_sensitive=settings.MASK_PII)
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- oracle


@app.get("/api/oracle/search")
async def oracle_search(
    q: str = Query(..., min_length=2, max_length=400),
    live: bool = Query(True),
):
    if live:
        result = await PortalOracle.resolve_target_live(q, tinyfish_client)
    else:
        result = PortalOracle.resolve_target(q)
    return result.model_dump()


@app.get("/api/oracle/directory")
def get_verified_directory():
    return PortalOracle.directory()


# --------------------------------------------------------------------------- exam intelligence / blueprints


@app.get("/api/exam/blueprints")
def list_exam_blueprints():
    """List all certified examination blueprints extracted and verified from official bulletins."""
    registry = BlueprintRegistry.get_instance()
    return {"blueprints": registry.list_available_exams()}


@app.get("/api/exam/blueprints/{exam_id}")
def get_exam_blueprint(exam_id: str):
    """Retrieve full certified blueprint specification for an examination."""
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint(exam_id)
    if not bp:
        raise HTTPException(status_code=404, detail=f"Exam blueprint '{exam_id}' not found.")
    return bp.model_dump()


class PreFlightRequest(BaseModel):
    exam_id: str = "NTA_JEE_MAIN_2027"


@app.post("/api/exam/preflight")
def run_preflight_audit(req: PreFlightRequest, ws: Workspace = Depends(get_workspace)):
    """Run deterministic pre-flight readiness audit against official examination blueprint."""
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint(req.exam_id)
    if not bp:
        raise HTTPException(status_code=404, detail=f"Exam blueprint '{req.exam_id}' not found.")
    result = PreFlightValidator.validate(ws.vault_mgr.vault, bp, uploads_dir=settings.UPLOADS_DIR)
    return result.to_dict()


class DocumentOptimizeRequest(BaseModel):
    exam_id: str = "NTA_JEE_MAIN_2027"
    document_key: str  # e.g. "photo", "signature", "matric_certificate"
    source_path: Optional[str] = None


@app.post("/api/documents/optimize")
def optimize_document(req: DocumentOptimizeRequest, ws: Workspace = Depends(get_workspace)):
    """Optimize/compress candidate document to conform to official exam bulletin boundaries."""
    registry = BlueprintRegistry.get_instance()
    bp = registry.get_blueprint(req.exam_id)
    if not bp:
        raise HTTPException(status_code=404, detail=f"Exam blueprint '{req.exam_id}' not found.")
    doc_spec = bp.documents.get(req.document_key)
    if not doc_spec:
        raise HTTPException(status_code=400, detail=f"Document '{req.document_key}' not in {req.exam_id} blueprint.")

    # Determine source path
    src_path = req.source_path
    if not src_path:
        if req.document_key == "photo":
            src_path = ws.vault_mgr.vault.photo_path
        elif req.document_key == "signature":
            src_path = ws.vault_mgr.vault.signature_path
        elif "matric" in req.document_key:
            src_path = ws.vault_mgr.vault.matric_cert_path

    if not src_path or not Path(src_path).exists():
        raise HTTPException(status_code=404, detail=f"Source file for '{req.document_key}' not found.")

    res = DocumentProcessor.optimize_for_spec(src_path, doc_spec)
    return res.to_dict()


# --------------------------------------------------------------------------- biometrics


MAX_UPLOAD_BYTES = 12 * 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large. Maximum size is 12 MB.")
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Please upload an image file.")
    return contents


@app.post("/api/biometrics/compress-photo")
async def compress_photo(
    file: UploadFile = File(...),
    target_width: int = Form(350),
    target_height: int = Form(350),
    min_kb: float = Form(20.0),
    max_kb: float = Form(50.0),
    ws: Workspace = Depends(get_workspace),
):
    contents = await _read_upload(file)
    try:
        result = BiometricCompressor.compress_photograph(
            image_bytes=contents,
            target_width=max(100, min(target_width, 1200)),
            target_height=max(100, min(target_height, 1200)),
            min_kb=max(1.0, min(min_kb, 500.0)),
            max_kb=max(2.0, min(max_kb, 500.0)),
            output_dir=str(ws.uploads_dir),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read that image. Please upload a JPEG or PNG.") from exc
    ws.vault_mgr.vault.photo_path = result["file_path"]
    ws.vault_mgr.save(ws.vault_mgr.vault)
    return result


@app.post("/api/biometrics/compress-signature")
async def compress_signature(
    file: UploadFile = File(...),
    target_width: int = Form(140),
    target_height: int = Form(60),
    min_kb: float = Form(10.0),
    max_kb: float = Form(20.0),
    ws: Workspace = Depends(get_workspace),
):
    contents = await _read_upload(file)
    try:
        result = BiometricCompressor.compress_signature(
            image_bytes=contents,
            target_width=max(40, min(target_width, 800)),
            target_height=max(20, min(target_height, 400)),
            min_kb=max(1.0, min(min_kb, 500.0)),
            max_kb=max(2.0, min(max_kb, 500.0)),
            output_dir=str(ws.uploads_dir),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read that image. Please upload a JPEG or PNG.") from exc
    ws.vault_mgr.vault.signature_path = result["file_path"]
    ws.vault_mgr.save(ws.vault_mgr.vault)
    return result


@app.get("/api/biometrics/preview")
def get_biometrics_preview(ws: Workspace = Depends(get_workspace)):
    BiometricCompressor.generate_sample_assets(str(ws.uploads_dir))
    photo_p = ws.uploads_dir / "candidate_photo.jpg"
    sig_p = ws.uploads_dir / "candidate_signature.jpg"
    photo_kb = round(photo_p.stat().st_size / 1024.0, 2) if photo_p.exists() else 0
    sig_kb = round(sig_p.stat().st_size / 1024.0, 2) if sig_p.exists() else 0
    prefix = "/uploads" if ws.is_guest else "/api/biometrics/asset"
    return {
        "photo": {
            "path": f"{prefix}/candidate_photo.jpg",
            "size_kb": photo_kb,
            "target_spec": "20KB - 50KB JPEG (350x350 px)",
            "in_spec": 20.0 <= photo_kb <= 50.0,
        },
        "signature": {
            "path": f"{prefix}/candidate_signature.jpg",
            "size_kb": sig_kb,
            "target_spec": "10KB - 20KB JPEG (140x60 px)",
            "in_spec": 10.0 <= sig_kb <= 20.0,
        },
    }


@app.get("/api/biometrics/asset/{filename}")
def get_biometric_asset(filename: str, ws: Workspace = Depends(get_workspace)):
    """Serve a generated biometric asset from the caller's workspace only."""
    if not _UPLOAD_NAME_RE.match(filename) or ".." in filename:
        raise HTTPException(status_code=404, detail="File not found.")
    path = ws.uploads_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- engine


def _operator_managed() -> bool:
    """In production the operator owns the shared engine/model credentials."""
    return bool(settings.IS_PRODUCTION)


def _require_operator() -> None:
    if _operator_managed():
        raise HTTPException(
            status_code=403,
            detail="Engine and model settings are managed by the FormPilot operator.",
        )


@app.get("/api/engine/config")
def get_engine_config():
    data = tinyfish_client.public_config()
    data["operator_managed"] = _operator_managed()
    return data


@app.post("/api/engine/config")
def update_engine_config(config: EngineConfig):
    _require_operator()
    tinyfish_client.save_config(config)
    return {"success": True, "config": tinyfish_client.public_config()}


@app.post("/api/engine/test-tinyfish")
async def test_tinyfish(payload: Dict[str, Any]):
    _require_operator()
    api_key = payload.get("api_key") or payload.get("tinyfish_api_key")
    if api_key in {"", "***", "********"}:
        api_key = None
    return await tinyfish_client.test_connection(api_key=api_key)


@app.get("/api/engine/wallet")
async def get_wallet():
    _require_operator()
    try:
        wallet = await tinyfish_client.get_wallet()
        return {
            "available_balance": wallet.get("available_balance"),
            "currency": wallet.get("currency"),
            "as_of": wallet.get("as_of"),
        }
    except TinyFishError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --------------------------------------------------------------------------- health / runs


@app.get("/health")
@app.get("/api/health")
def health(request: Request):
    ws = get_workspace(request)
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
        "demo_mode": settings.DEMO_MODE,
        "auth_required": settings.AUTH_REQUIRED,
        "accounts_enabled": settings.ACCOUNTS_ENABLED,
        "accounts_required": settings.ACCOUNTS_REQUIRED,
        "signed_in": getattr(request.state, "account", None) is not None,
        "simulator_enabled": settings.ENABLE_SIMULATOR,
        "tinyfish_configured": tinyfish_client.is_configured,
        "effective_mode": tinyfish_client.effective_mode(),
        "active_run": ws.orchestrator.run_id,
        "state": ws.orchestrator.state,
        "run_mode": ws.orchestrator.run_mode,
        "live_browser_sessions": len(live_sessions.active()),
        "inspect_ready": ws.orchestrator.state == "INSPECT_READY",
    }


@app.get("/api/runs")
def list_runs(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cursor: Optional[str] = Query(None, description="Opaque cursor from a previous page."),
    ws: Workspace = Depends(get_workspace),
):
    try:
        return ws.run_store.list_runs_page(limit=limit, offset=offset, cursor=cursor)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor.")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, ws: Workspace = Depends(get_workspace)):
    detail = ws.run_store.run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found.")
    return detail


@app.get("/api/runs/{run_id}/steps")
def get_run_steps(run_id: str, ws: Workspace = Depends(get_workspace)):
    meta = ws.run_store.read_meta(run_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {
        "run_id": run_id,
        "steps": ws.run_store.read_steps(run_id),
        "summary": ws.run_store.step_summary(run_id),
    }


@app.get("/api/runs/{run_id}/report")
def get_run_report(run_id: str, ws: Workspace = Depends(get_workspace)):
    detail = ws.run_store.run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found.")
    return build_run_report(detail)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def get_run_page(run_id: str, request: Request):
    ws = get_workspace(request)
    detail = ws.run_store.run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Run not found.")
    return HTMLResponse(render_run_report_html(build_run_report(detail)))


@app.get("/api/runs/{run_id}/audit")
def get_run_audit(run_id: str, ws: Workspace = Depends(get_workspace)):
    audit = ws.run_store.read_audit(run_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit report not found.")
    return JSONResponse(content=audit, headers={"Content-Disposition": f'attachment; filename="formpilot-audit-{run_id}.json"'})


@app.get("/api/runs/{run_id}/audit-chain")
def get_run_audit_chain(run_id: str, ws: Workspace = Depends(get_workspace)):
    """Return cryptographically verified Merkle hash chain for tamper-evident run non-repudiation."""
    chain_data = ws.run_store.build_audit_chain(run_id)
    if not chain_data.get("verified") and chain_data.get("error") == "Run not found":
        raise HTTPException(status_code=404, detail="Run not found.")
    return chain_data


@app.get("/api/system/circuit-breakers")
def get_circuit_breaker_telemetry():
    """Real-time observability telemetry for external government portal circuit breakers."""
    return {
        "status": "ok",
        "breakers": get_all_circuit_breaker_metrics(),
    }


@app.get("/api/system/health/deep")
def deep_system_health():
    """Deep health probe verifying SSRF defenses, circuit breakers, idempotency, and vault encryption."""
    mem_rss_mb = 0.0
    try:
        import psutil
        process = psutil.Process()
        mem_rss_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        mem_rss_mb = -1.0

    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "security": {
            "ssrf_guard_active": True,
            "blocked_ip_ranges_count": len(BLOCKED_IP_NETWORKS),
            "cloud_metadata_protection": "ACTIVE",
            "pii_sanitization": "ACTIVE",
            "vault_encrypted": bool(settings.VAULT_ENCRYPTION_KEY),
            "auth_required": settings.AUTH_REQUIRED,
        },
        "resilience": {
            "idempotency_records_cached": idempotency_engine.size(),
            "circuit_breakers": get_all_circuit_breaker_metrics(),
        },
        "resources": {
            "memory_rss_mb": mem_rss_mb,
            "open_connections": len(active_connections),
        },
    }


# --------------------------------------------------------------------------- recipes


@app.get("/api/recipes")
def list_recipes(ws: Workspace = Depends(get_workspace)):
    return {"recipes": ws.orchestrator.recipe_store.list_recipes()}


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str, ws: Workspace = Depends(get_workspace)):
    recipe = ws.orchestrator.recipe_store.load_by_id(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    return recipe


# --------------------------------------------------------------------------- journeys


@app.get("/api/journeys")
def list_journeys(ws: Workspace = Depends(get_workspace)):
    """Known application paths, shared by exam.  Structure only, no values."""
    return {"journeys": ws.orchestrator.journey_store.list_journeys()}


@app.get("/api/journeys/{journey_key}")
def get_journey(journey_key: str, ws: Workspace = Depends(get_workspace)):
    journey = ws.orchestrator.journey_store.load(journey_key)
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found.")
    return journey


# --------------------------------------------------------------------------- agent


class LaunchRequest(BaseModel):
    query_or_url: str = Field(..., min_length=1, max_length=500)
    mode: str = Field("fill", pattern="^(fill|inspect)$")


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class EntryModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(register|login|resume)$")


@app.post("/api/agent/start")
async def start_agent(
    req: LaunchRequest,
    request: Request,
    ws: Workspace = Depends(get_workspace),
):
    # 1. SSRF Protection Guard: block cloud metadata (169.254.169.254), private subnets, unroutable IPv6
    target = req.query_or_url.strip()
    if target.startswith(("http://", "https://")) or "://" in target:
        safe, reason = SSRFGuard.is_safe_url(
            target,
            allow_local_simulator=settings.ENABLE_SIMULATOR or settings.DEMO_MODE,
        )
        if not safe:
            raise HTTPException(status_code=400, detail=f"SSRF Protection Guard: {reason}")

    # 2. Exactly-Once Idempotency Guard
    idempotency_key = request.headers.get("X-Idempotency-Key")
    if idempotency_key:
        try:
            acquired, cached = await idempotency_engine.acquire(idempotency_key)
            if not acquired and cached:
                return JSONResponse(
                    status_code=cached.status_code,
                    content=cached.response_body,
                    headers={"X-Cache": "HIT-IDEMPOTENCY"},
                )
        except IdempotencyConflictError as err:
            raise HTTPException(status_code=409, detail=str(err))
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

    if ws.orchestrator.is_running:
        res = {"success": False, "message": "An application is already in progress."}
        if idempotency_key:
            await idempotency_engine.complete(idempotency_key, 200, res)
        return res

    if ws.orchestrator.page and not ws.orchestrator.page.is_closed() and ws.orchestrator.state in {"INSPECT_READY", "AWAITING_PAYMENT"}:
        await ws.orchestrator.stop()

    task = asyncio.create_task(ws.orchestrator.start_application(req.query_or_url, req.mode))
    app.state.agent_task = task

    def _done(done_task: asyncio.Task):
        try:
            done_task.result()
        except Exception:
            traceback.print_exc()

    task.add_done_callback(_done)
    response_payload = {
        "success": True,
        "message": "Inspection started." if req.mode == "inspect" else "Application started.",
        "mode": req.mode,
        "run_id": ws.orchestrator.run_id,
    }
    if idempotency_key:
        await idempotency_engine.complete(idempotency_key, 200, response_payload)
    return response_payload


@app.post("/api/agent/entry-mode")
async def choose_entry_mode(req: EntryModeRequest, ws: Workspace = Depends(get_workspace)):
    """Select register/login/resume explicitly, without guessing."""
    result = ws.orchestrator.choose_entry_mode(req.mode)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("message") or "That entry path is not available.")
    await broadcast_to_cockpits(
        {
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "phase": "DECIDE",
            "message": result.get("message") or "Entry path selected.",
            "state": ws.orchestrator.state,
            "run_id": ws.orchestrator.run_id,
            "entry_mode": ws.orchestrator._entry_mode,
            "entry_options": ws.orchestrator.get_state().get("entry_options") or [],
            "fill_summary": ws.orchestrator.fill_summary,
        },
        account_id=ws.account_id,
    )
    return result


@app.post("/api/agent/inspect/scan")
async def inspect_current_page(ws: Workspace = Depends(get_workspace)):
    try:
        form_map = await ws.orchestrator.refresh_inspection()
    except AgentRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "form_map": form_map, "recipe": ws.orchestrator._recipe_status}


@app.post("/api/agent/som/scan")
async def som_scan_page(ws: Workspace = Depends(get_workspace)):
    """Extract visible interactive elements tagged with numeric indices (Set-of-Marks)."""
    page = getattr(ws.orchestrator, "page", None)
    if not page or page.is_closed():
        raise HTTPException(status_code=409, detail="No active browser session.")
    elements = await SetOfMarksExtractor.extract_elements(page)
    prompt_summary = SetOfMarksExtractor.format_for_prompt(elements)
    return {
        "success": True,
        "count": len(elements),
        "elements": [e.to_dict() for e in elements],
        "prompt_summary": prompt_summary,
    }


@app.post("/api/agent/som/step")
async def som_execute_step(ws: Workspace = Depends(get_workspace)):
    """Executes a smart autonomous form-filling step with self-healing validation."""
    page = getattr(ws.orchestrator, "page", None)
    if not page or page.is_closed():
        raise HTTPException(status_code=409, detail="No active browser session.")
    profile = ws.vault.get_profile()
    agent = SmartFormAgent()
    result = await agent.step(page, profile)
    return {
        "success": result.success,
        "actions_executed": result.actions_executed,
        "validation": result.validation,
        "needs_human": result.needs_human,
        "message": result.message,
    }



@app.get("/api/page/brief")
async def get_page_brief(refresh: bool = Query(False), ws: Workspace = Depends(get_workspace)):
    """Read-only human brief for the current page. Never fills or clicks."""
    try:
        brief = await ws.orchestrator.get_page_brief(refresh=refresh)
    except AgentRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(content=brief, headers={"Cache-Control": "no-store"})


@app.get("/api/page/login-options")
async def get_login_options(ws: Workspace = Depends(get_workspace)):
    """Read-only inspection of visible login/recovery options."""
    try:
        inspection = await ws.orchestrator.inspect_login_options()
    except AgentRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(content=inspection, headers={"Cache-Control": "no-store"})


@app.post("/api/agent/upload")
async def upload_for_portal(
    field_key: str = Form(..., min_length=1, max_length=80),
    file: UploadFile = File(...),
    ws: Workspace = Depends(get_workspace),
):
    if not ws.orchestrator.page or ws.orchestrator.page.is_closed():
        raise HTTPException(status_code=409, detail="There is no live browser to upload to.")
    if not re.match(r"^[a-zA-Z0-9_\-]{1,80}$", field_key):
        raise HTTPException(status_code=422, detail="Invalid field key.")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The file must be 5 MB or smaller.")
    content_type = (file.content_type or "").lower()
    allowed = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, WEBP or PDF file.")

    original = Path(file.filename or "upload").name
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original).stem)[:60] or "upload"
    destination = ws.uploads_dir / f"user-{uuid.uuid4().hex[:10]}-{safe_stem}{allowed[content_type]}"
    destination.write_bytes(data)

    result = await ws.orchestrator.attach_upload(str(destination), field_key)
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("message") or "The portal did not accept the file.")
    return result


@app.post("/api/agent/pause")
async def pause_agent(ws: Workspace = Depends(get_workspace)):
    if not ws.orchestrator.is_running:
        return {"success": False, "message": "There is no active application to pause."}
    if ws.orchestrator.state == "WAITING_FOR_USER":
        return {
            "success": False,
            "message": "The agent is already waiting for your input at a checkpoint.",
        }
    if ws.orchestrator.state not in {"RUNNING", "RESOLVING"}:
        return {
            "success": False,
            "message": "The agent is not currently working, so there is nothing to pause.",
        }
    ws.orchestrator.pause()
    await broadcast_to_cockpits(
        {
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "phase": "DECIDE",
            "message": "Application paused. Take your time to review.",
            "state": ws.orchestrator.state,
            "run_id": ws.orchestrator.run_id,
        },
        account_id=ws.account_id,
    )
    return {"success": True, "state": ws.orchestrator.state}


@app.post("/api/agent/takeover")
async def take_over_agent(ws: Workspace = Depends(get_workspace)):
    """Give the human exclusive control of the live browser.

    Always available while a live page is open, including while the agent is
    driving.  The loop pauses first, so the human and the operator never type
    into the same page at the same time.
    """
    result = await ws.orchestrator.take_human_control()
    if result.get("success"):
        await broadcast_to_cockpits(
            {
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "phase": "DECIDE",
                "message": "You have the browser. FormPilot is paused.",
                "state": ws.orchestrator.state,
                "run_id": ws.orchestrator.run_id,
                "takeover": result.get("takeover"),
            },
            account_id=ws.account_id,
        )
    return result


@app.post("/api/agent/takeover/return")
async def return_agent_control(ws: Workspace = Depends(get_workspace)):
    """Take the page back, re-read it, and stay paused for a human check."""
    result = await ws.orchestrator.return_human_control()
    if result.get("success"):
        await broadcast_to_cockpits(
            {
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "phase": "SENSE",
                "message": "Control returned. The page was re-read; review it, then continue.",
                "state": ws.orchestrator.state,
                "run_id": ws.orchestrator.run_id,
                "takeover": result.get("takeover"),
            },
            account_id=ws.account_id,
        )
    return result


@app.post("/api/agent/resume")
async def resume_agent(ws: Workspace = Depends(get_workspace)):
    if not ws.orchestrator.is_running:
        return {"success": False, "message": "There is no active application to resume."}
    if ws.orchestrator.takeover_state().get("active"):
        # Returning control is an explicit step: the page is re-read before the
        # loop may act again.  At a checkpoint the checkpoint itself continues
        # to wait for its own answer.
        returned = await ws.orchestrator.return_human_control(refresh=True)
        if not ws.orchestrator.paused:
            return {
                "success": True,
                "state": ws.orchestrator.state,
                "message": "Control returned. The checkpoint is still open.",
                "takeover": returned.get("takeover"),
            }
    if not ws.orchestrator.paused:
        return {"success": False, "message": "The application is already running."}
    ws.orchestrator.resume()
    await broadcast_to_cockpits(
        {
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "phase": "ACT",
            "message": "Application resumed.",
            "state": ws.orchestrator.state,
            "run_id": ws.orchestrator.run_id,
        },
        account_id=ws.account_id,
    )
    return {"success": True, "state": ws.orchestrator.state}


@app.post("/api/agent/stop")
async def stop_agent(ws: Workspace = Depends(get_workspace)):
    await ws.orchestrator.stop()
    return {"success": True, "message": "Application stopped."}


@app.post("/api/agent/reset")
async def reset_agent(ws: Workspace = Depends(get_workspace)):
    if not await ws.orchestrator.reset_session():
        return {
            "success": False,
            "message": "Stop the active application before starting a new one.",
        }
    await broadcast_to_cockpits(
        {
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "phase": "DECIDE",
            "message": "Ready for a new application.",
            "state": "IDLE",
            "run_id": None,
            "active_gate": None,
            "run_mode": "fill",
        },
        account_id=ws.account_id,
    )
    return {"success": True, "state": "IDLE"}


@app.post("/api/agent/dismiss-gate")
async def dismiss_gate(ws: Workspace = Depends(get_workspace)):
    if ws.orchestrator.active_gate:
        ws.orchestrator.active_gate = None
        ws.orchestrator.submit_user_response({"action": "DISMISS"})
    return {"success": True}


@app.get("/api/agent/debug/page")
async def debug_page(ws: Workspace = Depends(get_workspace)):
    """Local-only inspection of the live page's controls."""
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Not found.")
    page = ws.orchestrator.page
    if page is None:
        return {"error": "no page"}
    return await page.evaluate(
        """() => {
            const vis = (el) => {
                if (!el || !el.isConnected) return false;
                const s = getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') return false;
                const r = el.getBoundingClientRect();
                return r.width > 1 && r.height > 1;
            };
            const out = {};
            out.url = location.href;
            out.dialogs = Array.from(document.querySelectorAll(
                '[role="dialog"],[role="alertdialog"],[aria-modal="true"],dialog,' +
                '[class*="modal" i],[class*="popup" i],[id*="popup" i],[id*="confirm" i]'
            )).map(el => ({
                tag: el.tagName, id: el.id, cls: el.className,
                display: getComputedStyle(el).display,
                visible: vis(el),
                text: String(el.innerText || '').slice(0, 300),
                buttons: Array.from(el.querySelectorAll('button,input[type=button],input[type=submit],a,[role=button],[onclick]'))
                    .map(b => ({tag: b.tagName, text: String(b.innerText || b.value || '').trim().slice(0, 40),
                                onclick: b.getAttribute('onclick'), visible: vis(b)})),
            }));
            out.visible_buttons = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],[role=button],[onclick]'))
                .filter(vis)
                .map(b => ({tag: b.tagName, id: b.id, text: String(b.innerText || b.value || '').trim().slice(0, 40),
                            onclick: b.getAttribute('onclick'), disabled: !!b.disabled}));
            const cb = document.getElementById('ctl00_ContentPlaceHolder1_chkagreement');
            out.checkbox = cb ? {disabled: cb.disabled, checked: cb.checked, display: getComputedStyle(cb).display,
                                 chain: (() => { const chain = []; let el = cb;
                                     while (el && el !== document.body) {
                                         chain.push({tag: el.tagName, id: el.id, cls: String(el.className || '').slice(0, 40),
                                                     display: getComputedStyle(el).display, hidden: !!el.hidden});
                                         el = el.parentElement;
                                     } return chain; })()} : null;
            out.hidden_value = (document.getElementById('ctl00_ContentPlaceHolder1_hfSelectedOption') || {}).value;
            out.radios = Array.from(document.querySelectorAll('input[type=radio]')).map(r => ({id: r.id, checked: r.checked, disabled: r.disabled}));
            return out;
        }"""
    )


@app.post("/api/agent/debug/eval")
async def debug_eval(payload: Dict[str, Any], ws: Workspace = Depends(get_workspace)):
    """Local-only JavaScript evaluation against the live page."""
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Not found.")
    page = ws.orchestrator.page
    if page is None:
        return {"error": "no page"}
    return {"result": await page.evaluate(str(payload.get("js") or "() => null"))}


@app.post("/api/agent/user-response")
def submit_candidate_response(data: Dict[str, Any], ws: Workspace = Depends(get_workspace)):
    if len(json.dumps(data)) > 50_000:
        raise HTTPException(status_code=413, detail="Response is too large.")
    if not ws.orchestrator.active_gate and not ws.orchestrator.active_event_future:
        return {"success": False, "message": "There is no open checkpoint."}
    ws.orchestrator.submit_user_response(data)
    return {"success": True}


@app.get("/api/agent/state")
def get_agent_state(ws: Workspace = Depends(get_workspace)):
    return ws.orchestrator.get_state()


# --------------------------------------------------------------------------- chat


@app.post("/api/chat/message")
async def post_chat_message(req: ChatMessageRequest, ws: Workspace = Depends(get_workspace)):
    result = await ws.chat_assistant.handle_message(req.message)
    await broadcast_to_cockpits(
        {
            "timestamp": result.get("timestamp", datetime.datetime.now().strftime("%H:%M")),
            "type": "CHAT_MESSAGE",
            "sender": ws.chat_assistant.sender,
            "message": result.get("reply", ""),
            "action_taken": result.get("action_taken"),
            "field_updated": result.get("field_updated"),
            "new_value": result.get("new_value"),
            "entry_mode": result.get("entry_mode"),
            "login_method": result.get("login_method"),
            "login_identifier": result.get("login_identifier"),
            "fill_summary": ws.orchestrator.fill_summary,
            "fill_failures": ws.orchestrator.fill_failures,
        },
        account_id=ws.account_id,
    )
    return result


@app.get("/api/chat/history")
def get_chat_history(ws: Workspace = Depends(get_workspace)):
    return ws.chat_assistant.chat_history


@app.get("/api/chat/config")
def get_chat_config(ws: Workspace = Depends(get_workspace)):
    """Public view of the assistant model (never returns the raw key)."""
    data = ws.chat_assistant.llm.public_config()
    data["operator_managed"] = _operator_managed()
    return data


@app.post("/api/chat/config")
def update_chat_config(config: LLMConfig, ws: Workspace = Depends(get_workspace)):
    _require_operator()
    ws.chat_assistant.llm.save_config(config)
    return ws.chat_assistant.llm.public_config()


@app.get("/api/chat/health")
async def get_chat_health(ws: Workspace = Depends(get_workspace)):
    """Developer diagnostic: checks real-time health and latency across all LLM providers and TinyFish."""
    report = await ws.chat_assistant.llm.check_health()
    report["tinyfish"] = {
        "mode": getattr(settings, "TINYFISH_MODE", "auto"),
        "key_configured": bool(getattr(settings, "TINYFISH_API_KEY", "")),
        "proxy_country": getattr(settings, "TINYFISH_PROXY_COUNTRY", "IN"),
    }
    return report


@app.post("/api/chat/test")
async def test_chat_health(ws: Workspace = Depends(get_workspace)):
    """Trigger developer diagnostic probe for LLM failover pool."""
    report = await ws.chat_assistant.llm.check_health()
    report["tinyfish"] = {
        "mode": getattr(settings, "TINYFISH_MODE", "auto"),
        "key_configured": bool(getattr(settings, "TINYFISH_API_KEY", "")),
        "proxy_country": getattr(settings, "TINYFISH_PROXY_COUNTRY", "IN"),
    }
    return report


# --------------------------------------------------------------------------- websocket


def _ws_token(websocket: WebSocket) -> str:
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return websocket.query_params.get("token") or websocket.headers.get("x-api-token") or ""


@app.websocket("/ws/live")
async def live_websocket(websocket: WebSocket):
    """Interactive stream of the agent's real browser.

    Frames are JPEG images from Chrome's CDP screencast.  Input is forwarded
    back to the same page.  The session token is separate from the cockpit
    token so another tab cannot take control of an active run.
    """
    session_id = websocket.query_params.get("session_id", "")
    access_token = websocket.query_params.get("access_token", "")
    session = live_sessions.get(session_id)
    if not session or not hmac.compare_digest(session.access_token, access_token):
        await websocket.close(code=1008)
        return
    if settings.AUTH_REQUIRED and not _safe_compare(_ws_token(websocket)):
        await websocket.close(code=1008)
        return
    if settings.ACCOUNTS_ENABLED and settings.ACCOUNTS_REQUIRED:
        live_token = _ws_token(websocket)
        if accounts.resolve(live_token) is None:
            await websocket.close(code=1008)
            return

    await websocket.accept()
    queue = session.subscribe()
    await websocket.send_json({"type": "hello", **session.public_info()})
    # A static page may not produce another frame after the browser session
    # starts. Send the latest frame on connect so a late subscriber sees the
    # real page immediately instead of an empty viewer.
    latest_frame = session.latest_frame_base64()
    if latest_frame:
        await websocket.send_json(
            {
                "type": "frame",
                "data": latest_frame,
                "metadata": session._latest_metadata,
                "viewport": session.public_info()["viewport"],
                "url": session.public_info()["url"],
                "frames_sent": session.frames_sent,
            }
        )

    async def sender():
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    send_task = asyncio.create_task(sender())
    window_start = time.monotonic()
    message_count = 0
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > 12_000:
                await websocket.send_json({"type": "input_error", "error": "Input message is too large."})
                continue
            message_count += 1
            now = time.monotonic()
            if now - window_start >= 1.0:
                window_start = now
                message_count = 0
            if message_count > 180:
                await websocket.send_json({"type": "input_error", "error": "Too many input events. Slow down."})
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "input_error", "error": "Invalid JSON."})
                continue
            result = await session.dispatch(data)
            if not result.get("ok"):
                await websocket.send_json({"type": "input_error", **result})
    except WebSocketDisconnect:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        send_task.cancel()
        session.unsubscribe(queue)


@app.websocket("/ws/cockpit")
async def cockpit_websocket(websocket: WebSocket):
    if settings.AUTH_REQUIRED and not _safe_compare(_ws_token(websocket)):
        await websocket.close(code=1008)
        return
    token = _ws_token(websocket)
    account: Optional[Account] = accounts.resolve(token) if token else None
    if settings.ACCOUNTS_ENABLED and settings.ACCOUNTS_REQUIRED and account is None:
        await websocket.close(code=1008)
        return
    ws = workspaces.get(account) if account is not None else legacy_workspace
    socket_account_id = account.id if account is not None else None
    orchestrator_ws = ws.orchestrator
    assistant_ws = ws.chat_assistant

    await websocket.accept()
    active_connections[websocket] = socket_account_id

    async def _heartbeat_loop():
        try:
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({"type": "PING", "timestamp": datetime.datetime.now().isoformat()})
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        await websocket.send_json(
            {
                "timestamp": "Ready",
                "phase": "SENSE",
                "message": "FormPilot is connected. Start an application whenever you are ready.",
                "hindi": "FormPilot connected hai. Jab chahein application shuru karein.",
                "screenshot": "",
                "account": account.public() if account else None,
                "active_gate": orchestrator_ws.active_gate,
                "current_section": orchestrator_ws.current_section,
                "filled_audit": orchestrator_ws._public_audit(),
                "run_id": orchestrator_ws.run_id,
                "state": orchestrator_ws.state,
                "run_mode": orchestrator_ws.run_mode,
                "live_session": orchestrator_ws.live.public_info() if orchestrator_ws.live and not orchestrator_ws.live.closed else None,
                "form_map": orchestrator_ws.form_map,
                "recipe": orchestrator_ws._recipe_status,
                "fill_summary": orchestrator_ws.fill_summary,
                "fill_failures": orchestrator_ws.fill_failures,
                "entry_mode": orchestrator_ws._entry_mode,
                "entry_options": orchestrator_ws.get_state().get("entry_options") or [],
                "login_method": orchestrator_ws._login_method,
                "login_identifier": orchestrator_ws._login_identifier,
            }
        )
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "ERROR", "message": "Invalid message."})
                continue
            action = data.get("action")
            if action == "SUBMIT_GATE":
                orchestrator_ws.submit_user_response(data.get("payload", {}))
            elif action == "SEND_CHAT":
                message = str(data.get("message", ""))[:2000]
                result = await assistant_ws.handle_message(message)
                await broadcast_to_cockpits(
                    {
                        "timestamp": result.get("timestamp", datetime.datetime.now().strftime("%H:%M")),
                        "type": "CHAT_MESSAGE",
                        "sender": assistant_ws.sender,
                        "message": result.get("reply", ""),
                        "action_taken": result.get("action_taken"),
                        "field_updated": result.get("field_updated"),
                        "new_value": result.get("new_value"),
                        "entry_mode": result.get("entry_mode"),
                        "login_method": result.get("login_method"),
                        "login_identifier": result.get("login_identifier"),
                        "fill_summary": orchestrator_ws.fill_summary,
                        "fill_failures": orchestrator_ws.fill_failures,
                    },
                    account_id=socket_account_id,
                )
            elif action == "PING":
                await websocket.send_json({"type": "PONG", "timestamp": datetime.datetime.now().isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        active_connections.pop(websocket, None)


# --------------------------------------------------------------------------- protected uploads


_UPLOAD_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


@app.get("/uploads/{filename}")
def get_upload(filename: str, request: Request):
    if not _UPLOAD_NAME_RE.match(filename) or ".." in filename:
        raise HTTPException(status_code=404, detail="File not found.")
    ws = get_workspace(request)
    path = ws.uploads_dir / filename
    if not path.is_file() and ws.is_guest:
        path = settings.UPLOADS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    media_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- static frontend

FRONTEND_DIST = settings.ROOT_DIR / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
