# LogicFlow — The Digital Archeologist

> **Autonomous AI Coding & Self-Healing CI/CD Agent**  
> *Surgically detects, isolates, and repairs software bugs in 100+ line codebases using lightweight local LLMs.*

---

## 🌟 Overview

**LogicFlow** is an autonomous AI coding agent designed to automate the bug repair lifecycle. Unlike naive AI fixers that attempt to rewrite entire files from scratch (frequently truncating lines, dropping imports, or hallucinating), LogicFlow utilizes **Surgical AST Slicing**:

1. **Autonomous Error Detection**: Executes unit tests or parses compiler stack traces to pinpoint the exact broken file and function.
2. **Surgical AST Slicing**: Isolates *only* the buggy 10–25 line function from a 100+ line codebase, protecting all surrounding code from accidental modification or truncation.
3. **Lightweight Local Inference**: Optimized for lightweight models such as `llama3.2:3b` via **Ollama**, ensuring fast local repairs without overloading laptop hardware or draining battery.
4. **Multi-Tier Sandbox Verification**: Validates candidate fixes inside isolated **Docker sandboxes** or local test runners against syntax compilers and full test suites (`pytest`, `unittest`).
5. **OWASP Security Review**: Analyzes proposed code against security guidelines and scans for injection primitives (`eval`, `exec`, `os.system`, command/SQL injection, hardcoded secrets, XSS).
6. **Git/GitHub Publishing**: Automatically creates isolated fix branches, commits patches, and files Pull Requests (with automatic fallback to local bash commands if offline).

---

## 🏗️ Architecture

```
                          ┌───────────────────────────┐
                          │     User Interface        │
                          │   CLI (main.py) / Web UI  │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │   Autonomous Detection    │
                          │ Runs Test Suite / Scanner │
                          └─────────────┬─────────────┘
                                        │ (Error / Assertion Failure)
                                        ▼
                          ┌───────────────────────────┐
                          │  AST Slicing (ast_tool)   │
                          │ Isolates Target Function  │
                          │  Protects 100+ Line File  │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │   Lightweight Local LLM   │
                          │     Ollama (llama3.2:3b)  │
                          └─────────────┬─────────────┘
                                        │ (Surgical Patch)
                                        ▼
                          ┌───────────────────────────┐
                          │  AST Splice & Integration │
                          │ Replaces function cleanly │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │   Sandbox Verification    │
                          │ Tier 1: Syntax / Compile  │
                          │ Tier 2: Unit Test Suite   │
                          └─────────────┬─────────────┘
                                        │
                   ┌────────────────────┴────────────────────┐
                   ▼                                         ▼
            [Tests Passed]                            [Tests Failed]
                   │                                         │
                   ▼                                         ▼
        ┌─────────────────────┐                   ┌─────────────────────┐
        │  OWASP Security     │                   │ Self-Healing Retry  │
        │  Heuristic Audit    │                   │ Feeds error to LLM  │
        └──────────┬──────────┘                   └─────────────────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │ Apply / GitHub PR   │
        └─────────────────────┘
```

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.10+** (Python 3.11–3.13 supported)
- **Ollama** installed and running locally:
  ```bash
  ollama run llama3.2:3b
  ```
- *(Optional)* **Docker Desktop** running (for containerized compilation sandbox)

### 2. Installation
Clone the repository and install dependencies in a virtual environment:
```bash
python -m venv .venv
.\.venv\Scripts\activate      # Windows
# source .venv/bin/activate   # Linux / macOS

pip install -r requirements.txt
```

### 3. Configuration (`.env`)
Create or edit your `.env` file:
```env
# Ollama Local LLM
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TIMEOUT=300

# LogicFlow Paths
LOGICFLOW_WORKSPACE=./workspace
LOGICFLOW_FAISS_PATH=./faiss_index
LOGICFLOW_EMBEDDING_MODEL=all-MiniLM-L6-v2

# Optional GitHub Integration
GITHUB_TOKEN=your_personal_access_token
GITHUB_REPO=owner/repo_name
GITHUB_BASE_BRANCH=main
```

