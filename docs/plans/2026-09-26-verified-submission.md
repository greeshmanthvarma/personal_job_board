# Verified Application Submission Implementation Plan

**Goal:** Submit one eligible, complete application and retain its answers and employer confirmation.

**Architecture:** An explicit single-job command consumes a saved draft and the latest CSV record. An Ashby browser adapter validates the live form, fills supported controls, and submits only after all checks pass; a durable attempt journal prevents repeat submissions after crashes or ambiguous results.

**Tech stack:** Python, Playwright, unittest, existing CSV and HTML tracker.

**Spec:** This plan records the accepted conversation requirement: validate one suitable application before broader runs.

## Global constraints

- First milestone supports Ashby only and one explicitly selected job per command. No bulk submissions, account creation, CAPTCHA bypass, or employer contact.
- Use saved profile facts; never invent authorization, dates, achievements, or consent. Unknown required answers and unsupported controls stop before submission.
- A click is not success. Require an explicit employer confirmation; ambiguous outcomes require human review and cannot be automatically retried.
- Preserve existing records and unrelated working-tree changes. No automatic commits.
- No claims of completed applications before live verification.

## Review focus

1. Duplicate/crash prevention: `test_attempt_cannot_be_retried`.
2. Stale or incomplete drafts: `test_changed_questions_block_submission`.
3. Unsupported controls and CAPTCHA: `test_unsupported_control_blocks_before_click`.
4. Explicit confirmation: `test_click_without_confirmation_is_unknown`.
5. Tracker evidence: `test_confirmed_attempt_creates_submitted_record`.

### Task 1: Durable single-job attempt gate

**Files:** Create `src/applications/submission.py`; test `tests/test_submission.py`.

**Interfaces:** `begin_attempt(data: Path, identity: str) -> str` creates an exclusive per-job journal file under `data/submission-attempts/`; `finish_attempt(data: Path, identity: str, status: str, evidence: dict) -> None` atomically updates it. States: prepared, clicking, confirmed, unknown, blocked. Existing clicking/confirmed/unknown attempts prohibit further automated clicks. Journal stores timestamp, URL, saved answers, status, and confirmation text; never credentials.

- [ ] Write `test_attempt_cannot_be_retried`, including an existing clicking journal after a simulated crash.
- [ ] Run `.venv/bin/python -m unittest discover -s tests -p test_submission.py`; expect missing interface failure.
- [ ] Implement exclusive file creation and atomic updates; reject records already submitted and drafts not in drafted state.
- [ ] Run the narrow suite; expect PASS.
- [ ] Run `.venv/bin/python -m unittest discover -s tests`; expect existing tests unchanged.

### Task 2: Ashby fill, verification, and confirmation

**Files:** Create `src/applications/ashby_submit.py`; modify `src/applications/submission.py`; test `tests/test_submission.py`.

**Interfaces:** `submit_ashby(page, draft: dict, resume: Path, before_click: Callable[[], None]) -> dict` returns status and evidence. Compare freshly extracted labels, required flags, kinds, and options with saved draft questions. Add this question snapshot to draft payloads in `src/applications/pipeline.py` and `src/applications/cli.py`; old drafts lacking snapshots must be regenerated.

- [ ] Write fixture tests `test_changed_questions_block_submission`, `test_unsupported_control_blocks_before_click`, and `test_click_without_confirmation_is_unknown`; run narrow suite and expect missing adapter failures.
- [ ] Implement exact question-container matching, text filling, file upload, native select/radio/checkbox and supported Yes/No controls. Verify resulting values and attachment before clicking. Search-backed autocomplete, unsupported custom controls, CAPTCHA, ambiguous matches, missing required fields, and validation errors block. Do not check optional consent implicitly.
- [ ] Persist clicking state through `before_click` immediately before the single Submit click. Wait for an explicit application-received confirmation on the same employer page; absence or browser failure after click returns unknown. Save confirmation text, URL, and screenshot path. Avoid interpreting generic thank-you text outside the application confirmation as success.
- [ ] Run narrow fixture suite; expect PASS with zero external transmissions.
- [ ] Run full suite with permitted browser execution.

### Task 3: Command and tracker integration, then one live validation

**Files:** Modify `src/applications/cli.py`, `src/applications/page.py`, `README.md`, `.gitignore`; test `tests/test_submission.py`.

**Interfaces:** `applications submit --portal ashby --job-id ID` loads latest record and saved draft, acquires an exclusive submission-run lock, and invokes the adapter. Refuse if polling is active, job is not drafted, record is already submitted, or attempt state is uncertain. Only confirmed results append a submitted `Record`; blocked/unknown outcomes append blocked records with evidence references. Keep saved answers visible in the tracker and label unknown outcomes as needing review.

- [ ] Write `test_confirmed_attempt_creates_submitted_record`, plus tests for blocked and unknown outcomes never becoming submitted. Run narrow suite; expect missing command failure.
- [ ] Implement command, lock release in finally, evidence persistence, tracker regeneration, and explicit scope documentation. Ignore journals/screenshots in git.
- [ ] Run narrow and full suites; expect PASS.
- [ ] Generate one eligible Ashby draft through the backlog scan. Inspect its saved factual and narrative answers for unsupported assertions. Select the role and disclose it to the user before transmitting the application.
- [ ] Run the single-job command only for the selected suitable application. Verify confirmation and tracker entry; stop if none exists. Report the actual outcome and any required user input. Do not enable broad runs in this milestone.

## Coverage and exclusions

This delivers one verified submission, saved responses, duplicate protection, and an exception path. Greenhouse, Lever, bulk automation, scheduling, generalized autocomplete, and automatic retry after an uncertain submit are intentionally excluded until the first adapter is proven.
