# Personal job board

A private, local job board for discovering relevant Ashby, Greenhouse, and Lever roles, preparing answers, and tracking applications you submit yourself. **No application filling or submission functionality exists.**

## Setup

Requires Python 3.11 or newer. Clone the repository and install the package:

```bash
git clone https://github.com/greeshmanthvarma/personal_job_board.git
cd personal_job_board
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Public job discovery and manual tracking do not require an API key. For personalized Jev assessments, create a private `profile.md` at the repository root and set `TYPESAFE_API_KEY` in `.env`. Assessments send your profile and the job's title, location, and description to Typesafe AI (Jev). Keep credentials and private files out of Git. `OPENAI_API_KEY` is optional and used only for narrative answer preparation, not discovery.

## Start

Build the local React interface (Node.js 22.19+ is supported by the pinned toolchain):

```bash
cd frontend
npm ci
npm run build
cd ..
```

The interface uses shadcn/ui (CLI 4.21.0), React, TypeScript, Vite, and Tailwind with a monochrome dark theme. Results contains only New jobs; Saved, Applied, Interviewing, Offers, Rejected, Skipped, and Needs verification are separate workspaces. Status changes move jobs only after confirmed saves. Tracking tabs retain closed postings. Unsaved edits stay in memory across refreshes; they are not a durable offline draft.

Run from this repository:

```bash
source .venv/bin/activate
python -m applications serve
```

Open http://127.0.0.1:8765. The server binds only to loopback and must stay running while you use it.

A typical session is to start the board in one terminal, run a bounded scan in another, and click **Refresh** on the board afterward:

```bash
python -m applications poll --limit 10 --assessment-limit 50
```

Review the role, open its application link, apply yourself, then save its status and notes. Neither opening the link nor preparing answers marks a job Applied.

## Discover jobs

```bash
python -m applications poll --limit 10
python -m applications poll --backlog
python -m applications poll --vendor ashby --board Ambral --backlog
```

Discovery uses public ATS APIs, never employer application writes. It runs without model keys. Titles, clearly incompatible locations, and hard eligibility requirements filter listings. Results show only postings dated within the past seven days; missing, invalid and future dates are excluded. Tracked jobs remain in their status tabs regardless of posting age. A successful full board scan marks missing listings closed; failed or job-scoped scans do not.

The 12,918-board directory is in `data/ats-board-directory.csv`. `--limit` caps boards, `--vendor` selects one provider, and `--board` selects one company slug. `--job-id` requires a board and vendor and processes only that listing. `--backlog` scans regardless of board schedule. Each manual `poll` command runs one pass; Railway's `host` process runs the background scheduler described below. GETs are paced at least one second apart with jitter, bounded timeout/retries, and provider-specific parsing. Greenhouse descriptions are hydrated only for title/location matches. Concurrent scans are prevented by a lock.

### Railway polling cadence

The hosted worker starts its first scan immediately. When a scan exits, the next one starts on the following supervision check. Scans never overlap. The worker checks supervision and updates its heartbeat every five seconds.

Individual boards are fetched only when due:

- Boards with an open software-engineer title that is not a hard location miss: every hour.
- Other nonempty boards: every six hours.
- Empty boards: once per day.
- Failed boards: retry after six hours for the first two failures, then after one week for three or more consecutive failures.

The default batch limits are **50 boards** and **50 new Jev assessments**. The scanner continues discovering listings after the assessment budget is exhausted. Broad discovery and boards currently hiring engineers share the board budget, borrowing unused slots. A batch has a twenty-minute deadline.

Railway variables control these defaults: `POLL_BOARD_LIMIT=50` and `POLL_ASSESSMENT_LIMIT=50`. Board due times are not refresh guarantees: limited capacity and the directory backlog can delay a check. Remote polling continues while your laptop sleeps; the local React interface is not required for discovery.

## Jev relevance and ranking

A board is scheduled hourly while its latest successful scan includes an open title from the software-engineer include list and that posting is not a hard location miss. A later scan with no such title returns it to six hours. Empty-board and failure backoff still take precedence. A failed request keeps the previous hiring flag until a successful scan replaces it. Bounded scans reserve capacity for both engineer-hiring boards and broad discovery, borrowing unused slots. Polling intervals determine when a board becomes due, not a guarantee that every board will be refreshed within that interval.

With `TYPESAFE_API_KEY` in `.env` and `profile.md` present, Jev assesses matching listings with a known posting date within the past seven days. The age check runs before Jev and, when the board exposes a date, before detail requests. Greenhouse listings without a date may need a detail request to obtain it; unknown dates still never use Jev budget. Existing tracking and listing presence are retained. An assessment is cached by job content and profile fingerprint. `--assessment-limit` defaults to 50 new assessments per scan; discovery continues beyond that budget or when Jev is unavailable. A later due scan can assess remaining recent jobs. OpenAI is not used during discovery.

Relevance is the mean of Jev's four scores: role family, level, responsibilities, and qualifications. It is an assessment signal, not a hiring prediction. The default ranking is `0.70 * relevance + 0.30 * exp(-age_days / 7)`. Future timestamps clamp to age zero. Unknown dates contribute no recency component. Unassessed jobs use the weighted recency component only and are explicitly labeled Not assessed, not given a fictitious fit score. Separate Newest first and Best fit sorts are available.

## Tracking

Each job card has a direct application link and a status dropdown that saves immediately. The detail view also provides the application link, status dropdown, notes box, and **Save tracking** button. States: New, Saved, Applied, Interviewing, Offer, Rejected, Skipped, and Needs verification. Applied means you manually report applying; it does not claim employer receipt. Opening an application link never changes status. The first Applied action records the date; later status changes preserve it. Notes and statuses survive refreshes, restarts, and discovery scans. Status membership changes only after a confirmed save, and failed writes retain detail edits.

Search covers company, role, location, and saved notes. Filters include status and provider, plus toggles for closed and unverified listings. Results enforce the seven-day posting cutoff; tracked jobs remain visible regardless of age or closure. Unverified listings are not claimed currently open until refreshed. Use Needs verification when an application outcome is unknown.

Export tracking CSV from the board. Cells that could be interpreted as spreadsheet formulas are escaped. `data/tracking.json` is the durable record; it is separate from discovery decisions. Tracking writes are validated, independently locked, and atomically replaced. Unknown job IDs and invalid statuses do not write anything.

## Prepare answers on demand

```bash
python -m applications prepare --portal ashby --job-id UUID
```

Refresh the job first so a currently open eligible listing is stored. The command reads questions without filling the form, uses confirmed profile facts, and optionally uses `OPENAI_API_KEY` for narrative answers (`ANSWER_MODEL` defaults to `gpt-6-luna`). Unsupported or unknown required facts block complete drafts. Jev confidence does not prevent preparation for a role you explicitly select. Saved responses are shown in the board's expandable details. This command never submits anything.

## Private files and local endpoints

`.env`, `profile.md`, `resume.pdf`, listing and tracking JSON, CSV/HTML exports, drafts, schedules, scan state, and application evidence are gitignored. Do not publish them. The local server exposes only `/`, `/api/jobs`, `/api/tracking`, and `/api/export`, not arbitrary repository files. Host validation prevents DNS rebinding; writes require same-origin JSON and are capped at 32 KB. No employer contacts, accounts, cloud hosting, email integrations, or agents are included.

`python -m applications page` generates a read-only HTML snapshot of application records. Use the HTTP board for editable tracking.

## Test

```bash
python -m unittest discover -s tests
git diff --check
```

Install the browser test dependency with `pip install -e '.[browser]'` and `playwright install chromium`. UI tests run against temporary local data only; they do not transmit applications.

Frontend checks:

```bash
cd frontend
npm test
npm run build
```

The compiled interface is served by the local Python server. No API keys are used by the frontend. Railway hosting supports an authenticated API, supervised polling, persistent-volume storage and validated snapshots. The local server's `serve --remote` mode proxies fixed operations without exposing credentials or falling back to local data. See [Hosting](docs/hosting.md) for environment variables, deployment, migration and backup instructions. Deployment and private-data migration remain operator steps; configuring independent volume backups is essential.

## Hosting and polling availability

The current implementation is local-only. No Railway deployment, authentication, scheduled polling, or Cloudflare Tunnel is configured. Polling does not continue during normal laptop sleep, and the board is unavailable when its local server stops.

Railway is the planned option for laptop-independent operation: reuse the Python board and scanner, persist data on a volume, and run bounded polling on a schedule. Before deployment, add authentication, configurable bind address/port and trusted origins, backups, and secure secret configuration. The current loopback-only Host and Origin protections must be adapted deliberately, not disabled. A hosted service also needs private profile provisioning; Git does not contain your profile or runtime data.

Keep a backup of the private `data/` directory, especially `tracking.json`, before any migration. Discovery and tracking must continue sharing a consistent data store; separate hosted services cannot be assumed to share a local volume. A Next.js rewrite or hosted database is not required for the proposed single-service approach.