---

## 💻 CLI Commands

Check system status (Ollama, Docker, GitHub, Index):
```bash
python main.py status
```

### 1. Autonomous Test & Repair (`test-and-fix`)
Autonomously runs the workspace test suite, captures any failing assertions or runtime errors, identifies the target file and broken function via AST, generates a surgical fix, and re-tests until all tests pass:
```bash
# Autonomous scan across the whole workspace:
python main.py test-and-fix --workspace workspace/logicflow-test-repo

# Target a specific test suite:
python main.py test-and-fix --workspace workspace/logicflow-test-repo --test test_payroll_calculator.py
```

### 2. Local File Repair (`fix-local`)
Directly repair a file with an error message or stack trace without needing a GitHub issue:
```bash
python main.py fix-local --file logicflow-test-repo/bug_fixtures/logic_error.py --error "Logic bug: calculate_total should multiply price by quantity"
```

### 3. Build / Reload FAISS Semantic Code Index (`index`)
Index all source code in the workspace for RAG dependency retrieval:
```bash
python main.py index --workspace ./workspace
```

### 4. GitHub Issue Workflow (`fix`)
Fetch an open GitHub issue, retrieve codebase context, compile-test in Docker, and submit an automated Pull Request:
```bash
python main.py fix 1
```

### 5. Launch Visual Dashboard (`dashboard`)
Launch the interactive Streamlit Web UI:
```bash
python main.py dashboard
# Or directly:
streamlit run dashboard/streamlit_app.py
```

---

## 🖥️ Streamlit Web Dashboard

The web dashboard provides an interactive control panel:
- **System Status Indicators**: Live connectivity diagnostics for Ollama, Docker, and GitHub.
- **Repository Indexer**: Build, reload, and inspect FAISS code vector chunks.
- **Autonomous Test & Repair Tab**: One-click execution of the self-healing test loop.
- **Local File Repair Tab**: Direct file selection and error trace input.
- **GitHub Issue Workflow Tab**: Browse open GitHub issues and generate PRs.
- **Live Execution Logs & Results**: Step-by-step progress logs, OWASP security badges, fix explanations, and syntax-highlighted patched code previews.

---

## 📁 Repository Structure

```
.
├── config.py                 # Central configuration dataclasses & compiler maps
├── main.py                   # Unified CLI entry point
├── requirements.txt          # Python dependencies
├── .env                      # Environment configuration & credentials
├── agents/
│   ├── __init__.py
│   └── core.py               # LogicFlowAgent orchestrator & self-healing loop
├── dashboard/
│   └── streamlit_app.py      # Streamlit Web UI
├── tools/
│   ├── __init__.py           # Package initializer
│   ├── ast_tool.py           # AST parser, surgical function slicer & splicer
│   ├── docker_test_tool.py   # Multi-tier compilation and test execution sandbox
│   ├── faiss_tool.py         # FAISS vector indexer & token-saving ContextTrimmer
│   └── github_tool.py        # PyGithub issue parser, branch creator & PR manager
├── faiss_index/              # Persisted vector database & chunk metadata
└── workspace/
    └── logicflow-test-repo/  # Test repository with benchmarks
        ├── payroll_calculator.py       # 135-line complex business logic module
        ├── test_payroll_calculator.py  # Unit test suite for payroll calculator
        ├── calculator.py               # Arithmetic module
        ├── calculator_api.py           # JSON HTTP API
        ├── test_calculator.py          # Unit tests
        └── bug_fixtures/               # Isolated logic, syntax, and import bugs
```

---

## 🛡️ Security & Privacy

- **100% Local Inference**: Source code never leaves your local machine; queries are handled entirely by your local Ollama instance and local embeddings.
- **Docker Sandboxing**: Code validation runs with `--network=none`, memory constraints (512MB), and CPU quotas to prevent runaway execution or network calls.
- **OWASP Heuristic Scanner**: Scans all proposed fixes against common vulnerability vectors prior to committing.
