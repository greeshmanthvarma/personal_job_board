# Personal job board: remote discovery and local React UI

Status: proposed specification; implementation and deployment require approval.

## Goal and scope

Provide one person's personalized job discovery and application tracking, with scans continuing while their laptop is asleep. React runs locally; Python on Railway owns discovery, Jev assessments, and durable tracking. Optimize for a useful daily shortlist, not a multi-user product.

In scope: local React UI, loopback Python proxy, authenticated Railway HTTP interface, scheduled scanning, persistent volume, data migration, backup/restore, and operational status.

Out of scope: automated applications, employer writes, accounts on employer sites, agents, Next.js, Vercel, Cloudflare Tunnel, database deployment, multi-user authorization, email ingestion, and mobile access. Answer preparation remains a separate local command; cloud answer generation is not part of this release.

## Architecture and module interfaces

React requests the loopback module at `http://127.0.0.1:8765`. That module serves the compiled React assets and forwards only approved requests over HTTPS to the remote board module. There is no browser-to-Railway connection. A developer may use a React development server, but browser requests must still be same-origin through its development proxy.

The local proxy earns its place by centralizing credential handling, URL validation, forwarding limits, and connectivity errors. It is not a general HTTP proxy. Its interface contains three operations: read board, save tracking, and export tracking. Only these fixed paths may be forwarded; no caller-controlled destination, redirect following, filesystem paths, or request headers.

The remote board module owns storage access and tracking validation. The scanner module owns ATS discovery, assessment caching, and scheduling. Both run in one Railway replica and use the same mounted data directory. The scanner runs in a background thread or supervised process inside that deployment; a scan crash must not take down the HTTP interface. No second Railway service is assumed to share the volume.

The React module owns presentation and unsaved edits, never scheduling or authoritative persistence. Profile text, model credentials, and the remote authentication token never enter its bundle or browser storage.

Reuse existing Python discovery, Jev, ranking, identity, eligibility, and tracking logic behind HTTP and scheduling adapters; do not duplicate business rules in React or the proxy. One remote Python process runs HTTP plus one supervised scanner thread. Storage locking stays private to the storage module. Prepared-answer display is deferred from the React release; local preparation remains independent.

## Deployment and configuration

One Railway Python deployment, one replica, persistent volume mounted at `/data`, `DATA_DIR=/data`. Remote HTTP binds `0.0.0.0` on Railway's injected `PORT`. Local HTTP remains loopback-only. Reject remote mode at startup if authentication is missing or the persistent directory is absent/unwritable. Do not silently fall back to ephemeral storage.

Remote secrets: `BOARD_API_TOKEN`, `TYPESAFE_API_KEY`, and private profile provisioning. Local secrets: `BOARD_API_TOKEN` and `BOARD_REMOTE_URL` (HTTPS origin only, no URL credentials, query, or fragment). Provision profile as a secret value or separately uploaded private file, never committed or included in a public image. Do not deploy `OPENAI_API_KEY` for this release.

Use Railway HTTPS ingress. The same long random token is provisioned manually to remote and local secret stores; document rotation on both sides. Local secrets are gitignored and restricted to the user's filesystem permissions. No credentials in command-line arguments or logs. Hosting authorization is not authorization to publish private files; confirm destination and private-data migration before provisioning.

## HTTP contract and security

Remote routes, versioned under `/api/v1`:

- `GET /api/v1/jobs`: `{jobs: Job[], scan: ScanStatus}` using the existing listing/scan fields, with a documented versioned schema. Includes ranking inputs, fit explanation, listing verification, tracking, and checked/posting timestamps. Never includes profile, secrets, arbitrary files, or internal exception details.
- `POST /api/v1/tracking`: exact JSON fields `{identity: string, status: string, notes: string}`. Return the stored tracking entry only after durable success. Unknown identity or invalid fields: 400. Maximum request body 32 KiB; maximum notes length 10,000 characters.
- `GET /api/v1/export`: tracking CSV attachment with spreadsheet-formula escaping.
- `GET /healthz`: public minimal liveness only; no scan, job, or profile data.

All data routes require `Authorization: Bearer <token>` before reading data or parsing bodies. Missing/invalid credentials return 401 with no private details, compared in constant time. Never expose a remote root dashboard. Remote API does not enable CORS; browser Origin requests to data routes are rejected. The server-to-server proxy omits Origin and attaches only its own authorization header. CORS is not an authentication mechanism.

