# Consent Companion — Policy Change Analysis API (MSc Project)

Consent Companion is a policy-change analysis engine designed to **detect, align, classify, and explain changes** between two versions of a Terms of Service or Privacy Policy document.

It exposes a **FastAPI backend** with a `/compare` endpoint that returns **ranked, structured policy changes** with **plain-language explanations and suggested user actions**.

This project is intended as an **industry-grade prototype** suitable for real deployment and further research extension.

---

## Key Features

- **Semantic policy comparison** using Sentence-BERT (`all-MiniLM-L6-v2`)
- **Real sentence segmentation** via spaCy
- **Change classification** across key privacy dimensions:
  - Data collection
  - Data sharing & third parties
  - Data retention & storage
  - Tracking, analytics & profiling
  - User rights & controls
  - Security & safeguards
- **Risk-based ranking** of changes
- **FastAPI backend** with automatic Swagger documentation
- Designed to be **locally runnable, deployable, and portable**

---

## Project Structure (Minimal)

ConsentCompanion/
│
├── backend/
│ ├── init.py
│ ├── api_main.py # FastAPI entry point
│ ├── consent_core.py # Core semantic analysis engine
│ └── policy_loader.py # Policy loading utilities (URL / text / file)
│
└── README.md


---

## Requirements

- **Python 3.11.x** (recommended for Windows compatibility)
- pip
- (Optional) Git

Tested with Python 3.11.9 on Windows.
> ⚠️ Python 3.13 is **not recommended** due to build issues with scientific and NLP libraries.

---

## Local Setup (Windows)

### 1. Create and activate a virtual environment

From the project root:

```bash
python -m venv .venv
.venv\Scripts\activate
2. Install dependencies
If you have a requirements.txt:
pip install -r backend/requirements.txt


Otherwise, install core dependencies manually:

pip install fastapi uvicorn[standard] pydantic python-multipart requests
pip install sentence-transformers torch
pip install spacy beautifulsoup4 lxml readability-lxml

3. Download the spaCy English model (run once)
python -m spacy download en_core_web_sm
This step is required for sentence-level policy segmentation.

Running the API Locally
From the project root directory:

uvicorn backend.api_main:app --host 127.0.0.1 --port 8000 --reload
If successful, you will see:

API running at:
http://127.0.0.1:8000

Swagger documentation at:
http://127.0.0.1:8000/docs

Testing the API (Backend Verification)
Option A — cURL (Recommended)
From Git Bash / PowerShell / Terminal:


curl -X POST http://127.0.0.1:8000/compare \
  -H "Content-Type: application/json" \
  -d '{"old_text":"We collect your email address.","new_text":"We collect your email address and phone number.","mode":"semantic"}'
✔ If JSON is returned → the backend is working independently of any UI.

Option B — Swagger UI
1.  Open:
http://127.0.0.1:8000/docs

2. Locate POST /compare

3. Click Try it out

4. Paste:
{
  "old_text": "We collect your email address.",
  "new_text": "We collect your email address and phone number.",
  "mode": "semantic",
  "max_changes": 10
}
5. Click Execute

API Endpoints
Health Checks
GET / → { "status": "ok" }

GET /ping → { "status": "ok" }

Compare Endpoint
POST /compare

Request Body
{
  "old_text": "string",
  "new_text": "string",
  "mode": "semantic",
  "max_changes": 50
}

Modes
basic → Line-based baseline comparison
semantic → Sentence-level semantic alignment and ranking

Troubleshooting
1. ModuleNotFoundError: No module named 'backend'
Run uvicorn from the project root
Ensure backend/__init__.py exists
uvicorn backend.api_main:app --reload

2. spaCy model error
Run:
python -m spacy download en_core_web_sm

3. Slow first request
The first request may take longer while Sentence-BERT loads model weights.
Subsequent requests will be faster.

4. Windows build errors
Use Python 3.11.x

Avoid Python 3.13 for now

Academic Context
This project was developed as part of an MSc-level research project and is designed to:

Demonstrate applied NLP and semantic similarity techniques

Bridge academic research and industry-grade system design

Serve as a foundation for further extension (e.g., policy monitoring, version tracking, UI integration)


Author
Mahesh Kumar Tamang
MSc Advanced Computer Science
Birmingham City University