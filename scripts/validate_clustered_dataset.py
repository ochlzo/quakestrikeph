import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_INPUT_CSV = Path("src/outputs/clustered_ml_ready_mc_1_0.csv")
ALLOWED_EVENT_ROLES = {"single", "mainshock", "foreshock", "aftershock"}
ALLOWED_LINK_TYPES = {"strong", "weak"}
ALLOWED_CLUSTER_TYPES = {"single", "family"}
BOOLEAN_VALUES = {"true", "false"}
UNSUPPORTED_COLUMNS = {"aftershock_probability", "risk_level"}
REQUIRED_COLUMNS = {
    "event_id",
    "origin_time",
    "origin_time_years",
    "latitude",
    "longitude",
    "depth_km",
    "magnitude",
    "location_text",
    "month",
    "year",
    "parent_id",
    "eta",
    "log10_eta",
    "is_strong_link",
    "link_type",
    "cluster_id",
    "cluster_type",
    "cluster_size",
    "event_role",
    "is_single",
    "is_family_member",
    "mainshock_id",
    "mainshock_time",
    "mainshock_magnitude",
    "foreshock_count_in_family",
    "aftershock_count_in_family",
}


def is_blank(value):
    return value is None or str(value).strip() == ""


def parse_int(value, field_name, row_number, errors):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        errors.append(
            f"row {row_number}: {field_name} must be an integer; got {value!r}"
        )
        return None


def parse_float(value, field_name, row_number, errors):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        errors.append(
            f"row {row_number}: {field_name} must be numeric; got {value!r}"
        )
        return None


def normalized_bool(value):
    return str(value).strip().lower()


def values_match_float(left, right):
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return False


def add_limited_error(errors, message, max_errors):
    if len(errors) < max_errors:
        errors.append(message)


