"""
Ingestion adapters.

Each adapter normalizes its source into the long-format `metrics` schema
defined in ontology.py. Adding a new wearable means writing a new adapter
function and nothing else — no schema migration, no downstream changes.

Metric IDs are derived deterministically from the natural key
``(client_id, date, kind, source)``. This means a re-sync overwrites
the previous row for the same signal-day-source via the table's PK,
instead of duplicating it. Downstream references (e.g. a
recommendation's ``source_metric_ids``) stay valid across re-syncs.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

# defusedxml's iterparse mirrors xml.etree.ElementTree.iterparse but
# installs a parser that refuses entity definitions and external
# references by default (billion-laughs / XXE defense). It still allows
# a DTD with only ELEMENT declarations, which is exactly the shape of
# Apple Health's ``<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)>]>``
# header — so legitimate exports parse while malicious ones raise.
from defusedxml.ElementTree import iterparse as _safe_iterparse

from .ontology import MetricKind, MetricSource


def metric_id(client_id: str, day, kind: str, source: str) -> str:
    """Deterministic ID for a metric row.

    SHA-1 of the natural key, truncated to 14 hex chars. Collisions are
    astronomically unlikely at this scale (~10^16 keys before a 50%
    birthday collision); the short form keeps DB rows compact while
    preserving stable IDs across re-syncs.

    The ``day`` arg is normalized to an ISO date string before hashing
    so we get the same ID regardless of whether the caller passes a
    Python ``date``, a ``datetime``, a pandas ``Timestamp`` (which is
    what DuckDB's ``.df()`` returns for DATE columns), or a pre-
    formatted ISO string. Without this, the migration script (reading
    Timestamps from DB) and the ingest path (passing Python dates)
    would derive different IDs for the same logical row.
    """
    if hasattr(day, "date") and callable(day.date):  # pandas Timestamp / datetime
        day = day.date()
    if hasattr(day, "isoformat"):  # date object
        day_str = day.isoformat()
    else:
        # Strip any time/zone portion and keep just YYYY-MM-DD.
        day_str = str(day).split(" ", 1)[0].split("T", 1)[0]
    key = f"{client_id}|{day_str}|{kind}|{source}"
    return "m_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]


def _assign_metric_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Helper that fills in the ``id`` column from the natural-key columns."""
    df.insert(
        0,
        "id",
        [
            metric_id(r["client_id"], r["date"], r["kind"], r["source"])
            for _, r in df.iterrows()
        ],
    )
    return df


def from_strava_export(path: Path, client_id: str) -> pd.DataFrame:
    """
    Strava bulk export ships a CSV of activities. We extract heart-rate and
    duration signals as daily metrics.

    Expected columns (Strava's actual export): Activity Date, Activity Type,
    Average Heart Rate, Max Heart Rate, Elapsed Time

    Multiple activities on the same day collapse to a daily mean per kind,
    matching the "one row per (client_id, date, kind, source)" convention
    the reasoning layer assumes. Without that aggregation, a two-workout
    day would create two rows with the same natural key — the second
    would overwrite the first via the deterministic-ID upsert and the
    first activity's data would silently disappear.
    """
    raw = pd.read_csv(path)
    raw = raw.rename(columns={
        "Activity Date": "date",
        "Average Heart Rate": "hr_avg",
        "Max Heart Rate": "hr_max",
    })
    # Strava exports use a human-readable month/day timestamp. Explicit
    # mixed parsing avoids pandas' per-row fallback warning while still
    # accepting localized exports and the synthetic fixture format.
    raw["date"] = pd.to_datetime(raw["date"], format="mixed").dt.date

    rows = []
    for _, r in raw.iterrows():
        if pd.notna(r.get("hr_avg")):
            rows.append((client_id, r["date"], MetricSource.STRAVA.value,
                         MetricKind.HR_AVG.value, float(r["hr_avg"]), "bpm"))
        if pd.notna(r.get("hr_max")):
            rows.append((client_id, r["date"], MetricSource.STRAVA.value,
                         MetricKind.HR_MAX.value, float(r["hr_max"]), "bpm"))
    df = pd.DataFrame(rows, columns=["client_id", "date", "source", "kind", "value", "unit"])
    if not df.empty:
        df = (
            df.groupby(["client_id", "date", "source", "kind", "unit"], as_index=False)["value"]
            .mean()
        )
    return _assign_metric_ids(df)[["id", "client_id", "date", "source", "kind", "value", "unit"]]


def from_whoop_json(path: Path, client_id: str) -> pd.DataFrame:
    """
    Whoop's API returns daily recovery records with HRV (RMSSD), resting HR,
    and a sleep score. We use a simplified JSON shape here:
      [{"date": "2026-05-14", "hrv_rmssd": 52.3, "resting_hr": 58, "sleep_hours": 7.4}, ...]
    """
    data = json.loads(Path(path).read_text())
    rows = []
    for d in data:
        day = date.fromisoformat(d["date"])
        if "hrv_rmssd" in d:
            rows.append((client_id, day, MetricSource.WHOOP.value,
                         MetricKind.HRV_RMSSD.value, float(d["hrv_rmssd"]), "ms"))
        if "resting_hr" in d:
            rows.append((client_id, day, MetricSource.WHOOP.value,
                         MetricKind.RESTING_HR.value, float(d["resting_hr"]), "bpm"))
        if "sleep_hours" in d:
            rows.append((client_id, day, MetricSource.WHOOP.value,
                         MetricKind.SLEEP_HOURS.value, float(d["sleep_hours"]), "h"))
    df = pd.DataFrame(rows, columns=["client_id", "date", "source", "kind", "value", "unit"])
    return _assign_metric_ids(df)


# Apple Health record types we care about. Apple's Health app names
# every signal with the HK* identifier prefix; we map a handful into our
# canonical MetricKind values. Other Record types in the export are
# ignored.
_APPLE_TYPE_MAP: dict[str, tuple[MetricKind, str]] = {
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": (MetricKind.HRV_SDNN, "ms"),
    "HKQuantityTypeIdentifierRestingHeartRate": (MetricKind.RESTING_HR, "bpm"),
    "HKQuantityTypeIdentifierBodyMass": (MetricKind.BODY_WEIGHT_KG, "kg"),
    "HKQuantityTypeIdentifierBodyFatPercentage": (MetricKind.BODY_FAT_PCT, "%"),
}


# ─── Apple Health ZIP/XML hardening ──────────────────────────────────
#
# The upload route already caps the *compressed* upload size, but a
# malicious archive can still declare a tiny compressed member that
# decompresses to gigabytes (a "zip bomb"), or pack millions of entries.
# These bounds cap the decompressed side too. They're generous enough
# that no realistic Apple Health export trips them: text XML compresses
# ~10–20×, and a heavy multi-year Watch export is a few hundred MB.
_APPLE_MAX_MEMBERS = 1000                      # a real export ships a handful of files
_APPLE_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024   # 1 GiB cap on export.xml
_APPLE_MAX_COMPRESSION_RATIO = 200             # ratio above this = bomb, not text
_APPLE_MAX_RECORDS = 5_000_000                 # cap parsed <Record> elements


class _BoundedReader:
    """Wrap a binary stream and raise once more than ``limit`` bytes have
    been read.

    Defends against a ZIP whose central-directory ``file_size`` understates
    the real decompressed size — the metadata guard in ``_guard_zip_member``
    trusts the declared size, so this is the belt to that suspenders and
    bounds the *actual* bytes the XML parser pulls."""

    def __init__(self, raw, limit: int) -> None:
        self._raw = raw
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        self._read += len(chunk)
        if self._read > self._limit:
            raise ValueError(
                f"Apple Health export.xml exceeded the {self._limit}-byte "
                "uncompressed cap while reading."
            )
        return chunk


def _guard_zip_member(info: zipfile.ZipInfo) -> None:
    """Reject a ZIP member whose declared size or compression ratio looks
    like a decompression bomb, before we open it for reading."""
    if info.file_size > _APPLE_MAX_UNCOMPRESSED_BYTES:
        raise ValueError(
            f"Apple Health export.xml is too large uncompressed "
            f"({info.file_size} bytes > {_APPLE_MAX_UNCOMPRESSED_BYTES})."
        )
    if info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > _APPLE_MAX_COMPRESSION_RATIO:
            raise ValueError(
                f"Apple Health export.xml has a suspicious compression ratio "
                f"({ratio:.0f}× > {_APPLE_MAX_COMPRESSION_RATIO}×); refusing to parse."
            )


def from_apple_health_export(path: Path, client_id: str) -> pd.DataFrame:
    """
    Apple Health Export. The user taps "Export All Health Data" in the iOS
    Health app and gets an ``export.zip`` containing ``apple_health_export/
    export.xml`` — that file (or the zip directly) is what we read here.

    We surface HRV (SDNN, not RMSSD — Apple's chosen variant), resting HR,
    body mass, and body-fat percentage. Apple Health's sleep schema uses
    stage-level intervals that need aggregation per night; we skip it for
    now and rely on Garmin/Whoop for sleep totals when both sources are
    available for the same client.

    Daily aggregation: when Apple writes multiple Records of the same kind
    on the same day (common for Apple Watch, which can capture HRV many
    times an hour), we take the mean per (date, kind). That matches the
    "one row per day per signal" convention the reasoning layer assumes.

    For large exports we stream with iterparse so memory stays bounded; an
    old Apple Watch user's export can run into hundreds of MB. The ZIP
    path is bounded against decompression bombs (member count, declared
    uncompressed size, compression ratio, and actual bytes read), and
    requires exactly one ``export.xml``. Malformed/suspicious inputs raise
    ``ValueError`` for the route layer to map to a 4xx.
    """
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > _APPLE_MAX_MEMBERS:
                raise ValueError(
                    f"Apple Health ZIP has too many entries "
                    f"({len(infos)} > {_APPLE_MAX_MEMBERS})."
                )
            # Require exactly one export.xml. The export ships it at
            # apple_health_export/export.xml; tolerate other directories
            # but not ambiguity (two export.xml entries → which is real?).
            candidates = [
                zi for zi in infos
                if zi.filename.endswith("export.xml") and not zi.is_dir()
            ]
            if not candidates:
                raise ValueError("Apple Health ZIP does not contain an export.xml.")
            if len(candidates) > 1:
                raise ValueError(
                    f"Apple Health ZIP contains {len(candidates)} export.xml "
                    "entries; expected exactly one."
                )
            info = candidates[0]
            _guard_zip_member(info)
            with z.open(info) as fh:
                bounded = _BoundedReader(fh, _APPLE_MAX_UNCOMPRESSED_BYTES)
                return _parse_apple_health_xml(bounded, client_id)
    else:
        return _parse_apple_health_xml(path, client_id)


def _parse_apple_health_xml(source, client_id: str) -> pd.DataFrame:
    """Stream-parse ``<Record>`` elements and aggregate to daily means.

    Uses defusedxml's iterparse so a hostile DOCTYPE (entity expansion,
    external references) raises instead of being processed, and caps the
    number of records parsed as a final guard on work."""
    # (date, kind) -> [values]; daily mean is computed after the full pass.
    buckets: dict[tuple[date, MetricKind, str], list[float]] = defaultdict(list)

    record_count = 0
    for _, elem in _safe_iterparse(source, events=("end",)):
        if elem.tag != "Record":
            elem.clear()
            continue

        record_count += 1
        if record_count > _APPLE_MAX_RECORDS:
            raise ValueError(
                f"Apple Health export has more than {_APPLE_MAX_RECORDS} "
                "records; refusing to parse."
            )

        type_attr = elem.get("type")
        spec = _APPLE_TYPE_MAP.get(type_attr) if type_attr else None
        if spec is None:
            elem.clear()
            continue

        kind, unit = spec
        try:
            value = float(elem.get("value", ""))
        except ValueError:
            elem.clear()
            continue

        start = elem.get("startDate")
        if not start:
            elem.clear()
            continue
        # Apple writes dates as "2026-05-18 06:14:23 -0700"; the date
        # portion is the local-day for that record.
        day = date.fromisoformat(start.split(" ", 1)[0])

        buckets[(day, kind, unit)].append(value)
        elem.clear()  # release the parsed element to keep memory flat

    rows = [
        (client_id, day, MetricSource.APPLE_HEALTH.value, kind.value, sum(vals) / len(vals), unit)
        for (day, kind, unit), vals in buckets.items()
    ]
    df = pd.DataFrame(rows, columns=["client_id", "date", "source", "kind", "value", "unit"])
    return _assign_metric_ids(df)


def from_intake_csv(path: Path) -> pd.DataFrame:
    """
    Trainer's own intake form export. Required columns:
      id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at
    """
    df = pd.read_csv(path)
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def from_session_log_csv(path: Path) -> pd.DataFrame:
    """Required columns: id, client_id, date, type, duration_min, rpe, notes"""
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df
