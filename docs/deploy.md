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
fly volumes create fit_data --region iad --size 1
```

- `fit_data` matches the `[mounts] source` in `fly.toml`
- 1 GB is enough for ~hundreds of trainers' worth of DuckDB rows;
  Fly auto-extends up to 5 GB per the `fly.toml` config
- Set the region to whichever you set as `primary_region` in `fly.toml`

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
fly volumes create fit_data_restored --snapshot-id <snapshot-id> --region iad
```

For higher-bar durability (Phase 5b/c), add Litestream replication
to S3-compatible storage — the application is single-writer so
Litestream's continuous-replication model fits without changes.

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
    for t in ('client_thresholds', 'planned_sessions',
              'recommendation_overrides', 'recommendations',
              'metrics', 'sessions', 'clients'):
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
