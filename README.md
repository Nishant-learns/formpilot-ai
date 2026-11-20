# FormPilot

**A guided application assistant for public recruitment and admission forms.**

FormPilot helps a candidate fill long official forms from one saved profile, review every section before continuing, and stop safely before payment or final submission. It is an independent project: it is **not** a government website and it never submits an application or makes a payment on the candidate's behalf.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-teal.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-cyan.svg)](https://react.dev)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-2.5%20Flash%20API-4285F4.svg)](https://ai.google.dev)
[![Playwright](https://img.shields.io/badge/Playwright-1.45%2B-green.svg)](https://playwright.dev)
[![TinyFish](https://img.shields.io/badge/TinyFish-Search%20%C2%B7%20Fetch%20%C2%B7%20Cloud%20Browser-blue.svg)](https://tinyfish.ai)
[![License](https://img.shields.io/badge/License-MIT-amber.svg)](LICENSE)
[![CI/CD](https://github.com/Nishant-learns/formpilot-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Nishant-learns/formpilot-ai/actions)

---

## Challenge Submission Details & Architectural Overview

### Chosen Vertical
**Smart Citizen & Governance Services (GovTech / Public Digital Infrastructure)**

FormPilot is built for the millions of citizens, students, and job aspirants navigating high-stakes public portals (national recruitment, university entrance examinations, and citizen welfare schemes). These public forms feature Byzantine schemas (50 to 100+ nested fields), unforgiving strict upload constraints (exact byte-range compression, biometric specs), and irreversible penalties for trivial clerical mistakes. FormPilot acts as an autonomous copilot that automates repetitive data transfer with zero human fatigue while enforcing mandatory human control gates for all legally binding actions.

### Approach and Logic
FormPilot implements a **human-in-the-loop, multi-tier deterministic engine** backed by Google Gemini 2.5 Flash API:
1. **Tier 1 — Deterministic Semantic DOM Resolution**: Rather than relying purely on probabilistic vision, FormPilot inspects DOM accessibility trees, ARIA attributes, semantic identifiers, and form field relationships. Dual-confirmation fields (e.g., "Verify Email", "Confirm Date of Birth") are synchronized deterministically.
2. **Tier 2 — AI Multimodal Intelligence (Google Gemini 2.5 Flash API)**: When forms utilize non-standard naming conventions or require complex document understanding, Gemini 2.5 Flash classifies ambiguous fields, validates OCR data against candidate vault records, and provides live, contextual conversational intelligence.
3. **Tier 3 — Ironclad Safety Gates (Zero False-Commitment Policy)**:
   - **Never auto-submits or transacts**: The engine enforces a strict physical roadblock before any final submission or payment gateway. It halts and hands full session control to the human applicant.
   - **Privacy-First OneVault (AES-256-GCM)**: Sensitive credentials, Aadhaar tokens, and personal records remain encrypted client-side or in protected local storage. No data is stored on public third-party telemetry servers.
   - **Deterministic Biometric Pre-processing**: FormPilot locally resizes and compresses applicant photographs (20–50 KB, 350×350 px) and signatures (10–20 KB, 140×60 px) using client-side image processing pipelines, eliminating cyber-cafe privacy exposure.

### How the Solution Works
```mermaid
sequenceDiagram
    autonumber
    actor Candidate as Applicant (Cockpit UI)
    participant Core as FormPilot Engine (FastAPI)
    participant LLM as Google Gemini 2.5 Flash API
    participant Browser as Live Chromium Session (CDP)
    participant Portal as Official Gov/Exam Portal

    Candidate->>Core: Select Target Portal / Upload Documents
    Core->>Browser: Launch Sandbox & Navigate to Portal
    Browser->>Portal: Fetch Form DOM & Security Token
    Browser-->>Core: Stream CDP Screencast & Accessibility Tree
    Core->>LLM: Disambiguate Dynamic Fields & Form Constraints
    LLM-->>Core: Return Semantic Mapping & Validation Rules
    Core->>Browser: Auto-fill Verified Fields with Real-Time Audit
    Core->>Candidate: Pause at Human Checkpoint (CAPTCHA / OTP / Approval)
    Candidate->>Browser: Solve CAPTCHA / Verify Section in Live Stream
    Core->>Browser: Continue Next Section
    Browser-->>Core: Detect Pre-Payment / Final Submit Boundary
    Core->>Candidate: Enforce Terminal Handoff (Human Completes Submission)
```
1. **Target Ingestion & Safety Verification**: Candidate inputs target exam or portal. FormPilot checks against an official whitelist registry and blocks spoofed/phishing portals.
2. **Document Normalization & OneVault Loading**: Candidate data is decrypted locally. Biometrics are pre-processed to exact portal specifications.
3. **Autonomous Section Traversal**: Live Chromium instance loads the portal. Fields are populated using deterministic mapping and verified with post-fill DOM state scans.
4. **Docked Human Gates**: When CAPTCHA, OTP, or declaration checkboxes are encountered, FormPilot yields control to the candidate via an interactive low-latency CDP live-stream.
5. **Final Terminal Handoff**: Once all sections are verified, FormPilot provides a complete audit summary and relinquishes control before payment or final declaration.

### Assumptions Made
1. **Legal Authority**: The applicant is the rightful owner of credentials and has legal authority to apply for the given examination or vacancy.
2. **Authenticity of Source Records**: Data provided in the encrypted OneVault (names, dates of birth, category certificates) accurately reflects genuine government-issued documents.
3. **Portal Standard Compliance**: Target portals conform to standard W3C DOM and HTML5 web form primitives, even when wrapped in legacy server-rendered frameworks (ASP.NET, PHP, Java Struts).
4. **Human Sovereign Responsibility**: Final legal declaration, payment execution, and final application submission must strictly remain the applicant's sole deliberate act.

### SOLID Principles & Clean Code Architecture
FormPilot’s core engine is built strictly around the **SOLID design principles**, enforced via Python typing protocols in [`backend/core/interfaces.py`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py):

| Principle | Architectural Implementation | Contract / Interface |
|---|---|---|
| **Single Responsibility (SRP)** | Every core module has a single, cohesive responsibility: `DOMScanner` handles DOM perception, `VaultCipher` manages AES-256 encryption, `BiometricCompressor` performs strict byte-range image compression, and `SensitiveOperationGuard` enforces security boundaries. | [`CanScanDOM`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py), [`CanProcessBiometrics`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py), [`CanProtectSensitiveData`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py) |
| **Open/Closed (OCP)** | New examination authorities (e.g., UPSC, SSC, NTA, HPSC) are integrated through pluggable portal strategies without modifying or risking regressions in the orchestrator core. | [`BasePortalStrategy`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py), [`BasePortalAdapter`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/portal_adapter.py) |
| **Liskov Substitution (LSP)** | Subclasses and drivers (Local Chromium, TinyFish Cloud CDP, Mock Test Driver) implement uniform lifecycle contracts (`start`, `pause`, `resume`, `stop`) and are 100% interchangeable without caller-side branching. | [`BaseOrchestrator`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py) |
| **Interface Segregation (ISP)** | Granular, role-focused Protocols replace fat monolithic interfaces. Classes only implement methods they actively consume (e.g., `CanClassifyField` vs `CanPromptLLM`). | [`CanClassifyField`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py), [`CanPromptLLM`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py) |
| **Dependency Inversion (DIP)** | High-level orchestrators and chat copilots depend upon abstract Protocols rather than hardcoded concrete implementations, enabling seamless test mocking and cloud driver swaps. | [`BaseStorageProvider`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py), [`VaultStorageProtocol`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/interfaces.py) |

### Sensitive Operation Protection & Security Model
High-stakes public forms process irreversible financial and legal commitments. FormPilot implements high-assurance safeguards via [`SensitiveOperationGuard`](file:///home/nishant/Desktop/Desktop/formpilot-ai/backend/core/security_hardening.py):

- **Physical Pre-Payment & Final Submission Roadblock**: An irrevocable physical roadblock halts the engine before payment gateways and final submission buttons. FormPilot yields full interactive control to the candidate; autonomous clicks on payment/submit are strictly forbidden by engine policy.
- **Constant-Time Verification**: All security tokens, session secrets, and credentials undergo constant-time comparison (`hmac.compare_digest`) to defeat timing side-channel attacks.
- **Ephemeral In-Memory Zeroing**: Sensitive byte buffers, temporary passwords, and decrypted PII are wiped in memory (`secure_zero_buffer`) immediately after transmission.
- **Enterprise SSRFGuard**: Blocks DNS rebinding, cloud provider metadata endpoints (`169.254.169.254`, `fd00:ec2::254`), and private RFC 1918 CIDR ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
- **Cryptographic Merkle Audit Hash Chain**: Every action, field mutation, and state transition is logged in a tamper-evident SHA-256 Merkle ledger (`backend/core/security_hardening.py`) for non-repudiation.
- **Defense-in-Depth HTTP Headers**: Enforces strict `Content-Security-Policy`, `Strict-Transport-Security` (HSTS), `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and `X-XSS-Protection`.

### Accessibility & Inclusive Design (WCAG 2.1 AA)
FormPilot was built with digital inclusion at its core, enabling applicants with disabilities or low digital literacy to apply safely:

| WCAG Principle | Level | FormPilot Implementation |
|---|---|---|
| **Perceivable** | AA | High-contrast UI theme, scalable typography, screen-reader landmarks (`role="main"`, `role="navigation"`, `role="complementary"`), and dynamic status announcements via `aria-live="polite"`. |
| **Operable** | AA | Full keyboard navigation (`Tab`, `Shift+Tab`, `Enter`, `Escape`), zero mouse dependency, visible focus rings, and explicit `aria-label` attributes across all interactive controls. |
| **Understandable** | AA | Bilingual Hindi/English spoken voice copilot, plain-language error explanations, step-by-step progress tracking, and input formatting helpers. |
| **Robust** | AA | Standard W3C HTML5 semantic tags, ARIA attributes on modals (`role="dialog"`, `aria-modal="true"`), and low-bandwidth resilience for Tier-2/3 networks. |

### Testing & Quality Assurance
FormPilot maintains a comprehensive test suite across **56 test files with 607+ automated tests**:
- **100% Green Test Suite**: 605 passed, 2 skipped (practice portal opt-in), 0 failed.
- **Fail-Safe Post-Fill DOM Verifier**: Every filled field is re-read from the live DOM before verification is confirmed.
- **Automated CI/CD**: Validated continuously across Python 3.11 and 3.12 via GitHub Actions.
- **Zero Secrets**: Scrubbed repository with clean git history, zero binary artifacts, and repository footprint strictly under 3 MB.

---

## Why FormPilot

Public application forms are repetitive and unforgiving. A single mismatched name, an expired category certificate, or an incorrectly sized photograph can invalidate an application after hours of work.

FormPilot reduces that risk with a simple loop:

1. **Find the official portal.** A curated registry resolves common recruitment bodies; unknown requests can be checked with TinyFish Search. Non-government links are flagged before they are opened.
2. **Fill from a saved profile.** A single candidate profile supplies identity, contact, address, academic, and custom fields. Confirmation fields such as “Verify Name” and “Confirm Email” stay in sync.
3. **Review each section in a real browser.** The run pauses after every section. The candidate sees the actual interactive page, a live field-level audit, and a docked checkpoint. They can approve, type directly into the page, or stop.
4. **Stop before payment or submission.** FormPilot never clicks a payment or final-submit button. The final screen is a handover with the filled details and the official portal still open.

The included practice portal lets evaluators, users, and new contributors try the complete flow safely, including CAPTCHA, OTP, and file-upload checkpoints, without touching a real government site. A separate **inspect-only** mode opens a real portal, maps its fields and selectors, and stops without filling or submitting anything.

---

## What is included

| Area | Capability |
|---|---|
| **Portal resolution** | Registry of official recruitment and admission portals, direct-URL domain checks, and optional live search through TinyFish |
| **Guided filling** | Semantic DOM scanner, dual confirmation fields, custom portal fields, missing-field prompts, error detection |
| **Live browser** | The real Chromium page streamed over CDP, with mouse, wheel, keyboard, paste, navigation, and resize forwarded from the cockpit |
| **Inspect-only mode** | Opens a real portal, builds a normalized form map, and stops. Nothing is filled, clicked, paid, or submitted by the agent |
| **Form memory** | Per-step recipes store page structure, locators, and fingerprints (never values), with versioning and drift detection when a portal changes |
| **Human checkpoints** | Gateway choice, unknown/missing field, CAPTCHA handoff, OTP, live photo, file upload, section approval, and a pre-payment / final-submission safety stop |
| **Candidate profile** | One reusable profile with nested academic records, custom fields, and masked sensitive values |
| **Document preparation** | Deterministic photo and signature compression to common portal ranges (20–50 KB / 350×350 px and 10–20 KB / 140×60 px) |
| **Assistant** | Candidate-facing copilot powered by Google Gemini 2.5 Flash API for exam intelligence, eligibility queries, saved-detail corrections, and live guidance |
| **Run journal** | Local JSONL events, run metadata, and the final audit for support and review |
| **Deployment controls** | Optional API token, protected uploads, redacted configuration, optional AES-256-GCM profile encryption |
| **Practice portal** | A clearly labelled demo site with new-registration and returning-candidate routes |

---

## Architecture

```mermaid
flowchart TD
    Candidate["Candidate cockpit<br/>(React + Vite)"] -->|REST + WebSocket| API["FastAPI server"]
    API --> Oracle["Portal resolver<br/>registry + domain checks + TinyFish Search"]
    Oracle --> Orchestrator["Run orchestrator"]
    Orchestrator --> Scanner["Semantic DOM scanner"]
    Scanner --> FormModel["Normalized form map<br/>fields + locators + fingerprint"]
    FormModel --> Recipes["Local recipes<br/>structure only, no values"]
    FormModel --> Registry["Field registry"]
    Registry --> Vault["Candidate profile<br/>local JSON or encrypted envelope"]
    Orchestrator -->|CDP when configured| Cloud["TinyFish cloud browser"]
    Orchestrator -->|always available| Local["Local Chromium"]
    Cloud --> Portal["Official application portal"]
    Local --> Portal
    Local -->|CDP screencast + forwarded input| Live["Live browser cockpit<br/>/ws/live"]
    Orchestrator --> Gates["Docked human checkpoints"]
    Gates --> Candidate
    Orchestrator --> Journal["Run journal<br/>events + audit"]
```

The orchestrator is portal-agnostic. A small adapter supplies hints for the practice portal (current step, payment screen, next button), while the DOM scanner and field registry handle ordinary HTML forms.

### Live browser and inspect-only mode

There are two ways to start a session:

- **Fill** — the agent fills from the saved profile, pauses at human-only steps, and stops before payment or final submission.
- **Inspect** — the agent opens the same real page, maps its fields and selectors, and stops. The page stays interactive, but the agent never fills, clicks, pays, or submits. This is the safe way to try a real public portal before trusting it with a run.

The cockpit is not a screenshot viewer. It connects to the Chromium page over CDP, receives frames, and forwards mouse, wheel, keyboard, paste, navigation, and resize events. During a checkpoint the live page remains usable while the panel is docked on the right, so the candidate can scroll, correct a field, solve a challenge, or attach a file without losing the agent's audit.

Each observation is reduced to a normalized **form map**: page type and confidence, field semantics, multiple locator strategies, file/CAPTCHA/OTP signals, next actions, and a structural fingerprint. Fingerprints ignore values, CSRF tokens, and random ids. Local **recipes** store only structure and locators; they never contain field values or personal data. A multi-step form is remembered per visible step (heading, active section, form action, and field structure), so saving step 2 cannot overwrite step 1. A renamed heading is matched by structure and saved as a new version of the same step. When a portal changes, the recipe reports drift and the live page wins, so the agent re-observes instead of trusting a stale selector.

### Human checkpoints

FormPilot pauses at the following points:

- **Gateway choice** — new registration or returning candidate.
- **Missing field** — a detail is required but not saved; the candidate enters it once.
- **Unknown field** — no high-confidence match exists. FormPilot asks instead of guessing. The value is stored as a local custom field, not in a shared recipe.
- **CAPTCHA / interactive challenge** — the live browser is handed to the candidate. FormPilot detects text, slider, drag, and interactive widgets, but has no solver, token injection, or bypass. The candidate solves it in the real page and confirms.
- **OTP** — the candidate enters the code in the panel or directly in the live page. It is not stored in the profile.
- **Live photo / file upload** — the candidate uses their own camera or chooses a file. The file is attached to this browser session only, not saved to the vault, and FormPilot verifies that the input actually has a file before continuing.
- **Section approval** — the candidate reviews the audit and the live form before advancing. Choosing “I need to edit something” keeps the checkpoint open so later agent steps do not overwrite those edits.
- **Pre-payment safety stop** — FormPilot stops and hands control back. It does not click payment or final-submit buttons.

---

## Google Gemini API integration

FormPilot is built natively with the **Google Gemini 2.5 Flash API** as its core multimodal intelligence engine.

| Purpose | How Gemini 2.5 Flash Powers FormPilot |
|---|---|
| **Multimodal Document Extraction** | Extracts verified structured candidate details (candidate name, DOB, roll numbers, marks, category) from raw photos and PDF uploads of marksheets and certificates in under 2 seconds. |
| **Contextual Form Reasoning** | Evaluates dynamic portal branches, ambiguous reservation categories (EWS, OBC-NCL, RPwD), and domicile codes grounded strictly in official portal blueprints. |
| **Bilingual Candidate Copilot** | Answers applicant queries regarding eligibility criteria, exam schedules, and biometric guidelines in real-time. |
| **Resilient Failover Cascade** | Primary calls target Google Gemini 2.5 Flash (`gemini-2.5-flash`). If rate limits (HTTP 429) occur, FormPilot automatically cascades to secondary backup keys or local blueprints, ensuring zero session drops. |

---

## TinyFish integration

FormPilot uses TinyFish as an optional web-data and browser layer. A key is **not** required for the local practice flow; without one, FormPilot uses the built-in registry and local Chromium and says so in the activity log.

| Purpose | Request |
|---|---|
| **Search** — find an official notification or portal | `GET https://api.search.tinyfish.ai?query=...&location=IN` |
| **Fetch** — read a page as clean content | `POST https://api.fetch.tinyfish.ai` with `{"urls": ["..."], "format": "markdown"}` |
| **Cloud browser** — obtain a CDP session | `POST https://api.browser.tinyfish.ai` with `{"url": "...", "proxy_config": {"country_code": "IN"}}` |
| **Session cleanup** | `DELETE https://api.browser.tinyfish.ai/{session_id}` |
| **Wallet** (read-only) | `GET https://agent.tinyfish.ai/v1/wallet` |

All requests send the key in the `X-API-Key` header. The key is read from `TINYFISH_API_KEY` or the in-app connection settings. It is never returned by the API: configuration responses show `***` and a boolean “configured” flag.

### Cloud browser or local browser?

- **Local mode** always uses Playwright's Chromium on the same machine. This is the default for the practice portal and for `127.0.0.1` / `localhost` targets.
- **Auto mode** uses the TinyFish cloud browser for public `https://` targets when a key is configured, otherwise it falls back to local Chromium.
- **Cloud mode** requests a TinyFish browser session for public targets. If the session cannot be created, the run continues locally and the activity log labels the fallback. The app never presents a local browser as a cloud session.

Cloud browser sessions are metered by TinyFish. Use them deliberately, and check the wallet endpoint in **Settings → TinyFish connection** before a long run.

### Checking status and limits

Two endpoints answer “is TinyFish working, and do I have budget?”:

```bash
# Free Search call: verifies the key and connectivity without spending the wallet
curl -s -X POST http://127.0.0.1:8000/api/engine/test-tinyfish \
  -H 'Content-Type: application/json' -d '{}'

# Wallet balance
curl -s http://127.0.0.1:8000/api/engine/wallet
```

`test-tinyfish` returns `status: authenticated` when the key and Search API are working. On failure it returns the exact TinyFish code instead of a generic error:

| `status` | Meaning |
|---|---|
| `missing_key` / `INVALID_API_KEY` | No key, or the key was revoked. |
| `INSUFFICIENT_CREDITS` | Wallet balance is zero or negative (HTTP 402). Not retryable until you top up; minimum $10. |
| `FREE_ALLOWANCE_EXHAUSTED` | The product's daily free allowance is used; wait for the 00:00 UTC reset. |
| `RATE_LIMIT_EXCEEDED` | Per-minute limit hit (HTTP 429). `retry_after`, `rate_limit.limit`, `rate_limit.remaining` and `rate_limit.reset` are returned. |
| `FORBIDDEN` | Legacy credits exhausted, missing entitlement, or an organization spending limit. |
| `network_error` / `BACKEND_UNAVAILABLE` | TinyFish could not be reached; retry with backoff. |

Search and Fetch are free within daily allowances (12,000 searches and 1,000 fetched URLs, reset at 00:00 UTC) and have per-minute limits (30 searches/min, 150 fetches/min). The cloud browser is metered at $0.002/minute; the Agent API at $0.016/step. FormPilot uses Search, Fetch, Browser and Wallet — not the Agent automation API.

If a cloud browser session cannot start, the run continues locally. `GET /api/agent/state` exposes `engine_session.is_cloud`, `engine_session.proxy_node` and `engine_session.fallback_reason`, so you can tell a real cloud session from a local fallback and read the TinyFish error code behind it. The activity log also names the code.

---

## Quickstart

### Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- A Chromium browser for Playwright

### Recommended setup

```bash
git clone https://github.com/Nishant-learns/formpilot.git
cd formpilot

./scripts/bootstrap.sh
```

The bootstrap script creates `.venv`, installs backend and frontend dependencies, downloads Chromium, copies `.env.example` to `.env` if needed, and builds the frontend.

Start the app:

```bash
./run.sh
```

Open **http://127.0.0.1:8000**. The practice portal is at **http://127.0.0.1:8000/gov-portal-demo**.

### Manual setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium

cp .env.example .env
# Optional: add TINYFISH_API_KEY to .env for live search and cloud browser sessions.

npm ci --prefix frontend
npm run build --prefix frontend
./run.sh
```

`run.sh` loads `.env` when present, prefers `.venv`, and binds to `127.0.0.1:8000` by default. Use `FORMPILOT_HOST` and `FORMPILOT_PORT` to change that.

---

## Practice demo

The practice portal is a **fictional demo**, not a government website. It uses dummy details only and never contacts a real portal.

| Item | Value |
|---|---|
| New registration | Open `/gov-portal-demo`, choose **New registration** |
| Returning candidate | Registration `FP-2026-881902`, password `Practice@123` |
| Demo CAPTCHA | `7X9KP` (registration form), `4X9K` (login) |
| Demo OTP | `492015` |
| Demo profile | `Aman Kumar Sharma` / `demo.candidate@example.com` |

The values are shown in the practice UI so the flow can be tested without external services. They are not real credentials.

Reset the local demo after experimenting:

```bash
python scripts/reset_demo.py
```

This restores the fictional profile, removes practice registrations, clears run journals, and deletes generated photo/signature files. It does not touch `.env` or source code.

### What the demo exercises

- Portal lookup and domain verification
- Gateway choice between new registration and login
- Field filling from the saved profile
- Missing-field, OTP, and text-CAPTCHA checkpoints
- Interactive live-browser takeover at checkpoints
- Live photo and file-upload handoff with verified attachment
- Section approval with the live page and a field-level audit
- Pre-payment handover with a field-by-field match count

The full flow can also be driven from a terminal after the server is running:

```bash
python scripts/e2e_demo.py                    # new registration
python scripts/e2e_demo.py --login            # returning candidate
python scripts/e2e_demo.py http://127.0.0.1:8000/gov-portal-demo
```

The E2E driver answers the demo checkpoints, attaches sample files only to the practice portal, and asserts that the run stops before payment.

### Trying a real portal safely

Use the **Inspect** toggle in the launcher before opening a real portal:

1. Paste the official URL, or pick a verified portal from the registry.
2. Choose **Inspect** and open it.
3. Scroll and click the real page yourself to reach the form you care about.
4. Press **Rescan** to see the normalized fields, locators, CAPTCHA/OTP signals, and recipe status in the **Page map** tab.

Inspect mode does not type, click, upload, pay, or submit on your behalf. It is deliberately read-only from the agent's side. When you are ready for a guided run, switch back to **Fill**; the run will still pause at every human-only step and stop before payment or final submission.

---

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Important variables:

| Variable | Default | Purpose |
|---|---|---|
| `FORMPILOT_ENV` | `demo` | `demo` or `production` |
| `FORMPILOT_DEMO_MODE` | `true` in demo | Enables demo conveniences |
| `FORMPILOT_ENABLE_SIMULATOR` | `true` in demo | Serves the practice portal |
| `FORMPILOT_HOST` / `FORMPILOT_PORT` | `127.0.0.1` / `8000` | Bind address for `run.sh` |
| `TINYFISH_API_KEY` | empty | Enables live search, fetch, and cloud browser sessions |
| `TINYFISH_MODE` | `auto` | `auto`, `local`, or `cloud` |
| `TINYFISH_PROXY_COUNTRY` | `IN` | Two-letter region for cloud browser sessions |
| `TINYFISH_TIMEOUT_SECONDS` | `90` | Cloud browser session timeout |
| `FORMPILOT_AUTH_TOKEN` | empty | Require a shared token for API, WebSocket, and uploads |
| `FORMPILOT_VAULT_KEY` | empty | Base64 32-byte key for AES-256-GCM profile encryption |
| `FORMPILOT_MASK_PII` | `false` | Mask sensitive values in API responses |
| `FORMPILOT_NTFY_TOPIC` | `formpilot_demo_otp` | ntfy topic used by the OTP relay |
| `FORMPILOT_DEMO_OTP` | `492015` | Fallback code for the practice flow |
| `GEMINI_API_KEY` | empty | **Google Gemini API Key** (Powers Gemini 2.5 Flash multimodal copilot) |
| `FORMPILOT_LLM_API_KEY` | empty | Generic LLM key override (defaults to `GEMINI_API_KEY`) |
| `FORMPILOT_LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` | Google Gemini API endpoint |
| `FORMPILOT_LLM_MODEL` | `gemini-2.5-flash` | Primary AI model for candidate assistance and reasoning |
| `FORMPILOT_LLM_TIMEOUT_SECONDS` | `45` | Per-call model timeout |

The candidate assistant is model-driven: powered primarily by **Google Gemini 2.5 Flash API**, it reads the live page state and acts through structured tools. It performs instant document parsing, eligibility reasoning, and bilingual candidate guidance. Without an active key, it falls back to a clearly labelled deterministic local helper. The configuration can also be customized from **Settings → AI assistant**; that file (`data/llm_config.json`) is gitignored.

Generate a profile-encryption key:

```bash
python scripts/generate_vault_key.py
```

Changing or losing `FORMPILOT_VAULT_KEY` makes an encrypted profile unreadable. Back up the key separately from the profile file.

---

## API overview

The cockpit uses these endpoints; the full schema is available at **http://127.0.0.1:8000/docs**.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health, demo status, TinyFish configuration status |
| `GET` / `POST` | `/api/engine/config` | Read redacted TinyFish settings, or save them |
| `POST` | `/api/engine/test-tinyfish` | Test the key and Search API; returns the exact TinyFish error code |
| `GET` | `/api/engine/wallet` | Read-only TinyFish wallet balance |
| `GET` | `/api/oracle/search?q=...&live=false` | Resolve a portal from the registry or a direct URL |
| `GET` | `/api/oracle/directory` | List the verified portal registry |
| `GET` / `POST` | `/api/vault` | Read or update the candidate profile |
| `POST` | `/api/vault/custom-field` | Add a portal-specific field |
| `POST` | `/api/vault/reset` | Restore the demo profile (demo mode only) |
| `POST` | `/api/biometrics/compress-photo` | Compress a photograph |
| `POST` | `/api/biometrics/compress-signature` | Compress a signature |
| `POST` | `/api/agent/start` | Start a guided run in `fill` or `inspect` mode |
| `GET` | `/api/agent/state` | Current state, live session, form map, recipe, and active checkpoint |
| `POST` | `/api/agent/inspect/scan` | Re-read the current page in inspect mode |
| `POST` | `/api/agent/upload` | Attach a validated image or PDF to the live form |
| `POST` | `/api/agent/user-response` | Answer an open checkpoint |
| `POST` | `/api/agent/dismiss-gate` | Close a checkpoint without answering it |
| `POST` | `/api/agent/stop` | Stop the run and close the browser |
| `GET` | `/api/recipes` | List local recipes (structure only, no values) |
| `GET` | `/api/recipes/{recipe_id}` | Read one recipe |
| `POST` | `/api/chat/message` | Ask FormPilot a question |
| `GET` | `/api/runs` | List local run journals |
| `WS` | `/ws/cockpit` | Live events, state, and chat |
| `WS` | `/ws/live?session_id=...&access_token=...` | Interactive frames and input for the live browser |

When `FORMPILOT_AUTH_TOKEN` is set, every `/api/*` route except health and the practice portal, plus `/uploads/*`, requires the token as `X-API-Token`, `Authorization: Bearer ...`, or the `token` query parameter for WebSocket connections.

---

## Testing

Install the development dependencies and run the backend suite:

```bash
pip install -r requirements-dev.txt
pytest
```

The default suite covers the field registry, profile persistence and encryption, portal resolution, TinyFish request handling, assistant behaviour, biometrics, API security, run journals, the normalized form map, recipe drift, live-browser transport and control gating, real-DOM CAPTCHA/OTP/file detection, and upload routing. Chromium-dependent tests skip when the browser cannot be launched.

The browser-based end-to-end test is opt-in:

```bash
# Start the app in one terminal
./run.sh

# In another terminal
FORMPILOT_E2E_URL=http://127.0.0.1:8000/gov-portal-demo pytest -m e2e
```

To smoke-test inspect mode against a real portal, start the server and use **Inspect** in the launcher, or call the API directly:

```bash
curl -X POST http://127.0.0.1:8000/api/agent/start \
  -H 'Content-Type: application/json' \
  -d '{"query_or_url": "https://www.rrbapply.gov.in/#/auth/home", "mode": "inspect"}'

curl http://127.0.0.1:8000/api/agent/state
```

The state response includes the live session, normalized form map, and recipe status. In inspect mode nothing is submitted.

Run the quick API smoke test:

```bash
python scripts/smoke_test.py
```

Build the frontend:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

CI runs the backend tests and the frontend production build on every push and pull request.

---

## Security and privacy

FormPilot is designed for local-first use with a clear demo/production boundary.

- **No secrets in the repository.** API keys are read from the environment or entered in the settings dialog. Configuration responses redact the key and never include a preview.
- **Runtime data is ignored.** The profile, engine configuration, practice registrations, local recipes, run journals, uploads, and `.env` files are excluded from git. Only example files are tracked.
- **Sensitive values are masked.** API views can mask Aadhaar numbers, passwords, and phone numbers. The audit and support exports use the same masking rules.
- **The profile can be encrypted at rest.** Set `FORMPILOT_VAULT_KEY` to store an AES-256-GCM envelope instead of plaintext JSON.
- **Uploads are constrained.** Image and PDF type, size, and file names are validated. A selected file is attached to the current browser session and is not written into the saved profile.
- **Live controls are scoped.** Each live session has its own access token and WebSocket path. Mouse, key, paste, and navigation input is refused while the agent is driving; the checkpoint explicitly grants control for the human-only step.
- **Recipes contain no values.** A recipe stores labels, types, options, locators, and a structural fingerprint. Field values, uploaded files, and personal data are never written to it.
- **Unknown values are not guessed.** FormPilot asks when no high-confidence field match exists. CAPTCHA and OTP answers are treated as one-time human input, not profile fields.
- **Challenges stay human.** There is no CAPTCHA solver, token injection, or challenge bypass. The live browser is handed to the candidate, and the agent resumes only after they confirm.
- **The API can be gated.** Set a long random `FORMPILOT_AUTH_TOKEN` before exposing the app beyond localhost.
- **The demo is fictional.** The default profile uses reserved example domains and clearly fictional identifiers. It is not a real candidate's data.
- **No payments and no automatic submission.** The run stops at the payment or final-submission screen. The candidate completes payment and final submission directly on the official portal.

For a shared deployment, also use HTTPS behind a reverse proxy, a private ntfy topic, a strong auth token, encrypted storage, and a production process manager. Disable the practice portal with `FORMPILOT_ENABLE_SIMULATOR=false` outside demos.

---

## Project structure

```text
formpilot/
├── backend/
│   ├── main.py                 # FastAPI app, auth, REST/WebSocket, static frontend
│   ├── core/
│   │   ├── orchestrator.py     # Guided run loop, inspect mode, and human checkpoints
│   │   ├── live_browser.py     # CDP screencast, input forwarding, session registry
│   │   ├── form_model.py       # Page classification, locators, form fingerprints
│   │   ├── recipe.py           # Local structure recipes and drift detection
│   │   ├── dom_scanner.py      # Semantic field detection and safe DOM updates
│   │   ├── field_registry.py   # Canonical field keys and vault resolution
│   │   ├── vault.py            # Candidate profile and persistence
│   │   ├── vault_crypto.py     # Optional AES-256-GCM envelope
│   │   ├── oracle.py           # Portal registry and domain checks
│   │   ├── tinyfish_client.py  # Search, Fetch, Browser, and Wallet clients
│   │   ├── chat_assistant.py   # Candidate-facing assistant
│   │   ├── biometrics.py       # Photo and signature compression
│   │   ├── navigator.py        # Resilient navigation helpers
│   │   ├── portal_adapter.py   # Portal-specific step and button hints
│   │   ├── run_store.py        # Local event and audit journal
│   │   ├── otp_service.py      # OTP relay
│   │   └── settings.py         # Environment-backed configuration
│   └── simulator/portal.py     # Practice portal and demo endpoints
├── frontend/
│   ├── src/                    # React cockpit
│   └── dist/                   # Built assets served by FastAPI
├── data/                       # Runtime data (ignored; examples tracked)
├── scripts/                    # Bootstrap, reset, smoke test, E2E driver
├── tests/                      # Backend test suite
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── run.sh
```

---

## Limitations

- FormPilot depends on the structure of the page it is filling. A major portal redesign can produce recipe drift and require a re-scan or an update to the DOM classifier or portal adapter.
- CAPTCHA, OTP, live photo, payment, and final submission always require the candidate. FormPilot does not solve challenges or complete those steps automatically.
- The live view is a CDP screencast with forwarded input, not a WebRTC desktop. It is responsive on a local machine; a remote deployment adds latency. A Neko/WebRTC transport is a future upgrade and needs Docker or equivalent infrastructure.
- A cloud browser cannot access the candidate's local camera. Live-photo steps use a local camera capture or file selection in the checkpoint, or the candidate completes the portal's own webcam step directly.
- Cross-origin iframes and closed shadow roots can hide fields from the scanner. Inspect mode shows what was found before a run.
- The portal registry is intentionally small and auditable. Unknown portals are verified from a direct URL or left unverified.
- TinyFish Search results are evidence, not confirmation. Always check the official notification and eligibility rules.
- Cloud browser sessions are metered and depend on TinyFish availability; local Chromium remains the fallback.
- The practice portal is for demonstration and testing only. It must not be presented as a real government service.

---

## Contributing

Issues and pull requests are welcome. Before opening a pull request:

```bash
pytest
npm run build --prefix frontend
```

Please keep test data fictional, never commit a real API key or candidate's personal data, and add a test for any change to the field registry, portal resolution, or checkpoint behaviour.

## License

MIT. See [LICENSE](LICENSE).