Local routes retain `/api/jobs`, `/api/tracking`, and `/api/export`. Validate exact loopback Host; tracking writes require exact same Origin, JSON content type, and size limits. GET responses carry `Cache-Control: no-store`. An unrelated website must not read data or make the local proxy write to Railway. Restrict local asset serving to compiled assets with traversal prevention. Use a restrictive CSP and render all employer content and notes as text, not HTML.

Outbound proxy timeout: 15 seconds; cap successful board payload at 32 MiB and display a clear error if exceeded. Do not retry tracking writes automatically. Return 502 for remote failure and 504 for timeout, with sanitized messages. Never pretend a failed save succeeded. Reads may be retried by the user. Export streams or uses a bounded response. Validate configured remote origin; never forward browser Authorization, cookies, or redirect targets.

Apply bounded request concurrency and basic request-rate limits at the remote interface; specify exact thresholds in the implementation plan. Logs contain route/status/timing and scan summaries, not credentials, profile, descriptions, or notes.

## Storage and consistency

Railway is authoritative. Store jobs and assessment fingerprints in `jobs.json`, statuses/notes/dates in `tracking.json`, scheduling in `board-schedule.json`, and progress in `scan-state.json`. Keep locks on the volume. Preserve canonical job identities and existing status/date semantics. Discovery cannot overwrite manual tracking. Opening a link does not mark Applied. First Applied records a UTC timestamp, which subsequent transitions preserve.

All mutable JSON files use locked read-modify-write where applicable, write to a same-directory temporary file, flush/fsync, then atomic replace. A crash must leave either the complete old or complete new document. API reads never observe partial JSON. Separate tracking and scanning locks avoid holding tracking writes during long scans. A single scan execution lock excludes overlap; do not hold a file lock across an HTTP response unnecessarily.

Tracking saves use whole-entry last-successful-write-wins semantics. Multiple tabs can overwrite each other's saved notes; expose updated timestamp and retain unsaved text on refresh. Conflict resolution or offline writes are excluded. When Railway is unreachable, keep unsaved edits and show disconnected status; no background write queue, local authoritative copy, or automatic replay.

Version stored schemas and validate before startup or import. Corrupt data must not be replaced with an empty feed; show degraded status and preserve files for recovery.

## Polling and ranking

Wake the scheduler every five minutes. It selects due boards, prioritizing boards that currently have open software-engineer titles while reserving capacity for broader discovery. One scan at a time; at most 50 boards per batch and 50 new Jev assessments. Limits are configurable without adding browser controls. Complete a batch before starting another; missed ticks coalesce, not accumulate.

Default intervals: boards with an open software-engineer title that is not a hard location miss, hourly; other active boards every six hours; empty boards daily; first two consecutive failures six hours, third and later failures seven days. Recompute that hiring flag from the latest successful job list. A later scan with no matching title returns the board to six hours. A failed request keeps the previous flag until a successful scan replaces it. An empty board clears the flag. A past Jev score does not change the interval. Do not classify unavailable assessments as poor fit.

Avoid starvation: within each batch reserve at least half the slots for due boards that are not currently hiring engineers, borrowing unused slots in either direction. Within both groups select oldest due time first; never repeatedly take the first entries in directory order. Unseen boards are due and get a stable FIFO initial order. Report outstanding due count and oldest due age. The directory cannot be promised fully refreshed every six hours: total coverage depends on pacing, board count, and runtime. The interval is eligibility for another scan, not a freshness guarantee.

Retain >=1-second GET spacing with jitter, bounded retries/timeouts, provider backoff, title/location screening before description hydration, assessment content/profile fingerprint cache, and continued discovery when Jev is down. A failed, partial, or job-scoped fetch must not close missing jobs. Use UTC for schedules. Shutdown stops starting new work and drains or safely interrupts current work; restart resumes overdue boards and never treats an old running status as a live scan.

Ranking remains 70% relevance plus 30% seven-day exponential recency. Missing dates and assessments are explicitly labeled. Do not invent timestamps or scores. Support blended, newest, and fit sorting.

## Local React experience

### Visual direction

