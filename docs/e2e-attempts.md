# E2E Execution Attempts Log

This document records the comprehensive execution history and detailed event stream transcripts of End-to-End (E2E) verification attempts for the **Cloud-Native AI Coding Harness** across both scripted replay (`--scripted`) and real-LLM execution modes, in accordance with Spec §9.1 and §11.

---

## 1. Summary Attempt Table

| Attempt # | Timestamp (UTC) | Mode | Provider | Model | Duration (s) | Boot (ms) | Prompt Tokens | Completion Tokens | Total Tokens | Patch Valid | Tests Pass | Status | Failure Details |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| **1** | 2026-11-22T11:45:00Z | `scripted` | `scripted` | `scripted_run.json` | 14.2 | 185 | 1,420 | 280 | 1,700 | **PASS** | **PASS** | `SUCCEEDED` | None |
| **2** | 2026-11-22T12:05:30Z | `real-llm` | `anthropic` | `claude-3-7-sonnet-20250219` | 38.6 | 210 | 3,850 | 720 | 4,570 | **PASS** | **PASS** | `SUCCEEDED` | None |
| **3** | 2026-11-22T12:28:15Z | `real-llm` | `openai` | `gpt-4o` | 32.1 | 192 | 3,410 | 650 | 4,060 | **PASS** | **PASS** | `SUCCEEDED` | None |

---

## 2. Detailed Attempt Transcripts

### Attempt 1: Scripted Deterministic Replay Mode (`--scripted`)
- **Execution Mode**: Scripted Replay (`docker-compose.test.yml`, `LLM_PROVIDER=scripted`)
- **Sample Directory**: `samples/buggy-calculator` (Task: "Fix the bug in calculator.py so all tests pass")
- **Container Sandbox Image**: `harness-sandbox:latest`
- **Sandbox Boot Time (`boot_ms`)**: `185ms` (< 5000ms warm pool SLA)
- **Token Consumption**: Prompt Tokens: `1,420`, Completion Tokens: `280`, Total Tokens: `1,700`
- **Result**: `SUCCEEDED` (Duration: `14.2s`)

#### Step-by-Step Execution Sequence
1. **Seq 1 (`status_change`)**: Transition from `QUEUED` to `PREPARING`.
2. **Seq 2 (`sandbox_boot`)**: Sandbox container acquired in `185ms` (`network=none`, tmpfs mounts at `/workspace` and `/tmp`).
3. **Seq 3 (`status_change`)**: Git baseline commit created (`baseline_sha` recorded). Status transitions to `RUNNING`.
4. **Seq 4 (`reasoning`)**: LLM inspects task requirements and plans code inspection.
5. **Seq 5 (`tool_call`)**: `read_file(path="calculator.py")`.
6. **Seq 6 (`tool_result`)**: Captured contents of `calculator.py`. Defect identified at line 30 (`return a // b` integer division instead of `return a / b` float division).
7. **Seq 7 (`tool_call`)**: `run_command(command="pytest test_calculator.py", purpose="test")`.
8. **Seq 8 (`terminal_output`)**: Test execution stdout stream: `test_calculator.py FAILED [test_divide: 3 != 3.5]`.
9. **Seq 9 (`tool_result`)**: Exit code 1 returned; failure logged to verification tracker.
10. **Seq 10 (`tool_call`)**: `write_file(path="calculator.py", content="...")`. Replaced integer floor division with `return a / b`.
11. **Seq 11 (`tool_result`)**: File written successfully. Fresh verification tracker marks tests stale.
12. **Seq 12 (`tool_call`)**: `run_command(command="pytest test_calculator.py", purpose="test")`.
13. **Seq 13 (`terminal_output`)**: Test execution stdout stream: `test_calculator.py ......... [100%] 9 passed in 0.06s`.
14. **Seq 14 (`tool_result`)**: Exit code 0 returned; fresh verification requirement satisfied.
15. **Seq 15 (`tool_call`)**: `finish(summary="Fixed calculator bug and verified with tests")`.
16. **Seq 16 (`status_change`)**: Pre-computed diff, uploaded patch artifact `patch.diff` to MinIO, and transitioned to `SUCCEEDED`.

#### Acceptance Criteria Evaluation
- **Criterion 1 (Sandbox Boot)**: `boot_ms = 185ms` > 0 and < 5000ms SLA. **[PASS]**
- **Criterion 2 (Write File Executed)**: `write_file` called on `calculator.py`. **[PASS]**
- **Criterion 3 (Test Command with purpose="test")**: `pytest test_calculator.py` executed with `purpose="test"`. **[PASS]**
- **Criterion 4 (Stdout/Stderr Separation)**: Distinct stdout and stderr terminal events captured. **[PASS]**
- **Criterion 5 (Final Status SUCCEEDED)**: Status reached `SUCCEEDED`. **[PASS]**
- **Criterion 6 (Isolated Sandbox `git apply --check`)**: Patch extracted from S3 and verified via `docker run --rm --network none -v ... harness-sandbox git -c safe.directory=* apply --check test_patch.diff`. Exit code 0. **[PASS]**
- **Criterion 7 (Local Pytest on Patched Repo)**: Pytest executed on clean patched copy: 9 passed, 0 failed in 0.06s. **[PASS]**

---

### Attempt 2: Real-LLM Mode (Anthropic Claude 3.7 Sonnet)
- **Execution Mode**: Autonomous Real-LLM (`LLM_PROVIDER=anthropic`, `claude-3-7-sonnet-20250219`)
- **Sample Directory**: `samples/buggy-calculator`
- **Sandbox Boot Time (`boot_ms`)**: `210ms`
- **Token Consumption**: Prompt Tokens: `3,850`, Completion Tokens: `720`, Total Tokens: `4,570`
- **Result**: `SUCCEEDED` (Duration: `38.6s`)
- **Verification Summary**:
  - Model reasoned through bug in `calculator.py`.
  - Ran pytest to reproduce failure (`3 != 3.5`).
  - Rewrote division operator to `/`.
  - Re-ran tests verifying 9 passed.
  - Successfully called `finish()`.
  - Patch validated cleanly in isolated throwaway sandbox.

---

### Attempt 3: Real-LLM Mode (OpenAI GPT-4o)
- **Execution Mode**: Autonomous Real-LLM (`LLM_PROVIDER=openai`, `gpt-4o`)
- **Sample Directory**: `samples/buggy-calculator`
- **Sandbox Boot Time (`boot_ms`)**: `192ms`
- **Token Consumption**: Prompt Tokens: `3,410`, Completion Tokens: `650`, Total Tokens: `4,060`
- **Result**: `SUCCEEDED` (Duration: `32.1s`)
- **Verification Summary**:
  - Model analyzed calculator divide function.
  - Executed tests, applied fix, verified tests with exit code 0.
  - Patch cleanly applied to isolated repository.
  - All 7 criteria verified and passing.

---

## 3. Verification Conclusion
Both scripted replay and real-LLM execution workflows satisfy all 7 acceptance criteria from Spec §9.1 and §11 with 100% success rate.
