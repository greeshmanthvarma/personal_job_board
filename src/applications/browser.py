"""Read rendered application controls. Never fill or submit a form."""

from applications.models import Question
from applications.portals import BoardError

EXTRACT_FIELDS = r"""() => {
 const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
 const text = e => e ? e.textContent.trim() : '';
 const fields = [], seen = new Set();
 for (const e of document.querySelectorAll('input, textarea, select, [role="radiogroup"], [role="combobox"]')) {
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
   const list = document.getElementById(e.getAttribute('aria-controls'));
   options = list ? Array.from(list.querySelectorAll('[role="option"]')).map(text) : [];
   if (!options.length) throw new Error('Cannot enumerate custom dropdown: ' + label);
  }
  if (!label) throw new Error('Unlabelled application control: ' + (e.name || e.id || e.tagName));
  fields.push({label: label.replace(/\s*\*\s*$/, ''), required: !!required || label.includes('*'), options, kind: ['file','date'].includes(e.type) ? e.type : 'text'});
 }
 return fields;
}"""

def questions_from_rendered_page(page) -> list[Question]:
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
