# Original User Request

## Initial Request — 2026-11-20T11:34:28Z
# Cloud-Native AI Coding Harness

Working directory: `c:\Users\Sujal\Desktop\Work\cloud-native-ai-coding-harness`
Host: Windows, Docker Desktop with WSL2. All containers are Linux. Add `.gitattributes` enforcing LF; use forward slashes inside containers.

Integrity mode: `development` means compose defaults use local services and dev auth, bound to localhost only. Every security requirement in section 8 still applies in this mode. `production` (see `HARNESS_ENV`) additionally refuses dev auth and the scripted LLM.

## 1. Outcome

A full-stack system where a user submits a repository and a task, an autonomous coding agent works on it inside an isolated, ephemeral Docker sandbox, and the user watches and steers the run live from a web dashboard. A finished run yields a git patch that applies cleanly to the original repository.

`docker compose up --build` with only an LLM API key in `.env` brings up the whole system, with everything else running locally. Provider selection rules are in section 3.6.

Items marked **MUST** are required for acceptance. Items marked **SHOULD** are built only after every MUST works end to end. Nothing is a SHOULD unless listed in section 10.

## 2. Versions

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async + Alembic, `docker` SDK, `boto3`, `httpx`, `pytest` + `pytest-asyncio`, `ruff`. Node 20, Vite, React 18, TypeScript strict, Tailwind, shadcn/ui, `lucide-react`, `@xterm/xterm` + `@xterm/addon-fit`, `react-diff-viewer-continued` (or `diff` + custom side-by-side), `eslint`, `vitest`. Postgres 16, MinIO (pin a dated release tag), `tecnativa/docker-socket-proxy` (pin a tag).

## 3. Fixed contracts

Tests are written against these. Implement names and shapes exactly, and document them in the README.

### 3.1 Architecture
Dependencies point inward: `api/` → `application/` → `domain/`; `infrastructure/` implements `domain` ports. The orchestrator imports only `domain`. A single composition root, `bootstrap.py`, selects concrete adapters from env vars. Adding an LLM provider requires a new class and a registry entry, and no orchestrator edit.

**Single Backend Architecture:** The harness architecture (in-memory run state synchronization, serialized monotonic event sequence assignment, concurrency gating, and restart recovery) is explicitly designed for a single-replica backend instance. Multi-replica deployments are out of scope.

### 3.2 Domain protocols (`typing.Protocol`, runtime-checkable)
- `IExecutionTerminal`: `run(command, cwd="/workspace", timeout=None) -> AsyncIterator[ExecEvent]`, `cancel_current()`
- `IFileAccess`: `read_file`, `write_file`, `list_dir`, `upload_workspace(tar_gz)`, `download_workspace() -> tar_gz`
- `ILogStreamer`: `subscribe() -> AsyncIterator[LogEvent]`, replaying from the start, then live
- `ISandboxEnvironment`: the three above plus `id`, `start()`, `stop()` (idempotent)
- `ISandboxProvider`: `acquire(spec) -> ISandboxEnvironment`
- `ILLMProvider`: `complete(messages, tools) -> LLMResponse`
- `IObjectStorage`: `put`, `get`, `presigned_url(key, ttl)`
- `IRunRepository`: `create`, `get`, `list`, `update_status`, `append_event`, `list_events`
- `IAuthProvider`: `authenticate(request) -> User`

A component needing only part of the sandbox depends only on that interface. All implementations, including `FakeSandbox`, must be substitutable for one another.

### 3.3 Event schema
Every event in a run (reasoning, plan, decision, tool call, tool result, terminal output, status change, guidance) is `{seq, ts, type, payload}` with **one persisted, gap-free, monotonic `seq` per run**. Sequence assignment is serialized per run, so concurrent producers (the agent loop, the terminal coalescer, control endpoints) can never produce gaps or duplicates. The WebSocket `after=seq` and `GET /events` use this same counter. Terminal output is coalesced (flush every 100 ms or 4 KB, whichever comes first), keeps stdout and stderr separate, and is capped per run with an explicit truncation marker event.

