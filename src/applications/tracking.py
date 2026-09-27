"""Manual tracking, independent of the discovery feed and AI assessments."""
import csv
import io
import json
import fcntl
from pathlib import Path
from applications.schedule import stamp, utc_now
from applications.log import load_records

STATUSES = ('new','saved','applied','interviewing','offer','rejected','skipped','needs_verification')

def load_tracking(data: Path) -> dict:
    path = data/'tracking.json'
    return json.loads(path.read_text()) if path.exists() else {}

def update_tracking(data: Path, identity: str, status: str, notes: str) -> dict:
    from applications.listings import load_listings
    if not isinstance(identity,str) or not isinstance(status,str) or not isinstance(notes,str) or status not in STATUSES or len(notes)>10000:
        raise ValueError('Invalid identity, status, or notes')
    known = set(load_listings(data)) | {f'{r.portal}\t{r.external_job_id}' for r in load_records(data/'applications.csv')}
    if identity not in known:
        raise ValueError('Unknown job')
    data.mkdir(parents=True, exist_ok=True)
    with (data/'tracking.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = load_tracking(data)
        previous = values.get(identity,{})
        now = stamp(utc_now())
        entry = dict(status=status, notes=notes, updated_at=now, applied_at=previous.get('applied_at',''))
        if status == 'applied' and not entry['applied_at']:
            entry['applied_at'] = now
        values[identity] = entry
        temporary = data/'tracking.tmp'
        temporary.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
        temporary.replace(data/'tracking.json')
        return entry

def export_tracking(data: Path) -> bytes:
    from applications.listings import list_board_jobs
    output = io.StringIO()
    writer = csv.writer(output)
    keys = ('identity','company','title','link','status','applied_at','updated_at','notes')
    writer.writerow(keys)
    for job in list_board_jobs(data):
        if job['status']=='new' and not job.get('notes'):
            continue
        cells=[]
        for key in keys:
            cell = str(job.get(key,'') or '')
            cells.append("'"+cell if cell.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else cell)
        writer.writerow(cells)
    return output.getvalue().encode('utf-8-sig')
