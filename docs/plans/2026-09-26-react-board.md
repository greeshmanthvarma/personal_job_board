# React Job Board Implementation Plan

**Goal:** Deliver the monochrome shadcn status-workspace UI against the local Python interface.

**Architecture:** React uses same-origin `/api/jobs`, `/api/tracking`, and `/api/export`; Python retains all persistence and ranking logic. Vite compiles assets served by the loopback server. Railway adapters are a separate increment.

**Tech stack:** React, TypeScript, Vite, Tailwind, shadcn/ui, Python.

**Spec:** `docs/remote-job-board-spec.md`

## Global constraints

No employer writes, deployment, model calls, private-data migration, automatic commit, or push. Preserve existing working-tree changes and Python tests. Only confirmed saves move jobs. No secrets in browser assets.

## Review focus

Status partition and closed tracking: Task 1 model tests. Failed saves and refreshed drafts: Task 2 browser tests. Traversal and local Host/Origin protections: Task 3 server tests. Monochrome responsive keyboard UI: Task 2 smoke tests. Build/API schema compatibility: Tasks 2–3 type/build checks.

### Task 1: Workspace model

**Files:** Create `frontend/src/model.ts`, `frontend/src/model.test.ts`; configure test command in `frontend/package.json`.

**Interfaces:** `Status` is the eight existing status strings. `Job` declares identity, company, title, location, portal, link, description, assessment, fit nullable, priority, posted_at, checked_at, is_listed nullable, status, notes, applied_at, updated_at. `visibleJobs(jobs, status, query, provider, includeClosed, includeUnverified, sort)` returns a sorted partition without mutating jobs; `mergeTracking(jobs, identity, entry)` returns immutable confirmed updates.

- [ ] Write failing tests for status exclusion, closed tracked jobs, and immutable confirmed transition.
- [ ] Run `npm test`; expect missing module failure.
- [ ] Implement pure helpers with no persistence/score calculation.
- [ ] Run `npm test`; expect pass.
- [ ] Run `npm run build` with TypeScript checking.

### Task 2: shadcn UI

**Files:** Create `frontend/src/App.tsx`, API client, CSS, entry point and generated `components/ui/*`; preserve `components.json` and lockfile.

**Interfaces:** GET returns `{jobs: Job[], scan: object}`; tracking request exact `{identity,status,notes}`, response `{status,notes,applied_at,updated_at}`. Existing local errors have string `error`; client accepts both that and future structured error. Fixed same-origin routes only.

- [ ] Test success moves New to Applied and updates counts; failed save retains edits and membership; refresh preserves draft by identity.
- [ ] Implement eight tabs, search/provider/sort, open-listing toggles, details, notes/status edit, export, refresh, connection states, 60-second visible refresh.
- [ ] Run tests and build; no token or profile config consumed by Vite.
- [ ] Browser smoke on disposable fixtures at desktop/mobile; check keyboard and monochrome appearance. No real tracking mutations in smoke tests.

### Task 3: Local asset hosting

**Files:** Modify `src/applications/server.py`; add `tests/test_react_assets.py`; update README and gitignore.

**Interfaces:** Serve `frontend/dist/index.html` and only resolved files under `frontend/dist/assets`; preserve all current data routes and loopback validation. If assets not built, retain current fallback board. Static assets have correct MIME types; no arbitrary file paths served.

- [ ] Write tests for root build serving, asset content type, traversal rejection and fallback.
- [ ] Run narrow tests red; implement constrained static serving.
- [ ] Run full Python suite, frontend tests/build, and `git diff --check`.
- [ ] Record completed checkpoint and remote work remaining. No deployment until authentication/storage/scanner/backup gates are implemented and independently verified.
