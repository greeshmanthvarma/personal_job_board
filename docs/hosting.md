# Hosting the personal job board

The React app runs on your laptop. Railway runs one Python backend replica, the authenticated data interface, and a supervised polling worker. Railway's persistent volume is authoritative for jobs, assessments and tracking. The local Python proxy holds the bearer secret; React never sees it.

## Railway configuration

Deploy this GitHub repository from its root, using the included `Dockerfile` and `railway.toml`. Do not set the root to `frontend`. No frontend build is needed on Railway. Attach one volume at `/data`, and keep exactly one replica.

Required variables:

- `BOARD_API_TOKEN`: a cryptographically random secret of at least 32 characters. Generate locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`; enter it only into Railway Variables and your private local `.env`.
- `DATA_DIR=/data`.
- `TYPESAFE_API_KEY`: needed for Jev; omit only if you deliberately want unassessed discovery.
- `PROFILE_TEXT`: private contents of your profile, as a Railway secret variable. Alternatively provision `/data/profile.md` privately. Do not commit the profile, resume, API keys, or tracking files.

Railway supplies `PORT` and `RAILWAY_VOLUME_MOUNT_PATH`. Startup rejects missing/mismatched volume settings and corrupted stored JSON. The entrypoint adjusts ownership of the mounted data directory and known files, then drops to UID/GID 10001 before serving or scanning. Do not override the start command with `serve`; it is local-only. The configured start command is `python -m applications.volume_entrypoint`.

Optional variables: `POLL_BOARD_LIMIT=50`, `POLL_ASSESSMENT_LIMIT=50`. These are bounded scheduling budgets. Limits do not promise that all directory boards refresh every six hours. No OpenAI key is needed in Railway.

The worker wakes every five seconds for heartbeat/supervision and starts the next polling subprocess as soon as the previous one has exited. Broad discovery and boards currently hiring engineers share the batch budget. HTTP stays available during scanning. Requests/assessments/boards have deadlines, and batches have a twenty-minute deadline. Graceful interruption is attempted first; a stuck process is terminated after 45 seconds and killed only if it still fails to exit. Atomic persistence protects against partial JSON; interrupted work remains due. A deployment restart marks old running scan status interrupted.

## Local frontend connection

Keep these in the repository root `.env`, not in `frontend` and never in `VITE_*` variables:

```dotenv
BOARD_REMOTE_URL=https://your-backend.up.railway.app
BOARD_API_TOKEN=the-same-private-token
```

Build and start:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
source .venv/bin/activate
python -m applications serve --remote
```

Open `http://127.0.0.1:8765`. `--remote` is explicit: it never silently falls back to local files. To use independent local-only data, omit `--remote`. Do not run local polling against your old data and assume it syncs to Railway.

The proxy validates the HTTPS origin, permits only three fixed operations, rejects redirects/private destination resolutions, and attaches its own token. GET/export failures show errors; tracking timeouts are ambiguous and require read-back before retrying. Authentication protects Railway data; CORS is not relied on as authentication. `/healthz` is public and returns only liveness. `/api/v1/jobs`, `/api/v1/tracking`, and `/api/v1/export` require bearer authentication and reject browser Origin headers.

## Private migration and restore

Do not upload private data until you approve its destination. Before migration, stop local polling and tracking writes and create a snapshot outside the repo:

```bash
python -m applications snapshot --output /private/tmp/job-board-migration.tar.gz
```

The archive excludes profile, resume and secrets. It includes tracking, cached jobs/assessments, schedule, public directory and application records. Keep it private. Import on the target only while the backend is stopped, into an empty volume directory:

```bash
python -m applications restore --source /path/to/private-snapshot.tar.gz --data-dir /data
```

The restore validates allowed archive names, total size, checksums and JSON objects before writing; it never overwrites a populated directory. It resets an imported running scan to interrupted. If restoring into a staging directory, complete the swap with the backend stopped and preserve the existing volume state until verified. Do not repeatedly upload a snapshot over live tracking. Check job/tracking counts, applied dates and a sample of notes without publishing their contents.

Rollback requires stopping remote writes/scans, snapshotting the current authoritative remote data, restoring into an empty local data directory, and explicitly selecting that directory with `serve --data-dir`. Do not revert to a stale local snapshot after new remote applications have been tracked.

## Backups and deployment checks

The worker creates a coordinated private snapshot under `/data/backups` daily and retains seven daily archives. These are recovery points, not disaster recovery: losing the volume loses those archives too. Configure independent Railway volume backups and verify their retention and cost before importing real tracking. If those backups are unavailable, choose another private destination and approve it before adding export automation. No independent backup destination is silently provisioned by the code.

Before real use:

1. Verify the volume is attached in Railway and the app passes `/healthz`.
2. Verify unauthenticated data requests return 401; valid server-to-server requests work; root/private-file paths are inaccessible.
3. Test a disposable listing/status update, restart/redeploy, and confirm it persists. Restore a snapshot into disposable storage and compare tracking and assessment state.
4. Verify scheduler heartbeat continues and no scan overlap occurs. A stale heartbeat is shown after ten minutes.
5. Provision private profile/key only after approval; inspect logs for secret-free summaries.
6. Import private data, then connect the local proxy. Keep the source snapshot until all checks pass.

## Verification commands

```bash
python -m unittest discover -s tests
npm --prefix frontend test
npm --prefix frontend run build
docker build -t personal-job-board:local .
git diff --check
```

The image copies only Python source, package metadata and the public board directory. Private runtime data, frontend, `.env`, profile and resume are excluded by both explicit COPY paths and `.dockerignore`. No real job application is filled or submitted.
