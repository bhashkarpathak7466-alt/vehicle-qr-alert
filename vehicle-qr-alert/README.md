# Vehicle QR Alert System

A backend service where vehicle owners register their car, get a QR code
sticker generated for it, and receive risk-scored alerts when someone
scans the sticker to report an issue (bad parking, break-in, accident,
etc). Alerts are automatically scored for urgency and the owner is
notified, with the most critical alerts surfaced first.

Built as a portfolio/resume project. Everything below is real, running
code — the only pieces that are mocked are the two that require paid
external services (see [What's mocked and why](#whats-mocked-and-why)).

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Visit `http://localhost:8000` for the actual web app (register, add a
vehicle, scan-and-report flow). `http://localhost:8000/docs` has the
auto-generated interactive API docs, if you want to exercise the API
directly. No database setup needed — it defaults to a local SQLite
file so it runs in under a minute.

To turn on the real vision-AI authenticity check instead of the
rule-based fallback:
```bash
pip install -r requirements-ai.txt
# then set AI_ENABLED=true and AI_API_KEY=<your key> in .env
```

Run the full end-to-end test (register → login → add vehicle → QR
generated → report alert → risk scored + authenticity checked →
duplicate reports grouped into one incident → owner notified):

```bash
python tests/test_end_to_end.py
```

---

## Architecture

This is a **modular monolith**: one deployable service, but internally
organized into clearly separated modules, each with a single
responsibility — the same separation you'd want if you later split it
into microservices, without paying the operational cost of microservices
on day one.

```
app/
├── main.py           # App wiring only — no business logic
├── core/              # Config, security (JWT/password hashing), shared deps
├── db/                 # Database engine/session setup
├── models/            # SQLAlchemy tables: User, Vehicle, Alert
├── schemas/            # Pydantic request/response shapes (API contract)
├── routers/            # HTTP endpoints — thin, delegate to services
└── services/           # Business logic: QR tokens, risk scoring, notifications
```

**Why this layering matters:** routers never talk to the database or
implement business rules directly — they call into `services/`. This
means the risk-scoring logic, for example, could be reused by a future
background worker or CLI tool without duplicating code, and it's
independently testable without spinning up the whole HTTP stack.

### Request flow

```
Owner:     Register -> Login (JWT) -> Add Vehicle -> QR code generated
Reporter:  Scan QR sticker -> Submit alert text (no login needed)
System:    Match QR hash -> Score risk -> Save alert -> Notify owner
Owner:     Views alerts, sorted by risk (highest first)
```

---

## Key design decisions

### 1. QR tokens are hashed, never stored raw

Each vehicle gets a cryptographically random token (`secrets.token_urlsafe`)
embedded into its QR sticker. The database stores only the **SHA-256 hash**
of that token — the same pattern used for password storage.

**Why:** if the database ever leaked, an attacker could not reconstruct
working QR stickers from the stolen hashes. The raw token is shown to
the owner exactly once, at registration, and never persisted.

See `app/services/qr_service.py`.

### 2. AI risk scoring with graceful degradation

Alert text is scored for urgency (0.0–1.0) using keyword matching by
default, with a real LLM call as an optional upgrade path. The scorer
tries the AI path first *only if* `AI_ENABLED=true` and an API key is
configured; if that call fails, times out, or isn't configured at all,
it **falls back to a deterministic rule-based matcher** instead of
failing the request.

**Why:** for something that might be safety-related (a car break-in
report), the request should never hard-fail just because an external
AI API is slow or down. The response always reports which path
(`ai` or `rule_based`) actually scored the alert, so nothing is hidden.

See `app/services/ai_service.py`.

### 2b. Authenticity ("fraud") check — real vision AI, with a rule-based fallback

Every report gets a `likely_genuine` / `needs_review` / `likely_prank`
label. **Being precise about what this is:**

- If `AI_ENABLED=true` and a real Anthropic API key is set,
  `_ai_authenticity_check()` genuinely calls the API — it sends the
  reporter's message *and* the uploaded photo (if any) to a
  vision-capable model and asks it to judge whether they plausibly
  describe a real issue. This is a real network call, not a stub —
  verified in this build by testing it against an invalid key and
  confirming it fails over cleanly rather than crashing.
- If AI isn't configured, the `anthropic` package isn't installed, or
  the call fails for any reason (bad key, network error, malformed
  response), it falls back to a transparent rule-based heuristic —
  message length, a small prank-phrase list, and whether a photo was
  attached. This is **not** ML or computer vision, and the response
  says so explicitly: every alert includes a `source` value (`"ai"`
  or `"rule_based"`) so the label is never presented as more
  authoritative than it actually is.

**Non-negotiable design rule:** a `likely_prank` label never
suppresses or hides an alert — it still reaches the owner, just
labeled. A false positive on this heuristic must never cost someone
a real emergency report.

See `app/services/ai_service.py::assess_authenticity()`. To actually
enable the real AI path: `pip install -r requirements-ai.txt`, then
set `AI_ENABLED=true` and `AI_API_KEY=<your key>` in `.env`.

### 2c. Evidence fusion — combining signals into one score

A single heuristic in isolation is weak evidence. `fuse_evidence()`
combines several signals the system actually has into one
confidence-adjusted `fused_risk_score` (0–100), with every
contributing reason listed on the alert (never a hidden black-box
number):

- the base message-urgency score
- the authenticity check's result
- whether a photo was attached
- how many *other* independent reports were matched to the same
  real-world incident (see below)

**Signals deliberately left out, on purpose:** reporter history and
GPS location — both common items on a "fraud detection" checklist —
don't fit this system honestly. Reporting is anonymous by design (no
account, no phone number required, no location capture); faking
those signals with placeholder data would be dishonest rather than
a real feature. If reporter accounts or consent-based geolocation
were added later, those would be legitimate additions here.

See `app/services/ai_service.py::fuse_evidence()`.

### 2d. Incident detection — grouping duplicate reports

If two people scan the same car within a few hours and describe a
similar-sounding issue, `find_or_create_incident()` groups them as
the same incident rather than showing the owner two disconnected
alerts. That corroboration count also feeds into evidence fusion
above — multiple independent reports of the same thing is real
evidence, and the dashboard shows "N independent reports" on the
alert.

**Being precise about the technique:** this compares reports using
word-overlap similarity (Jaccard similarity on significant words) —
not embeddings or a trained semantic model. It's an explainable,
legitimate heuristic, but a version that compares *meaning* rather
than *word overlap* would swap in sentence embeddings + a vector
similarity search — that's a drop-in replacement for
`jaccard_similarity()`, the grouping logic around it doesn't change.

See `app/services/incident_service.py`.

### 2e. What's intentionally NOT built here, and why

Async background workers (Celery/Redis) for offloading AI scoring
were considered and deliberately not built. That's a real solution to
a real scaling problem — but this project doesn't have that problem
yet (one AI call per report, low request volume). Building it now,
before the AI path itself was proven out, would have meant adding
real operational complexity (a message broker, worker processes, job
monitoring) to solve a bottleneck that doesn't exist. It's a natural
"what would you do at scale" answer for an interview, not a box to
tick in a portfolio project.

### 3. Auth is stateless (JWT)

Login issues a signed JWT instead of server-side sessions, so the API
can scale horizontally without needing shared session storage.

### 4. SQLite by default, Postgres-ready

`DATABASE_URL` is the single source of truth for the database
connection (`app/core/config.py`). It defaults to SQLite so the project
runs with zero setup, but the same code path works unchanged against
Postgres — just change the env var. In production I'd add Alembic
migrations instead of relying on `create_all()`.

---

## What's mocked and why

Two pieces would cost real money or require infrastructure this project
doesn't need to prove the design, so they're implemented as **local
mocks with the same interface a real integration would use** — swapping
them for the real thing later is a body-swap inside one function, not a
rewrite:

| Component | Status | Real version |
|---|---|---|
| SMS/call notifications | Mocked — needs a paid provider (e.g. Twilio) + verified phone number | `app/services/notification_service.py` — swap `send_sms()`'s body for a Twilio API call; the function signature doesn't change |
| Risk scoring's AI path | Stubbed — the rule-based keyword matcher is what actually runs | `app/services/ai_service.py::_ai_score()` has the exact call shape commented in; enabling it is a config flag away |
| Authenticity check's AI path | **Genuinely wired up**, not a stub — real vision-AI call, tested against an invalid key to confirm graceful fallback | Already real: `app/services/ai_service.py::_ai_authenticity_check()`. Needs `pip install -r requirements-ai.txt` + `AI_ENABLED=true` + a real key in `.env` |

Everything else — auth, QR generation/hashing, the database, the API,
the risk-scoring fallback logic, notification dispatch triggering,
incident/duplicate detection, and evidence fusion — is real, running
code, verified in `tests/test_end_to_end.py`.

---

## What I'd do with more resources

- Swap SQLite for Postgres in a hosted environment (e.g. Render/Railway)
  and deploy for a live demo link.
- Add Alembic migrations instead of `create_all()`.
- Add rate limiting on the public `/alerts/report` endpoint (it's
  unauthenticated by design, so it's the most exposed surface).
- Load-test the alert-reporting path — it's the one endpoint that's
  genuinely public and could see bursty traffic (e.g. a viral incident
  causing many people to scan the same QR code at once). I'd want to
  verify DB contention behavior under concurrent writes, likely with
  k6 or Locust rather than anything at real Kubernetes scale.
- Wire up the real Anthropic API call in `_ai_score()` (risk scoring)
  the same way `_ai_authenticity_check()` already is, and compare its
  scoring against the keyword baseline on a labeled test set.
- Move to an embeddings-based similarity check in
  `incident_service.py` instead of word-overlap, for better duplicate
  detection when two reports describe the same thing in very
  different words.
- Move AI calls to an async job queue (Celery + Redis): `POST
  /alerts/report` would enqueue the report and return immediately,
  with a background worker doing risk scoring, the authenticity
  check, and notification dispatch. **Deliberately not built now** —
  it solves a request-volume/latency problem this project doesn't
  have yet (one AI call per report, low traffic), and introducing a
  message broker before the AI path itself was proven real would have
  been complexity for its own sake. This is the right next step once
  request volume or AI call latency actually becomes a bottleneck.

---

## Tech stack

- **FastAPI** — async-capable Python web framework, auto-generated
  OpenAPI docs
- **Jinja2** — server-rendered HTML pages (the actual browsable web app)
- **SQLAlchemy** — ORM, database-agnostic (SQLite locally, Postgres in prod)
- **Pydantic** — request/response validation
- **JWT (python-jose) + bcrypt (passlib)** — stateless auth, password hashing
- **qrcode** — QR image generation (encodes a real scannable report URL)
- **anthropic** (optional, `requirements-ai.txt`) — real vision-AI
  authenticity check, when enabled