def validate_rows(reader, max_errors):
    errors = []
    role_counts = Counter()
    link_counts = Counter()
    cluster_type_counts = Counter()
    groups = defaultdict(
        lambda: {
            "rows": 0,
            "roles": Counter(),
            "cluster_sizes": Counter(),
            "cluster_types": Counter(),
            "mainshock_rows": [],
            "mainshock_refs": Counter(),
            "foreshock_counts": Counter(),
            "aftershock_counts": Counter(),
            "row_numbers": [],
        }
    )

    total_rows = 0
    for row_number, row in enumerate(reader, start=2):
        total_rows += 1
        role = row["event_role"].strip().lower()
        link_type = row["link_type"].strip().lower()
        cluster_type = row["cluster_type"].strip().lower()
        cluster_id = row["cluster_id"].strip()
        event_id = row["event_id"].strip()
        cluster_size = parse_int(
            row["cluster_size"], "cluster_size", row_number, errors
        )
        foreshock_count = parse_int(
            row["foreshock_count_in_family"],
            "foreshock_count_in_family",
            row_number,
            errors,
        )
        aftershock_count = parse_int(
            row["aftershock_count_in_family"],
            "aftershock_count_in_family",
            row_number,
            errors,
        )

        role_counts[role] += 1
        link_counts[link_type] += 1
        cluster_type_counts[cluster_type] += 1

        if role not in ALLOWED_EVENT_ROLES:
            add_limited_error(
                errors,
                f"row {row_number}: invalid event_role {row['event_role']!r}",
                max_errors,
            )
        if link_type not in ALLOWED_LINK_TYPES:
            add_limited_error(
                errors,
                f"row {row_number}: invalid link_type {row['link_type']!r}",
                max_errors,
            )
        if cluster_type not in ALLOWED_CLUSTER_TYPES:
            add_limited_error(
                errors,
                f"row {row_number}: invalid cluster_type {row['cluster_type']!r}",
                max_errors,
            )

        for field_name in ("is_strong_link", "is_single", "is_family_member"):
            value = normalized_bool(row[field_name])
            if value not in BOOLEAN_VALUES:
                add_limited_error(
                    errors,
                    f"row {row_number}: {field_name} must be true/false; got {row[field_name]!r}",
                    max_errors,
                )

        is_strong_link = normalized_bool(row["is_strong_link"])
        if link_type == "strong" and is_strong_link != "true":
            add_limited_error(
                errors,
                f"row {row_number}: strong link has is_strong_link={row['is_strong_link']!r}",
                max_errors,
            )
        if link_type == "weak" and is_strong_link != "false":
            add_limited_error(
                errors,
                f"row {row_number}: weak link has is_strong_link={row['is_strong_link']!r}",
                max_errors,
            )
        if is_strong_link == "true" and is_blank(row["parent_id"]):
            add_limited_error(
                errors,
                f"row {row_number}: strong link is missing parent_id",
                max_errors,
            )
        if not is_blank(row["parent_id"]):
            if is_blank(row["eta"]) or is_blank(row["log10_eta"]):
                add_limited_error(
                    errors,
                    f"row {row_number}: parent_id exists but eta/log10_eta is blank",
                    max_errors,
                )
            else:
                parse_float(row["eta"], "eta", row_number, errors)
                parse_float(row["log10_eta"], "log10_eta", row_number, errors)

        is_single = normalized_bool(row["is_single"])
        is_family_member = normalized_bool(row["is_family_member"])
        if cluster_type == "single":
            if cluster_size != 1:
                add_limited_error(
                    errors,
                    f"row {row_number}: single cluster has cluster_size={cluster_size}",
                    max_errors,
                )
            if role != "single":
                add_limited_error(
                    errors,
                    f"row {row_number}: single cluster has event_role={role!r}",
                    max_errors,
                )
            if is_single != "true" or is_family_member != "false":
                add_limited_error(
                    errors,
                    f"row {row_number}: single flags do not match cluster_type=single",
                    max_errors,
                )
            if (
                not is_blank(row["mainshock_id"])
                or not is_blank(row["mainshock_time"])
                or not is_blank(row["mainshock_magnitude"])
            ):
                add_limited_error(
                    errors,
                    f"row {row_number}: single cluster has non-null mainshock fields",
                    max_errors,
                )
        elif cluster_type == "family":
            if cluster_size is not None and cluster_size < 2:
                add_limited_error(
                    errors,
                    f"row {row_number}: family cluster has cluster_size={cluster_size}",
                    max_errors,
                )
            if is_single != "false" or is_family_member != "true":
                add_limited_error(
                    errors,
                    f"row {row_number}: family flags do not match cluster_type=family",
                    max_errors,
                )
            if (
                is_blank(row["mainshock_id"])
                or is_blank(row["mainshock_time"])
                or is_blank(row["mainshock_magnitude"])
            ):
                add_limited_error(
                    errors,
                    f"row {row_number}: family row is missing mainshock fields",
                    max_errors,
                )

        group = groups[cluster_id]
        group["rows"] += 1
        group["roles"][role] += 1
        group["cluster_sizes"][cluster_size] += 1
        group["cluster_types"][cluster_type] += 1
        group["foreshock_counts"][foreshock_count] += 1
        group["aftershock_counts"][aftershock_count] += 1
        group["row_numbers"].append(row_number)
        if not is_blank(row["mainshock_id"]):
            group["mainshock_refs"][
                (
                    row["mainshock_id"].strip(),
                    row["mainshock_time"].strip(),
                    row["mainshock_magnitude"].strip(),
                )
            ] += 1
        if role == "mainshock":
            group["mainshock_rows"].append(
                {
                    "event_id": event_id,
                    "origin_time": row["origin_time"].strip(),
                    "magnitude": row["magnitude"].strip(),
                    "row_number": row_number,
                }
            )

    return {
        "errors": errors,
        "groups": groups,
        "total_rows": total_rows,
        "role_counts": role_counts,
        "link_counts": link_counts,
        "cluster_type_counts": cluster_type_counts,
    }


