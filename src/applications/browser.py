"""Read rendered application controls. Never fill or submit a form."""

from applications.models import Question
from applications.portals import BoardError

EXTRACT_FIELDS = r"""() => {
 const visible = e => {
  const s = getComputedStyle(e), r = e.getBoundingClientRect();
  return !!e.getClientRects().length && s.visibility !== 'hidden' && s.display !== 'none' &&
   !(r.width <= 1 && r.height <= 1 && (s.clipPath !== 'none' || s.clip !== 'auto'));
 };
 const text = e => e ? e.textContent.trim() : '';
 const fields = [], seen = new Set();
 const handled = new Set();
 for (const entry of document.querySelectorAll('.ashby-application-form-field-entry, fieldset.ashby-application-form-input-checkbox-group, fieldset.ashby-application-form-input-radio-group')) {
  if (!visible(entry)) continue;
  const title = entry.querySelector('.ashby-application-form-question-title, legend, label');
  const label = text(title).replace(/\s*\*\s*$/, '');
  if (!label) throw new Error('Unlabelled Ashby question');
  const controls = Array.from(entry.querySelectorAll('input,textarea,select,[role="combobox"],[role="radiogroup"]'));
  const enabled = controls.filter(e => !e.disabled && e.type !== 'hidden' && !e.closest('.ashby-application-form-texting-consent-description'));
  controls.forEach(e => handled.add(e));
  const required = enabled.some(e=>e.required || e.getAttribute('aria-required')==='true') ||
   !!(title && (/required/i.test(title.className) || text(title).includes('*'))) || entry.getAttribute('aria-required')==='true';
  let options = [], kind = 'text';
  const yesno = Array.from(entry.querySelectorAll('.ashby-application-form-input-yesno-option, button[data-option]'));
  const fixtureButtons = Array.from(entry.querySelectorAll('button')).filter(e=>['Yes','No'].includes(text(e)));
  if (yesno.length || fixtureButtons.length === 2) {
   options = (yesno.length ? yesno : fixtureButtons).map(text);
  } else if (enabled.some(e=>e.type==='file')) {
   kind = 'file';
  } else if (enabled.some(e=>e.type==='checkbox' || e.type==='radio')) {
   const choices = enabled.filter(e=>e.type==='checkbox'||e.type==='radio');
   options = choices.map(e=>e.getAttribute('aria-label') || Array.from(e.labels||[]).map(text).join(' ') || e.value);
   kind = choices.some(e=>e.type==='checkbox') ? 'multiselect' : 'text';
  } else if (enabled.some(e=>e.tagName==='SELECT')) {
   options = Array.from(enabled.find(e=>e.tagName==='SELECT').options).filter(o=>!o.disabled&&o.value!=='').map(text);
  } else if (entry.querySelector('[role="combobox"]')) {
   const combo = entry.querySelector('[role="combobox"]');
   if (combo.getAttribute('aria-autocomplete') === 'list') {
    kind = 'autocomplete';
   } else {
    const list = document.getElementById(combo.getAttribute('aria-controls'));
    options = combo.dataset.extractedOptions ? JSON.parse(combo.dataset.extractedOptions) : (list ? Array.from(list.querySelectorAll('[role="option"]')).map(text) : []);
    if (!options.length) throw new Error('Cannot enumerate custom dropdown: '+label);
   }
  } else if (enabled.some(e=>e.type==='date')) {
   kind = 'date';
  } else if (!enabled.length) {
   throw new Error('Unsupported Ashby question control: '+label);
  }
  fields.push({label,required,options,kind});
 }
 for (const consent of document.querySelectorAll('.ashby-application-form-texting-consent-description')) {
  if (!visible(consent)) continue;
  const choices = Array.from(consent.querySelectorAll('input[type="radio"]'));
  choices.forEach(e=>handled.add(e));
  fields.push({label:'Consent to receive text message updates', required:choices.some(e=>e.required),
   options:choices.map(e=>Array.from(e.labels||[]).map(text).join(' ')),kind:'text'});
 }
 for (const e of document.querySelectorAll('input, textarea, select, [role="radiogroup"], [role="combobox"]')) {
  if (handled.has(e) || e.closest('.ashby-application-form-autofill-input-root')) continue;
  if (!visible(e) || e.disabled || ['hidden','submit','button','reset'].includes(e.type)) continue;
  if (e.closest('[role="radiogroup"]') && e.getAttribute('role') !== 'radiogroup') continue;
  const group = e.closest('fieldset, [role="group"], [role="radiogroup"]');
  let label = (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => text(document.getElementById(id))).filter(Boolean).join(' ') || e.getAttribute('aria-label') || Array.from(e.labels || []).map(text).join(' ');
  let options = [], required = e.required || e.getAttribute('aria-required') === 'true' || !!(group && group.getAttribute('aria-required') === 'true');
  if (e.type === 'radio') {
   if (seen.has(e.name)) continue;
   seen.add(e.name);
   const peers = Array.from(document.querySelectorAll('input[type="radio"]')).filter(r => r.name === e.name && visible(r));
   options = peers.map(r => r.getAttribute('aria-label') || Array.from(r.labels || []).map(text).join(' ') || r.value);
   required = required || peers.some(r => r.required);
   label = group && (text(group.querySelector('legend')) || group.getAttribute('aria-label')) || '';
  } else if (e.tagName === 'SELECT') {
   options = Array.from(e.options).filter(o => !o.disabled && o.value !== '').map(text);
  } else if (e.getAttribute('role') === 'radiogroup') {
   options = Array.from(e.querySelectorAll('[role="radio"]')).map(r => r.getAttribute('aria-label') || text(r));
  } else if (e.getAttribute('role') === 'combobox') {
   if (e.getAttribute('aria-autocomplete') === 'list') {
    if (!label) throw new Error('Unlabelled autocomplete control');
    fields.push({label,required:!!required,options:[],kind:'autocomplete'});
    continue;
   }
   const list = document.getElementById(e.getAttribute('aria-controls'));
   options = e.dataset.extractedOptions ? JSON.parse(e.dataset.extractedOptions) : (list ? Array.from(list.querySelectorAll('[role="option"]')).map(text) : []);
   if (!options.length) throw new Error('Cannot enumerate custom dropdown: ' + label);
  }
  if (!label) throw new Error('Unlabelled application control: ' + (e.name || e.id || e.tagName));
  fields.push({label: label.replace(/\s*\*\s*$/, ''), required: !!required || label.includes('*'), options, kind: ['file','date'].includes(e.type) ? e.type : 'text'});
 }
 return fields;
}"""

