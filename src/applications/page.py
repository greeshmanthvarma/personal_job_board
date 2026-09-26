"""Static applications page. Submitted is the default view."""

import html
from pathlib import Path

from applications.log import latest_by_job, load_drafts, load_records
from applications.schedule import load_schedule
from applications.runstate import load_run

_PAGE_STAGES = {"submitted", "drafted", "blocked", "failed", "jev_yes", "jev_no"}


def render_page(csv_path: Path, html_path: Path, drafts_path: Path) -> None:
    rows = latest_by_job(load_records(csv_path))
    drafts = load_drafts(drafts_path)
    visible = []
    for row in rows:
        if row.stage not in _PAGE_STAGES:
            continue
        if row.stage == "jev_no" and not row.reason.startswith("uncertain"):
            continue
        visible.append(row)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {'screened': len(rows), 'boards': len(load_schedule(csv_path.parent / 'board-schedule.json')),
               'rejected': sum(r.stage in {'keyword_reject', 'eligibility_reject'} or (r.stage == 'jev_no' and not r.reason.startswith('uncertain')) for r in rows),
               'evaluated': sum(bool(r.model) for r in rows)}
    html_path.write_text(_document(visible, drafts, summary=summary, run=load_run(csv_path.parent / 'scan-state.json')), encoding="utf-8")


