"""Initialize only the configured mount ownership, then drop root privileges."""
import os
import sys
from pathlib import Path
from applications.hosting import config_from_env
from applications.snapshots import FILES

def main():
    try:
        config=config_from_env(os.environ)
        if os.geteuid()==0:
            os.chown(config.data,10001,10001)
            for name in (*FILES,'snapshot.lock','tracking.lock','execution.lock'):
                path=config.data/name
                if path.exists():
                    if path.is_symlink():raise ValueError('Symlink in volume')
                    os.chown(path,10001,10001)
            os.setgroups([]);os.setgid(10001);os.setuid(10001)
        os.execv(sys.executable,[sys.executable,'-m','applications','host'])
    except (ValueError,OSError):
        print('Volume initialization failed; check mount and configuration.',file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
