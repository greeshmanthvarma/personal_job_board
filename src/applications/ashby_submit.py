"""Conservative Ashby adapter. Unsupported controls stop before the click."""

import re
import time
from pathlib import Path

from applications.browser import questions_from_rendered_page
from applications.submission import SubmissionBlocked


def validate_snapshot(questions, draft):
    snapshot = [{'label': q.label, 'required': q.required, 'kind': q.kind, 'options': list(q.options)} for q in questions]
    if 'questions' not in draft or snapshot != draft['questions']:
        raise SubmissionBlocked('Live questions differ from saved draft; regenerate and review the draft.')
    fields = draft.get('fields', [])
    if len(fields) != len(questions):
        raise SubmissionBlocked('Incomplete draft field mapping.')
    for question, field in zip(questions, fields):
        if field.get('label') != question.label or field.get('required') != question.required:
            raise SubmissionBlocked('Draft field mapping changed.')
        if field.get('kind') not in {'answered', 'attach', 'omitted'}:
            raise SubmissionBlocked('Draft contains an unresolved answer.')
        if question.required and (field.get('kind') == 'omitted' or not field.get('answer')):
            raise SubmissionBlocked('Required answer missing.')
        if question.options and field.get('kind') == 'answered' and field.get('answer') not in question.options:
            raise SubmissionBlocked('Answer is not an exact available option.')


def confirmation_text(text):
    for sentence in ('Your application has been received', 'Your application was successfully submitted', 'Thank you for applying'):
        if re.search(r'(?im)^\s*' + re.escape(sentence) + r'[.!]?\s*$', text):
            return sentence
    return None


def _captcha(page):
    # Passive CAPTCHA widgets are common. Challenge frames or visible tasks require a human.
    return page.locator('iframe[title*="challenge" i]:visible, iframe[title*="recaptcha" i]:visible, iframe[title*="hcaptcha" i]:visible').count() > 0


def fill_ashby(page, draft, resume: Path):
    questions = questions_from_rendered_page(page)
    validate_snapshot(questions, draft)
    if _captcha(page):
        raise SubmissionBlocked('CAPTCHA requires manual completion.')
    verification = []
    entries = page.locator('.ashby-application-form-field-entry, fieldset.ashby-application-form-input-checkbox-group, fieldset.ashby-application-form-input-radio-group')
    for q, field in zip(questions, draft['fields']):
        if field['kind'] == 'omitted':
            continue
        matching = []
        for index in range(entries.count()):
            entry = entries.nth(index)
            if not entry.is_visible():
                continue
            title = entry.locator('.ashby-application-form-question-title, legend, label').first
            if title.count() and re.sub(r'\s*\*\s*$', '', title.inner_text().strip()) == q.label:
                matching.append(entry)
        if len(matching) != 1:
            raise SubmissionBlocked('Question does not map to one supported Ashby container.')
        entry = matching[0]
        answer = field['answer']
        if q.kind in {'autocomplete', 'multiselect'}:
            raise SubmissionBlocked('Autocomplete or multiselect requires manual review.')
        if field['kind'] == 'attach':
            upload = entry.locator('input[type="file"]')
            if upload.count() != 1 or not resume.is_file():
                raise SubmissionBlocked('Resume upload unavailable.')
            upload.set_input_files(str(resume))
            if upload.evaluate('(e)=>e.files.length === 1 && e.files[0].name === "resume.pdf"') is not True:
                raise SubmissionBlocked('Resume attachment could not be verified.')
            continue
        select = entry.locator('select')
        radios = entry.locator('input[type="radio"], input[type="checkbox"]')
        buttons = entry.locator('.ashby-application-form-input-yesno-option, button[data-option]')
        if q.options:
            if select.count() == 1:
                select.select_option(label=answer)
                verification.append(lambda control=select, value=answer: control.locator('option:checked').inner_text().strip() == value)
            elif radios.count() and not buttons.count():
                control = entry.get_by_role('radio', name=answer, exact=True)
                if control.count() != 1:
                    control = entry.get_by_role('checkbox', name=answer, exact=True)
                if control.count() != 1:
                    raise SubmissionBlocked('Choice mapping is ambiguous.')
                control.check()
                verification.append(lambda control=control: control.is_checked())
            elif buttons.count():
                control = buttons.filter(has_text=re.compile(r'^\s*' + re.escape(answer) + r'\s*$'))
                if control.count() != 1:
                    raise SubmissionBlocked('Yes/No mapping is ambiguous.')
                control.click()
                # Require a standard semantic selected state, not a guessed CSS class.
                verification.append(lambda control=control: control.get_attribute('aria-pressed') == 'true' or control.get_attribute('aria-checked') == 'true')
            else:
                raise SubmissionBlocked('Custom choice control is not supported yet.')
        else:
            control = entry.locator('input:not([type="hidden"]):not([type="file"]):not([type="radio"]):not([type="checkbox"]), textarea')
            if control.count() != 1 or control.get_attribute('role') == 'combobox':
                raise SubmissionBlocked('Text control is ambiguous or unsupported.')
            control.fill(answer)
            verification.append(lambda control=control, value=answer: control.input_value() == value)
    if not all(check() for check in verification):
        raise SubmissionBlocked('Filled answers could not all be verified.')
    if page.locator('[aria-invalid="true"]:visible').count():
        raise SubmissionBlocked('Form contains validation errors.')
    if not page.evaluate('() => Array.from(document.querySelectorAll("input,textarea,select")).filter(e=>!e.disabled && e.type!=="hidden" && e.getClientRects().length).every(e=>e.checkValidity())'):
        raise SubmissionBlocked('Browser validation failed.')


def submit_ashby(page, draft, resume, before_click, evidence_dir):
    fill_ashby(page, draft, resume)
    button = page.get_by_role('button', name=re.compile(r'^Submit application$', re.I))
    if button.count() != 1 or not button.is_enabled():
        raise SubmissionBlocked('Submit button is unavailable or ambiguous.')
    page.screenshot(path=str(evidence_dir/'prepared.png'), full_page=True)
    before_click()
    button.click(timeout=15000)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _captcha(page):
            return {'status': 'unknown', 'reason': 'CAPTCHA appeared after submit; review before retrying'}
        # Require the application form to disappear as well as exact confirmation text.
        text = page.locator('body').inner_text()
        confirmation = confirmation_text(text)
        if confirmation and not page.locator('.ashby-application-form-field-entry:visible').count() and not button.count():
            path = evidence_dir/'confirmed.png'
            page.screenshot(path=str(path), full_page=True)
            return {'status': 'confirmed', 'confirmation': confirmation, 'url': page.url, 'screenshot': str(path)}
        page.wait_for_timeout(500)
    page.screenshot(path=str(evidence_dir/'unknown.png'), full_page=True)
    return {'status': 'unknown', 'reason': 'No explicit employer confirmation; manual review required', 'url': page.url}


def submit_ashby_url(url, draft, resume, before_click, evidence_dir):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if response is None or response.status >= 400:
                raise SubmissionBlocked('Application page unavailable.')
            page.locator('.ashby-application-form-field-entry').first.wait_for(timeout=20000)
            return submit_ashby(page, draft, resume, before_click, evidence_dir)
        finally:
            browser.close()