### 3.4 Run states and state transitions
Valid lifecycle states: `QUEUED`, `PREPARING`, `RUNNING`, `PAUSED`, `SUCCEEDED`, `FAILED`, `TERMINATED`.

**State transition matrix:**
- `QUEUED`: can transition to `PREPARING` or `TERMINATED`.
- `PREPARING`: can transition to `RUNNING` or `TERMINATED`. Calling `pause` while in `PREPARING` returns 409 Conflict (pause is valid only from `RUNNING`).
- `RUNNING`: can transition to `PAUSED`, `SUCCEEDED`, `FAILED`, `TERMINATED`.
  - For `boundary` pause, an explicit `is_pausing: bool` flag is set while the current step finishes before fully entering `PAUSED`. `is_pausing` is exposed in `GET /api/runs/{id}`, and a status event is emitted when `is_pausing` changes.
  - Calling `resume` while `is_pausing=True` cancels the pending boundary pause (clears `is_pausing`, returns 200).
- `PAUSED`: can transition to `RUNNING` (via resume) or `TERMINATED`.
- **Control idempotency vs. terminal immutability:**
  - Repeating the *same* control action that produced or matches the current state returns 200 OK as a no-op (e.g. `terminate` on `TERMINATED`, `pause` on `PAUSED`, `resume` on `RUNNING`).
  - Calling a *different* control on a terminal run (or any invalid transition, such as `pause` or `resume` on `TERMINATED`, or `resume` on `QUEUED`) returns 409 Conflict.

### 3.5 Endpoints & Per-User Isolation
```
POST /api/runs                      {repo_url | archive upload, task, options: {verification?: "required" | "none"}}
GET  /api/runs        GET /api/runs/{id}
POST /api/runs/{id}/pause           {"mode": "boundary" | "now"}
POST /api/runs/{id}/resume   POST /api/runs/{id}/terminate
POST /api/runs/{id}/guidance        {"message": str}
GET  /api/runs/{id}/events?after=seq
WS   /api/runs/{id}/stream?after=seq&token=...
GET  /api/runs/{id}/artifacts       patch, logs, transcript with presigned URLs
GET  /api/runs/{id}/diff            per-file before/after for the viewer
GET  /healthz    GET /readyz        (readyz fails until DB, storage, docker-proxy, and sandbox image are all ready)
```
- **Per-User Scoping:** All runs are strictly scoped to the authenticated user. In multi-user modes (e.g. Clerk), if User A attempts to access User B's run, events, artifacts, diff, or WebSocket stream, the API MUST return 404 (preventing run ID enumeration and existence leakage).
- **Namespaced S3 Artifact Keys:** Artifact keys in S3 must be partitioned by user ID and run ID (`artifacts/{user_id}/{run_id}/...`) so presigned URLs cannot be guessed or derived across users.
- Browsers cannot set WebSocket headers, so the token goes in the query string. `DevAuthProvider` ignores it, so the dashboard connects without login. The frontend nginx config excludes or masks the `token` parameter in access logs.
- `GET /api/runs/{id}` returns run details including `is_pausing: bool`.
- `MAX_CONCURRENT_RUNS` is enforced; surplus runs stay `QUEUED`.

