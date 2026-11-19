import React, { useMemo, useState } from 'react';
import {
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  Copy,
  Cpu,
  Database,
  ExternalLink,
  FileCode,
  FileText,
  Filter,
  Globe,
  Hash,
  Layers,
  Lock,
  Printer,
  Search,
  Shield,
  Terminal,
  Workflow,
  Zap,
} from 'lucide-react';

const CATEGORIES = [
  { id: 'all', label: 'All Sections', count: 14 },
  { id: 'languages', label: '1.0 Core Languages', count: 3 },
  { id: 'browser', label: '2.0 Browser Automation & CDP', count: 2 },
  { id: 'architecture', label: '3.0 Agentics & State Machines', count: 3 },
  { id: 'security', label: '4.0 Cryptography & Identity', count: 2 },
  { id: 'backend', label: '5.0 Web Frameworks & Protocols', count: 2 },
  { id: 'frontend', label: '6.0 Reactive UI & Tooling', count: 2 },
];

const TECHNICAL_MANUAL = [
  // ==========================================
  // SECTION 1.0: CORE LANGUAGES
  // ==========================================
  {
    id: 'python',
    sectionNumber: '1.1',
    category: 'languages',
    title: 'Python 3.12+ (AsyncIO & Structural Typing)',
    codebasePath: 'backend/core/orchestrator.py, backend/core/dom_scanner.py',
    summary:
      'The foundational systems language executing FormPilot’s autonomous decision loop, DOM classification engine, biometric pipeline, and ASGI web service.',
    whyChosen:
      'Provides first-class asynchronous non-blocking event loops, native subprocess piping to headless Chromium, rich scientific image libraries (Pillow), and strict type verification via PEP 484/585 without runtime overhead.',
    howUsed:
      'Powers FormPilotOrchestrator._run_agent. Employs asyncio.create_task for non-blocking telemetry broadcasts, asyncio.Lock for thread-safe state synchronization, and structural pattern matching to classify DOM interactive elements.',
    pitfallsSolved:
      'Traditional multi-threaded scraping engines encounter severe race conditions when browsers navigate between steps. Python\'s cooperative AsyncIO ensures single-threaded deterministic event processing where DOM scans, mutations, and verification steps happen in strict sequential order.',
    asciiDiagram: `+--------------------------------------------------------------+
|                     Python AsyncIO Event Loop                |
|                                                              |
|   +-------------------+    task    +---------------------+   |
|   | Orchestrator Loop | ---------> | Playwright CDP Host |   |
|   +-------------------+            +---------------------+   |
|             |                                 |              |
|        event stream                      binary frame        |
|             v                                 v              |
|   +-------------------+            +---------------------+   |
|   | WebSocket Manager |            | Biometric Compressor|   |
|   +-------------------+            +---------------------+   |
+--------------------------------------------------------------+`,
    codeSnippet: `# Excerpt from backend/core/orchestrator.py
async def _run_agent(self):
    while self.is_running and not self._stop_requested:
        dom = await self._scan_dom()
        if page_actions.is_consent_page(dom):
            if await self._handle_consent_page(dom):
                continue
        if self._is_external_identity_page(dom):
            if await self._identity_provider_checkpoint(dom):
                continue
        await self._fill_form(dom)
        await self._advance(dom)`,
    keyConcepts: [
      'AsyncIO Non-blocking Event Loops & Cooperative Multitasking',
      'Structural Type Annotations (PEP 484, PEP 585)',
      'Subprocess Management & Async Process Pipelines',
      'Asynchronous Locking (asyncio.Lock) & Mutex Queues',
    ],
    links: [
      { name: 'Python 3 Documentation', url: 'https://docs.python.org/3/' },
      { name: 'AsyncIO Developer Guide', url: 'https://docs.python.org/3/library/asyncio.html' },
      { name: 'PEP 484 – Type Hints Specification', url: 'https://peps.python.org/pep-0484/' },
    ],
  },
  {
    id: 'javascript',
    sectionNumber: '1.2',
    category: 'languages',
    title: 'Modern JavaScript (ES2024 & DOM Engine Injection)',
    codebasePath: 'backend/core/dom_scanner.py (INJECTION_JS)',
    summary:
      'Evaluates directly inside the target portal\'s execution context to inspect the live DOM tree, compute geometry, and dispatch synthetic events.',
    whyChosen:
      'External HTML string scrapers cannot see runtime state like CSS visibility, computed layout rects, or JavaScript-bound event listeners. Injected JavaScript executes within the portal page with full access to window, document, and window.getComputedStyle.',
    howUsed:
      'Injected via CDP into every navigated page. FormPilot\'s INJECTION_JS walks the DOM using document.createTreeWalker, measures element bounding client rects, associates <label> tags with inputs via for attributes and aria-labelledby, and serializes the interactive state into a clean JSON blueprint.',
    pitfallsSolved:
      'Government portals (specifically Indian NIC/NTA ASP.NET portals) rely on __doPostBack and synchronous page reload. Standard JavaScript assignment (el.value = "val") does not trigger validation or form state sync. FormPilot dispatches synthetic Event("input", {bubbles: true}) and Event("change", {bubbles: true}) to wake up legacy ASP.NET validation handlers.',
    asciiDiagram: `Target Portal DOM Tree
   |
   +--> TreeWalker Traversal (INJECTION_JS)
   |       |-- Filter non-visible (offsetWidth === 0, getComputedStyle)
   |       |-- Label Association (for="", aria-label, parent <label>)
   |       \\-- Checkbox/Radio Hierarchy & Group Extraction
   |
   v
Serialized JSON Page Blueprint -> Sent to Python Orchestrator`,
    codeSnippet: `// In-browser DOM Scanner snippet
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
while (walker.nextNode()) {
    const el = walker.currentNode;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    // Extract interactive attributes and dispatch events safely
}`,
    keyConcepts: [
      'Document Object Model (DOM) Tree Traversal & TreeWalker',
      'Window.getComputedStyle() Visibility & Layer Stacking Calculation',
      'Synthetic Event Dispatch (KeyboardEvent, MouseEvent, EventTarget.dispatchEvent)',
      'ASP.NET __doPostBack and Web Form lifecycle synchronization',
    ],
    links: [
      { name: 'MDN Web Docs – JavaScript Reference', url: 'https://developer.mozilla.org/en-US/docs/Web/JavaScript' },
      { name: 'MDN DOM API Specification', url: 'https://developer.mozilla.org/en-US/docs/Web/API/Document_Object_Model' },
      { name: 'W3C DOM Level 3 Events Specification', url: 'https://www.w3.org/TR/uievents/' },
    ],
  },
  {
    id: 'react',
    sectionNumber: '1.3',
    category: 'languages',
    title: 'React 19 & JSX (Declarative State & Virtual DOM)',
    codebasePath: 'frontend/src/App.jsx, frontend/src/components/',
    summary:
      'Drives FormPilot’s real-time cockpit workstation, live viewport canvas, OneVault identity manager, and cyber-bhaiya guidance interface.',
    whyChosen:
      'React 19 provides efficient concurrent reconciliation and lightweight component state without requiring external state management libraries like Redux. Real-time WebSocket patches update the UI at 60 FPS.',
    howUsed:
      'Consumes WebSocket event streams from /ws/cockpit. Coordinates modal states, live browser session streaming, and biometric preview generation using useMemo, useCallback, and useRef.',
    pitfallsSolved:
      'High-frequency WebSocket events (telemetry logs, screenshots, DOM updates) frequently cause UI lag and unnecessary re-renders. FormPilot uses unrolled ref references and memoized sub-trees to isolate log rendering from viewport canvas updates.',
    asciiDiagram: `WebSocket Stream (/ws/cockpit)
        |
        +---> events[]   -----> Cognitive Stream (Memoized List)
        +---> state      -----> State Badge & Action Bar
        +---> active_gate-----> Checkpoint Modal (HITL Intercept)
        \\---> screenshot -----> Viewport Canvas (Base64 JPEG)`,
    codeSnippet: `// React 19 WebSocket consumer pattern in App.jsx
useEffect(() => {
    const ws = new WebSocket(getWsUrl('/ws/cockpit'));
    ws.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.phase) setRunState(payload.phase);
        if (payload.active_gate) setCurrentGate(payload.active_gate);
    };
    return () => ws.close();
}, []);`,
    keyConcepts: [
      'Declarative Component State & Fiber Reconciliation',
      'React Hooks Lifecycle (useEffect, useRef, useState, useCallback)',
      'Zero-Latency WebSocket Event Streaming Updates',
      'Optimistic UI Updates & Safe Modal Portals',
    ],
    links: [
      { name: 'React Official Documentation (react.dev)', url: 'https://react.dev/' },
      { name: 'React 19 Features & Architectural Changes', url: 'https://react.dev/blog/2024/12/05/react-19' },
      { name: 'React Built-in Hooks API Reference', url: 'https://react.dev/reference/react/hooks' },
    ],
  },

  // ==========================================
  // SECTION 2.0: BROWSER AUTOMATION & CDP
  // ==========================================
  {
    id: 'playwright',
    sectionNumber: '2.1',
    category: 'browser',
    title: 'Playwright for Python (Native Chromium Driver)',
    codebasePath: 'backend/core/orchestrator.py:1630-1785, action_resolver.py',
    summary:
      'Drives local and remote Chromium instances using operating-system level native input events, frame interception, and auto-waiting.',
    whyChosen:
      'Unlike legacy Selenium or Puppeteer wrappers, Playwright communicates directly with Chromium via CDP, features built-in actionability checks (visible, enabled, stable), and handles complex cross-origin iframes effortlessly.',
    howUsed:
      'Controls browser lifecycle in orchestrator._open_browser. Launches Chromium in either local headless mode or attaches to remote cloud sessions via connect_over_cdp. Executes actions using page.locator and page.evaluate.',
    pitfallsSolved:
      'Traditional web scrapers suffer from "element not interactable" errors when elements are animating or temporarily occluded. Playwright verifies actionability automatically and FormPilot adds retry cascades with Playwright locator fallbacks.',
    asciiDiagram: `+--------------------------------------------------------------+
|              FormPilot Orchestrator Process                  |
|                             |                                |
|                   CDP Pipe / WebSocket                       |
|                             v                                |
|        +----------------------------------------+            |
|        |           Chromium Browser             |            |
|        |   Page | Runtime | Network | DOM       |            |
|        +----------------------------------------+            |
+--------------------------------------------------------------+`,
    codeSnippet: `# Launching and attaching Playwright browser
self.playwright = await async_playwright().start()
self.browser = await self.playwright.chromium.launch(headless=True)
self.context = await self.browser.new_context(
    viewport={"width": 1280, "height": 800},
    user_agent="Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0.0.0"
)
self.page = await self.context.new_page()`,
    keyConcepts: [
      'Chrome DevTools Protocol (CDP) Low-Level Session Attachment',
      'Actionability Guarantees (Element Visible, Stable, Enabled)',
      'Isolated Browser Contexts & Ephemeral Incognito Storage',
      'Synchronous Viewport Screenshot Encoding to Base64',
    ],
    links: [
      { name: 'Playwright Python Official Documentation', url: 'https://playwright.dev/python/' },
      { name: 'Playwright Locators & Selection Architecture', url: 'https://playwright.dev/python/docs/locators' },
      { name: 'Playwright Actionability & Auto-Waiting Guide', url: 'https://playwright.dev/python/docs/actionability' },
    ],
  },
  {
    id: 'cdp',
    sectionNumber: '2.2',
    category: 'browser',
    title: 'Chrome DevTools Protocol (CDP Wire Protocol)',
    codebasePath: 'backend/core/orchestrator.py, action_resolver.py',
    summary:
      'The raw protocol providing granular control over Chromium’s rendering engine, network sockets, input pipeline, and JavaScript runtime.',
    whyChosen:
      'Allows FormPilot to connect to cloud browser nodes (such as TinyFish cloud infrastructure) over a standard WebSocket URL, capturing screenshots and dispatching native hardware mouse/keyboard events remotely.',
    howUsed:
      'Used via connect_over_cdp(session.cdp_url) when running in cloud mode. Enables remote frame captures, dialog handling, and cookie injection across distributed server nodes.',
    pitfallsSolved:
      'Geographic blocking and IP reputation filters often block data-center IP addresses. CDP over secure WebSocket allows FormPilot to route browser sessions through localized Indian ISP network gateways.',
    asciiDiagram: `Cloud Proxy Node (IN) <=== CDP / WebSocket ===> FormPilot Controller
  [Chromium Headless]                               [Python AsyncIO]
  Captures live frames                             Dispatches inputs
  Bypasses geo-blocks                              Maintains Vault crypto`,
    codeSnippet: `# CDP Session Attachment in backend/core/orchestrator.py
if session.is_cloud:
    self.browser = await self.playwright.chromium.connect_over_cdp(
        session.cdp_url,
        timeout=60000
    )
    self.context = self.browser.contexts[0]
    self.page = self.context.pages[0]`,
    keyConcepts: [
      'Remote Debugging Protocol Specification',
      'JSON-RPC 2.0 Message Wire Framing over WebSocket',
      'Target, Page, DOM, and Runtime Protocol Domains',
      'Zero-Footprint Remote Driving Architecture',
    ],
    links: [
      { name: 'Chrome DevTools Protocol Viewer & Specs', url: 'https://chromedevtools.github.io/devtools-protocol/' },
      { name: 'Playwright CDP Session API Reference', url: 'https://playwright.dev/python/docs/api/class-cdpsession' },
    ],
  },

  // ==========================================
  // SECTION 3.0: AGENTICS & STATE MACHINES
  // ==========================================
  {
    id: 'fsm',
    sectionNumber: '3.1',
    category: 'architecture',
    title: 'Deterministic Finite State Machine (FSM & Control Loop)',
    codebasePath: 'backend/core/orchestrator.py:2840-3050, decision_policy.py',
    summary:
      'A formal 12-state deterministic automaton that guarantees strict safety bounds, predictable recovery, and zero hallucinated form submissions.',
    whyChosen:
      'Pure LLM-driven agents are notorious for unpredictable loops, hallucinated submissions, and accidental payments. FormPilot enforces a deterministic FSM where state transitions are governed by concrete DOM evidence and policy rules, with AI only used for contextual advisory.',
    howUsed:
      'Executes the Sense-Plan-Decide-Act (SPDA) cycle on every page. States include: IDLE, CONNECTING, SENSING, THINKING, ACTING, WAITING_FOR_USER, PAUSED, AWAITING_PAYMENT, COMPLETED, STOPPED, FAILED, and DONE.',
    pitfallsSolved:
      'Government forms often reject submissions without clear error messages or silently reload sections. FormPilot’s FSM compares pre-action and post-action DOM blueprints to verify changes, detects page loops via rolling hash stall detection, and prompts the user before irreversible steps.',
    asciiDiagram: `[IDLE] ---> [CONNECTING] ---> [SENSING] ---> [THINKING] ---> [ACTING]
                                  ^                             |
                                  |--- (Next Step / Section) ---+
                                  |
               [WAITING_FOR_USER] <--- (Gate: CAPTCHA / OTP / Consent)
                      |
                      v (User Resolves)
                 [RESUMING]`,
    codeSnippet: `# FSM State transitions in backend/core/orchestrator.py
async def emit_state(self, state: str):
    self.state = state
    await self.broadcast({
        "phase": self.state,
        "active_gate": self.active_gate,
        "run_id": self.run_id
    })`,
    keyConcepts: [
      'Deterministic Automata Theory & State Space Enumeration',
      'Sense-Plan-Decide-Act (SPDA) Closed Feedback Loop',
      'Stall Detection & Rolling DOM Hash Comparison',
      'Fail-Safe Recovery States & Non-Terminal Error Handlers',
    ],
    links: [
      { name: 'Finite State Machine Fundamentals (Brilliant)', url: 'https://brilliant.org/wiki/finite-state-machines/' },
      { name: 'Sense-Plan-Act Paradigm in Robotics (Wikipedia)', url: 'https://en.wikipedia.org/wiki/Sense_plan_act' },
      { name: 'Anthropic – Building Effective Deterministic Agents', url: 'https://www.anthropic.com/research/building-effective-agents' },
    ],
  },
  {
    id: 'hitl',
    sectionNumber: '3.2',
    category: 'architecture',
    title: 'Human-in-the-Loop (HITL) Checkpoint Boundaries',
    codebasePath: 'backend/core/decision_policy.py, gates.py',
    summary:
      'Enforces strict legal, cryptographic, and safety boundaries where automated execution halts and yields full control to the candidate.',
    whyChosen:
      'Automated solving of CAPTCHAs, automated extraction of 2FA SMS OTPs, and automated initiation of bank payments violate government Terms of Service and legal standards. FormPilot makes automated bypassing structurally impossible.',
    howUsed:
      'When the DOM scanner identifies a CAPTCHA input, an SMS OTP field, Aadhaar biometric authentication, or a final payment portal, decision_policy triggers a LIVE_HANDOFF gate. The agent pauses, streams the real browser canvas to the candidate, and waits for manual entry.',
    pitfallsSolved:
      'Credentials entered during a checkpoint (like OTPs or MeriPehchaan PINs) are processed ephemerally: they are entered directly into the browser session and are never logged, written to disk, or sent to external servers.',
    asciiDiagram: `Agent Loop Running
       |
       v
Check: Is CAPTCHA, OTP, Biometric, or Payment visible?
  |                   |
  +-- YES             +-- NO
  |                       |
  v                       v
PAUSE AGENT         CONTINUE AUTONOMOUS FILL
Emit LIVE_HANDOFF
Yield Canvas to User
Wait for explicit resume`,
    codeSnippet: `# Decision Policy Gate Enforcement
if is_captcha_present(dom) or is_otp_input(dom):
    return GateAction(
        gate_type="LIVE_HANDOFF",
        title="Verification Checkpoint",
        solver_policy="human_handoff_only"
    )`,
    keyConcepts: [
      'Zero-Automated-Bypass Safety Boundary Design',
      'Ephemeral Credential Lifecycle (Zero-Disk / Zero-Log)',
      'Live Canvas Control Yielding & Event Arbitration',
      'Pre-Payment Hard Lock & Non-Repudiation Audit',
    ],
    links: [
      { name: 'OWASP Authentication Cheat Sheet', url: 'https://owasp.org/www-community/Authentication_Cheat_Sheet' },
      { name: 'Harvard Business Review – Designing Human-in-the-Loop Systems', url: 'https://hbr.org/2022/04/designing-human-in-the-loop-systems' },
    ],
  },
  {
    id: 'govtech-sso',
    sectionNumber: '3.3',
    category: 'architecture',
    title: 'GovTech SSO Protocols (DigiLocker / MeriPehchaan OAuth)',
    codebasePath: 'backend/core/orchestrator.py:6815-7050, page_actions.py',
    summary:
      'Automated negotiation and handoff for Indian Government Single Sign-On systems including DigiLocker, MeriPehchaan, and JanParichay.',
    whyChosen:
      'Nearly all national portals (JEE Main, NEET, CUET, UPSC) require authentication through national identity bridges. FormPilot natively understands OAuth 2.0 redirect parameters, consent screens, and multi-factor modes.',
    howUsed:
      'Detects whether the portal opened a Sign-In or Sign-Up tab. Pre-fills the candidate’s registered mobile number from OneVault, auto-ticks agreement terms, presents options to switch modes, and auto-ticks document scopes (Marksheets, Aadhaar) on /oauth2/consent before clicking "Allow".',
    pitfallsSolved:
      'On OAuth consent screens (e.g. digilocker.meripehchaan.gov.in/oauth2/consent), generic bots get stuck assuming it is a login screen. FormPilot checks is_consent_page before identity checkpoints, auto-selects required document scopes, and clicks affirmative buttons seamlessly.',
    asciiDiagram: `NTA Portal ----> Redirects to DigiLocker OAuth
                          |
             +------------+------------+
             |                         |
       [Sign Up Tab]             [Sign In Tab]
             |                         |
   Pre-fills Mobile          Candidate Enters PIN
   Auto-ticks Terms                    |
             |                         v
             +------------> [OAuth Consent Screen]
                                  |
                       Auto-ticks Document Scopes
                       Clicks 'Allow'
                                  |
             <--------------------+
      Returns to NTA Registration Form`,
    codeSnippet: `# Consent Screen Handling in orchestrator.py
if page_actions.is_consent_page(dom):
    # Tick document scopes (Marksheet, Aadhaar, Profile)
    for control in consent_controls:
        await self._select_choice_element(control, "yes")
    # Click affirmative button ("Allow", "Authorize", "I Agree")
    await self._click_affirmative_button()`,
    keyConcepts: [
      'OAuth 2.0 Authorization Code Flow & Query State Preservation',
      'Identity Provider Mode Detection (Sign In vs Sign Up)',
      'Document Scope Permission Granting & Automated Ticking',
      'Dual-Tier Event Dispatching for React/Angular GovTech UI',
    ],
    links: [
      { name: 'RFC 6749 – The OAuth 2.0 Authorization Framework', url: 'https://datatracker.ietf.org/doc/html/rfc6749' },
      { name: 'DigiLocker Partner Ecosystem Documentation', url: 'https://partners.digitallocker.gov.in/' },
      { name: 'MeriPehchaan SSO National Portal', url: 'https://meripehchaan.gov.in/' },
    ],
  },

  // ==========================================
  // SECTION 4.0: CRYPTOGRAPHY & IDENTITY
  // ==========================================
  {
    id: 'aes-vault',
    sectionNumber: '4.1',
    category: 'security',
    title: 'AES-256-GCM Zero-Knowledge Vault Encryption',
    codebasePath: 'backend/core/crypto.py, backend/core/vault.py',
    summary:
      'Symmetric Authenticated Encryption with Associated Data (AEAD) securing candidate PII and identity documents at rest.',
    whyChosen:
      'Government application forms require storing sensitive personally identifiable information (Aadhaar numbers, caste certificates, parent names). AES-256-GCM provides both mathematical confidentiality and cryptographic authenticity in a single pass.',
    howUsed:
      'When candidate data or documents are saved in data/candidate_vault.json or data/documents/, FormPilot derives a 256-bit symmetric key using PBKDF2 with SHA-256 and generates a unique 96-bit initialization vector (nonce) for every record.',
    pitfallsSolved:
      'Traditional block cipher modes (like AES-CBC) are vulnerable to padding oracle attacks and bit-flipping manipulation. AES-GCM appends a 128-bit authentication tag; if even a single bit of encrypted data is tampered with, decryption fails instantly.',
    asciiDiagram: `Plaintext JSON + Secret Key + 96-bit Random Nonce
                      |
                      v
             [ AES-256-GCM Engine ]
                      |
                      v
         Ciphertext + 128-bit Auth Tag
       (Zero-knowledge storage at rest)`,
    codeSnippet: `# AES-256-GCM Encryption in backend/core/crypto.py
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

def encrypt_payload(data: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)  # 96-bit unique IV
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext  # Prepend nonce for decryption`,
    keyConcepts: [
      'AES-256 in Galois/Counter Mode (GCM / AEAD)',
      '96-bit Cryptographic Nonce Uniqueness Guarantees',
      'PBKDF2 HMAC-SHA256 Key Derivation with High Iteration Counts',
      'Local Data Sovereignty: Keys Never Uploaded to Central Servers',
    ],
    links: [
      { name: 'NIST Special Publication 800-38D – Recommendation for GCM', url: 'https://csrc.nist.gov/publications/detail/sp/800-38d/final' },
      { name: 'RFC 5116 – An Interface and Algorithms for AEAD', url: 'https://datatracker.ietf.org/doc/html/rfc5116' },
      { name: 'Python Cryptography Library (hazmat AEAD)', url: 'https://cryptography.io/en/latest/hazmat/primitives/ciphers/aead/' },
    ],
  },
  {
    id: 'biometrics',
    sectionNumber: '4.2',
    category: 'security',
    title: 'Biometric Compliance & Binary Search Image Compression',
    codebasePath: 'backend/core/biometrics.py',
    summary:
      'Mathematical image conformer and iterative quality compressor that satisfies strict government biometric specifications.',
    whyChosen:
      'Indian government exam portals enforce draconian upload limits: passport photos must be between 10 KB and 200 KB, exactly 3.5cm x 4.5cm, 200 DPI, with 80% white face coverage. Candidates frequently get rejected due to improper formatting.',
    howUsed:
      'Pillow (PIL) analyzes candidate photos and signatures. It calculates aspect ratios, pads with white borders to prevent distortion, converts to standard 24-bit RGB, and uses an iterative binary search algorithm to discover the exact JPEG quality factor that fits within size bounds.',
    pitfallsSolved:
      'Fixed-quality JPEG compression (e.g. quality=85) fluctuates wildly based on image entropy and lighting. FormPilot’s binary search converges in at most 8 steps to ensure the file strictly complies with both the floor (10 KB) and the ceiling (200 KB).',
    asciiDiagram: `Input Photo (Any format / size)
           |
           v
  Aspect Ratio Calculation
  (Letterbox Padding with Pure White RGB 255,255,255)
           |
           v
  Binary Search Quality Tuning [low=10, high=95]
       Is size between 10 KB and 200 KB?
           /               \\
        Too Big          Too Small
      high = mid - 1    low = mid + 1
           \\               /
       Optimal JPEG Output Generated`,
    codeSnippet: `# Binary search JPEG compression algorithm
low, high = 10, 95
best_buffer = None
while low <= high:
    mid = (low + high) // 2
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=mid, dpi=(200, 200))
    size = buf.tell()
    if 10240 <= size <= 204800:
        best_buffer = buf
        low = mid + 1  # Try higher quality
    elif size > 204800:
        high = mid - 1
    else:
        low = mid + 1`,
    keyConcepts: [
      'Aspect-Ratio Preserving Affine Transforms & Letterboxing',
      'Binary Search Convergence for File Size Optimization ($O(\\log N)$)',
      'Dots Per Inch (DPI) Metadata Normalization',
      'RGB 24-bit Color Space Standardization',
    ],
    links: [
      { name: 'Pillow (PIL) Official Documentation', url: 'https://pillow.readthedocs.io/en/stable/' },
      { name: 'Binary Search Algorithm Analysis (MIT OpenCourseWare)', url: 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/' },
      { name: 'JPEG Standard Specification (ITU-T T.81)', url: 'https://www.w3.org/Graphics/JPEG/itu-t81.pdf' },
    ],
  },

  // ==========================================
  // SECTION 5.0: WEB FRAMEWORKS & PROTOCOLS
  // ==========================================
  {
    id: 'fastapi',
    sectionNumber: '5.1',
    category: 'backend',
    title: 'FastAPI (Asynchronous Server Gateway Interface)',
    codebasePath: 'backend/main.py, backend/core/accounts.py',
    summary:
      'High-performance Python web framework exposing REST endpoints for identity management and bidirectional WebSocket pipelines.',
    whyChosen:
      'FastAPI natively leverages Python async/await, validates incoming request payloads using Pydantic v2 with Rust-backed core speed, and automatically generates interactive OpenAPI/Swagger documentation.',
    howUsed:
      'Hosts the API on 127.0.0.1:8000. Provides routes for /api/vault, /api/agent/start, /api/agent/stop, and handles session token dependency injection for multi-tenant accounts.',
    pitfallsSolved:
      'Traditional WSGI servers (Django/Flask) block the operating system thread during long-running tasks. FastAPI runs on ASGI (Asynchronous Server Gateway Interface), allowing a single worker to maintain persistent WebSocket streams and serve concurrent requests without blocking.',
    asciiDiagram: `Client Web Browser (React 19)
       |
       +--- HTTP REST (JSON)  ---> FastAPI Endpoints (/api/vault)
       |
       \\--- RFC 6455 Frames  ---> FastAPI WebSocket (/ws/cockpit)
                                        |
                                        v
                               Python AsyncIO Loop`,
    codeSnippet: `# FastAPI ASGI route with session token authentication
@app.post("/api/agent/start")
async def start_agent(
    req: AgentStartRequest,
    account: Optional[AppAccount] = Depends(get_current_account)
):
    task = asyncio.create_task(
        orchestrator.start_application(req.query_or_url, req.mode)
    )
    return {"status": "started", "run_id": orchestrator.run_id}`,
    keyConcepts: [
      'ASGI (Asynchronous Server Gateway Interface) Specification',
      'Pydantic v2 Schema Validation & Type Coercion',
      'FastAPI Dependency Injection System (Depends)',
      'OpenAPI 3.1 & JSON Schema Automated Documentation',
    ],
    links: [
      { name: 'FastAPI Official Documentation', url: 'https://fastapi.tiangolo.com/' },
      { name: 'ASGI Standard Specification', url: 'https://asgi.readthedocs.io/en/latest/' },
      { name: 'Uvicorn ASGI Web Server', url: 'https://www.uvicorn.org/' },
    ],
  },
  {
    id: 'websockets',
    sectionNumber: '5.2',
    category: 'backend',
    title: 'RFC 6455 WebSockets (Full-Duplex Cockpit Streaming)',
    codebasePath: 'backend/core/orchestrator.py, backend/main.py:120-190',
    summary:
      'Full-duplex persistent TCP communication layer that streams telemetry events, DOM tree diffs, and live canvas frames.',
    whyChosen:
      'HTTP polling (e.g. asking every 1 second "what happened?") wastes bandwidth, introduces up to 1000ms latency, and drains client battery. WebSockets maintain an open socket where the agent pushes events instantaneously.',
    howUsed:
      'Exposed at /ws/cockpit. FormPilot broadcasts typed events: SENSE (DOM scans), THINK (reasoning and field matches), DECIDE (actions to take), ACT (synthetic clicks/fills), and GATE (human checkpoints).',
    pitfallsSolved:
      'Uncontrolled WebSocket streams can flood the browser during high-frequency screen recording. FormPilot implements frame rate throttling (700ms minimum interval) and backpressure checks to ensure the browser UI stays responsive.',
    asciiDiagram: `Client (Browser)                           Server (FastAPI)
       |                                                 |
       +----- HTTP GET /ws/cockpit (Upgrade: websocket) ->|
       |<---- HTTP 101 Switching Protocols --------------+
       |                                                 |
       |  === Persistent Full-Duplex RFC 6455 Socket === |
       |<---- [SENSE] 42 fields scanned in 0.8s ---------+
       |<---- [THINK] Matched 'Full Name' to vault ------+
       |<---- [ACT] Ticked Indian Nationality -----------+
       |<---- [FRAME] Binary Base64 JPEG Frame ----------+`,
    codeSnippet: `# Cockpit broadcast manager
async def broadcast(self, payload: dict):
    message = json.dumps(payload)
    for connection in self.active_connections:
        try:
            await connection.send_text(message)
        except Exception:
            pass`,
    keyConcepts: [
      'RFC 6455 Protocol Handshake & Binary Frame Masking',
      'Full-Duplex Bidirectional Messaging over Single TCP Connection',
      'Heartbeat Ping/Pong Liveness Verification',
      'Backpressure Management & Frame Rate Throttling',
    ],
    links: [
      { name: 'RFC 6455 – The WebSocket Protocol', url: 'https://datatracker.ietf.org/doc/html/rfc6455' },
      { name: 'MDN WebSockets Client Application Guide', url: 'https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API' },
    ],
  },

  // ==========================================
  // SECTION 6.0: REACTIVE UI & TOOLING
  // ==========================================
  {
    id: 'vite',
    sectionNumber: '6.1',
    category: 'frontend',
    title: 'Vite 8 & Modern Build Tooling (ESM & Rolldown)',
    codebasePath: 'frontend/vite.config.js, frontend/package.json',
    summary:
      'Next-generation frontend tooling providing instant Hot Module Replacement (HMR) and optimized production bundles.',
    whyChosen:
      'Traditional Webpack bundlers crawl the entire dependency graph before starting, resulting in slow 30-second start times. Vite leverages native browser ES Modules in development and Rolldown/Rollup for lightning-fast production compilation.',
    howUsed:
      'Bundles the React 19 application in frontend/. Configured to output clean static assets to frontend/dist with hash-versioned scripts and stylesheets.',
    pitfallsSolved:
      'Single Page Applications (SPAs) deployed on edge hosts often return 404 when refreshing deep URLs like /vault or /docs. Vite build outputs are paired with vercel.json rewrite rules that route all paths to index.html.',
    asciiDiagram: `Source Files (JSX, CSS)
         |
         v
    [ Vite Dev Server ] === (Native ESM) ===> Browser (Instant HMR)
         |
         v (npm run build)
    [ Production Bundle ] ===> dist/assets/index-[hash].js (< 600 KB)`,
    codeSnippet: `// frontend/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
  }
})`,
    keyConcepts: [
      'Native Browser ECMAScript Modules (ESM)',
      'Instant Hot Module Replacement (HMR)',
      'Rollup/Rolldown Tree-Shaking & Dead Code Elimination',
      'Single Page Application (SPA) HTML5 History Mode Routing',
    ],
    links: [
      { name: 'Vite Official Guide & Documentation', url: 'https://vite.dev/' },
      { name: 'Rollup.js Module Bundler Reference', url: 'https://rollupjs.org/' },
      { name: 'MDN JavaScript Modules Guide', url: 'https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules' },
    ],
  },
  {
    id: 'testing-devops',
    sectionNumber: '6.2',
    category: 'frontend',
    title: 'pytest & CI/CD Verification Engine (585+ Tests)',
    codebasePath: 'tests/test_live_hardening.py, tests/test_journey.py',
    summary:
      'Comprehensive automated test suite validating DOM scanner classifications, IDP state transitions, crypto security, and journey histories.',
    whyChosen:
      'Autonomous agents interacting with government portals must never misbehave or corrupt user data. A 585-test regression harness guarantees every code change preserves reliability across all form types.',
    howUsed:
      'Run via pytest tests/ -q. Covers unit tests for encryption, integration tests for identity provider transitions, and end-to-end simulated form journeys.',
    pitfallsSolved:
      'Edge cases like radio button postback desynchronization, consent screen traps, and mobile number pre-fills were permanently solved by adding targeted regression tests that run before every git push.',
    asciiDiagram: `[ Pull Request / Git Commit ]
              |
              v
     pytest tests/ -q
     =============================
     [OK] 585 passed in 4m 52s
     [OK] 0 failures
              |
              v
     [ Push to GitHub / Vercel Edge Deploy ]`,
    codeSnippet: `# Example regression test in tests/test_live_hardening.py
@pytest.mark.asyncio
async def test_consent_screen_priority():
    dom = {
        "url": "https://digilocker.meripehchaan.gov.in/oauth2/consent",
        "inputs": [{"type": "checkbox", "text": "Class X Marksheet"}]
    }
    assert page_actions.is_consent_page(dom) is True
    # Ensures IDP checkpoint does not capture consent pages`,
    keyConcepts: [
      'Asynchronous Testing Fixtures (pytest-asyncio)',
      'Synthetic DOM Tree Mocking & Snapshot Assertions',
      'Cryptographic Round-Trip Validation',
      'Automated Zero-Downtime Deployment via Vercel',
    ],
    links: [
      { name: 'pytest Official Documentation', url: 'https://docs.pytest.org/en/stable/' },
      { name: 'pytest-asyncio Documentation', url: 'https://pytest-asyncio.readthedocs.io/' },
      { name: 'Vercel Deployment Architecture', url: 'https://vercel.com/docs' },
    ],
  },
];

export default function TechDocsPage({ onSelectNav }) {
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('detailed'); // 'detailed' | 'table'
  const [activeSectionId, setActiveSectionId] = useState('');
  const [copiedId, setCopiedId] = useState(null);

  const filteredTopics = useMemo(() => {
    return TECHNICAL_MANUAL.filter((topic) => {
      const matchesCategory =
        selectedCategory === 'all' || topic.category === selectedCategory;
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !q ||
        topic.title.toLowerCase().includes(q) ||
        topic.summary.toLowerCase().includes(q) ||
        topic.whyChosen.toLowerCase().includes(q) ||
        topic.howUsed.toLowerCase().includes(q) ||
        topic.pitfallsSolved.toLowerCase().includes(q) ||
        topic.keyConcepts.some((k) => k.toLowerCase().includes(q)) ||
        topic.links.some((l) => l.name.toLowerCase().includes(q)) ||
        topic.codebasePath.toLowerCase().includes(q);
      return matchesCategory && matchesSearch;
    });
  }, [selectedCategory, searchQuery]);

  const copyPath = (path, id) => {
    navigator.clipboard.writeText(path);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 font-sans text-slate-200">
      {/* Editorial Header / Classic Manual Masthead */}
      <header className="border-b-2 border-slate-700 pb-6 mb-8">
        <div className="flex flex-col md:flex-row md:items-baseline justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-slate-400">
              <span className="font-bold text-slate-300">FormPilot Engine</span>
              <span>/</span>
              <span>Technical Manual & Reference Specification</span>
            </div>
            <h1 className="mt-2 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
              Architecture, Concepts & Standards
            </h1>
            <p className="mt-2 text-sm text-slate-300 max-w-3xl leading-relaxed">
              A comprehensive technical reference detailing the systems programming, browser automation protocols,
              deterministic finite state machines, cryptographic standards, and computer science foundations that
              drive FormPilot.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono shrink-0">
            <span className="border border-slate-700 bg-slate-900 px-2.5 py-1 text-slate-300 rounded">
              Rev: 1.1.0-prod
            </span>
            <span className="border border-slate-700 bg-slate-900 px-2.5 py-1 text-emerald-400 font-semibold rounded">
              585 Tests Passing
            </span>
          </div>
        </div>

        {/* Quick Jump Index / Table of Contents Bar */}
        <div className="mt-6 flex flex-wrap items-center gap-2 text-xs font-mono border-t border-slate-800 pt-4">
          <span className="text-slate-400 font-bold uppercase tracking-wider text-[11px] mr-1">
            Index:
          </span>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setSelectedCategory(cat.id)}
              className={`px-2.5 py-1 rounded transition-colors text-xs ${
                selectedCategory === cat.id
                  ? 'bg-slate-200 text-slate-950 font-bold shadow-sm'
                  : 'bg-slate-900 text-slate-400 hover:text-white hover:bg-slate-800 border border-slate-800'
              }`}
            >
              {cat.label} ({cat.count})
            </button>
          ))}
        </div>
      </header>

      {/* Control Bar: Search & View Toggle */}
      <section className="mb-8 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 p-3 rounded-lg">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search documentation (e.g. Playwright, CDP, AES-256, FSM, TreeWalker, PostBack, React 19)..."
            className="w-full bg-slate-950 border border-slate-800 pl-9 pr-8 py-1.5 text-xs text-white placeholder-slate-500 rounded focus:border-slate-500 focus:outline-none font-mono"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-white"
            >
              ×
            </button>
          )}
        </div>

        {/* View Mode Toggle */}
        <div className="flex items-center gap-1 shrink-0 text-xs font-mono">
          <span className="text-slate-400 text-[11px] mr-2">Layout:</span>
          <button
            type="button"
            onClick={() => setViewMode('detailed')}
            className={`px-3 py-1 rounded border text-xs ${
              viewMode === 'detailed'
                ? 'bg-slate-800 border-slate-600 text-white font-bold'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            Manual (Full Notes)
          </button>
          <button
            type="button"
            onClick={() => setViewMode('table')}
            className={`px-3 py-1 rounded border text-xs ${
              viewMode === 'table'
                ? 'bg-slate-800 border-slate-600 text-white font-bold'
                : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            Compact Table
          </button>
        </div>
      </section>

      {/* Topics Counter */}
      <div className="mb-4 flex items-center justify-between text-xs text-slate-400 font-mono">
        <span>Displaying {filteredTopics.length} technical specifications</span>
        {searchQuery && <span>Filter: "{searchQuery}"</span>}
      </div>

      {/* Main Content Area */}
      {filteredTopics.length === 0 ? (
        <div className="border border-slate-800 bg-slate-900/50 p-8 text-center rounded">
          <FileText className="mx-auto h-8 w-8 text-slate-500 mb-2" />
          <p className="text-sm font-bold text-white">No matching specifications found</p>
          <p className="text-xs text-slate-400 mt-1">Try keywords like Python, CDP, FSM, AES, or WebSockets.</p>
          <button
            type="button"
            onClick={() => { setSearchQuery(''); setSelectedCategory('all'); }}
            className="mt-3 text-xs font-mono text-indigo-400 hover:underline"
          >
            Reset query and filters
          </button>
        </div>
      ) : viewMode === 'table' ? (
        /* ==========================================
           COMPACT REFERENCE TABLE VIEW
           ========================================== */
        <div className="overflow-x-auto border border-slate-800 rounded bg-slate-900">
          <table className="w-full text-left text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950 text-slate-400">
                <th className="py-2.5 px-3">§</th>
                <th className="py-2.5 px-3">Technology / Concept</th>
                <th className="py-2.5 px-3">Codebase Target</th>
                <th className="py-2.5 px-3">Role & Problem Solved</th>
                <th className="py-2.5 px-3">Official Docs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-300">
              {filteredTopics.map((topic) => (
                <tr key={topic.id} className="hover:bg-slate-850">
                  <td className="py-3 px-3 text-slate-500 font-bold">{topic.sectionNumber}</td>
                  <td className="py-3 px-3 text-white font-bold">{topic.title}</td>
                  <td className="py-3 px-3 text-slate-400 text-[11px] truncate max-w-[200px]" title={topic.codebasePath}>
                    {topic.codebasePath}
                  </td>
                  <td className="py-3 px-3 font-sans text-slate-300 max-w-xs">{topic.summary}</td>
                  <td className="py-3 px-3 whitespace-nowrap">
                    {topic.links.map((link, idx) => (
                      <a
                        key={idx}
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-block mr-2 text-indigo-400 hover:text-indigo-300 underline text-[11px]"
                      >
                        {link.name} ↗
                      </a>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        /* ==========================================
           DETAILED MANUAL / NOTEBOOK VIEW
           ========================================== */
        <div className="space-y-10">
          {filteredTopics.map((topic) => (
            <article
              key={topic.id}
              id={topic.id}
              className="border border-slate-800 bg-slate-900/80 rounded-lg p-6 sm:p-8"
            >
              {/* Header with Section Number and Title */}
              <div className="border-b border-slate-800 pb-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-black text-amber-500 bg-amber-950/40 border border-amber-800/60 px-2 py-0.5 rounded">
                      § {topic.sectionNumber}
                    </span>
                    <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-white">
                      {topic.title}
                    </h2>
                  </div>

                  {/* Codebase File Link */}
                  <div className="flex items-center gap-1.5 text-xs font-mono text-slate-400 bg-slate-950 border border-slate-800 px-2.5 py-1 rounded">
                    <FileCode className="h-3.5 w-3.5 text-slate-500" />
                    <span>{topic.codebasePath}</span>
                    <button
                      type="button"
                      onClick={() => copyPath(topic.codebasePath, topic.id)}
                      title="Copy codebase path"
                      className="ml-1 text-slate-500 hover:text-white"
                    >
                      <Copy className="h-3 w-3" />
                    </button>
                    {copiedId === topic.id && (
                      <span className="text-[10px] text-emerald-400 ml-1">Copied!</span>
                    )}
                  </div>
                </div>

                {/* Summary */}
                <p className="mt-3 text-sm leading-relaxed text-slate-300 font-sans">
                  {topic.summary}
                </p>
              </div>

              {/* Deep Dive Content Columns */}
              <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6 text-xs leading-relaxed font-sans">
                {/* Column 1: Why Chosen & How It Works */}
                <div className="space-y-4">
                  <div>
                    <h3 className="font-mono font-bold uppercase tracking-wider text-slate-400 text-[11px] mb-1.5 flex items-center gap-1.5">
                      <Cpu className="h-3.5 w-3.5 text-slate-400" />
                      1. Engineering Rationale & Why We Chose It
                    </h3>
                    <p className="text-slate-300 bg-slate-950/60 p-3 rounded border border-slate-800/80">
                      {topic.whyChosen}
                    </p>
                  </div>

                  <div>
                    <h3 className="font-mono font-bold uppercase tracking-wider text-slate-400 text-[11px] mb-1.5 flex items-center gap-1.5">
                      <Workflow className="h-3.5 w-3.5 text-slate-400" />
                      2. Implementation in FormPilot Codebase
                    </h3>
                    <p className="text-slate-300 bg-slate-950/60 p-3 rounded border border-slate-800/80">
                      {topic.howUsed}
                    </p>
                  </div>
                </div>

                {/* Column 2: Pitfalls & Problems Solved */}
                <div className="space-y-4">
                  <div>
                    <h3 className="font-mono font-bold uppercase tracking-wider text-slate-400 text-[11px] mb-1.5 flex items-center gap-1.5">
                      <Shield className="h-3.5 w-3.5 text-amber-500" />
                      3. Concrete Technical Pitfalls Solved
                    </h3>
                    <p className="text-slate-300 bg-slate-950/60 p-3 rounded border border-slate-800/80">
                      {topic.pitfallsSolved}
                    </p>
                  </div>

                  <div>
                    <h3 className="font-mono font-bold uppercase tracking-wider text-slate-400 text-[11px] mb-1.5 flex items-center gap-1.5">
                      <Hash className="h-3.5 w-3.5 text-slate-400" />
                      4. Core Theoretical Concepts
                    </h3>
                    <ul className="space-y-1 bg-slate-950/60 p-3 rounded border border-slate-800/80">
                      {topic.keyConcepts.map((concept, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-slate-300 text-[11px]">
                          <span className="text-emerald-400 font-mono mt-0.5">•</span>
                          <span>{concept}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* ASCII Architecture Flow Diagram */}
              {topic.asciiDiagram && (
                <div className="mt-6">
                  <h3 className="font-mono font-bold uppercase tracking-wider text-slate-400 text-[11px] mb-2 flex items-center gap-1.5">
                    <Terminal className="h-3.5 w-3.5 text-slate-400" />
                    Architecture Dataflow & State Mechanics
                  </h3>
                  <pre className="font-mono text-[11px] leading-tight text-slate-300 bg-slate-950 p-4 rounded border border-slate-800 overflow-x-auto selection:bg-slate-700">
                    {topic.asciiDiagram}
                  </pre>
                </div>
              )}

              {/* Code Snippet */}
              {topic.codeSnippet && (
                <div className="mt-5">
                  <h3 className="font-mono font-bold uppercase tracking-wider text-slate-400 text-[11px] mb-2 flex items-center gap-1.5">
                    <Code2 className="h-3.5 w-3.5 text-slate-400" />
                    Representative Implementation Snippet
                  </h3>
                  <pre className="font-mono text-[11px] text-amber-200/90 bg-slate-950 p-3.5 rounded border border-slate-800 overflow-x-auto">
                    <code>{topic.codeSnippet}</code>
                  </pre>
                </div>
              )}

              {/* Direct Documentation & Standard Links */}
              <div className="mt-6 border-t border-slate-800/80 pt-4 flex flex-wrap items-center justify-between gap-3">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400">
                  Primary Documentation & Standards:
                </span>
                <div className="flex flex-wrap gap-2">
                  {topic.links.map((link, idx) => (
                    <a
                      key={idx}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 bg-slate-950 hover:bg-slate-800 border border-slate-700/80 px-2.5 py-1 text-xs text-indigo-300 hover:text-white rounded transition-colors"
                    >
                      <span>{link.name}</span>
                      <ArrowUpRight className="h-3 w-3 text-slate-400" />
                    </a>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Classic Document Footer */}
      <footer className="mt-16 border-t-2 border-slate-700 pt-6 text-xs text-slate-400 font-mono flex flex-col sm:flex-row items-center justify-between gap-4">
        <div>
          FormPilot Engineering Specifications &bull; Local & Server Runtime Manual
        </div>
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="hover:text-white underline"
          >
            Back to Top ↑
          </button>
          <button
            type="button"
            onClick={() => onSelectNav && onSelectNav('portal')}
            className="text-amber-400 hover:text-amber-300 font-bold"
          >
            Return to Live Cockpit →
          </button>
        </div>
      </footer>
    </main>
  );
}
