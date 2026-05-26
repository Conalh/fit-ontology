"""Upload the DuckDB file to S3-compatible object storage.

The Fly volume is single-zone — a regional outage or volume corruption
loses every trainer's roster. This script uploads ``FIT_ONTOLOGY_DB``
to whichever S3-shaped bucket you configure (Tigris, Backblaze B2,
Cloudflare R2, AWS S3 — all the same API). Scheduled daily, it gives
you a point-in-time backup chain off the Fly volume.

Why a separate script rather than a Litestream sidecar: DuckDB's
write semantics aren't the same as SQLite's, Litestream's
WAL-shipping design assumes the SQLite WAL format, and DuckDB
doesn't expose one. A nightly cp-to-S3 of the whole file isn't as
elegant as continuous WAL streaming, but the DB is currently ~10MB
even with five clients of data — uploading the full file is cheap.
If/when the DB grows past a few hundred MB, switch to incremental
backups via ``ATTACH 'data.duckdb' AS db (READ_ONLY); EXPORT
DATABASE 's3://...';`` (DuckDB native), or migrate to Postgres and
use point-in-time recovery.

Required env vars:
  FIT_ONTOLOGY_BACKUP_BUCKET    Bucket / container name.
  AWS_ACCESS_KEY_ID             Access key id.
  AWS_SECRET_ACCESS_KEY         Secret access key.

Optional env vars:
  FIT_ONTOLOGY_DB               Path to the duckdb file. Defaults to
                                /data/fit.duckdb (the Fly mount).
  AWS_ENDPOINT_URL_S3           Endpoint for non-AWS providers.
                                Tigris: https://fly.storage.tigris.dev
                                B2:     https://s3.us-west-002.backblazeb2.com
                                R2:     https://<account-id>.r2.cloudflarestorage.com
  AWS_REGION                    Region for AWS S3; ignored by most
                                S3-compatible providers but boto3
                                still requires a value. Defaults to
                                "auto" (works for Tigris/R2/B2).
  FIT_ONTOLOGY_BACKUP_PREFIX    Key prefix inside the bucket. Default
                                ``fit-ontology/``. Useful when the
                                bucket is shared with other apps.
  FIT_ONTOLOGY_BACKUP_RETAIN    How many recent backups to keep.
                                Default 14 — covers two weeks of
                                daily backups, hour by hour if needed.
                                Set to 0 to disable pruning.

Usage:
  pip install -e .[backup]
  FIT_ONTOLOGY_BACKUP_BUCKET=fit-ontology-backups \\
  AWS_ACCESS_KEY_ID=... \\
  AWS_SECRET_ACCESS_KEY=... \\
  AWS_ENDPOINT_URL_S3=https://fly.storage.tigris.dev \\
      python scripts/backup_db.py

Scheduling on Fly: see docs/deploy.md "Backups" section.

Exit codes (so a cron supervisor can alert on non-zero):
  0  Upload succeeded.
  1  DuckDB file not found at FIT_ONTOLOGY_DB.
  2  Required env var missing.
  3  S3 upload failed (network, credentials, permissions).
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def _stderr(msg: str) -> None:
    """Log to stderr — Fly's machine logs capture both streams, but
    stderr makes the operator's grep for "backup" lines easier when
    something fails."""
    print(f"[backup_db] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    bucket = os.environ.get("FIT_ONTOLOGY_BACKUP_BUCKET", "").strip()
    if not bucket:
        _stderr("FIT_ONTOLOGY_BACKUP_BUCKET not set; nothing to do")
        return 2
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        _stderr("AWS_ACCESS_KEY_ID not set")
        return 2
    if not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        _stderr("AWS_SECRET_ACCESS_KEY not set")
        return 2

    db_path = Path(os.environ.get("FIT_ONTOLOGY_DB", "/data/fit.duckdb"))
    if not db_path.exists():
        _stderr(f"DB file not found at {db_path}; nothing to back up")
        return 1

    prefix = os.environ.get("FIT_ONTOLOGY_BACKUP_PREFIX", "fit-ontology/").rstrip("/")
    retain = int(os.environ.get("FIT_ONTOLOGY_BACKUP_RETAIN", "14"))

    # Lazy import — boto3 is an optional extra so the runtime image
    # doesn't carry it unless backups are configured. ImportError here
    # is a configuration error, not a code bug.
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        _stderr("boto3 not installed; run `pip install -e .[backup]`")
        return 2

    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3") or os.environ.get("AWS_ENDPOINT_URL")
    region = os.environ.get("AWS_REGION", "auto")
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
    )

    # Key includes UTC timestamp + the DB file's own basename so two
    # apps sharing a bucket via different prefixes don't conflict.
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")
    key = f"{prefix}/{stamp}-{db_path.name}"

    size_mb = db_path.stat().st_size / (1024 * 1024)
    _stderr(f"uploading {db_path} ({size_mb:.2f} MB) → s3://{bucket}/{key}")

    try:
        s3.upload_file(str(db_path), bucket, key)
    except (BotoCoreError, ClientError) as e:
        _stderr(f"upload failed: {e}")
        return 3

    _stderr(f"upload ok: s3://{bucket}/{key}")

    # Prune old backups beyond the retention window. List keys under
    # the prefix, sort by name (key includes ISO-ish timestamp so
    # lexical sort == chronological), delete the oldest beyond retain.
    if retain > 0:
        try:
            resp = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/")
            keys = sorted(obj["Key"] for obj in resp.get("Contents", []))
            to_delete = keys[:-retain]
            if to_delete:
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": k} for k in to_delete]},
                )
                _stderr(f"pruned {len(to_delete)} old backup(s); {len(keys) - len(to_delete)} remain")
            else:
                _stderr(f"retention ok: {len(keys)} backup(s) on hand, retain={retain}")
        except (BotoCoreError, ClientError) as e:
            # Pruning failure is non-fatal — the backup landed, the
            # bucket just has more rows than configured. Surface it
            # loud but don't return non-zero.
            _stderr(f"prune failed (non-fatal): {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
