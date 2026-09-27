"""Private validated snapshots. No secrets/profile included; never overwrite imports."""
import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path
from applications.storage import snapshot_lock, atomic_json

FILES=('jobs.json','tracking.json','board-schedule.json','scan-state.json','scheduler-state.json','storage-version.json','applications.csv','drafts.json','ats-board-directory.csv')
MAX_SIZE=512*1024*1024

def create_snapshot(data: Path, destination: Path):
    if destination.exists():raise ValueError('Snapshot destination already exists')
    with snapshot_lock(data):
        values={name:(data/name).read_bytes() for name in FILES if (data/name).exists()}
        if sum(map(len,values.values()))>MAX_SIZE:raise ValueError('Snapshot too large')
        for name,body in values.items():
            if name.endswith('.json') and not isinstance(json.loads(body),dict):raise ValueError('Invalid stored JSON')
        manifest={'version':1,'files':{name:hashlib.sha256(body).hexdigest() for name,body in values.items()}}
        values['manifest.json']=json.dumps(manifest).encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation avoids silently overwriting backups.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as raw:
            temporary=Path(raw.name)
            with tarfile.open(fileobj=raw,mode='w:gz') as archive:
                for name,body in values.items():
                    item=tarfile.TarInfo(name);item.size=len(body);item.mode=0o600
                    archive.addfile(item,io.BytesIO(body))
            raw.flush();os.fsync(raw.fileno())
        os.link(temporary,destination)  # Atomic publication, never overwrite.
        directory_fd=os.open(destination.parent,os.O_RDONLY)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return manifest

def validate_snapshot(source: Path):
    values={};total=0
    with tarfile.open(source,'r:gz') as archive:
        for member in archive:
            if not member.isfile() or member.name not in (*FILES,'manifest.json') or member.name in values:
                raise ValueError('Unexpected snapshot member')
            total+=member.size
            if total>MAX_SIZE:raise ValueError('Snapshot too large')
            with archive.extractfile(member) as item:values[member.name]=item.read()
    manifest=json.loads(values.pop('manifest.json'))
    if manifest.get('version')!=1 or set(manifest.get('files',{}))!=set(values):raise ValueError('Invalid snapshot manifest')
    for name,body in values.items():
        if hashlib.sha256(body).hexdigest()!=manifest['files'][name]:raise ValueError('Snapshot checksum mismatch')
        if name.endswith('.json') and not isinstance(json.loads(body),dict):raise ValueError('Invalid snapshot JSON')
    return values

def restore_snapshot(source: Path, destination: Path):
    values=validate_snapshot(source)
    destination.mkdir(parents=True,exist_ok=True)
    with snapshot_lock(destination):
        if any(p.name!='snapshot.lock' for p in destination.iterdir()):raise ValueError('Restore requires an empty destination')
        for name,body in values.items():
            if name.endswith('.json'):
                value=json.loads(body)
                if name=='scan-state.json' and value.get('status')=='running':value.update(status='interrupted',message='Restored snapshot')
                atomic_json(destination/name,value)
            else:
                with (destination/name).open('xb') as handle:
                    os.chmod(destination/name,0o600);handle.write(body);handle.flush();os.fsync(handle.fileno())
    return len(values)

def daily_snapshot(data: Path, day: str):
    directory=data/'backups';destination=directory/f'{day}.tar.gz'
    if not destination.exists():create_snapshot(data,destination)
    # Exactly seven named daily archives; no arbitrary paths/globs are deleted.
    archives=sorted(p for p in directory.iterdir() if p.is_file() and len(p.name)==17 and p.name.endswith('.tar.gz') and p.name[:10].replace('-','').isdigit())
    for old in archives[:-7]:old.unlink()
