#!/usr/bin/env python3
"""Fetch a USGS earthquake catalog region in safely bounded time chunks."""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable


BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1"
CSV_COLUMNS = [
    "time",
    "latitude",
    "longitude",
    "depth",
    "mag",
    "magType",
    "nst",
    "gap",
    "dmin",
    "rms",
    "net",
    "id",
    "updated",
    "place",
    "type",
    "horizontalError",
    "depthError",
    "magError",
    "magNst",
    "status",
    "locationSource",
    "magSource",
]


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days)


def parse_date(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)


def format_usgs_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def request_text(path: str, params: dict[str, object], retries: int = 4) -> str:
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "quakestrikeph-usgs-catalog-fetcher/1.0"},
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"USGS request failed after {retries} attempts: {url}") from last_error


def base_params(args: argparse.Namespace, window: Window) -> dict[str, object]:
    return {
        "starttime": format_usgs_date(window.start),
        "endtime": format_usgs_date(window.end),
        "minmagnitude": args.min_magnitude,
        "eventtype": "earthquake",
        "minlatitude": args.min_latitude,
        "maxlatitude": args.max_latitude,
        "minlongitude": args.min_longitude,
        "maxlongitude": args.max_longitude,
    }


def count_window(args: argparse.Namespace, window: Window) -> int:
    params = {"format": "geojson", **base_params(args, window)}
    payload = json.loads(request_text("count", params))
    return int(payload["count"])


def split_window(window: Window) -> tuple[Window, Window]:
    midpoint = window.start + (window.end - window.start) / 2
    midpoint = datetime.combine(midpoint.date(), datetime.min.time(), timezone.utc)
    if midpoint <= window.start:
        midpoint = window.start.replace(hour=12)
    if midpoint <= window.start or midpoint >= window.end:
        raise ValueError(f"Cannot split oversized one-day window: {window}")
    return Window(window.start, midpoint), Window(midpoint, window.end)


def iter_leaf_windows(
    args: argparse.Namespace,
    root: Window,
    max_records: int,
) -> Iterable[tuple[Window, int]]:
    stack = [root]
    while stack:
        window = stack.pop()
        count = count_window(args, window)
        if count == 0:
            print(f"skip  {format_usgs_date(window.start)}..{format_usgs_date(window.end)} count=0")
            continue
        if count > max_records:
            left, right = split_window(window)
            print(
                "split "
                f"{format_usgs_date(window.start)}..{format_usgs_date(window.end)} "
                f"count={count}"
            )
            stack.append(right)
            stack.append(left)
            continue
        yield window, count


def row_in_scope(args: argparse.Namespace, row: dict[str, str]) -> bool:
    if row.get("type") != "earthquake":
        return False
    try:
        magnitude = float(row["mag"])
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        magnitude >= args.min_magnitude
        and args.min_latitude <= latitude <= args.max_latitude
        and args.min_longitude <= longitude <= args.max_longitude
    )


def fetch_csv_rows(args: argparse.Namespace, window: Window) -> tuple[list[dict[str, str]], int]:
    params = {
        "format": "csv",
        "orderby": "time-asc",
        "limit": args.usgs_limit,
        **base_params(args, window),
    }
    text = request_text("query", params)
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    filtered_rows = [row for row in rows if row_in_scope(args, row)]
    return filtered_rows, len(rows) - len(filtered_rows)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a USGS earthquake catalog region without exceeding API result caps."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", default="1900-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--min-magnitude", type=float, default=4.0)
    parser.add_argument("--min-latitude", type=float, required=True)
    parser.add_argument("--max-latitude", type=float, required=True)
    parser.add_argument("--min-longitude", type=float, required=True)
    parser.add_argument("--max-longitude", type=float, required=True)
    parser.add_argument("--max-records-per-query", type=int, default=19000)
    parser.add_argument("--usgs-limit", type=int, default=20000)
    args = parser.parse_args()

    root = Window(parse_date(args.start_date), parse_date(args.end_date))
    if root.end <= root.start:
        raise ValueError("--end-date must be after --start-date")
    if args.max_records_per_query > args.usgs_limit:
        raise ValueError("--max-records-per-query cannot exceed --usgs-limit")

    rows_by_id: dict[str, dict[str, str]] = {}
    total_expected = 0
    leaf_windows = 0
    for window, expected_count in iter_leaf_windows(
        args,
        root,
        args.max_records_per_query,
    ):
        leaf_windows += 1
        total_expected += expected_count
        rows, dropped_rows = fetch_csv_rows(args, window)
        print(
            "fetch "
            f"{format_usgs_date(window.start)}..{format_usgs_date(window.end)} "
            f"expected={expected_count} kept={len(rows)} dropped={dropped_rows}"
        )
        if len(rows) + dropped_rows != expected_count:
            raise RuntimeError(
                "USGS returned "
                f"{len(rows) + dropped_rows} rows for {window}, expected {expected_count}"
            )
        for row in rows:
            event_id = row.get("id")
            if event_id:
                rows_by_id[event_id] = row

    rows = sorted(rows_by_id.values(), key=lambda row: row["time"])
    write_csv(args.output, rows)

    print(f"wrote {len(rows)} unique rows to {args.output}")
    print(f"leaf_windows={leaf_windows} expected_rows_before_dedupe={total_expected}")


if __name__ == "__main__":
    main()
