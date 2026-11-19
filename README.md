# FormPilot ("AI Cyber Bhaiya")
> **Autonomous Examination & Public-Form Operations Agent with Human-in-the-Loop Safety Controls**  
> *Submitted for PromptWars X Noor AITH — Build for Impact: Reimagining the Future with AI*

[![Live Demo](https://img.shields.io/badge/Live_Demo-formpilot--assistant.vercel.app-0284c7?style=for-the-badge&logo=vercel)](https://formpilot-assistant.vercel.app/)
[![License](https://img.shields.io/badge/License-MIT-emerald?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![Playwright](https://img.shields.io/badge/Playwright-1.45+-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev)

---

## 1. Challenge & Chosen Vertical

* **Challenge:** PromptWars X Noor AITH — Build for Impact
* **Primary Vertical:** **Accessibility and Inclusion** & **Smart Cities and Civic Technology**
* **Secondary Alignment:** **Productivity and Everyday Life**

### The Real-World Problem
Every year across India, over **25 million candidates** apply for public recruitment and competitive examinations (UPSC, SSC, State PSCs, Railway, JEE, NEET). 
1. **Clerical Rejections:** Forms feature rigid, multi-page validation constraints. A minor typo in name verification, category selection, or a slight error in photograph dimensions leads to immediate disqualification without refund.
2. **Predatory Cyber Café Ecosystem:** Millions of first-generation learners and rural students cannot navigate unforgiving government web portals. They are forced to travel to local cyber cafés, paying ₹100–₹500 per form and sharing sensitive personal documents (Aadhaar, marks, certificates) over insecure shared computers.
3. **Complex Document Constraints:** Portals demand exact file sizes (e.g., photo 20–50 KB, signature 10–20 KB, specific pixel aspect ratios), creating huge barriers for mobile users.

---

## 2. Approach and Logic

FormPilot was architected not as a simple scraper or blind form-filling bot, but as a **co-pilot agent** that combines autonomous browser automation with strict **institutional safety guardrails**.

```
[Candidate Profile] ───> [Semantic DOM Scanner] ───> [Live Chromium over CDP]
                                │                               │
                     [Structural Fingerprint]       [Bidirectional WebSockets]
                                │                               │
                     [7-Stage Human Gates] ◄─────── [Interactive Cockpit]
                                │
                   [HARD PRE-PAYMENT STOP] (Zero Unauthorized Transactions)
```

### Core Architecture & Logic:
1. **Semantic DOM Scanner & Structural Fingerprints:** Instead of relying on brittle, hardcoded CSS/XPath selectors that break whenever a government portal updates, FormPilot performs semantic DOM tree analysis. It derives structural fingerprints and matches input intent (`identity.full_name`, `contact.email`, `education.passing_year`).
2. **Dual-Confirmation Synchronization:** Public forms frequently require confirmation fields (e.g., "Confirm Email", "Re-enter Roll Number"). FormPilot guarantees zero typographical drift by linking and validating confirmed pairs.
3. **Bi-Directional CDP Streaming:** Using Playwright and Chrome DevTools Protocol (CDP), the real Chromium session is screencasted live via WebSockets into the React web dashboard. The candidate retains full control: mouse, keyboard, scrolling, and navigation events are forwarded bidirectionally.
4. **Deterministic Biometric Processing:** In-memory image processing automatically scales, sharpens, and compresses uploaded photos and signatures to match exact government portal constraints (e.g., 20–50 KB at 350×350 px) without manual photo editing software.

---

## 3. How the Solution Works (End-to-End Workflow)

1. **Step 1: OneVault Setup**
   * The candidate maintains their reusable master profile once (personal details, address, categories, academic records). Sensitive fields are masked.
2. **Step 2: Portal Resolution & Inspection**
   * Candidate selects an official portal or provides a portal URL. FormPilot checks domain legitimacy against official government registries and maps the form's visible structure.
3. **Step 3: Autonomous Autofill with Live Visual Stream**
   * The orchestrator enters fields one by one, highlighting active elements on the live browser stream. The candidate watches real-time progress inside the cockpit.
4. **Step 4: Docked Human Checkpoints (Safety by Design)**
   * FormPilot never guesses when confidence is below threshold. It docks a checkpoint panel and yields control to the candidate for:
     - **CAPTCHA / Slider Verification** (Candidate solves the challenge directly in the live browser).
     - **OTP Verification** (Candidate enters SMS/Email OTP).
     - **Live Webcam / Document Uploads**.
5. **Step 5: Pre-Payment & Final Submission Safety Stop**
   * When reaching payment gateways or the final submission button, FormPilot triggers a **hard circuit breaker**. It hands full control back to the user, ensuring no financial transaction or irrevocable submission is ever performed autonomously.

---

## 4. Key Assumptions & Safety Boundaries

| Action | Automated by FormPilot | Human-Only Responsibility | Rationale |
| :--- | :---: | :---: | :--- |
| **Field Mapping & Filling** | ✅ | ❌ | Eliminates hours of repetitive typing and typo risks. |
| **Photo & Signature Resizing** | ✅ | ❌ | Meets strict KB and pixel dimensional rules deterministically. |
| **Solving CAPTCHA / Cloudflare** | ❌ | ✅ | **No bypasses or bots.** Upholds portal terms and security standards. |
| **OTP Entry** | ❌ | ✅ | Ensures authentic two-factor ownership verification. |
| **Payment & Final Submit** | ❌ | ✅ | **Hard pre-payment stop.** Prevents accidental charges or irreversible submissions. |

---

## 5. Technology Stack & AI Tooling

* **Backend:** Python 3.11+, FastAPI (ASGI), WebSockets, Playwright, Chrome DevTools Protocol (CDP), Pillow (PIL), NumPy, Pydantic.
* **Frontend:** React 19, Vite, Tailwind CSS, Lucide Icons, Canvas Screencast Client.
* **AI & Automation:** Multi-modal LLM reasoning for ambiguous field semantics, structural DOM tree fingerprinting, and Set-of-Marks (SoM) locator grounding.
* **Security & Infrastructure:** Merkle Audit Hash Chain (SHA-256 event ledger), SSRF defense boundary against cloud metadata exploitation, AES-256-GCM encrypted local vault.

---

## 6. Quickstart / How to Run Locally

### Prerequisites
* Python 3.11+
* Node.js 18+
* Chromium / Playwright

### Backend Setup
```bash
# Clone the repository
git clone https://github.com/Nishant-learns/formpilot-ai.git
cd formpilot-ai

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Launch the backend server
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` to access the FormPilot Cockpit.

---

## 7. Verification & Tests

The project includes an end-to-end automated test suite verifying the DOM scanner, orchestrator, biometric compressor, and human safety checkpoints:

```bash
pytest tests/ -v
```

---

## 8. Summary for Judges

FormPilot re-imagines public administration access by combining generative AI with deterministic safety boundaries. It transforms a stressful, error-prone 2-hour ordeal into a safe, guided 5-minute interaction—empowering millions of students to apply with dignity and confidence.
