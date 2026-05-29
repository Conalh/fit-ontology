# Deploying FitOntology

Single-machine Fly.io deploy. The DuckDB file lives on a Fly
persistent volume; the Next.js static export and FastAPI process
run together in one container.

## First-time setup

You'll need:
- A Fly account with `flyctl` installed and authenticated
- An [Anthropic API key](https://console.anthropic.com/) (only if you
  want Ask FitOntology / Coach Assistant working)

### 1. Initialize the app

```bash
fly launch --no-deploy --copy-config
```

`--copy-config` keeps the `fly.toml` in this repo as the canonical
spec — don't let `flyctl` rewrite it. `--no-deploy` skips the first
deploy until secrets are set.

If `fly launch` prompts about a volume, decline; we create it
explicitly in the next step so we control the size + region.

### 2. Create the persistent volume

```bash
fly volumes create fit_data --region sjc --size 1
```

- `fit_data` matches the `[mounts] source` in `fly.toml`
- 1 GB is enough for ~hundreds of trainers' worth of DuckDB rows;
  Fly auto-extends up to 5 GB per the `fly.toml` config
- The region MUST match `primary_region` in `fly.toml` (currently
  `sjc`) — otherwise the volume + machine land in different regions
  and the mount fails to attach

### 3. Set secrets

Every secret is set via `fly secrets set`. They live in Fly's
encrypted store and never appear in the repo.

```bash
# REQUIRED — signs the session cookie. Rotating this invalidates
# every live session (one-time pain). Keep this secret long-lived
# unless you're deliberately logging everyone out.
fly secrets set FIT_ONTOLOGY_SESSION_SECRET="$(openssl rand -base64 48)"

# REQUIRED — bootstrap password for the default trainer (you).
# Setting this once causes the migration to hash + store it on the
# next boot. After the first deploy, clear this secret so a future
# operator who loses it doesn't lock you out.
fly secrets set FIT_ONTOLOGY_DEFAULT_TRAINER_PASSWORD="..."

# OPTIONAL — only required if you want the Ask FitOntology
# conversational layer and Coach Assistant message drafting.
fly secrets set ANTHROPIC_API_KEY="sk-ant-..."

# OPTIONAL — match the email of the default trainer to a real
# inbox you control (defaults to conal.hg@gmail.com).
fly secrets set FIT_ONTOLOGY_DEFAULT_TRAINER_EMAIL="you@example.com"
fly secrets set FIT_ONTOLOGY_DEFAULT_TRAINER_NAME="Your Name"
fly secrets set FIT_ONTOLOGY_DEFAULT_TRAINER_ID="t_default"
```

Non-secret env values (`FIT_ONTOLOGY_DB`, `FIT_ONTOLOGY_REQUIRE_AUTH`,
`FIT_ONTOLOGY_SESSION_SECURE`, `FIT_ONTOLOGY_DEMO_MODE`) are declared
in `fly.toml`'s `[env]` block — they're not secrets, just
configuration.

Advanced self-hosted deployments can set `FIT_ONTOLOGY_PERIMETER_AUTH=1`
instead of `FIT_ONTOLOGY_REQUIRE_AUTH=1` only when every request is
already protected by a trusted upstream gate such as Cloudflare Access.
This flag only tells the startup guard that the perimeter is responsible
for access control; it does not map upstream identities into trainers.
Keep it off for Fly's public demo and normal app-auth deployments.

### 4. Deploy

```bash
fly deploy
```

The first deploy:
1. Builds the Docker image (multi-stage: Node builds the Next
   export, Python stage installs deps).
2. Pushes to Fly's registry.
3. Starts a machine, mounts the volume at `/data`.
4. `connect()` runs the migration: creates `trainers` row for you,
   hashes your bootstrap password, seeds the demo trainer + synthetic
   data (because `FIT_ONTOLOGY_DEMO_MODE=1` in `fly.toml`).
5. Health check passes → traffic starts flowing.

### 5. Smoke test

```bash
fly open                                     # opens the app URL
# OR
curl https://fit-ontology.fly.dev/api/health # → {"ok": true}
```

The home page should show the demo trainer's roster (3 synthetic
clients). Hit `/login` to sign in with your real trainer creds.

## Subsequent deploys

Just `fly deploy`. Fly does a rolling restart with the new image.

## Rotating secrets

```bash
# Generate a new session secret. Logs everyone out (their cookies
# can no longer be decoded).
fly secrets set FIT_ONTOLOGY_SESSION_SECRET="$(openssl rand -base64 48)"

# Or unset the bootstrap password so a future restart can't
# accidentally re-hash a stale value. Do this after your first
# successful login.
fly secrets unset FIT_ONTOLOGY_DEFAULT_TRAINER_PASSWORD
```

Use `scripts/trainer.py set-password` for routine password rotation
once you have shell access on the running machine (`fly ssh console`).

## Custom domain

```bash
fly certs create app.mobility.rest
fly certs check app.mobility.rest
```

Point your DNS A/AAAA at the addresses `fly certs check` prints. Once
verified, the public URL is your own domain; Fly's `*.fly.dev` URL
still works as a fallback.

## Backups

Fly's volume auto-snapshot is on by default (one daily, 5-day
retention). To take an explicit snapshot before a risky deploy:

```bash
fly volumes snapshots list -v <volume-id>
fly volumes snapshots create -v <volume-id>
```

To restore from a snapshot, create a new volume from it and update
`fly.toml`'s `[mounts] source`:

```bash
fly volumes create fit_data_restored --snapshot-id <snapshot-id> --region sjc
```

