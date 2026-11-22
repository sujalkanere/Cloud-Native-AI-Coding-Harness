# Manual Verification Checklist

This checklist is for a human reviewer performing a click-through verification of the Cloud-Native AI Coding Harness dashboard.

## Prerequisites

- [ ] Docker Desktop is running
- [ ] `docker compose up --build` completes with all services healthy
- [ ] `GET http://127.0.0.1:8000/readyz` returns `{"status": "ok"}`
- [ ] `GET http://127.0.0.1:8000/healthz` returns `{"status": "ok"}`
- [ ] Web dashboard loads at `http://127.0.0.1:3000`

---

## 1. Session Manager

- [ ] Dashboard renders a list of runs (empty on first launch)
- [ ] "Create Run" button opens a dialog
- [ ] Dialog has fields: **Repository URL** (or file upload) and **Task Description**
- [ ] Dialog has a **Verification Mode** selector (`required` / `none`)
- [ ] Submit creates a run and shows it in the list with status badge `QUEUED` → `PREPARING` → `RUNNING`
- [ ] Multiple runs can coexist in the list simultaneously
- [ ] Each run row shows: run ID, status badge, timestamps
- [ ] Artifact download links appear for completed runs
- [ ] Live status badges update without full page reload

---

## 2. Run View — Reasoning Stream

- [ ] Navigate into a run while it is RUNNING
- [ ] Reasoning panel shows streaming thoughts, plan steps, and decisions
- [ ] Tool calls appear with collapsible detail (inputs and outputs)
- [ ] Auto-scroll follows latest output
- [ ] "Jump to Latest" button appears when scrolled up; clicking it resumes auto-scroll
- [ ] All reasoning events are visible (no missing events after reconnect)

---

## 3. Run View — Terminal (xterm)

- [ ] Terminal panel shows stdout in white, stderr in yellow
- [ ] Output appears while commands are still running (live streaming)
- [ ] Terminal scrollback works (scroll up to see earlier output)
- [ ] After disconnecting and reconnecting, all output from `seq=0` is replayed without duplicates
- [ ] If output is capped (>5 MB), a red "Output Capped (5MB)" badge appears
- [ ] A truncation banner is written to the terminal at the cap point

---

## 4. Run View — Diff Viewer

- [ ] Diff viewer shows a file tree on the left
- [ ] Selecting a file shows side-by-side before/after content
- [ ] Added lines are highlighted green, deleted lines red
- [ ] Add/delete line counts are displayed per file
- [ ] Binary files are indicated as binary
- [ ] Diff updates live as the agent makes changes

---

## 5. Control Bar

### Pause
- [ ] Click **Pause (Boundary)** while run is RUNNING
  - [ ] Run status shows `is_pausing=true` briefly (boundary pause pending)
  - [ ] After current step completes, status changes to `PAUSED`
- [ ] Click **Pause (Now)** while run is RUNNING
  - [ ] In-flight command is cancelled immediately
  - [ ] Status transitions to `PAUSED`
- [ ] While `is_pausing=true`, clicking **Resume** cancels the pending pause (status stays `RUNNING`)

### Resume
- [ ] Click **Resume** while run is `PAUSED`
  - [ ] Status transitions to `RUNNING`
  - [ ] Agent continues from next step

### Guidance
- [ ] Type a message in the Guidance input field
- [ ] Click **Send Guidance**
  - [ ] Guidance event appears in the reasoning stream
  - [ ] The message is included in the LLM's next context

### Terminate
- [ ] Click **Terminate** while run is RUNNING
  - [ ] A confirmation dialog appears
  - [ ] Confirm terminate
  - [ ] Status transitions to `TERMINATED`
  - [ ] Artifact download links for the patch appear (if changes existed)
- [ ] Termination patch passes `git apply --check` on a clean baseline checkout

---

## 6. Cross-User Isolation (requires 2 tokens)

- [ ] With two different JWT tokens (Alice and Bob), Alice's runs are invisible to Bob
- [ ] Bob's attempts to access Alice's run ID via REST return 404 (not 403)
- [ ] Bob's WebSocket connection to Alice's run closes with code 4404

---

## 7. Presigned Artifact URLs

- [ ] After a completed run, click artifact download links
- [ ] URLs open in the browser without additional auth
- [ ] Presigned URLs expire (short TTL)
- [ ] S3 keys are of the form `artifacts/{user_id}/{run_id}/...`

---

## 8. WebSocket Reconnection

- [ ] While a run is live, disable and re-enable network
- [ ] Dashboard reconnects automatically with `after=<last_seq>`
- [ ] No events are duplicated after reconnect
- [ ] No events are dropped (all events from last seen seq are delivered)

---

## 9. Production Mode Guards

- [ ] With `HARNESS_ENV=production` and `AUTH_PROVIDER=dev`, backend startup fails with a clear error message
- [ ] With `HARNESS_ENV=production` and `LLM_PROVIDER=scripted`, backend startup fails
- [ ] With `HARNESS_ENV=test` and `LLM_PROVIDER=scripted`, backend starts normally

---

## 10. Nginx Token Masking

- [ ] Check nginx access logs: WebSocket connection log entries must NOT contain the `token=` query parameter value