Initialize and add real shadcn/ui components using the official shadcn CLI, following the supplied CLI reference; do not approximate them with lookalike custom controls. Use the Vite template for the local React app and a neutral monochrome base. Keep `components.json`, generated component source, theme CSS variables, and the package lockfile in the repository. Inspect components before adding them, install only those the UI needs, and avoid `--all`, forced overwrites, unrelated migrations, or ejecting shared styles. Resolve and record actual CLI/dependency versions at implementation time rather than treating `@latest` as a reproducible version. Custom styling must preserve component accessibility and the agreed black/grey/white palette.

Use shadcn/ui components with React, TypeScript, and Tailwind CSS. The visual direction is classy, restrained, and minimal: black/charcoal surfaces, grey borders and secondary text, and white primary text. Default to dark appearance. No conventional blue-and-white SaaS theme, blue primary actions, colored gradients, loud status colors, oversized dashboard tiles, or decorative charts. Use a monochrome palette for buttons, badges, focus indicators, and status labels; distinguish states through text and shape, not color alone.

Prefer a compact header, quiet navigation, a tidy search/filter toolbar, and readable job rows or restrained cards with subtle separators. Give company/title hierarchy and fit/recency enough space without making metadata compete with the job. Details and editing belong in an expandable area or shadcn Sheet. Use shadcn Tabs, Button, Input, Select, Badge, Sheet, and appropriate feedback primitives where useful, not every available component. Keep borders, corner radii, shadows, and motion subtle and consistent. Meet accessible contrast and visible keyboard-focus requirements; subdued must not mean unreadable.

### Status workspaces

Top-level shadcn tabs: Results, Saved, Applied, Interviewing, Offers, Rejected, Skipped, and Needs verification. Results contains only `new`; every other tab contains only its corresponding stored status. Tabs partition the feed by canonical identity, so a job is in exactly one status workspace and never duplicated in Results after a successful status change. Offers maps to `offer`; Needs verification maps to `needs_verification`.

After confirmed save, remove the row from its old tab, insert it in the destination tab, update tab counts, and retain the active tab. Show a brief confirmation with an action to open the destination tab. An unsaved selection or failed/ambiguous write does not move the job; retain edits and explain the error. Changing back to New returns the listing to Results subject to its open/unverified filters. Refresh and restart preserve tab membership from authoritative tracking, not browser-only state. Status updates never change canonical identity or erase notes/applied dates.

Search and provider filters apply within the active tab. Results defaults to open listings, with explicit closed/unverified toggles; tracking tabs include their jobs even when closed or unverified so applications never disappear because a posting expires. Tab counts show total workspace membership before search/provider filters, while the list shows its filtered result count. Use blended ranking in Results/Saved and latest tracking update first in the other workspaces, with sort controls available. Narrow screens must keep all tabs reachable with accessible horizontal navigation rather than hiding statuses.

Use React + TypeScript with a lightweight build tool. Production local startup is one command serving compiled assets and the proxy; no need to run a separate development server for daily use. Preserve search, provider/status filters, closed/unverified toggles, ranking, expandable fit explanations, job descriptions, notes, statuses, dates, and CSV export.

Show connection state and remote scan state separately: scheduler heartbeat, last successful completion, current board, last error, assessed count, and polling backlog. Refresh does not discard unsaved edits. Save updates counts/status immediately only on confirmed success. Accessible controls, keyboard operation, responsive layout, and clear loading/empty/error states are required. No automatic submission or application status inference.

## Migration, backup, and rollback

Before migration, stop local scanning and tracking writes and make a private backup. Import a validated snapshot of listings, tracking, schedule, and scan state into the stopped remote deployment; include directory configuration and private profile separately. Import must be idempotent and fail on conflicting populated data unless explicitly approved. Validate counts, identities, dates, and sample notes without printing private values. Treat imported running scan state as interrupted.

Switch local proxy only after remote read/export/save smoke tests with disposable fixtures and verification that no secrets are exposed. Preserve the local snapshot; do not dual-write. Rollback stops remote writes/scans, exports its current authoritative state, validates it, then restores local operation. Never revert to an old snapshot after new tracking writes without reconciliation.

Require daily recoverable backups and a manual pre-migration backup; retain seven daily copies. Document the backup destination, persistence independent of the live volume, access controls, and cost before deployment. A copy on the same volume is not sufficient disaster recovery. Perform a restore drill using disposable storage; check tracking dates/notes and cached assessments survive.

## Acceptance and review gates

### Reviewed contract clarifications