def questions_from_rendered_page(page) -> list[Question]:
    # Opening a menu exposes its choices; never choose one or enter field data.
    if hasattr(page, 'locator'):
        combos = page.locator('[role="combobox"]')
        for index in range(combos.count()):
            combo = combos.nth(index)
            if not combo.is_visible() or combo.is_disabled() or combo.evaluate('(e)=>e.tagName === "SELECT"'):
                continue
            if combo.get_attribute('aria-autocomplete') == 'list':
                continue  # Search-backed field: capture its label, not guessed choices.
            combo.click()
            options = page.locator('[role="option"]:visible')
            options.first.wait_for(state='visible', timeout=5000)
            values = options.all_text_contents()
            values = [value.strip() for value in values if value.strip()]
            if not values:
                raise BoardError(None, 'Custom dropdown has no readable options')
            combo.evaluate('(e, values)=>e.dataset.extractedOptions=JSON.stringify(values)', values)
            combo.press('Escape')
    return [Question(f['label'], f['required'], tuple(f['options']), f['kind']) for f in page.evaluate(EXTRACT_FIELDS)]

def fetch_rendered_questions(url: str) -> list[Question]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as err:
        raise BoardError(None, 'Install applications[browser] and run playwright install chromium') from err
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                if response is not None and response.status >= 400:
                    raise BoardError(response.status, 'Application page could not be loaded')
                page.locator('input:not([type="hidden"]), textarea, select, [role="radiogroup"], [role="combobox"]').first.wait_for(state='visible', timeout=20000)
                page.wait_for_load_state('networkidle', timeout=15000)
                return questions_from_rendered_page(page)
            finally:
                browser.close()
    except BoardError:
        raise
    except Exception as err:
        raise BoardError(None, f'Rendered form discovery failed: {err}') from err
