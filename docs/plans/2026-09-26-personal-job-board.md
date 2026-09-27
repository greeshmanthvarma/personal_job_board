# Personal Job Board and Tracking Implementation Plan

**Goal:** Find relevant jobs, prepare answers for manual applications, and track outcomes in one private local dashboard.

**Architecture:** Keep the existing public ATS discovery clients and scheduling, but separate discovered listings from application status. A lightweight loopback-only Python server serves the job board and persists manual tracking updates; it never fills or submits employer forms.

**Tech stack:** Existing Python package, standard-library HTTP server, JSON files, vanilla HTML/CSS/JavaScript, unittest and local Playwright fixtures.

**Spec:** This document records the accepted conversation scope: replace submission automation with personal discovery, preparation, and tracking. Baseline is removal commit `c9ae25e`.

## Global constraints

- No employer writes, submission adapters, accounts, browser filling, or CAPTCHA bypass.
- Keep profile, resume, historical CSV records, drafts, and attempt evidence private and unchanged. Ambral remains Needs verification unless explicitly resolved by the user.
- Start from the clean removal commit. Do not restore the unfinished tracking prototype automatically.
- Reuse existing ATS clients and board schedule; no cloud hosting, authentication system, framework migration, or agent orchestration.
- Discovery works without model API keys. Freshness prioritizes jobs, not a blanket exclusion of older open listings. AI uncertainty is information for the user, not a barrier to displaying a role.
- Manual Applied is user-reported, not an assertion of verified employer receipt. Opening an application link never marks it applied.
- No automatic commits or pushes beyond the already requested removal commit.

## Review focus

1. Durable tracking after restart and rerender: `test_tracking_survives_restart` in Task 1.
2. Discovery without keys or hidden model rejection: `test_discovery_without_keys_keeps_older_matches` in Task 2.
3. Historical ambiguity: `test_ambral_defaults_to_needs_verification` in Task 2.
4. Local endpoint safety and validation: `test_cross_origin_tracking_write_rejected` in Task 3.
5. UI edits and exports: `test_status_note_reload_and_export` in Task 3.

### Task 1: Manual tracking state

**Files:** Create `src/applications/tracking.py`, `tests/test_tracking.py`; modify `.gitignore`.

**Interfaces:** `load_tracking(data: Path) -> dict[str, dict]`; `update_tracking(data: Path, identity: str, status: str, notes: str) -> dict`; `export_tracking(data: Path) -> bytes`.

Statuses are `new`, `saved`, `applied`, `interviewing`, `offer`, `rejected`, `skipped`, and `needs_verification`. `data/tracking.json` maps canonical `portal\tjob_id` to `{status, notes, applied_at, updated_at}`. First manual Applied sets applied_at; later transitions retain it. Updates use a dedicated file lock and atomic replacement so polling cannot overwrite tracking. Notes are limited to 10,000 characters and identities must resolve to a known listing or historical record. Invalid requests make no changes. Export is CSV with identity, company, title, application link, status, applied_at, updated_at, and notes; escape cells beginning with spreadsheet formula characters.

- [ ] Write `test_tracking_survives_restart`, `test_invalid_status_does_not_write`, `test_applied_date_is_preserved`, and `test_export_escapes_formulas`.
- [ ] Run `.venv/bin/python -m unittest discover -s tests -p test_tracking.py`; expect missing interfaces.
- [ ] Implement validation, locking, persistence, and export. Ignore tracking JSON, temporary, and lock files in Git.
- [ ] Run the narrow suite; expect PASS.
- [ ] Run `.venv/bin/python -m unittest discover -s tests`; expect all existing tests preserved.

### Task 2: Listing feed and on-demand preparation

**Files:** Create `src/applications/listings.py`, `tests/test_listings.py`; modify `src/applications/cli.py`, `src/applications/page.py`, `.gitignore`, `README.md`.

**Interfaces:** `save_listings(data: Path, jobs: list[JobPosting], checked_at: str) -> None`; `list_board_jobs(data: Path) -> list[dict]`. Persist `data/jobs.json` keyed by canonical identity, with portal, job_id, company, title, location, link, description, posted_at, checked_at, is_listed, eligibility_reason, and any existing AI screening reason. Merge tracking independently rather than changing original screening records.

