# Cloud-Native AI Coding Harness

An autonomous, full-stack AI coding harness running in isolated, ephemeral Docker sandboxes with live reasoning streaming, interactive terminal control, and side-by-side git diff inspection.

---

## 1. Quickstart

### Prerequisites
- **OS**: Windows with WSL2 and Docker Desktop installed (or Linux / macOS with Docker Engine).
- **Tools**: Git, Docker CLI, Docker Compose v2.
- **API Key**: Anthropic API key (`ANTHROPIC_API_KEY`) or OpenAI API key (`OPENAI_API_KEY`).

### Step-by-Step Launch
1. Clone repository and navigate to root:
   ```bash
   cd cloud-native-ai-coding-harness
   ```
2. Configure environment:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and supply your `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
3. Start the entire local stack:
   ```bash
   docker compose up --build
   ```
4. Access the web dashboard:
   - Web UI: [http://127.0.0.1:3000](http://127.0.0.1:3000)
   - REST API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
   - MinIO Console: [http://127.0.0.1:9001](http://127.0.0.1:9001)

---

## 2. Architecture & Design Principles

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Browser                           │
│            React 18 + Vite SPA (port 3000)                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP/WebSocket (nginx proxy → :8000)
┌──────────────────────────▼──────────────────────────────────────┐
│                   FastAPI Backend (port 8000)                   │
│  api/        ──▶  application/  ──▶  domain/ (interfaces)      │
│                                      ▲                          │
│  infrastructure/ (adapters) ─────────┘                         │
│  ├── auth/      (DevAuthProvider, ClerkAuthProvider)            │
│  ├── llm/       (AnthropicProvider, OpenAIProvider)             │
│  ├── storage/   (S3ObjectStorage via boto3)                     │
│  ├── db/        (PostgresRunRepository via SQLAlchemy async)    │
│  └── sandbox/   (DockerSandboxProvider)                         │
└──────┬───────────────────┬────────────────────────────────────┬─┘
       │                   │                                    │
┌──────▼──────┐  ┌─────────▼─────────┐  ┌──────────────────────▼──┐
│  Postgres   │  │      MinIO        │  │  docker-socket-proxy    │
│  (port 5432)│  │  (ports 9000/9001)│  │  (port 2375)            │
└─────────────┘  └───────────────────┘  └──────────┬──────────────┘
                                                    │ Docker API
                                         ┌──────────▼──────────────┐
                                         │  Sandbox Containers     │
                                         │  (network=none, tmpfs)  │
                                         └─────────────────────────┘
```

### Inward Dependency Flow
Dependencies point strictly inward:
`api/` → `application/` → `domain/` ← `infrastructure/`

- **`domain/`**: Pure interfaces (`typing.Protocol` with `@runtime_checkable`), core models, state machines, domain events, and typed errors. Zero framework dependencies.
- **`application/`**: Agent execution loop, fresh verification logic, git diff calculations against baseline commit SHA, and untrusted archive decompression.
- **`infrastructure/`**: Adapters implementing domain protocols:
  - `DockerSandboxProvider` / `DockerSandboxEnvironment` via `docker-socket-proxy`.
  - `S3ObjectStorage` via `boto3`.
  - `PostgresRunRepository` via SQLAlchemy 2 async and Alembic.
  - `DevAuthProvider` and `ClerkAuthProvider` (JWKS/issuer).
  - `AnthropicProvider`, `OpenAIProvider`, `ScriptedLLMProvider`.
- **`bootstrap.py`**: Composition root that wires adapters based on validated environment configuration.
- **`api/`**: FastAPI REST endpoints, WebSocket streaming, and middleware.
- **`frontend/`**: Vite + React 18 + TypeScript SPA with xterm.js terminal and side-by-side diff viewer.

### Single Backend Architecture
The harness architecture (in-memory state synchronization, serialized monotonic event sequence assignment, concurrency gating via `MAX_CONCURRENT_RUNS`, and restart recovery) is designed specifically for a single-replica backend instance. Multi-replica deployments are out of scope.

---

## 3. Fixed Contracts & Endpoints