### 3.6 Environment variables and provider selection
Provide `.env.example` containing all of these, with comments. `LLM_PROVIDER` is blank by default.
```
HARNESS_ENV=development|test|production
LLM_PROVIDER=anthropic|openai|scripted     # blank = infer; scripted accepted only when HARNESS_ENV=test
LLM_MODEL=   ANTHROPIC_API_KEY=   OPENAI_API_KEY=   OPENAI_BASE_URL=
AUTH_PROVIDER=dev|clerk   CLERK_JWKS_URL=   CLERK_ISSUER=
DATABASE_URL=postgresql+asyncpg://...
S3_ENDPOINT_URL=   S3_PUBLIC_ENDPOINT_URL=   S3_BUCKET=   S3_ACCESS_KEY=   S3_SECRET_KEY=   S3_REGION=
DOCKER_HOST=tcp://docker-proxy:2375
SANDBOX_IMAGE=harness-sandbox:latest   SANDBOX_NETWORK_MODE=none
SANDBOX_CPU_LIMIT=1.0   SANDBOX_MEM_LIMIT=1g   SANDBOX_PIDS_LIMIT=256   SANDBOX_WARM_POOL_SIZE=2
SANDBOX_WORKSPACE_SIZE=384m   SANDBOX_TMP_SIZE=128m
MAX_CONCURRENT_RUNS=4   AGENT_MAX_STEPS=40   AGENT_MAX_TOKENS=200000
AGENT_MAX_CONSECUTIVE_FAILURES=5   COMMAND_TIMEOUT_SECONDS=120
MAX_UPLOAD_MB=50   MAX_OUTPUT_BYTES_PER_RUN=5242880   CORS_ORIGINS=
```
**Provider selection (single source of truth; other sections refer here):**
- `LLM_PROVIDER` set explicitly: use it; its key must be present (`scripted` needs none).
- `LLM_PROVIDER` unset and exactly one of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` set: use that provider.
- Both keys set and `LLM_PROVIDER` unset: fail fast at startup with a message asking the user to set `LLM_PROVIDER`.
- No key set (and not `scripted`): fail fast naming both key variables.

**Model default:** if `LLM_MODEL` is unset, each provider uses a default model pinned in one config file. The implementer picks a current model for each provider and documents it in the README.

**Startup rules & tmpfs memory headroom:**
- tmpfs mounts count against container memory cgroups. Total tmpfs memory (`SANDBOX_WORKSPACE_SIZE` + `SANDBOX_TMP_SIZE`) must not exceed 60% of `SANDBOX_MEM_LIMIT` to avoid cgroup OOM kills. Shipped defaults (384m + 128m = 512m, exactly 50% of 1g) pass this rule. Startup must fail fast naming the variables if headroom is violated. A unit test asserts that shipped defaults pass headroom validation.
- When `HARNESS_ENV=production`, `AUTH_PROVIDER=dev` and `LLM_PROVIDER=scripted` are refused. `LLM_PROVIDER=scripted` is refused unless `HARNESS_ENV=test`.

Compose sets `AUTH_PROVIDER=dev`, `DATABASE_URL` to the `postgres` service, and the S3 variables to the `minio` service. Compose publishes the frontend and backend ports on `127.0.0.1` only, because dev auth plus a real LLM key must not be reachable from the network.

## 4. Behaviors that must be true: agent runs

- The agent can inspect a repository, edit files, and run compile/lint/test commands, always through sandbox interfaces, using JSON-schema tools:
  - `read_file(path: str)`
  - `write_file(path: str, content: str)`
  - `list_dir(path: str)`
  - `run_command(command: str, purpose: "test" | "other" = "other")`
  - `finish(summary: str)`
- Every thought, plan, decision, tool call, and result is visible as an event while it happens.
- When a test, lint, or compile command fails, the agent sees the (truncated) failure and can correct course. After `AGENT_MAX_CONSECUTIVE_FAILURES` the run ends `FAILED` with a stated reason. `AGENT_MAX_STEPS` and `AGENT_MAX_TOKENS` are hard limits.
- **Definition of SUCCEEDED & Fresh Verification:**
  - When run option `verification` is `"required"` (default): `finish` transitions the run to `SUCCEEDED` only if at least one test command (`purpose="test"`) was executed, the most recent test command exited with code 0, AND no `write_file` tool call occurred after that passing test. If `write_file` was called after the last passing test, `finish` fails the run with `FAILED(reason=finish_without_fresh_verification)`. If `finish` is called without running tests or while tests are failing, the run fails with `FAILED(reason=finish_with_failing_tests)`.
  - When run option `verification` is `"none"`: `finish` is accepted without requiring test execution.
- **Reproducible baseline & untrusted archive handling:**
  - Before the first agent action, a baseline snapshot of the repository (a git commit with a configured author identity) exists, its baseline commit SHA is recorded in the database, and its archive is stored via `IObjectStorage`, so a clean checkout of the baseline can be reproduced at any time, including after a backend restart.
  - Untrusted archive handling (uploaded archives, baseline snapshots, clean checkouts) must enforce strict tarbomb and traversal defenses: reject directory traversal (`..`), absolute paths, symlinks escaping the target directory, hardlinks, and special files (FIFOs, devices). Enforce limits on maximum decompressed size (bounded by `MAX_UPLOAD_MB`), maximum file count, and maximum compression ratio.
- **Patches & isolated patch validation:**
  - Git diffs must be computed against the specific baseline commit SHA recorded during `PREPARING` (e.g. `git diff --binary <baseline_sha>`), never against `HEAD`, ensuring agent commits in the workspace do not hide modifications.
  - The patch captures **modified, new, deleted, renamed, and binary files**.
  - Patches must be generated and stored for all terminal states (`SUCCEEDED`, `FAILED` including step/token limit exhaustion, and `TERMINATED`) whenever file modifications exist against the baseline snapshot.
  - **Termination timing:** On `terminate`, the patch is extracted *before* destroying the sandbox container. Container destruction must complete within 5 s after patch extraction finishes.
  - **Backend restart exception:** No patch can be produced for runs left in `FAILED(reason=backend_restarted)` because the tmpfs workspace is destroyed upon container exit.
  - A patch is **valid** if and only if `git apply --check` succeeds on a clean checkout of the baseline snapshot.
  - **Patch validation isolation:** `git apply --check` must be executed inside an isolated, throwaway `network=none` sandbox container, never in the host or backend process. Patch, logs, and transcript are stored through `IObjectStorage` and downloadable.
- **Pause:** `boundary` halts at the next step boundary (setting `is_pausing` while completing the in-flight step). `now` also cancels the in-flight command via `cancel_current()`. If an LLM call is in flight, it completes and its result is stored as an event; **no new LLM call starts while paused**.
- **Guidance:** a user message appears in the model's context at its next step and in the event log.
- **Terminate:** the loop and in-flight command stop, the patch is extracted if changes exist, the container is destroyed within 5 s after extraction, and status is set to `TERMINATED`.
- Controls are idempotent.
- LLM calls retry with backoff on 429 and 5xx. Configured secret values never appear in events, logs, or artifacts.
- Run state and events persist in Postgres. After a backend restart, runs left in RUNNING or PAUSED become `FAILED(reason=backend_restarted)`, their sandboxes are reaped, and completed runs and artifacts stay accessible.
- A `git_url` repository is cloned by the backend (shallow, size-limited), never by the sandbox. URLs must be https, and hosts resolving to private, loopback, or link-local addresses are rejected (SSRF guard). The result is uploaded to the sandbox as a tarball. The backend image includes `git`.

## 5. Behaviors that must be true: sandbox

- `DockerSandboxProvider` implements `ISandboxProvider`.
- **Docker access:** the backend reaches Docker only through `docker-socket-proxy`. `/var/run/docker.sock` is never mounted into the backend; the README explains why. Enable only the proxy API sections the harness needs (containers, exec, and image inspect for `readyz`), and verify the exact variable names against the proxy's README. The proxy filters by API section and method, not request body, so it cannot forbid privileged containers. That guarantee therefore comes from code and tests: no code path sets privileged mode, host mounts, host network, or added capabilities, and a test asserts the created container's HostConfig.
- **Exec Stdin Streaming Spike & Fallback:** As the very first task built, implement and execute a spike test of exec stdin streaming through `docker-socket-proxy`. The Docker SDK high-level `exec_run` does not stream stdin, requiring low-level hijacked socket attachment across the proxy. If socket hijacking fails or proves unreliable across the proxy, use the specified fallback: chunked base64 transfer in 64 KB chunks over short exec calls with SHA-256 checksum verification after reassembly in the container. The implementation must not improvise untested transfer mechanisms.
- **Hardening & No Secrets in Sandbox:**
  - Non-root user, `cap-drop ALL`, `no-new-privileges`, read-only root filesystem, CPU/memory/pids limits from env, no host mounts, network `none`.
  - The sandbox container receives zero backend environment variables or cloud credentials. A test asserts that `env` inside the sandbox contains no secrets or backend configuration.
- **Writable areas:** `/workspace` (`SANDBOX_WORKSPACE_SIZE`) and `/tmp` (`SANDBOX_TMP_SIZE`) are tmpfs mounts with `exec,nosuid,nodev`. Docker mounts tmpfs `noexec` by default, so `exec` is required to run compiled binaries, venv executables, and `node_modules/.bin` scripts. A test runs an executable from `/workspace`.
- **Tooling works under a read-only root:** set `HOME=/tmp`, `PYTHONDONTWRITEBYTECODE=1`, and cache directories under `/tmp`, so git, pytest, pip, and npm run normally.
- **Workspace transfer:** Tarballs move through `exec` stdin/stdout (`tar -x` / `tar -c`) or the 64 KB chunked base64 fallback with SHA-256 validation. Round trips are lossless for file contents and modes.
- **Path safety:** `..`, absolute paths outside `/workspace`, and symlinks escaping it are rejected with a typed error.
- **Boot latency & warm pool spec matching:**
  - Under 5 s from `acquire()` to the first successful command on a pre-built image, using a warm pool of `SANDBOX_WARM_POOL_SIZE` idle containers replenished in the background. `boot_ms` is recorded per run. The sandbox image is built before the backend reports ready.
  - Warm pool containers only serve runs with default resource limits. Custom `SandboxSpec` requests bypass the warm pool, perform a cold boot, and are exempt from the 5s boot limit.
- **Ephemeral:** containers are destroyed on success, failure, termination, and backend shutdown. At startup, orphans labeled `harness.managed=true` are reaped.
- **Streaming:** stdout/stderr chunks reach `ILogStreamer` while a command is still running, in order, with stdout and stderr distinguishable.
- `sandbox/Dockerfile` provides Python, Node, git, and common build tools. `FakeSandbox` exists in the test support package only.

## 6. Behaviors that must be true: control plane

Dark-mode-first, responsive at 1280 px and 768 px, Tailwind + shadcn/ui + Lucide. Real data only; no mock data in the production build.

- **Session manager:** concurrent runs with live status badges, a create-run dialog (including verification mode option), and artifact download links.
- **Run view:** reasoning stream (thoughts, plan steps, decisions, collapsible tool calls, sub-task progress, auto-scroll with "jump to latest"); xterm terminal with fit addon, stdout/stderr visually distinct, replay from seq 0 for late joiners, and no duplicated output after reconnect; side-by-side diff viewer with file tree, add/delete counts, and live updates; control bar with Pause (both modes), Resume, Guidance input, and Terminate with confirmation.
- One WebSocket per open run, reconnecting automatically with `after=seq`.
- Loading, empty, and error states in every panel; keyboard-accessible controls.

## 7. Behaviors that must be true: cloud adapters and containerisation

- **LLM:** `AnthropicProvider`, `OpenAIProvider` (honoring `OPENAI_BASE_URL`), selected per section 3.6.
- **Scripted provider:** `ScriptedLLMProvider` lives in the test support package. `backend/Dockerfile` has two build targets: `prod` (no test package) and `test` (adds the test support package). Only `docker-compose.test.yml` selects the `test` target. The scripted provider replays the fixture `samples/buggy-calculator/scripted_run.json`, which contains the tool calls that fix the sample's bug. Production code paths never import test code, and the `prod` image does not contain it.
- **Auth:** `DevAuthProvider` (fixed user); `ClerkAuthProvider` (JWT verification through JWKS and issuer, including for WebSocket tokens), tested against a locally generated JWKS.
- **Storage:** `S3ObjectStorage` via `boto3`, working with MinIO and AWS S3. Presigned URLs are signed against `S3_PUBLIC_ENDPOINT_URL` so a browser outside compose can open them.
- **Metadata:** Postgres via SQLAlchemy async + Alembic, compatible with local Postgres, Neon, and Supabase. Migrations run automatically on backend start.
- **Containers:** multi-stage non-root `backend/Dockerfile` (targets above); `frontend/Dockerfile` (nginx serving static files and proxying `/api` including WebSocket upgrade); `sandbox/Dockerfile`; root `docker-compose.yml` with `frontend`, `backend`, `postgres`, `minio` (+ bucket init), `docker-proxy`, and a `sandbox-image` build job. Long-running services use health checks with `depends_on: condition: service_healthy`. One-shot jobs (`sandbox-image`, bucket init) use `condition: service_completed_successfully`. `docker-compose.test.yml` overrides the backend to the `test` target with `HARNESS_ENV=test` and `LLM_PROVIDER=scripted`.

## 8. Security (MUST)

- No host Docker socket in the backend; per-sandbox hardening as in section 5; traversal-safe and tarbomb-safe file access; commands run only inside sandboxes.
- **Untrusted Repos & Prompt Injection:** Repository content and task descriptions are untrusted inputs capable of indirect prompt injection. `SECURITY.md` must analyze this threat model, with `SANDBOX_NETWORK_MODE=none` documented as the primary data exfiltration defense.
- **No secrets to sandbox:** Sandbox containers receive zero backend credentials or config env vars.
- **Per-user isolation:** Cross-user run access returns 404 across all endpoints and WebSocket connections. S3 artifact keys are partitioned by user ID (`artifacts/{user_id}/{run_id}/...`).
- Secrets redacted everywhere; CORS limited to `CORS_ORIGINS`; upload size limits; short-TTL presigned URLs; SSRF guard on repo URLs; WebSocket tokens kept out of access logs; ports bound to localhost in compose; dev auth and scripted LLM refused in `production`.
- Patch validation (`git apply --check`) executed exclusively within isolated throwaway sandboxes.
- Ship `SECURITY.md` with threat model, residual risks (for example: Docker daemon remains a high-value target behind the proxy), and known limitations.

## 9. Verification and independent review

### 9.1 Tests to ship
- **Backend (`pytest`, `ruff`):**
  - Spike test: exec stdin streaming through `docker-socket-proxy` (or 64 KB chunked base64 fallback with SHA-256 verification).
  - Headroom validation test: assert shipped `.env.example` defaults pass startup headroom validation.
  - Control idempotency test: repeating same control returns 200, conflicting control returns 409.
  - Unit tests: domain models, state transitions (including `is_pausing` flag, boundary pause cancellation via resume, and 409 rejections), tarbomb and path traversal guard, SSRF guard, redaction, patch-validity helper (modified, new, deleted, renamed, binary files), provider selection rules, and event sequencing (concurrency test with simultaneous producers).
  - Security tests: per-user isolation returning 404 for User A accessing User B's resources, tested against Clerk auth provider with two distinct tokens from a local test JWKS keypair; sandbox `env` secret absence assertion; isolated sandbox patch validation test.
  - Orchestration tests with `FakeSandbox` and `ScriptedLLMProvider`: success, self-correction after a failing test, finish tool validation (`finish_without_fresh_verification`, `finish_with_failing_tests`, and `verification: "none"`), pause (both modes, including during in-flight LLM call), resume, guidance, terminate (asserting patch extracted before container destruction and container destroyed within 5 s after extraction), baseline SHA diffing (asserting diff generated against baseline commit SHA even if agent committed changes), step/token limits, restart recovery (asserting no patch produced for backend_restarted).
  - Adapter tests (`@pytest.mark.docker`): boot under 5 s, streaming order, stdout/stderr separation, workspace round trip under read-only root, executable runs from `/workspace`, network isolation, HostConfig assertions, cleanup. S3 adapter against MinIO with namespaced keys. Fail-fast config errors naming the variable.
- **Frontend:** `npm run build` and `npm run lint` exit 0; `vitest` for the event reducer and WebSocket reconnect/dedupe logic.
- **E2E `scripts/e2e.py`:** runs against `samples/buggy-calculator/`, a small Python repo you create, using only the standard library plus pytest and containing a deliberate bug that a failing test exposes (no installs are possible with network `none`). It asserts sandbox boot, at least one file write, a test command executed, stdout/stderr captured, final status `SUCCEEDED`, a valid patch that passes `git apply --check` in an isolated sandbox, and the sample's tests passing after the patch. Exits non-zero on any failure.
  - In real-LLM mode: passes at least once in up to 3 attempts. Attempt history must be recorded in `docs/e2e-attempts.md`.
  - In `--scripted` mode: brings the stack up with `docker-compose.test.yml` override (real Docker sandbox, no LLM key) and passes on the first run.
- **`docs/manual-verification.md`:** a click-through checklist covering the dashboard, terminal, diff viewer, and every control.

### 9.2 Independent review (required)
The builder does not certify its own work, and no session that wrote the code reviews it. The repository's `SPEC.md` must be a byte-identical copy of this document.

**Review process & document separation:**
- `docs/e2e-attempts.md`: Maintained by the builder to record real-LLM e2e attempt history.
- `docs/review-report.md`: Reviewer-only report. The coordinator/user starts each independent review round manually in a fresh session (ideally on a different model, with no access to the build transcript) and pastes the reviewer's output verbatim into `docs/review-report.md`. The builder is strictly forbidden from editing `docs/review-report.md`. Maximum 3 review rounds.

Reviewer prompt:
```
Review the repository against the spec you were given. First confirm the repo's
SPEC.md is identical to your copy; report any difference as a failure. You have the
repo and a shell; you have no knowledge of how it was built. For every acceptance
criterion in section 11, run the command or perform the check yourself and report PASS
or FAIL with the evidence (command and output). Do not infer a pass from reading code.

