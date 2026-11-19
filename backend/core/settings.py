"""Runtime configuration for FormPilot.

Everything that can differ between a local demo, a judge's laptop and a
production deployment lives here.  Secrets are read from the environment
first; the JSON config file is only a local-demo convenience.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


ROOT_DIR = Path(__file__).resolve().parents[2]

APP_NAME = "FormPilot"
APP_VERSION = "1.1.0"
APP_ENV = os.getenv("FORMPILOT_ENV", "demo").strip().lower()
IS_PRODUCTION = APP_ENV in {"prod", "production"}
DEMO_MODE = _env_bool("FORMPILOT_DEMO_MODE", not IS_PRODUCTION)
ENABLE_SIMULATOR = _env_bool("FORMPILOT_ENABLE_SIMULATOR", DEMO_MODE)
PRACTICE_PORTAL_URL = os.getenv(
    "FORMPILOT_PRACTICE_PORTAL_URL",
    "https://gov-portal-simulator.vercel.app" if IS_PRODUCTION else "http://127.0.0.1:8000/gov-portal-demo",
).strip()

DATA_DIR = Path(os.getenv("FORMPILOT_DATA_DIR", ROOT_DIR / "data")).resolve()
UPLOADS_DIR = Path(os.getenv("FORMPILOT_UPLOADS_DIR", ROOT_DIR / "uploads")).resolve()
RUNS_DIR = Path(os.getenv("FORMPILOT_RUNS_DIR", DATA_DIR / "runs")).resolve()
# Sealed document vault (Aadhaar scans, photos, signatures).  Never served
# statically; every read goes through the API and is decrypted in memory.
DOCUMENTS_DIR = Path(os.getenv("FORMPILOT_DOCUMENTS_DIR", DATA_DIR / "documents")).resolve()

VAULT_FILE = DATA_DIR / "candidate_vault.json"
ENGINE_CONFIG_FILE = DATA_DIR / "engine_config.json"

# FormPilot app accounts.  Each account owns a private workspace under
# ACCOUNTS_DIR: its own vault, sealed documents, run journals and live session.
# Accounts are available in every mode; requiring them is what differs.
ACCOUNTS_DIR = Path(os.getenv("FORMPILOT_ACCOUNTS_DIR", DATA_DIR / "accounts")).resolve()
ACCOUNTS_ENABLED = _env_bool("FORMPILOT_ACCOUNTS", True)
ACCOUNTS_REQUIRED = _env_bool("FORMPILOT_ACCOUNTS_REQUIRED", False)
SESSION_DAYS = max(1, min(int(os.getenv("FORMPILOT_SESSION_DAYS", "90")), 365))

# Brute-force and signup-flood limits, per client IP and per process.
RATE_LIMIT_ENABLED = _env_bool("FORMPILOT_RATE_LIMIT", True)
LOGIN_RATE_LIMIT = max(1, int(os.getenv("FORMPILOT_LOGIN_RATE_LIMIT", "10")))
LOGIN_RATE_WINDOW_SECONDS = max(10, int(os.getenv("FORMPILOT_LOGIN_RATE_WINDOW_SECONDS", "300")))
SIGNUP_RATE_LIMIT = max(1, int(os.getenv("FORMPILOT_SIGNUP_RATE_LIMIT", "5")))
SIGNUP_RATE_WINDOW_SECONDS = max(60, int(os.getenv("FORMPILOT_SIGNUP_RATE_WINDOW_SECONDS", "3600")))

# Optional shared-secret gate for the API/WebSocket.  When empty the app is a
# local-only demo and must be bound to 127.0.0.1.
AUTH_TOKEN = os.getenv("FORMPILOT_AUTH_TOKEN", "").strip()
AUTH_REQUIRED = bool(AUTH_TOKEN)
MASK_PII = _env_bool("FORMPILOT_MASK_PII", False)

# Optional AES-256-GCM key (base64, 32 bytes) for the vault at rest.
VAULT_ENCRYPTION_KEY = os.getenv("FORMPILOT_VAULT_KEY", "").strip()

# Google OAuth / Sign-In for Web
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", os.getenv("FORMPILOT_GOOGLE_CLIENT_ID", "")).strip()


# TinyFish
TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY", "").strip()
TINYFISH_MODE = os.getenv("TINYFISH_MODE", "auto").strip().lower()
TINYFISH_SEARCH_URL = os.getenv("TINYFISH_SEARCH_URL", "https://api.search.tinyfish.ai").rstrip("/")
TINYFISH_BROWSER_URL = os.getenv("TINYFISH_BROWSER_URL", "https://api.browser.tinyfish.ai").rstrip("/")
TINYFISH_FETCH_URL = os.getenv("TINYFISH_FETCH_URL", "https://api.fetch.tinyfish.ai").rstrip("/")
TINYFISH_AGENT_URL = os.getenv("TINYFISH_AGENT_URL", "https://agent.tinyfish.ai/v1").rstrip("/")
TINYFISH_PROXY_COUNTRY = os.getenv("TINYFISH_PROXY_COUNTRY", "IN").strip().upper()
TINYFISH_TIMEOUT_SECONDS = int(os.getenv("TINYFISH_TIMEOUT_SECONDS", "90"))

# Candidate assistant model. Any OpenAI-compatible endpoint works; a local
# server (for example Ollama at http://127.0.0.1:11434/v1) needs no key.
LLM_API_KEY = os.getenv("FORMPILOT_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
LLM_BASE_URL = os.getenv("FORMPILOT_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.getenv("FORMPILOT_LLM_MODEL", "gpt-4o-mini").strip()
LLM_TIMEOUT_SECONDS = int(os.getenv("FORMPILOT_LLM_TIMEOUT_SECONDS", "45"))
LLM_MAX_HISTORY = int(os.getenv("FORMPILOT_LLM_MAX_HISTORY", "16"))

# OTP relay. The default topic is intentionally demo-only; deployments should
# set FORMPILOT_NTFY_TOPIC to a private, unguessable topic.
NTFY_TOPIC = os.getenv("FORMPILOT_NTFY_TOPIC", "formpilot_demo_otp").strip()
NTFY_RANDOMIZE_TOPIC = _env_bool("FORMPILOT_NTFY_RANDOMIZE", False)
OTP_TTL_SECONDS = int(os.getenv("FORMPILOT_OTP_TTL_SECONDS", "600"))
DEMO_OTP = os.getenv("FORMPILOT_DEMO_OTP", "492015").strip()

# CORS.  Comma-separated list; defaults are safe for local development.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FORMPILOT_CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

# Optional fields with no saved value stay blank instead of opening a
# checkpoint.  A two-token name has no middle name; a guardian is often absent.
# Set this to true only when every optional field must be asked about.
ASK_OPTIONAL_FIELDS = _env_bool("FORMPILOT_ASK_OPTIONAL_FIELDS", False)
# Human gate timeout.  A gate that never resolves is a support incident, but a
# real person may need many minutes.  Ten-minute pauses must not expire a gate.
GATE_TIMEOUT_SECONDS = int(os.getenv("FORMPILOT_GATE_TIMEOUT_SECONDS", "1800"))
# The run clock pauses while a gate is open.  These are the budgets on active
# work and on absolute wall time; the wall ceiling still applies to a paused run.
RUN_CEILING_SECONDS = int(os.getenv("FORMPILOT_RUN_CEILING_SECONDS", "1800"))
RUN_WALL_CEILING_SECONDS = int(os.getenv("FORMPILOT_RUN_WALL_CEILING_SECONDS", "7200"))
SCREENSHOT_MIN_INTERVAL_MS = int(os.getenv("FORMPILOT_SCREENSHOT_INTERVAL_MS", "700"))
# Known-path replay.  When a page has been completed successfully before and
# every field verifies, skip the manual section-approval gate.  Human-only
# checkpoints (CAPTCHA, OTP, live photo, payment, declarations, final submit)
# are never auto-approved.  Set to false for a review-every-section workflow.
AUTOPILOT_KNOWN_PATHS = _env_bool("FORMPILOT_AUTOPILOT_KNOWN_PATHS", True)
# Section review is a convenience checkpoint, not a human-only action.  When
# every field verified and the page has no CAPTCHA/OTP/photo/payment/final
# declaration, an autonomous run may continue without a review click.  Set to
# false to review every section manually.
AUTOPILOT_SECTIONS = _env_bool("FORMPILOT_AUTOPILOT_SECTIONS", True)
# "I have read the instructions" acknowledgements are not final declarations.
# When this is on, an autonomous run may tick them after reading the portal's
# instruction page.  A declaration about the truth of the submitted data is
# still handed to the human.
AUTOPILOT_INSTRUCTION_CONSENT = _env_bool(
    "FORMPILOT_AUTOPILOT_INSTRUCTION_CONSENT", True
)
# Stall detection.  The low threshold only records evidence; the high
# threshold stops the run and asks the human.
STALL_REPEAT_THRESHOLD = int(os.getenv("FORMPILOT_STALL_REPEAT_THRESHOLD", "3"))
STALL_THRESHOLD = int(os.getenv("FORMPILOT_STALL_THRESHOLD", "6"))
STALL_MIN_SHADOW_SECONDS = float(os.getenv("FORMPILOT_STALL_MIN_SHADOW_SECONDS", "15"))
STALL_MIN_SECONDS = float(os.getenv("FORMPILOT_STALL_MIN_SECONDS", "45"))
STALL_SHADOW = _env_bool("FORMPILOT_STALL_SHADOW", True)
# Optional price table for cost metering, in USD per million tokens.  Zero
# means "do not estimate money"; token counts are always recorded.
LLM_PRICE_INPUT_PER_MTOK = float(os.getenv("FORMPILOT_LLM_PRICE_INPUT_PER_MTOK", "0"))
LLM_PRICE_OUTPUT_PER_MTOK = float(os.getenv("FORMPILOT_LLM_PRICE_OUTPUT_PER_MTOK", "0"))

# Demo-only by default; production deployments must opt in explicitly.
ALLOW_DEMO_BACKDOORS = _env_bool("FORMPILOT_ALLOW_DEMO_BACKDOORS", DEMO_MODE)


def ensure_directories() -> None:
    for directory in (DATA_DIR, UPLOADS_DIR, RUNS_DIR, DOCUMENTS_DIR, ACCOUNTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def new_session_token() -> str:
    """Used by the local demo to bind a browser tab to the API process."""
    return secrets.token_urlsafe(24)
