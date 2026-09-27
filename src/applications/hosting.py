"""Single-replica Railway process: HTTP plus supervised polling subprocess."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from applications.remote import make_remote_server
from applications.storage import atomic_json, snapshot_lock
from applications.schedule import stamp, utc_now

@dataclass(frozen=True)
class HostConfig:
    data: Path
    token: str
    port: int
    interval: int
    boards: int
    assessments: int

def config_from_env(env):
    token=env.get('BOARD_API_TOKEN','')
    if len(token)<32 or not token.isascii() or '\n' in token or '\r' in token:
        raise ValueError('BOARD_API_TOKEN must be at least 32 ASCII characters without newlines')
    data=Path(env.get('DATA_DIR',''))
    mount=env.get('RAILWAY_VOLUME_MOUNT_PATH','')
    if not mount or not data.is_absolute() or data.resolve()!=Path(mount).resolve() or not data.is_dir() or not os.access(data,os.W_OK):
        raise ValueError('DATA_DIR must be the existing writable Railway volume mount')
    def number(key,default,low,high):
        value=int(env.get(key,str(default)))
        if not low<=value<=high:raise ValueError(f'{key} is outside its supported range')
        return value
    config=HostConfig(data,token,number('PORT',8080,1,65535),number('POLL_INTERVAL_SECONDS',300,300,86400),number('POLL_BOARD_LIMIT',50,1,100),number('POLL_ASSESSMENT_LIMIT',50,0,100))
    if env.get('TYPESAFE_API_KEY') and not (env.get('PROFILE_TEXT','').strip() or (data/'profile.md').is_file()):
        raise ValueError('Set PROFILE_TEXT or provision /data/profile.md for Jev assessments')
    for name in ('jobs.json','tracking.json','board-schedule.json','scan-state.json','scheduler-state.json'):
        path=data/name
        if path.exists() and not isinstance(json.loads(path.read_text()),dict):
            raise ValueError('Stored JSON must contain an object')
    version=data/'storage-version.json'
    if version.exists() and json.loads(version.read_text()) != {'version':1}:
        raise ValueError('Unsupported storage version')
    return config

class PollWorker:
    def __init__(self, root, config, spawn=subprocess.Popen, monotonic=time.monotonic):
        self.root=root;self.config=config;self.spawn=spawn;self.clock=monotonic
        self.stop=threading.Event();self.child=None;self.next_at=0;self.started=0;self.interrupted_at=None
        self.state={'status':'idle','last_error':'','last_completed_at':''}
    def tick(self):
        now=self.clock()
        if self.child is not None:
            result=self.child.poll()
            if result is not None:
                self.state.update(status='idle',last_completed_at=stamp(utc_now()),last_error='' if result==0 else 'scan_failed')
                self.child=None;self.interrupted_at=None;self.next_at=now+self.config.interval
            elif now-self.started>=1200 and self.interrupted_at is None:
                self.child.send_signal(signal.SIGINT);self.interrupted_at=now
                self.state.update(status='stopping',last_error='scan_deadline')
            elif self.interrupted_at is not None and now-self.interrupted_at>=45:
                self.child.terminate()
                try:self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
                self.child=None;self.next_at=now+self.config.interval
                self.state.update(status='idle',last_error='scan_deadline')
        elif now>=self.next_at and not self.stop.is_set():
            env=dict(os.environ,APPLICATIONS_HOSTED='1')
            # No cloud answer generation, even if accidentally configured.
            env.pop('OPENAI_API_KEY',None)
            self.child=self.spawn([sys.executable,'-m','applications','poll','--data-dir',str(self.config.data),'--limit',str(self.config.boards),'--assessment-limit',str(self.config.assessments)],cwd=self.root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.started=now;self.state.update(status='running',last_error='')
        self.state['heartbeat_at']=stamp(utc_now())
        with snapshot_lock(self.config.data):atomic_json(self.config.data/'scheduler-state.json',self.state)
        from applications.snapshots import daily_snapshot
        daily_snapshot(self.config.data,stamp(utc_now())[:10])
    def run(self):
        while not self.stop.is_set():
            try:self.tick()
            except Exception:
                self.state.update(last_error='worker_failed')
                if self.child is None:self.next_at=self.clock()+60
            self.stop.wait(5)
        if self.child is not None:
            self.child.send_signal(signal.SIGINT)
            try:self.child.wait(timeout=45)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
        self.state.update(status='stopped',heartbeat_at=stamp(utc_now()))
        with snapshot_lock(self.config.data):atomic_json(self.config.data/'scheduler-state.json',self.state)

def host_board(root):
    try:
        config=config_from_env(os.environ)
        # Directory is public configuration, not user data; never replace a migrated copy.
        directory=config.data/'ats-board-directory.csv'
        if not directory.exists():directory.write_bytes((root/'data/ats-board-directory.csv').read_bytes())
        if (config.data/'profile.md').exists() and not os.environ.get('PROFILE_TEXT'):
            os.environ['PROFILE_TEXT']=(config.data/'profile.md').read_text()
        with snapshot_lock(config.data):
            atomic_json(config.data/'storage-version.json',{'version':1})
            saved=config.data/'scan-state.json'
            if saved.exists():
                run=json.loads(saved.read_text())
                if run.get('status')=='running':run.update(status='interrupted',message='Deployment restarted');atomic_json(saved,run)
        server=make_remote_server(config.data,config.token,config.port)
    except (ValueError,OSError,KeyError):
        print('Hosting configuration or stored data is invalid. Check token, volume, port and profile; private details omitted.',file=sys.stderr)
        return 2
    stop=threading.Event()
    def request_stop(*_):stop.set()
    previous={sig:signal.signal(sig,request_stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    worker=PollWorker(root,config)
    scan_thread=threading.Thread(target=worker.run,name='poll-supervisor',daemon=True)
    server_thread=threading.Thread(target=server.serve_forever,daemon=True)
    scan_thread.start();server_thread.start()
    try:
        while not stop.wait(1):
            if not scan_thread.is_alive():
                # Fail loudly so Railway restart policy can recover a dead supervisor.
                print('Polling supervisor stopped; restarting deployment.',file=sys.stderr)
                return 1
    finally:
        worker.stop.set();server.shutdown();server.server_close();scan_thread.join(timeout=60)
        for sig,handler in previous.items():signal.signal(sig,handler)
    return 0