def validate_groups(result, max_errors):
    errors = result["errors"]
    groups = result["groups"]
    family_count = 0

    for cluster_id, group in groups.items():
        row_count = group["rows"]
        row_label = f"cluster {cluster_id}"

        if len(group["cluster_sizes"]) != 1 or next(iter(group["cluster_sizes"])) != row_count:
            add_limited_error(
                errors,
                f"{row_label}: cluster_size column does not match actual group size {row_count}",
                max_errors,
            )

        if row_count == 1:
            if group["roles"]["single"] != 1:
                add_limited_error(
                    errors,
                    f"{row_label}: one-row cluster must have event_role=single",
                    max_errors,
                )
            if group["cluster_types"]["single"] != 1:
                add_limited_error(
                    errors,
                    f"{row_label}: one-row cluster must have cluster_type=single",
                    max_errors,
                )
            if group["mainshock_refs"]:
                add_limited_error(
                    errors,
                    f"{row_label}: single cluster has mainshock references",
                    max_errors,
                )
            continue

        family_count += 1
        if group["cluster_types"]["family"] != row_count:
            add_limited_error(
                errors,
                f"{row_label}: multi-row cluster must have cluster_type=family on every row",
                max_errors,
            )
        if group["roles"]["mainshock"] != 1:
            add_limited_error(
                errors,
                f"{row_label}: family must have exactly one mainshock; found {group['roles']['mainshock']}",
                max_errors,
            )
            continue

        if len(group["mainshock_refs"]) != 1:
            add_limited_error(
                errors,
                f"{row_label}: family rows must share one mainshock reference",
                max_errors,
            )
            continue

        mainshock = group["mainshock_rows"][0]
        ref_id, ref_time, ref_magnitude = next(iter(group["mainshock_refs"]))
        if ref_id != mainshock["event_id"]:
            add_limited_error(
                errors,
                f"{row_label}: mainshock_id {ref_id!r} does not match mainshock event_id {mainshock['event_id']!r}",
                max_errors,
            )
        if ref_time != mainshock["origin_time"]:
            add_limited_error(
                errors,
                f"{row_label}: mainshock_time does not match the mainshock row",
                max_errors,
            )
        if not values_match_float(ref_magnitude, mainshock["magnitude"]):
            add_limited_error(
                errors,
                f"{row_label}: mainshock_magnitude does not match the mainshock row",
                max_errors,
            )

        expected_foreshocks = group["roles"]["foreshock"]
        expected_aftershocks = group["roles"]["aftershock"]
        if len(group["foreshock_counts"]) != 1 or next(iter(group["foreshock_counts"])) != expected_foreshocks:
            add_limited_error(
                errors,
                f"{row_label}: foreshock_count_in_family does not match event_role totals",
                max_errors,
            )
        if len(group["aftershock_counts"]) != 1 or next(iter(group["aftershock_counts"])) != expected_aftershocks:
            add_limited_error(
                errors,
                f"{row_label}: aftershock_count_in_family does not match event_role totals",
                max_errors,
            )

    return family_count


def validate_file(input_csv, max_errors):
    with input_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        unsupported = sorted(UNSUPPORTED_COLUMNS & fieldnames)
        if missing:
            return {
                "ok": False,
                "errors": [f"missing required columns: {missing}"],
                "warnings": [],
                "total_rows": 0,
                "families": 0,
                "role_counts": Counter(),
                "link_counts": Counter(),
                "cluster_type_counts": Counter(),
            }

        result = validate_rows(reader, max_errors)
        families = validate_groups(result, max_errors)
        warnings = []
        if unsupported:
            warnings.append(
                f"unsupported probability/risk columns present: {unsupported}"
            )

    return {
        "ok": not result["errors"],
        "errors": result["errors"],
        "warnings": warnings,
        "total_rows": result["total_rows"],
        "families": families,
        "role_counts": result["role_counts"],
        "link_counts": result["link_counts"],
        "cluster_type_counts": result["cluster_type_counts"],
    }


def print_summary(input_csv, report):
    print(f"path={input_csv}")
    print(f"rows={report['total_rows']}")
    print(
        "roles="
        + ";".join(
            f"{name}={count}"
            for name, count in sorted(report["role_counts"].items())
        )
    )
    print(
        "link_types="
        + ";".join(
            f"{name}={count}"
            for name, count in sorted(report["link_counts"].items())
        )
    )
    print(
        "cluster_types="
        + ";".join(
            f"{name}={count}"
            for name, count in sorted(report["cluster_type_counts"].items())
        )
    )
    print(f"families={report['families']}")

    for warning in report["warnings"]:
        print(f"WARNING: {warning}")

    if report["ok"]:
        print("VALIDATION PASSED")
        return

    print("VALIDATION FAILED")
    for error in report["errors"]:
        print(f"ERROR: {error}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Validate an ML-ready Zaliapin clustered dataset CSV without "
            "rerunning clustering."
        )
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help=f"Clustered dataset CSV to validate. Defaults to {DEFAULT_INPUT_CSV}.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=50,
        help="Maximum number of row/group errors to print before truncating.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input_csv.exists():
        raise FileNotFoundError(f"Input CSV does not exist: {args.input_csv}")

    report = validate_file(args.input_csv, args.max_errors)
    print_summary(args.input_csv, report)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