- Identity is the exact existing `portal + "\t" + external_job_id` string. Allowed statuses: `new`, `saved`, `applied`, `interviewing`, `offer`, `rejected`, `skipped`, `needs_verification`. Stored/API dates use UTC ISO 8601; unknown dates are empty strings. `fit` is a number or null; `is_listed` is true, false, or null. Tracking response: `{status, notes, updated_at, applied_at}`. Errors: `{error: {code: string, message: string}}`, with stable sanitized codes. The implementation plan must freeze a complete Job/ScanStatus schema and fixtures before frontend work.
- React loads on startup and refreshes every 60 seconds while visible, with a manual Refresh action. Failed reads retain the last successful snapshot labeled stale and its fetched time; initial failure shows an error rather than an empty result. Draft edits are keyed by canonical identity and remain recoverable even if the job disappears from the refreshed feed. A tracking timeout is ambiguous: it may already have committed. Offer read-back before another manual save; never blindly replay.
- All persistence replacements also fsync the parent directory. Verify volume locking/durability on the target deployment. Require Railway volume attachment verification and a redeploy persistence smoke test, not only an existing writable `/data` directory.
- Per-board commit order is listings/assessments first, then next-due scheduling. A crash may cause duplicate reads, never advancement without saved results. Assessment-cap overflow remains eligible for the next due scan; changed profiles invalidate fingerprints, and assessments process new/changed jobs before older pending jobs within the bounded budget.
- Use explicit deadlines: network request 30 seconds, assessment operation 90 seconds including retries, board processing 5 minutes, batch 20 minutes. On deadline, safely persist partial discoveries without closing missing jobs; unfinished boards remain due. Stop after the current bounded operation, not by killing a thread mid-write.
- Supervise scanner failure with capped restart backoff; show scheduler stale after 10 minutes without heartbeat. Heartbeats must continue during scans. Health liveness is separate from authenticated scanner-health status. Diagnostic messages are sanitized codes, not raw exceptions.
- Restrict ATS discovery/hydration destinations to documented provider HTTPS hosts, validate redirects, and prohibit private/link-local destinations. Model credentials are scoped only to the configured model endpoint; never forwarded to ATS hosts.
- Backups acquire a coordinated short snapshot lock across storage writers, produce a validated manifest, then release the lock before uploading. Approve the independent destination/mechanism and cost as a deployment decision, not a new backup-management feature. Validate complete snapshot generations on restore.
- Apply remote limits of 10 concurrent requests and 120 requests/minute per token; return 429 with Retry-After. Public health checks have separate ingress limits. These are configurable operational limits, not React features.

1. Remote scan progresses with laptop off; scheduler restart resumes due work and excludes overlap.
2. Both engineer-hiring and other due boards progress under sustained load; test caps, FIFO fairness, and failure backoff with a fake clock.
3. Bad tokens, direct cross-origin requests, forged local Host/Origin, oversized bodies, traversal, and arbitrary forwarding fail without data disclosure.
4. Browser bundles/network responses/logs contain no token, profile, or model key. Untrusted descriptions cannot execute scripts.
5. Save/export survive HTTP restart, scanner activity, and deployment restart with the mounted volume. Crash-injection tests prove atomic files; corrupted files fail safely.
6. Remote timeouts retain unsaved edits and never show Saved; multi-tab last-write behavior is explicit.
7. Migration preserves tracking/identities, restore drill passes, and rollback incorporates post-migration writes.
8. Existing discovery/ranking/tracking tests remain green; React tests cover filtering, save success/failure, refresh preservation, and accessibility. No test contacts employers or sends private profile to a model.
9. Every stored status maps to exactly one workspace. A successful New-to-Applied save removes the job from Results and adds it to Applied; Applied-to-Interviewing/Offer/Rejected moves it without duplication. Failed saves do not move rows, counts update only on success, reverting to New respects listing filters, and closed tracked jobs remain in their status tabs after refresh/restart.
10. Verify the monochrome shadcn design at desktop and mobile widths, including empty tabs, long titles, keyboard navigation/focus, readable contrast, loading, and error feedback. No blue theme accents or color-only status distinctions.

Deployment gate: no exposure until authentication, volume validation, private-data authorization, restore procedure, and secret-safe logging are verified. No commit, push, paid provisioning, or deployment is implied by approving this document alone.