Polling collects all listed title/location matches using public APIs; hydrate matching Greenhouse descriptions before hard eligibility checks. Clearly incompatible jobs remain excluded. Posting age does not exclude otherwise suitable open roles. After a successful full board response, mark missing listings for that board closed; never mark closed on timeout or a scoped job-only scan. Do not invoke models or read application forms during discovery. Preserve board scheduling, pacing, and failed-board recovery.

For historical records not yet refreshed, show only prior relevant matches/uncertainties and age-only rejections, label them Not recently verified, and never claim they are currently open. Do not resurrect known title, hard eligibility, or location rejections. Preserve already tracked jobs even if closed. Ambral's recorded unknown submission defaults to needs_verification; historical confirmed submissions default to applied, retaining their provenance.

Add `applications prepare --portal PORTAL --job-id ID` for an explicitly selected listing. It reuses read-only question discovery and supported profile facts, calls the model only for narrative answers, saves the draft, and never submits. Hard eligibility still applies; fit confidence alone does not prohibit user-requested preparation. Existing unknown authorization dates and required missing facts still block complete answers.

- [ ] Write `test_discovery_without_keys_keeps_older_matches`, `test_failed_board_does_not_close_jobs`, `test_scoped_scan_does_not_close_other_jobs`, `test_ambral_defaults_to_needs_verification`, and `test_prepare_never_submits`.
- [ ] Run `.venv/bin/python -m unittest discover -s tests -p test_listings.py`; expect missing listing feed and old freshness/model coupling failures.
- [ ] Implement listing storage, discovery separation, canonical identities, historical import, and preparation command.
- [ ] Run the narrow suite; expect PASS.
- [ ] Run full suite and `git diff --check`; expect PASS. Update old tests only where accepted discovery behavior changes, retaining no-submission coverage.

### Task 3: Local dashboard with editable tracking

**Files:** Create `src/applications/server.py`, `tests/test_board_ui.py`; modify `src/applications/page.py`, `src/applications/cli.py`, `README.md`.

**Interfaces:** `applications serve --port 8765`; `GET /` serves the dashboard; `GET /api/jobs` returns merged listing/tracking objects; `POST /api/tracking` accepts `{identity, status, notes}` and returns the persisted tracking entry; `GET /api/export` downloads tracking CSV. Server binds only `127.0.0.1`; validates Host and same-origin writes, accepts JSON only, caps request size at 32 KB, and never exposes arbitrary filesystem paths, profile, resume, .env, or historical screenshots. Unsupported endpoints return 404. Invalid updates return 400 without changing files.

UI defaults to relevant open jobs sorted newest first, with missing dates sorted last. Show company, title, location, posting date, source, listing freshness, existing fit explanation where available, status, applied date, notes, direct application link, and saved answers in expandable details. Do not invent a fit score when none exists. Include search across company/title/location/notes, portal and status filters, Older/Unverified and Closed visibility toggles, and counts based on the displayed feed. Status and note edits show saving/saved/error feedback; failed writes retain the user's text and are not presented as saved. The local HTTP view is the authoritative editable UI; the old static HTML remains a clearly labeled read-only snapshot. Apply links never mutate tracking.

- [ ] Write `test_cross_origin_tracking_write_rejected`, `test_server_does_not_expose_private_files`, `test_status_note_reload_and_export`, and `test_open_link_does_not_mark_applied` using local fixtures and a temporary data directory.
- [ ] Run `.venv/bin/python -m unittest discover -s tests -p test_board_ui.py`; expect missing server and controls.
- [ ] Implement the endpoints and lightweight responsive dashboard with durable tracking and export.
- [ ] Run the narrow suite; expect PASS. Render at desktop and mobile widths and inspect screenshots for clipping and readable notes/answers.
- [ ] Run the full suite, `git diff --check`, and a local `applications serve` smoke test. Open the local board for the user and report exactly which data was imported and any uncertain historical statuses.

## Coverage and exclusions

The three tasks cover discovery, prioritization, direct links, answer preparation, saved/application tracking, notes, dates, search/filtering, and export. Submission is absent by design. Cloud deployment, email integration, agents, company-account login, automatic outcome inference, and bulk application are excluded. Historical data is preserved, not reset.
