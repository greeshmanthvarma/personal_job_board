# Personal job board

A private, local job board for discovering relevant Ashby, Greenhouse, and Lever roles, preparing answers, and tracking applications you submit yourself. **No application filling or submission functionality exists.**

## Start

Run from this repository:

```bash
source .venv/bin/activate
python -m applications serve
```

Open http://127.0.0.1:8765. This editable board replaces the old file-based HTML view. The server binds only to loopback and must stay running while you use it.

## Discover jobs

```bash
python -m applications poll --limit 10
python -m applications poll --backlog
python -m applications poll --vendor ashby --board Ambral --backlog
```

Discovery uses public ATS APIs, never employer application writes. It runs without model keys. Titles, clearly incompatible locations, and hard eligibility requirements filter listings; posting age and AI uncertainty do not hide otherwise relevant roles. Older currently listed roles remain available. A successful full board scan marks missing listings closed; failed or job-scoped scans do not. The historical records and attempt evidence are untouched.

The 12,918-board directory is in `data/ats-board-directory.csv`. `--limit` caps boards, `--vendor` selects one provider, and `--board` selects one company slug. `--job-id` requires a board and vendor and processes only that listing. `--backlog` scans regardless of board schedule. Standard polling checks due boards: nonempty boards after six hours, empty boards after one day, first two failed attempts after six hours, and three or more consecutive failures after one week. There is no background scheduler installed; each poll is one pass. GETs are paced at least one second apart with jitter, bounded timeout/retries, and provider-specific parsing. Greenhouse descriptions are hydrated only for title/location matches. Concurrent scans are prevented by a local lock.

## Jev relevance and ranking

With `TYPESAFE_API_KEY` in `.env` and `profile.md` present, Jev assesses matching listings. An assessment is cached by job content and profile fingerprint. `--assessment-limit` defaults to 50 new assessments per scan; discovery continues beyond that budget or when Jev is unavailable. A later due scan can assess remaining jobs. OpenAI is not used during discovery.

Relevance is the mean of Jev's four existing scores: role family, level, responsibilities, and qualifications. It is an assessment signal, not a hiring prediction. The default ranking is `0.70 * relevance + 0.30 * exp(-age_days / 7)`. Future timestamps clamp to age zero. Unknown dates contribute no recency component. Unassessed jobs use the weighted recency component only and are explicitly labeled Not assessed, not given a fictitious fit score. Separate Newest first and Best fit sorts are available.

## Tracking

Use the status dropdown, notes box, and **Save tracking** button on each listing. States: New, Saved, Applied, Interviewing, Offer, Rejected, Skipped, and Needs verification. Applied means you manually report applying; it does not claim employer receipt. Opening an application link never changes status. The first Applied action records the date; later status changes preserve it. Notes and statuses survive refreshes, restarts, and discovery scans. Unsaved edits are labeled only after a successful save, and failed writes retain your text.

Search covers company, role, location, and saved notes. Filters include status and provider, and toggles include closed jobs and historical unverified listings. Existing tracked closed jobs remain visible. Older open roles are not excluded by the default view. Historical age-only rejections and AI assessments can be viewed under Older / unverified; they are not claimed currently open until refreshed. Historical confirmed submissions default to Applied. Ambral's unknown outcome defaults to Needs verification and is not automatically changed to Applied or New.

Export tracking CSV from the board. Cells that could be interpreted as spreadsheet formulas are escaped. `data/tracking.json` is the durable record; it is separate from discovery decisions. Tracking writes are validated, independently locked, and atomically replaced. Unknown job IDs and invalid statuses do not write anything.

## Prepare answers on demand

```bash
python -m applications prepare --portal ashby --job-id UUID
```

Refresh the job first so a currently open eligible listing is stored. The command reads questions without filling the form, uses confirmed profile facts, and optionally uses `OPENAI_API_KEY` for narrative answers (`ANSWER_MODEL` defaults to `gpt-6-luna`). Unsupported or unknown required facts block complete drafts. Jev confidence does not prevent preparation for a role you explicitly select. Saved responses are shown in the board's expandable details. This command never submits anything.

## Private files and local endpoints

`.env`, `profile.md`, `resume.pdf`, listing and tracking JSON, the legacy CSV/HTML, drafts, schedules, scan state, and historical submission evidence are gitignored. Do not publish them. The local server exposes only `/`, `/api/jobs`, `/api/tracking`, and `/api/export`, not arbitrary repository files. Host validation prevents DNS rebinding; writes require same-origin JSON and are capped at 32 KB. No employer contacts, accounts, cloud hosting, email integrations, or agents are included.

`python -m applications page` regenerates the old read-only historical HTML snapshot. It does not offer editable tracking; use the HTTP board instead. Removed submission code is recoverable in Git commit `2ddeec1`; removal is recorded in `c9ae25e`. Old attempt outcomes remain evidence, not active submission functionality.

## Test

```bash
python -m unittest discover -s tests
git diff --check
```

Install the browser test dependency with `pip install -e '.[browser]'` and `playwright install chromium`. UI tests run against temporary local data only; they do not transmit applications.