def _document(rows: list, drafts: dict, *, summary: dict | None = None, run: dict | None = None) -> str:
    summary, run = summary or {}, run or {}
    stats = ''.join(f'<div class="stat"><span>{label}</span><strong>{int(summary.get(key, 0)):,}</strong></div>' for key, label in [('screened','Jobs screened'),('boards','Boards checked'),('rejected','Rejected'),('evaluated','AI evaluated')])
    run_label = html.escape(str(run.get('status', 'unknown')).capitalize())
    progress = f"{int(run.get('processed_boards', 0)):,} / {int(run.get('target_boards', 0)):,} boards this run"
    run_detail = html.escape(' · '.join(str(v) for v in [progress, run.get('current_board'), run.get('message'), 'Last update: ' + str(run.get('updated_at', 'not recorded'))] if v))
    counts = {"submitted": 0, "drafted": 0, "blocked": 0, "failed": 0, "uncertain": 0}
    body = []
    for row in rows:
        key = f"{row.portal}\t{row.external_job_id}"
        stage = "uncertain" if row.stage == "jev_no" else ("drafted" if row.stage == "jev_yes" else row.stage)
        if stage in counts:
            counts[stage] += 1
        date = (row.timestamp or "")[:10]
        link = html.escape(row.link, quote=True)
        body.append(
            "<tr data-stage=\"{stage}\" data-key=\"{key}\" data-search=\"{search}\">"
            "<td>{company}</td><td>{role}</td><td>{portal}</td><td>{date}</td>"
            "<td><a href=\"{link}\" target=\"_blank\" rel=\"noopener\">{link_text}</a></td>"
            "<td><span class=\"status\">{status}</span></td><td>{responses}</td></tr>".format(
                stage=html.escape(stage, quote=True),
                key=html.escape(key, quote=True),
                search=html.escape(' '.join([row.company, row.job, row.portal, row.reason]).lower(), quote=True),
                company=html.escape(row.company),
                role=html.escape(row.job),
                portal=html.escape(row.portal),
                date=html.escape(date),
                link=link,
                link_text=html.escape(row.link),
                status=html.escape(row.stage),
                responses=_responses(row.reason, drafts.get(key)),
            )
        )
    buttons = " ".join(
        f'<button type="button" data-filter="{name}">{label} ({counts[name]})</button>'
        for name, label in (
            ("submitted", "Submitted"),
            ("drafted", "Drafted"),
            ("blocked", "Blocked"),
            ("failed", "Failed"),
            ("uncertain", "Uncertain"),
        )
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Applications</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f4f6fa; color: #253047; }}
main {{ max-width: 1440px; margin: auto; padding: 56px 32px; }}
.eyebrow {{ font-size: 11px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; color: #64748b; margin: 0 0 8px; }}
h1 {{ font-size: 36px; letter-spacing: -.04em; line-height: 1.2; margin: 0 0 16px; color: #17243b; }}
.notice {{ max-width: 780px; color: #64748b; margin-bottom: 28px; }}
.filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 24px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 12px; margin: 22px 0; }}
.stat {{ background: white; border: 1px solid #e1e6ef; border-radius: 12px; padding: 18px; }}
.stat span {{ display: block; color: #64748b; font-size: 12px; }}
.stat strong {{ font-size: 28px; letter-spacing: -.03em; }}
.run-status {{ color: #526078; background: #eaf0ff; padding: 14px 18px; border-radius: 10px; overflow-wrap: anywhere; }}
.search {{ display: block; margin: 0 0 20px; color: #526078; font-size: 12px; font-weight: 600; }}
.search input {{ display: block; width: 100%; max-width: 520px; margin-top: 6px; padding: 12px 14px; border: 1px solid #dbe2ed; border-radius: 9px; font: inherit; font-size: 14px; background: white; }}
.search input:focus-visible {{ outline: 3px solid #818cf8; outline-offset: 2px; }}
button {{ font: inherit; font-weight: 600; border: 1px solid #dbe2ed; border-radius: 9px; background: white; color: #526078; padding: 10px 16px; cursor: pointer; transition: background .15s, border-color .15s; }}
button:hover {{ background: #eef2ff; border-color: #a5b4fc; }}
button.active {{ background: #243c70; border-color: #243c70; color: white; box-shadow: 0 3px 8px #243c701c; }}
button:focus-visible, a:focus-visible, summary:focus-visible {{ outline: 3px solid #818cf8; outline-offset: 3px; }}
.table-wrap {{ overflow-x: auto; border: 1px solid #e1e6ef; border-radius: 14px; background: white; box-shadow: 0 8px 28px #17243b06; }}
table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
th, td {{ text-align: left; padding: 18px 16px; border-bottom: 1px solid #eef1f6; vertical-align: top; }}
th {{ background: #f9fafc; color: #768196; text-transform: uppercase; font-size: 10px; font-weight: 700; letter-spacing: .09em; white-space: nowrap; }}
tbody tr:last-child td {{ border-bottom: none; }}
tbody tr:hover {{ background: #fafbfe; }}
td:first-child {{ font-weight: 650; color: #17243b; }}
td:nth-child(3), td:nth-child(4) {{ color: #768196; font-size: 12px; white-space: nowrap; }}
td:nth-child(5) {{ max-width: 200px; overflow-wrap: anywhere; font-size: 12px; }}
tr[hidden] {{ display: none; }}
a {{ color: #4266a8; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.status {{ display: inline-block; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 650; background: #eef2f7; color: #526078; }}
tr[data-stage="submitted"] .status {{ background: #e5f6ed; color: #21724c; }}
tr[data-stage="drafted"] .status {{ background: #eaf0ff; color: #395cad; }}
tr[data-stage="blocked"] .status, tr[data-stage="uncertain"] .status {{ background: #fff3db; color: #966414; }}
tr[data-stage="failed"] .status {{ background: #fdebec; color: #a3434d; }}
.responses {{ min-width: 220px; }}
.responses summary {{ cursor: pointer; font-size: 12px; font-weight: 600; color: #4266a8; }}
.responses[open] {{ max-width: 440px; }}
.responses p {{ font-size: 12px; color: #64748b; overflow-wrap: anywhere; }}
.responses dt {{ font-weight: 600; margin-top: 0.8rem; }}
.responses dd {{ margin: 6px 0 14px; white-space: pre-wrap; overflow-wrap: anywhere; padding: 10px 12px; background: #f4f6fa; border-radius: 8px; font-size: 13px; font-weight: 400; }}
.field-status {{ font-weight: normal; color: #57534e; }}
#empty {{ color: #64748b; padding: 30px; text-align: center; border: 1px dashed #cbd5e1; border-radius: 12px; background: #ffffff80; margin: 0 0 20px; }}
@media (max-width: 640px) {{ main {{ padding: 28px 16px; }} h1 {{ font-size: 29px; }} button {{ padding: 8px 12px; font-size: 12px; }} }}
@media (prefers-reduced-motion: reduce) {{ button {{ transition: none; }} }}
</style>
</head>
<body>
<main>
<p class="eyebrow">Job search workspace</p>
<h1>Applications</h1>
<p class="notice">Automatic submission has been removed. Drafts are prepared answers for manual applications. Historical unknown outcomes, including Ambral, still need verification. Expand Responses for details. Keep this file private.</p>
<p class="run-status"><strong>Scan: {run_label}</strong><br>{run_detail}<br>Refresh to load the latest saved progress.</p>
<div class="stats">{stats}</div>
<label class="search" for="search">Search company, role, portal, or reason<input id="search" type="search" placeholder="Search this status…" autocomplete="off"></label>
<div class="filters">{buttons}</div>
<p id="empty"></p>
<div class="table-wrap">
<table>
<thead><tr><th>Company</th><th>Role</th><th>Portal</th><th>Date</th><th>Link</th><th>Status</th><th>Responses</th></tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>
</div>
</main>
<script>
const empty = document.getElementById("empty");
const search = document.getElementById("search");
let currentFilter = "submitted";
const messages = {{
  submitted: "No submitted applications. Drafts are behind the Drafted filter.",
  drafted: "No drafts.",
  blocked: "No blocked applications.",
  failed: "No failed applications.",
  uncertain: "No uncertain decisions."
}};
function apply(filter) {{
  currentFilter = filter;
  const query = search.value.trim().toLowerCase();
  let shown = 0;
  document.querySelectorAll("tbody tr").forEach((row) => {{
    const visible = row.dataset.stage === filter && (!query || row.dataset.search.includes(query));
    row.hidden = !visible;
    if (visible) shown += 1;
  }});
  empty.hidden = shown !== 0;
  empty.textContent = query ? "No matches in this status. Clear the search or choose another status." : messages[filter];
  document.querySelectorAll("button").forEach((button) => {{
    button.classList.toggle("active", button.dataset.filter === filter);
    button.setAttribute("aria-pressed", String(button.dataset.filter === filter));
  }});
}}
search.addEventListener("input", () => apply(currentFilter));
document.querySelectorAll("button").forEach((button) => {{
  button.addEventListener("click", () => apply(button.dataset.filter));
}});
apply("submitted");
</script>
</body>
</html>
"""


def _responses(reason: str, draft: dict | None) -> str:
    fields = (draft or {}).get("fields") or []
    label = f"View responses ({len(fields)})" if fields else "View details"
    parts = [f'<details class="responses"><summary>{label}</summary>', f'<p>{html.escape(reason)}</p>']
    if not fields:
        parts.append('<p>No saved responses for this entry.</p>')
    else:
        parts.append('<dl>')
        for field in fields:
            status = str(field.get('kind') or 'unknown')
            required = 'required' if field.get('required') else 'optional'
            answer = field.get('answer')
            value = str(answer) if answer is not None else str(field.get('reason') or 'No response saved')
            parts.append(f'<dt>{html.escape(str(field.get("label") or "Untitled field"))} <span class="field-status">({html.escape(status)}, {required})</span></dt><dd>{html.escape(value)}</dd>')
        parts.append('</dl>')
    parts.append('</details>')
    return ''.join(parts)
