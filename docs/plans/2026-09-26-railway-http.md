# Railway HTTP and Local Proxy Implementation Plan

**Goal:** Prepare authenticated remote storage access and a secret-hiding local proxy without deployment.

**Architecture:** Reuse listing/tracking modules behind a versioned authenticated remote interface. Local loopback server forwards three fixed operations with HTTPS and no redirects; standalone local mode remains explicit. Railway config and container exclude all private runtime data.

**Tech stack:** Python stdlib HTTP, HTTPS urllib, Docker, Railway.

**Spec:** `docs/remote-job-board-spec.md`

## Global constraints

No provisioning, uploading profile, migration, live scans, employer writes, commit, or push. Remote endpoint tests use disposable data. Cloud deployment is gated until worker supervision/deadlines, durable storage/backup/restore, and authentication review pass.

## Review focus

Invalid token/Origin: Task 1 `test_remote_auth`. Persistence and corrupted data: Task 1 tracking tests. Redirect/config SSRF: Task 2 `test_proxy`. Local Origin and failed saves: Task 2 local tests. Secret inclusion and missing volume: Task 3 `test_config` and Docker allowlist inspection.

### Task 1: Remote HTTP adapter

**Files:** Create `src/applications/remote.py`, `tests/test_remote.py`.

**Interfaces:** `make_remote_server(data: Path, token: str, port: int, host: str)`. Three `/api/v1` data routes and minimal `/healthz`; JSON errors `{error:{code,message}}`; constant-time bearer check before storage/body access, reject Origin, no CORS. Bounded active connections/rate and body limits. Returns existing confirmed tracking entry; read errors sanitized.

- [ ] Write missing/invalid/valid-token, Origin, no-private-file, tracking-invalid/valid, corrupt-data, export tests.
- [ ] Run `python -m unittest discover -s tests -p test_remote.py`; expect import failure.
- [ ] Implement adapter reusing storage, with no root UI.
- [ ] Run narrow tests then full suite.

### Task 2: Local forwarding adapter

**Files:** Create `src/applications/proxy.py`, `tests/test_proxy.py`; modify `server.py` and `cli.py`.

**Interfaces:** `RemoteClient(origin, token).request(path, payload=None) -> (status, bytes, content_type)`; only jobs/export/tracking paths. Validate HTTPS origin/no URL credentials, public hostname, no redirects; scoped auth header only. Timeout 15s, payload cap 32MiB, no retries. Server retains exact Host and write Origin. Remote mode never calls local storage for reads/writes.

- [ ] Test invalid config, unknown path, redirect rejection, fixed bearer forwarding, failure sanitization; run red.
- [ ] Implement client with injectable opener test seam and integrate optional proxy.
- [ ] Test local server protects proxy calls with same Origin and returns 502/504 without local writes.
- [ ] Run full tests and React checks.

### Task 3: Deployment preparation

**Files:** Create `src/applications/hosting.py`, `tests/test_hosting.py`, `Dockerfile`, `.dockerignore`, `railway.toml`, `docs/hosting.md`; modify `.env.example` and CLI.

**Interfaces:** `host` command consumes BOARD_API_TOKEN, DATA_DIR, PORT; fails closed on missing/short token, absent/unwritable directory, or Railway volume mount mismatch. Healthcheck only minimal liveness. Private profile/keys provision separately after approval. Hosting includes a supervised polling subprocess, fair-share selection, bounded scans, durable writes and validated snapshots; real deployment and migration remain separate operator steps.

- [ ] Test absent secrets/mount, bad port, normal config with temp fixtures; run red.
- [ ] Add CLI and Docker explicit COPY allowlist, single-replica instructions, healthcheck/config documentation.
- [ ] Verify no tracked secrets/data enter image; run tests/diff checks.
- [ ] Document remaining scanner, durability, backup, migration and real-deployment gates. No claim of production readiness before those gates.
