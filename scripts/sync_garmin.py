"""
Pull recent metrics from your Garmin Connect account into FitOntology.

Reads credentials from environment variables (or a .env file):
  GARMIN_EMAIL    your Garmin Connect email
  GARMIN_PASSWORD your Garmin Connect password
  GARMIN_CLIENT_ID (optional) the FitOntology client_id to attach the rows
                   to. Defaults to "c_self".
  GARMIN_LOOKBACK_DAYS (optional) integer days back; defaults to 14.

If your account has 2FA enabled, the script prompts once for the code on
first login. The session token is cached in ~/.garminconnect/ so reruns
don't need it again until the token expires (~30 days).

Usage:
  python scripts/sync_garmin.py
"""
from __future__ import annotations

import os
import sys
from getpass import getpass

from fit_ontology.config import load_env
from fit_ontology.db import connect, ensure_client, insert_metrics, insert_sessions
from fit_ontology.garmin import fetch_activities, fetch_daily_metrics, make_garmin_client

load_env()

DEFAULT_CLIENT_ID = "c_self"


def _prompt_mfa() -> str:
    return input("Garmin 2FA code: ").strip()


def main() -> int:
    email = os.environ.get("GARMIN_EMAIL", "").strip()
    password = os.environ.get("GARMIN_PASSWORD", "").strip()
    client_id = os.environ.get("GARMIN_CLIENT_ID", DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID
    lookback = int(os.environ.get("GARMIN_LOOKBACK_DAYS", "14"))

    if not email:
        email = input("Garmin email: ").strip()
    if not password:
        password = getpass("Garmin password: ")

    if not email or not password:
        print("Missing Garmin credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD.")
        return 1

    print(f"Authenticating to Garmin Connect as {email}...")
    client = make_garmin_client(email, password, mfa_prompt=_prompt_mfa)
    print("Authenticated. Fetching metrics...")

    metrics_df = fetch_daily_metrics(client, client_id, lookback_days=lookback)
    sessions_df = fetch_activities(client, client_id, lookback_days=lookback)

    if metrics_df.empty and sessions_df.empty:
        print(f"No data returned for the last {lookback} days.")
        return 0

    con = connect()
    ensure_client(con, client_id, name="Self (Garmin)")
    if not metrics_df.empty:
        insert_metrics(con, metrics_df)
    if not sessions_df.empty:
        insert_sessions(con, sessions_df)
    con.close()

    print(f"Synced for client_id={client_id} (last {lookback} days):")
    if not metrics_df.empty:
        by_kind = metrics_df.groupby("kind").size().to_dict()
        print(f"  metrics: {len(metrics_df)} rows")
        for kind, count in sorted(by_kind.items()):
            print(f"    {kind}: {count}")
    if not sessions_df.empty:
        by_type = sessions_df.groupby("type").size().to_dict()
        print(f"  sessions: {len(sessions_df)} rows")
        for stype, count in sorted(by_type.items()):
            print(f"    {stype}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
