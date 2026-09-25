# LogicFlow Complex Error Benchmark Suite

This directory contains real-world, complex multi-line modules (all **50 to 90+ lines of code**) specifically crafted to test and train the **LogicFlow Autonomous AI Coding Agent**.

These benchmarks cover two categories:
1. **Modules WITH GitHub Issues**: Linked to issues on `https://github.com/kavya12024/logicflow-test-repo` for the GitHub Issue workflow.
2. **Modules WITHOUT GitHub Issues**: Production modules with complex logic, mathematical, and state errors detectable autonomously via unit tests or compiler pre-checks.

---

## Benchmark Catalog

| File Name | Lines | Category | Issue # | Bug Description | Verification Test |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`banking_transaction_processor.py`** | 88 lines | **WITH Issue** | Issue #9 | Double fee deduction in `process_withdrawal`: Fee is debited twice from account balance. | `test_banking_transaction_processor.py` |
| **`token_bucket_rate_limiter.py`** | 78 lines | **WITH Issue** | Issue #10 | Negative token state: `allow_request` decrements tokens before checking sufficiency. | `test_token_bucket_rate_limiter.py` |
| **`ecommerce_discount_engine.py`** | 92 lines | **WITHOUT Issue** | None | Tax calculation bug: Sales tax applied to gross subtotal instead of discounted taxable amount. | `test_ecommerce_discount_engine.py` |
| **`fleet_telemetry_analyzer.py`** | 84 lines | **WITHOUT Issue** | None | Trigonometry bug: `haversine_distance` passes raw degrees instead of converting to radians. | `test_fleet_telemetry_analyzer.py` |
| **`session_cache_lru.py`** | 75 lines | **WITHOUT Issue** | None | Eviction order bug: `put()` updating existing key forgets to refresh LRU priority (`move_to_end`). | `test_session_cache_lru.py` |
| **`payroll_calculator.py`** | 132 lines | **WITHOUT Issue** | None | Overtime wage calculation and progressive tax deduction tiers. | `test_payroll_calculator.py` |
| **`aiml.py` / `tictactoe.py`** | 50 lines | **WITH Issue** | Issue #7 | Multi-error Tic-Tac-Toe: 7 syntax, indentation, and variable naming errors. | Compiler & game loop |

---

## How to Test Each Scenario with LogicFlow

### Mode 1: Autonomous Test Detection & Repair (No GitHub Issue Required)
Run LogicFlow against any of the benchmark test suites. LogicFlow runs the test, captures the assertion diff, surgically isolates the failing function, repairs it with `llama3.2:3b`, and re-verifies:

```bash
# Test & repair Ecommerce discount tax bug:
python main.py test-and-fix --workspace workspace/logicflow-test-repo --test test_ecommerce_discount_engine.py

# Test & repair Fleet GPS Haversine trigonometry bug:
python main.py test-and-fix --workspace workspace/logicflow-test-repo --test test_fleet_telemetry_analyzer.py

# Test & repair Session Cache LRU eviction bug:
python main.py test-and-fix --workspace workspace/logicflow-test-repo --test test_session_cache_lru.py
```

---

### Mode 2: Local File Repair (Direct Surgical Fix)
Repair any local file with an error description or assertion failure:

```bash
python main.py fix-local --file banking_transaction_processor.py --error "AssertionError: remaining balance 4897.0 != 4898.50 due to double fee deduction"
```

---

### Mode 3: Upload & Auto-Fix Full Code (Web Application)
1. Open the interactive dashboard:
   ```bash
   python main.py dashboard
   ```
2. Navigate to the **"📤 Upload & Auto-Fix Code"** tab.
3. Upload any broken script or paste your code.
4. Click **"🚀 Analyze & Auto-Fix Code"**.

---

### Mode 4: GitHub Issue Workflow
1. Select the **"🐙 GitHub Issue Workflow"** tab in the dashboard.
2. Select an open issue (e.g. Issue #7, #8, #9).
3. Click **"Launch Fix for Issue"**. LogicFlow will fetch the issue, branch, commit, and create a Pull Request!