### Off-volume backup to S3-compatible storage

Fly's volume snapshots cover most recovery paths, but they're
single-zone — a region-level outage takes both the volume and the
snapshots with it. `scripts/backup_db.py` uploads the DuckDB file
to any S3-shaped bucket (Tigris, Backblaze B2, Cloudflare R2, AWS
S3) so a copy lives outside the Fly region.

**1. Pick a bucket provider.** Tigris is the path-of-least-friction
on Fly — same dashboard, free tier covers the working-set:

```bash
fly storage create fit-ontology-backups   # creates a Tigris bucket
# Fly auto-injects AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
# AWS_ENDPOINT_URL_S3 secrets into the app.
```

B2 / R2 / S3 work identically — set the same env vars manually via
`fly secrets set`.

**2. Set the bucket name** (the only non-Tigris-default we need):

```bash
fly secrets set FIT_ONTOLOGY_BACKUP_BUCKET=fit-ontology-backups
```

**3. Schedule the backup.** Two ways:

- **One-shot machine on a daily schedule** (recommended for Fly):

  ```bash
  fly machine run \
      --schedule daily \
      --region sjc \
      --volume fit_data:/data \
      --env FIT_ONTOLOGY_DB=/data/fit.duckdb \
      registry.fly.io/fit-ontology:latest \
      python scripts/backup_db.py
  ```

  The machine wakes once a day, runs the backup script, exits.
  Costs ~free (the machine lives <60 seconds per day).

- **External cron** (GitHub Actions or your laptop), invoking the
  script against a downloaded copy of the volume. Workable but more
  moving parts; prefer the Fly machine schedule.

**4. Verify.** Check the bucket after the first scheduled run, or
trigger it manually:

```bash
fly ssh console -C "python scripts/backup_db.py"
```

Backups land at `s3://<bucket>/fit-ontology/YYYYMMDD-HHMMSSZ-fit.duckdb`.
Retention defaults to 14 days (`FIT_ONTOLOGY_BACKUP_RETAIN`); older
ones are pruned automatically.

**Restoring from S3** is a `fly ssh console` + `aws s3 cp` away;
no special tooling required since the backup is just the raw
DuckDB file.

### Error monitoring (Sentry)

Optional. When `FIT_ONTOLOGY_SENTRY_DSN` is set, uncaught
exceptions in route handlers + WARNING+ log lines flow to Sentry
with the FastAPI integration. Without the DSN, the SDK isn't
imported and the deploy is unaffected.

**1. Create a Sentry project** (free tier covers a portfolio app:
~5000 events/mo). Pick "FastAPI" as the platform; copy the DSN.

**2. Install the optional extra in the runtime image.** The simplest
path is to bake the `monitoring` extra into the Dockerfile install:

```dockerfile
# in the runtime stage of Dockerfile, replace `pip install .` with:
RUN pip install --no-cache-dir .[monitoring]
```

(Or skip the extra and install `sentry-sdk[fastapi]` directly —
both work.)

**3. Set the secret and deploy:**

```bash
fly secrets set FIT_ONTOLOGY_SENTRY_DSN=https://...ingest.sentry.io/...
fly deploy
```

The next deploy will start reporting; check the Sentry dashboard
for the first event within a few minutes (the FastAPI `/api/health`
check might be enough to trigger a startup-context event).

**Toggling environments.** `FIT_ONTOLOGY_SENTRY_ENV` defaults to
`production`; set to `staging` / `preview` to filter events in the
Sentry UI. Trace + profile sampling default to 10% — raise via the
SDK config if event volume is sparse.

## Removing demo mode

Once the app has real trainer data and the demo content is no longer
useful as a portfolio surface, flip the flag:

```bash
# In fly.toml [env], change DEMO_MODE to "0" and redeploy.
# The demo trainer + synthetic clients stay in the DB; no /me
# fallback to them happens once the flag flips.
```

To wipe the demo data entirely:

```bash
fly ssh console
$ python -c "
from fit_ontology.db import connect
from fit_ontology.demo import DEMO_TRAINER_ID
with connect(read_only=False) as con:
    # client_share_tokens.client_id FKs clients(id), so the token tables
    # must be deleted before clients or the clients DELETE raises an FK
    # violation. audit_log has no FK but carries trainer_id, so wipe it
    # too for a clean "entirely."
    for t in ('client_share_tokens', 'client_intake_tokens',
              'client_thresholds', 'planned_sessions',
              'recommendation_overrides', 'recommendations',
              'metrics', 'sessions', 'audit_log', 'clients'):
        con.execute(f'DELETE FROM {t} WHERE trainer_id = ?', [DEMO_TRAINER_ID])
    con.execute('DELETE FROM trainers WHERE id = ?', [DEMO_TRAINER_ID])
"
```

## Troubleshooting

**"Cookie didn't decode on the request after login"** — happens once,
right after rotating `FIT_ONTOLOGY_SESSION_SECRET`. Log in again; the
new cookie carries the new signature.

**"Health check failing on first deploy"** — most often the bootstrap
password is wrong or the volume mount path doesn't match
`FIT_ONTOLOGY_DB`. Check `fly logs` for the first 30s of startup
output; the migration prints which trainer it seeded.

**"Demo data not showing"** — confirm `FIT_ONTOLOGY_DEMO_MODE=1` is
set in `fly.toml`'s `[env]`. The seed runs once per volume; if you
restored from a snapshot taken before demo mode was enabled, the
seed will fire fresh on next boot.