### Domain Protocols (`typing.Protocol`, runtime checkable)
- `IExecutionTerminal`: `run(command, cwd="/workspace", timeout=None) -> AsyncIterator[ExecEvent]`, `cancel_current()`
- `IFileAccess`: `read_file`, `write_file`, `list_dir`, `upload_workspace(tar_gz)`, `download_workspace() -> tar_gz`
- `ILogStreamer`: `subscribe() -> AsyncIterator[LogEvent]`
- `ISandboxEnvironment`: Combines terminal, file access, log streamer, plus `id: str`, `start()`, `stop()`
- `ISandboxProvider`: `acquire(spec) -> ISandboxEnvironment`
- `ILLMProvider`: `complete(messages, tools) -> LLMResponse`
- `IObjectStorage`: `put(key, data)`, `get(key)`, `presigned_url(key, ttl)`
- `IRunRepository`: `create`, `get`, `list`, `update_status`, `append_event`, `list_events`
- `IAuthProvider`: `authenticate(request) -> User`

### Lifecycle States
`QUEUED` → `PREPARING` → `RUNNING` → `PAUSED` → `SUCCEEDED` / `FAILED` / `TERMINATED`
- Boundary pause sets `is_pausing=True` until step finishes.
- Calling `resume` during boundary pause cancels the pause and clears `is_pausing`.
- Repeated control action on matching state returns HTTP 200 (idempotent); invalid transition returns HTTP 409.

### API Endpoints
```
POST /api/runs                      Create run {repo_url | archive, task, options}
GET  /api/runs                      List user runs
GET  /api/runs/{id}                 Get run details (including is_pausing)
POST /api/runs/{id}/pause           Pause run {"mode": "boundary" | "now"}
POST /api/runs/{id}/resume          Resume paused run
POST /api/runs/{id}/terminate       Halt execution and extract patch before container removal
POST /api/runs/{id}/guidance        Inject guidance message {"message": str}
GET  /api/runs/{id}/events?after=seq Poll monotonic event stream
WS   /api/runs/{id}/stream?after=seq&token=... WebSocket event stream
GET  /api/runs/{id}/artifacts       Get presigned URLs for patch, logs, transcript
GET  /api/runs/{id}/diff            Get per-file structured diff
GET  /healthz                       Liveness probe
GET  /readyz                        Readiness probe (Postgres, S3, Docker proxy, Sandbox image)
```

---

## 4. LLM Providers & Pinned Models

### Selection Rules
1. If `LLM_PROVIDER` is set: use that provider (`anthropic`, `openai`, or `scripted`).
2. If `LLM_PROVIDER` is blank and exactly one API key is set: infer provider.
3. If both keys are set and `LLM_PROVIDER` is blank: fail fast at startup.
4. If no key is set and not `scripted`: fail fast at startup.

### Default Pinned Models
- **Anthropic**: `claude-3-7-sonnet-20250219`
- **OpenAI**: `gpt-4o`

### Adding a New LLM Provider
To add a new provider:
1. Implement `ILLMProvider` in `backend/app/infrastructure/llm/<provider>.py`.
2. Register the provider in `backend/app/bootstrap.py`.
3. Zero edits required in the agent loop or application layer.

### WebSocket Protocol

Connect: `WS /api/runs/{id}/stream?after=<seq>&token=<jwt>`

Each message is a JSON event:
```json
{"seq": 42, "ts": "2024-01-01T00:00:00Z", "type": "terminal_chunk", "payload": {...}}
```

Event types: `reasoning`, `plan`, `decision`, `tool_call`, `tool_result`, `terminal_chunk`, `status_change`, `guidance`, `truncation_marker`

Close codes:
- `4401` — Unauthenticated (no/invalid token)
- `4404` — Run not found (cross-user or non-existent)

---

