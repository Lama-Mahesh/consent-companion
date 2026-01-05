# **Consent Companion**

**Policy Change Monitoring & Analysis System**  
*MSc Advanced Computer Science – Birmingham City University*

---

## **Overview**

Consent Companion is an **end-to-end policy change analysis and monitoring system** designed to detect, rank, and explain meaningful changes in **Privacy Policies** and **Terms of Service** over time.

Unlike traditional “diff” tools that overwhelm users with formatting noise, Consent Companion focuses on:

* **semantic meaning**, not line changes  
* **material consent impacts**, not headings or boilerplate  
* **proactive notification**, not manual checking

The system combines a **FastAPI backend**, a **semantic NLP engine**, a **web-based frontend**, a **Chrome extension**, and an **OTA-based policy cache** to deliver clear, user-centred insights into how online services change their data practices.

This project was developed as an **industry-grade MSc research prototype**, suitable for real-world deployment and further academic extension.

---

## **What Problem Does It Solve?**

Privacy policies change frequently, but:

* users rarely notice updates  
* changes are buried in long legal documents  
* most tools only show raw diffs, not meaning

Consent Companion addresses this gap by introducing:

* **temporal monitoring** (what changed since last time)  
* **semantic alignment** (what changed in meaning)  
* **impact ranking** (what matters most)  
* **plain-language explanations** (what users should do)

---

## **System Architecture (High Level)**

Consent Companion consists of **five integrated components**:

1. **Semantic Analysis Engine (Backend)**  
   Detects, aligns, and classifies policy changes  
2. **OTA Cache & Sync Pipeline**  
   Periodically fetches and versions policies from Open Terms Archive  
3. **FastAPI REST API**  
   Exposes comparison, monitoring, and extension endpoints  
4. **Frontend Web Interface**  
   Provides human-readable inspection of policies, diffs, and risk-ranked changes  
5. **Chrome Extension (Manifest V3)**  
   Provides real-time site checks, watchlists, and user notifications

`User`

 `↓`

`Chrome Extension ──→ FastAPI API ──→ Semantic Engine`

        `│                    │`

        `│                    ↓`

        `│              OTA Cache`

        `↓`

`Frontend Web UI (Detailed inspection & explanations)`

---

## **Key Features**

### **1\. Semantic Policy Comparison**

* Sentence-level alignment using **Sentence-BERT (all-MiniLM-L6-v2)**  
* Robust sentence segmentation via **spaCy**  
* Detects **added**, **removed**, and **modified** clauses

---

### **2\. Strong Noise Suppression**

The engine aggressively removes:

* section headings (e.g. *“Service providers”*)  
* markdown tables and link fragments  
* bullet lists and boilerplate  
* trivial formatting edits

A **minimum-substance rule** ensures short labels are ignored unless they contain a real legal clause (e.g. *“we may collect”*).

---

### **3\. Change Classification**

Each detected change is classified into privacy-relevant themes, including:

* Data collection  
* Data sharing & third parties  
* Tracking, analytics & profiling  
* Data retention & storage  
* User rights & controls  
* Security & safeguards  
* Billing & financial terms

---

### **4\. Risk-Based Impact Scoring**

Changes are ranked using:

* category-level risk  
* content-level triggers (advertising, data brokers, profiling, cross-service data use)

This ensures that **material consent changes surface first**.

---

### **5\. Confidence per Change**

Each semantic result includes a confidence signal:

* **modified** → similarity score  
* **added / removed** → default confidence

This improves transparency and trust in the analysis.

---

### **6\. Proactive Policy Monitoring**

Users can watch specific services via the **Chrome extension**.

The system:

* tracks when a policy last changed  
* compares against a per-user baseline  
* sends notifications **only when new material changes occur**

---

## **Repository Structure**

`ConsentCompanion/`

`│`

`├── backend/                     # FastAPI backend + semantic engine`

`│   ├── api_main.py              # API entry point`

`│   ├── consent_core.py          # Core semantic analysis engine`

`│   ├── policy_loader.py         # URL / OTA / file ingestion`

`│   └── scripts/`

`│       └── ota_sync.py          # OTA cache update pipeline`

`│`

`├── frontend/                    # Web UI (React / Vite)`

`│`

`├── consent-companion-extension/ # Chrome extension (Manifest V3)`

`│   ├── background.js`

`│   ├── popup.html`

`│   ├── popup.js`

`│   ├── popup.css`

`│   └── icons/`

`│`

`├── sources/`

`│   └── ota_targets.json         # OTA service + policy definitions`

`│`

`├── data/cache/                  # Cached policy versions & diffs`

`│`

`└── README.md`

---

## **Requirements**

* **Python 3.11.x** (recommended)  
* pip  
* **Node.js** (frontend)  
* **Chrome** (extension testing)

⚠️ Python 3.13 is not recommended due to NLP dependency issues.

Tested on **Windows 10/11** with **Python 3.11.9**.

---

## **Backend Setup (FastAPI)**

### **1\. Create virtual environment**

From the project root:

`python -m venv .venv`

`.venv\Scripts\activate`

### **2\. Install dependencies**

`pip install -r backend/requirements.txt`

Or manually:

`pip install fastapi uvicorn[standard] pydantic python-multipart requests`

`pip install sentence-transformers torch`

`pip install spacy beautifulsoup4 lxml readability-lxml`

### **3\. Download spaCy model (once)**

`python -m spacy download en_core_web_sm`

### **4\. Run the API**

`uvicorn backend.api_main:app --host 127.0.0.1 --port 8000 --reload`

* API: [http://127.0.0.1:8000](http://127.0.0.1:8000)  
* Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## **Frontend Setup (Web UI)**

From the project root:

`cd frontend`

`npm install`

`npm run dev`

The frontend runs locally (typically at `http://localhost:5173`) and communicates with the FastAPI backend to:

* browse cached policies  
* inspect semantic diffs  
* explore ranked consent impacts in detail

---

## **Chrome Extension Setup**

### **Development Mode**

1. Open `chrome://extensions`  
2. Enable **Developer mode**  
3. Click **Load unpacked**  
4. Select `consent-companion-extension/`

### **Notes**

* After editing extension files, click **Reload** in `chrome://extensions`  
* Popup UI may auto-refresh, but **background logic requires reload**  
* Notifications require icons located in:  
  * `icons/icon16.png`  
  * `icons/icon48.png`  
  * `icons/icon128.png`

---

## **API Overview**

### **Core Comparison**

* `POST /compare`  
* `POST /compare/url`  
* `POST /compare/file`  
* `POST /compare/ota`  
* `POST /compare/ingest`

### **Monitoring (Extension)**

* `GET /extension/check?domain=example.com`  
* `POST /extension/updates`

---

## **Academic Context**

This project demonstrates:

* applied NLP and semantic similarity techniques  
* robust system design beyond proof-of-concept demos  
* integration of backend services with browser-based user agents  
* end-to-end system engineering suitable for real deployment

It is intended to support dissertation chapters on:

* system architecture  
* methodology  
* evaluation  
* limitations and future work

---

## **Author**

**Mahesh Kumar Tamang**  
MSc Advanced Computer Science  
Birmingham City University