Tools to use: pytest -m "not docker" and pytest -m docker, ruff check, npm run build,
npm run lint, vitest, docker compose up --build, docker inspect on a sandbox
container, docker compose ps, curl against /readyz and the API, scripts/e2e.py
(both modes), git apply --check on the produced patch, a WebSocket client.

Questions to answer:
- What is the strongest argument that this does not meet the spec?
- Can the sandbox write outside /workspace and /tmp, reach the network, or gain
  privileges? Show the attempt.
- Does Terminate extract the patch before destroying the container, and destroy the container within 5 s after extraction? Does Pause really stop new LLM calls?
- Does any production code path import test-only code or accept mock data? Does the prod
  image contain the test support package?
- Are ports reachable from outside localhost? Does a WebSocket token appear in any log?
- Does cross-user access return 404 without leaking run existence?
- Do sandbox containers receive any backend secrets or env vars?
- Are S3 artifact keys partitioned by user ID?
- Do shipped .env.example defaults pass headroom validation?
- Does finish require fresh verification when verification="required"?
- Which spec items are met only by a mock, a stub, or a hard-coded value?
- What fails if the backend restarts mid-run? If the browser reconnects mid-stream?
- Which statements in the README or SECURITY.md are untrue?
Finish with a list of failures ordered by severity (critical, high, medium, low).
```
Failures found by the reviewer go back to the builder as concrete defects, then a new fresh review round is started manually by the coordinator/user.

## 10. SHOULD items (only after all MUSTs work)

Playwright smoke test asserting the run list, reasoning stream, terminal, and diff viewer render live data; `SANDBOX_NETWORK_MODE=allowlist` using a restricted bridge network with documented egress rules.

## 11. Acceptance criteria

- [ ] `pytest` passes, including `@pytest.mark.docker` tests when Docker is available; `ruff` reports no errors.
- [ ] `npm run build` and `npm run lint` exit 0; `vitest` passes.
- [ ] Shipped `.env.example` defaults pass startup headroom validation (covered by test).
- [ ] Repeating the same control on matching run state returns 200 OK; invalid transitions return 409 Conflict.
- [ ] Calling `resume` while `is_pausing=True` cancels boundary pause; `is_pausing` is exposed in `GET /api/runs/{id}` and emits status events.
- [ ] `scripts/e2e.py` passes: in real-LLM mode at least once in up to 3 attempts (attempt history recorded in `docs/e2e-attempts.md`), and in `--scripted` mode (via `docker-compose.test.yml`) on first attempt; the patch passes `git apply --check` in an isolated sandbox and the sample's tests pass after applying it.
- [ ] The `finish` tool enforces fresh test verification when `verification="required"` (failing with `finish_without_fresh_verification` if `write_file` occurred after the last passing test, or `finish_with_failing_tests` if tests failed/unrun), and permits completion without tests when `verification="none"`.
- [ ] Git diffs are computed against the recorded baseline commit SHA; patches reproduce modified, new, deleted, renamed, and binary changes across all terminal states where changes exist; on terminate, patch extraction occurs before container destruction, and destruction completes within 5 s after extraction.
- [ ] A baseline snapshot is stored in `IObjectStorage` before the first agent action and can be restored to a clean checkout; untrusted archives enforce tarbomb and path traversal defenses.
- [ ] Tests assert `boot_ms` < 5000 on a warm image, and that an executable runs from `/workspace`.
- [ ] Tests assert: Pause starts no new LLM call; Guidance appears in the next model context.
- [ ] Event `seq` is gap-free under concurrent producers (concurrency test passes).
- [ ] Cross-user access returns 404 across runs, events, diff, artifacts, and WebSocket stream (tested against Clerk provider with test JWKS); S3 artifact keys are namespaced by user ID (`artifacts/{user_id}/{run_id}/...`).
- [ ] Sandbox containers receive zero backend secrets or environment variables (asserted by test).
- [ ] Total tmpfs memory (`SANDBOX_WORKSPACE_SIZE` + `SANDBOX_TMP_SIZE`) must not exceed 60% of `SANDBOX_MEM_LIMIT`; startup fails fast naming the variables if headroom is violated.
- [ ] Missing or conflicting env vars fail startup with a message naming the variable (no key; both keys with no `LLM_PROVIDER`); `scripted` is refused outside `HARNESS_ENV=test`; `dev` auth and `scripted` are refused in `production`.
- [ ] `docker compose up --build` brings `frontend`, `backend`, `postgres`, `minio`, and `docker-proxy` to healthy with only an LLM key in `.env`; ports are bound to `127.0.0.1`; the `prod` backend image does not contain the test support package.
- [ ] The dashboard renders live runs, reasoning stream, xterm terminal, and side-by-side diff over WebSocket (no login in dev mode); terminal output appears while a command is still running; a presigned artifact URL opens from the host browser; WebSocket tokens do not appear in nginx access logs.
- [ ] The repo's `SPEC.md` is byte-identical to the original spec, and the independent review (section 9.2) reports no critical or high failures within 3 rounds in `docs/review-report.md`.
- [ ] Deliverables are present: source, three Dockerfiles, `docker-compose.yml`, `docker-compose.test.yml`, `.env.example`, `.gitattributes`, Alembic migrations, sample repo with `scripted_run.json`, tests, e2e script, `SPEC.md`, `docs/manual-verification.md`, `docs/e2e-attempts.md`, `docs/review-report.md`, `SECURITY.md`, `README.md` (quick start, architecture diagram, contract and endpoint reference, default models, adding an LLM provider, running each test tier, Docker Desktop troubleshooting).