## 5. Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `HARNESS_ENV` | `development` | `development`, `test`, or `production` |
| `LLM_PROVIDER` | _(blank = infer)_ | `anthropic`, `openai`, or `scripted` |
| `LLM_MODEL` | _(provider default)_ | Override model (e.g. `claude-3-7-sonnet-20250219`) |
| `ANTHROPIC_API_KEY` | | Anthropic API key |
| `OPENAI_API_KEY` | | OpenAI API key |
| `OPENAI_BASE_URL` | | Override OpenAI base URL |
| `AUTH_PROVIDER` | `dev` | `dev` or `clerk` |
| `CLERK_JWKS_URL` | | Clerk JWKS endpoint |
| `CLERK_ISSUER` | | Clerk JWT issuer |
| `DATABASE_URL` | | `postgresql+asyncpg://...` |
| `S3_ENDPOINT_URL` | | S3/MinIO endpoint |
| `S3_PUBLIC_ENDPOINT_URL` | | Public S3 endpoint for presigned URLs |
| `S3_BUCKET` | | S3 bucket name |
| `S3_ACCESS_KEY` | | S3 access key |
| `S3_SECRET_KEY` | | S3 secret key |
| `S3_REGION` | | S3 region |
| `DOCKER_HOST` | `tcp://docker-proxy:2375` | Docker socket proxy URL |
| `SANDBOX_IMAGE` | `harness-sandbox:latest` | Sandbox container image |
| `SANDBOX_NETWORK_MODE` | `none` | Container network mode |
| `SANDBOX_CPU_LIMIT` | `1.0` | CPU limit (cores) |
| `SANDBOX_MEM_LIMIT` | `1g` | Memory limit |
| `SANDBOX_PIDS_LIMIT` | `256` | PID limit |
| `SANDBOX_WARM_POOL_SIZE` | `2` | Idle warm containers |
| `SANDBOX_WORKSPACE_SIZE` | `384m` | /workspace tmpfs size |
| `SANDBOX_TMP_SIZE` | `128m` | /tmp tmpfs size |
| `MAX_CONCURRENT_RUNS` | `4` | Max simultaneous runs |
| `AGENT_MAX_STEPS` | `40` | Max agent steps per run |
| `AGENT_MAX_TOKENS` | `200000` | Max total tokens per run |
| `AGENT_MAX_CONSECUTIVE_FAILURES` | `5` | Max consecutive failures before FAILED |
| `COMMAND_TIMEOUT_SECONDS` | `120` | Per-command timeout |
| `MAX_UPLOAD_MB` | `50` | Max archive upload size |
| `MAX_OUTPUT_BYTES_PER_RUN` | `5242880` | Max terminal output per run (5 MB) |
| `CORS_ORIGINS` | | Comma-separated allowed CORS origins |

---

## 6. Security & Isolation

### Why `/var/run/docker.sock` is NOT Mounted into Backend
Mounting the host Docker socket into the backend container gives the backend unrestricted root control over the host Docker daemon. Instead, the backend communicates with Docker exclusively through `tecnativa/docker-socket-proxy`, which filters API endpoints and exposes only containers, exec, and image inspect.

### Sandbox Container Hardening
- **Network Isolation**: `SANDBOX_NETWORK_MODE=none` prevents all outbound exfiltration.
- **Read-Only Root**: Container root filesystem is mounted `--read-only`.
- **Privilege Dropping**: Non-root user (uid 1000), `cap-drop ALL`, `no-new-privileges:true`.
- **Writable Tmpfs**: `/workspace` (384m) and `/tmp` (128m) mounted with `exec,nosuid,nodev`.
- **Zero Secrets**: Container environment receives zero backend secrets or API keys.
- **Patch Validation Isolation**: `git apply --check` runs exclusively inside a throwaway sandbox container.

---

## 7. Running Tests

### Backend Test Suite
```bash
# Unit and security tests (no Docker daemon required)
pytest -m "not docker"

# Integration tests (requires Docker daemon)
pytest -m docker

# Linting
ruff check .
```

### Frontend Test Suite
```bash
cd frontend
npm run build
npm run lint
npm run test
```

### End-to-End Verification (`scripts/e2e.py`)
```bash
# Automated replay test via scripted LLM (no API key required)
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build -d
python scripts/e2e.py --scripted

# Real-LLM test
python scripts/e2e.py
```

---

## 8. Troubleshooting (Docker Desktop / WSL2 / Windows)

- **Pipe / Socket Connection Errors**:
  Ensure Docker Desktop is running and WSL2 integration is enabled in Docker Desktop settings (*Settings > Resources > WSL Integration*).
- **Tmpfs Memory Headroom**:
  Ensure `SANDBOX_WORKSPACE_SIZE` (384m) + `SANDBOX_TMP_SIZE` (128m) does not exceed 60% of `SANDBOX_MEM_LIMIT` (1g).
- **Port Conflicts**:
  All compose services bind to `127.0.0.1`. If ports 3000, 8000, 5432, 9000, or 2375 are already bound by host processes, terminate the conflicting process or adjust port mappings.
