# Applications

Ashby/Lever form discovery uses rendered Chromium pages (read-only). Install with
`pip install -e '.[browser]'` and `playwright install chromium`.
Unsupported/unlabelled controls block discovery rather than guessing fields.
Failed/blocked jobs retry on subsequent board polls, even after the freshness cutoff.
Drafted/submitted and rejected jobs remain deduplicated.

Polls Greenhouse, Ashby, and Lever, filters new jobs, asks jev for a yes or no, drafts answers, and records every application.

The decided design is in [docs/job-application-spec.md](docs/job-application-spec.md). The board list is [data/ats-board-directory.csv](data/ats-board-directory.csv) (12,918 boards). The readout is [docs/ats-board-directory.md](docs/ats-board-directory.md).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[browser]'
playwright install chromium
cp .env.example .env
```

Paste keys into `.env`. That file stays out of git.

- `TYPESAFE_API_KEY` for jev
- `OPENAI_API_KEY` for drafted answers
- `ANSWER_MODEL` defaults to `gpt-6-luna`

Add `profile.md` and `resume.pdf` at the repo root. Those stay out of git too.

Polling now submits complete Ashby drafts through the workflow, verifies receipt, and records the outcome. Greenhouse/Lever submission is not implemented; those portals remain draft-only.

The initial safety limit is one Ashby submission attempt per run. `--submit-limit N` explicitly increases that cap; `--draft-only` disables submission. Saved complete Ashby drafts are processed first, then newly screened and drafted jobs. Unknown or blocked submission outcomes stop the run and appear in Blocked with evidence references. Unprocessed boards stay due after a mid-board stop. A workflow run holding the shared execution lock can submit without acquiring it twice; separate submission commands cannot run alongside it.

## One-time backlog and single-job submission

`poll --vendor ashby --board COMPANY --job-id UUID --backlog` scopes the actual workflow to one listing without changing screening. Add `--approve-screening` only after explicit human approval of that listing's fit. This overrides the AI fit score for that exact scoped identity, never hard eligibility, unresolved answers, prior submission, or attempt-journal protections. Approval is stored privately; it is used only when the same vendor, board, and job are explicitly scoped. Ashby UUIDs are canonical; legacy URL-based CSV/draft identities normalize on read to retain deduplication.

An explicitly reviewed pre-click blocked attempt may be retried through `review_preclick_attempt`; its prior evidence is retained in the journal. Unknown or clicked attempts cannot be cleared by that function. A real application that remains on its form after clicking without an explicit receipt is **unknown**, not a successful submission, and must be checked with the employer before retrying.

`python -m applications poll --backlog` scans all boards regardless of schedule and posting age, reopening only age-based rejections. Other rejected, drafted, and submitted jobs remain deduplicated. Normal polls retain the 24-hour freshness cutoff.

After reviewing a complete draft, run:

```bash
python -m applications submit --portal ashby --job-id JOB_ID
```

Submission stops while polling is active, for unresolved answers, changed questions, unsupported controls, CAPTCHA, or ambiguous mappings. Older drafts without live-question snapshots must be regenerated. The first adapter supports standard text, resume uploads, native select/radio choices, and semantically verifiable Yes/No buttons; search-backed autocomplete and multiselect require review.

`data/submission-attempts/` stores the exact draft, attempt states, confirmation text, URLs, and screenshots. Only explicit confirmation after the form disappears records `submitted`. A crash or absent confirmation becomes an unknown outcome requiring manual review; no automatic retry is permitted. Even pre-click blocked attempts require explicit review before any journal reset. Do not delete attempt files to retry without checking the employer outcome.

Polling and submission share a process lock. An interrupted attempt may retain `data/submission.lock`; inspect the journal and ensure no submission process is running before removing that file. Evidence contains personal information and remains gitignored.

## Run

```bash
python -m applications poll --limit 10
python -m applications poll
python -m applications poll --vendor ashby --limit 10
python -m applications poll --recheck-location
python -m applications page
```

Keyword and eligibility checks run without API keys. If `TYPESAFE_API_KEY` or `OPENAI_API_KEY` is missing, the run stops before jev and does not mark those jobs decided. `--data-dir` points the log, schedule, and page at another folder.

## Polling and deduplication

Company boards and individual jobs are tracked separately. Applying to one job
does not exclude the company's board: it may publish other suitable openings.

### Board schedule

The next-check times are stored in `data/board-schedule.json`:

- Previously unseen boards are immediately eligible for polling.
- A successful check with openings schedules the next check after 6 hours.
- A successful check with no openings schedules it after 24 hours.
- Failed requests retry after 6 hours. After 3 consecutive failures, the interval
  increases to 7 days. A successful check resets the failure count.
- Boards are not deleted when a request fails.

Each `poll` command makes one pass through the boards due when it starts.
These intervals determine when a board can be checked again; they do not launch
another run automatically. Recurring runs need a separate scheduler. Boards
checked during a recent pilot are skipped until their next-check time.

### Job-level skip rules

`--recheck-location` re-screens previous pre-model location uncertainties and
includes their Ashby boards even if not yet due. It uses structured primary and
secondary country addresses and known city aliases. Posting freshness is still
enforced; this option does not reopen drafts, submissions, or AI fit rejections.

Jobs are identified by portal plus external job ID. The latest stage in
`data/applications.csv` determines what happens on subsequent board polls:

- `drafted` or `submitted`: skipped.
- `keyword_reject`, `eligibility_reject`, or `jev_no` (including uncertain
  decisions): skipped; these are not automatically reconsidered after profile
  or filter changes.
- `failed`, `blocked`, or an incomplete `jev_yes`: retried when the board is due.
  Retries bypass the posting-age cutoff but still undergo screening.
- Unseen jobs: screened using the current 24-hour posting cutoff. Jobs with no
  posting date are rejected by that filter.

Applications completed manually outside this tool are not known unless their
status is recorded in the local log. Deduplication does not match equivalent
listings across different portals or new IDs for reposted jobs.

Polling can fill and submit supported Ashby forms; use `poll --draft-only` for discovery and drafting without employer submissions. The explicit `submit` command remains available for one saved draft.
Saved responses live in `data/drafts.json` and are displayed alongside each entry
in `data/applications.html`, including entries recorded as submitted. They are
saved drafts. The submission journal stores the draft actually used and receipt evidence; the dashboard links its local path in the status reason. Keep these files private because they can contain personal information.

## Technical behavior

### Discovery and screening

- Python 3.11+ CLI; no database or web server is needed. Run commands from the
  repository or one of its subdirectories.
- Greenhouse: public board API, with detailed descriptions fetched separately
  when needed and questions read with `?questions=true`.
- Ashby: public posting API; unlisted postings are excluded.
- Lever: public postings API, paginated in batches of 100. Tries the EU endpoint
  after a 404 on the default endpoint and remembers the working host.
- Posting timestamps use Greenhouse `first_published`, Ashby `publishedAt`, and
  Lever `createdAt`. These are vendor timestamps, not independently verified
  original posting dates.
- Screening order: job deduplication, title/location/freshness checks,
  deterministic eligibility checks, Jev fit evaluation, form discovery, answer
  drafting, persistence, and HTML regeneration.
- Deterministic checks cover experience, degree/graduation restrictions,
  citizenship, clearance, sponsorship, unpaid work, and non-US requirements.
  These are heuristic text checks, not a complete interpretation of every role.
- An unclear location stops before Jev. A missing description records a failure.
  Title rules live in `src/applications/keywords.py`; eligibility checks live in
  `src/applications/eligibility.py`.

### AI evaluation and answers

- Typesafe AI receives the profile, title, location, and cleaned job description
  (trimmed to 7,000 characters) for `jev-1.13.0` evaluation.
- Jev assesses role family, level, responsibilities, and qualifications. All
  four scores must be at least 0.80 to proceed. Scores at or below 0.20 are
  negative; scores between those thresholds are uncertain and stop the job.
  These thresholds are decision rules, not guarantees of fit or calibrated odds.
- Standard fields use deterministic answers in `answers.py`. Narrative fields
  use the configured OpenAI model with the profile, company, title, description,
  question labels, and available options. The prompt requests concise JSON
  answers and forbids invented candidate facts.
- Some standard candidate facts are currently hardcoded in `answers.py`.
  Updating `profile.md` alone will not update those answers; keep both aligned.
- Unknown required fields block a draft; unknown optional fields are omitted.
  Current employment authorization and STEM OPT eligibility require confirmation.
  Only resume-labelled uploads attach `resume.pdf`; other document requests are
  blocked or omitted until a document is supplied.
- Ashby/Lever questions are read using headless Chromium. The extractor supports
  labelled native controls and some ARIA controls, preserving required flags,
  options, file fields, and date fields. Unlabelled controls or custom dropdowns
  whose options cannot be enumerated fail discovery rather than guess.
  Ashby questions are read at the container level, including Yes/No buttons and
  radio/checkbox groups. The auxiliary resume-autofill uploader is ignored;
  actual resume uploads are retained. Fixed dropdowns may be opened to read
  choices without selecting them. Search-backed autocomplete fields are recorded
  without typing or inventing an option list; their drafted values still need
  review against the live suggestions. SMS consent is separate from the phone
  number and remains unanswered until a preference is supplied.
- No resume file is uploaded to employers. Model calls transmit profile text;
  they do not send the PDF binary. They can incur charges on configured accounts.

### Request limits and failures

- Boards are processed sequentially, in directory order. Public ATS API GET
  attempts are at least 1 second apart, with up to 0.2 seconds of jitter.
  Browser resources and model POSTs are not covered by this GET limiter.
- GET timeout: 30 seconds. Up to 3 attempts for network errors and HTTP 429/503.
  POST timeout: 60 seconds.
- Jev retries HTTP 429/529 up to 4 total attempts, with 2-, 4-, and 8-second waits.
  Answer-model requests do not currently have application-level retries.
- Board-fetch failures update the board schedule and continue. Job-detail or
  form-discovery failures record a failed job and continue.
- Missing credentials/profile, Jev errors, answer-model non-200 responses, and
  certain job-level network errors stop the run with exit code 2. The affected
  board remains immediately due; completed job records are retained.
- Successful completion returns exit code 0. Unexpected exceptions can terminate
  the process without the controlled-stop handling.

### Files and dashboard

- `profile.md`, `resume.pdf`, and `.env`: private inputs at the repository root.
- `data/ats-board-directory.csv`: company board inventory.
- `data/board-schedule.json`: next-check times, consecutive failures, last status,
  open-job count, and remembered Lever host.
- `data/scan-state.json`: run status, process ID, timestamps, current board,
  and completed/target board counts for the current run. Read timeouts are
  normalized into retryable network errors. Unexpected failures and interrupts
  save a terminal status and regenerate the dashboard.
- `data/applications.csv`: append-only stage log. The dashboard shows the latest
  stage for each portal/job ID, not every historical event.
- `data/drafts.json`: latest saved field responses per job. Retries can replace a
  previous draft; historical answer snapshots are not retained.
- `data/applications.html`: self-contained local dashboard, regenerated after
  each successfully processed board and at run completion. Refresh the browser
  to see changes; there is no live push or automatic refresh.
- The dashboard defaults to Submitted. Other filters show Drafted, Blocked,
  Failed, and Uncertain. Rejected jobs remain in the CSV but are not displayed.
  Summary cards count all logged jobs, rejected jobs, boards checked, and jobs
  with AI evaluations. The search box filters the selected status by company,
  role, portal, or reason, without a server or additional dependency. It does
  not search rejected jobs, whose detailed records remain in the CSV.
  Run status is a saved snapshot with a last-update timestamp: reload to see
  new progress. A force-killed process cannot rewrite its HTML; regenerating
  the page detects a missing recorded process and labels it interrupted.
- `--data-dir` changes the directory used for the board inventory and all output
  files. It does not change where the profile, resume, or `.env` are loaded from.

### Operational limits and tests

Only run one poll process at a time. Storage has no process lock, and JSON files
are rewritten without atomic replacement; concurrent runs can duplicate work or
overwrite state. There is no unattended submission, recurring scheduler,
cross-portal deduplication, job-description change detection, or automatic
reconsideration of rejected jobs. The profile is loaded once per run; edits to it
take effect on the next run.

Run the tests with:

```bash
python -m unittest discover -s tests
```

Tests cover filtering, schedules, deduplication/retries, answer planning,
dashboard rendering, and form extraction against local Chromium fixtures. They
do not establish that live vendor/model APIs or every hosted form are compatible.
The browser fixture test is skipped when Playwright is not installed; when it is
installed, Chromium binaries are required.
