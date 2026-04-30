import ast
import warnings

import pandas as pd


INPUT_CSV = "phivolcs_earthquake_1907_2026_combined.csv"
LABEL_SCRIPT = "zaliapin_label_phivolcs.py"

DATE_COL = "Date-Time"
NUMERIC_COLS = ["Latitude", "Longitude", "Depth", "Magnitude"]


def read_label_script_constant(name):
    with open(LABEL_SCRIPT, "r", encoding="utf-8") as script_file:
        tree = ast.parse(script_file.read())

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)

    raise AssertionError(f"{name} is not defined in {LABEL_SCRIPT}")


def main():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        df = pd.read_csv(INPUT_CSV, low_memory=False)

    dtype_warnings = [
        warning for warning in caught
        if warning.category.__name__ == "DtypeWarning"
    ]
    assert not dtype_warnings, "CSV import still emits DtypeWarning"

    parsed_dates = pd.to_datetime(
        df[DATE_COL],
        format="%d %B %Y - %I:%M %p",
        errors="coerce",
    )
    assert parsed_dates.notna().all(), "Date-Time has unparseable values"

    for column in NUMERIC_COLS:
        parsed = pd.to_numeric(df[column], errors="coerce")
        assert parsed.notna().all(), f"{column} has non-numeric values"

    longitude = pd.to_numeric(df["Longitude"], errors="coerce")
    assert longitude.between(115, 130).all(), "Longitude has implausible values"

    assert read_label_script_constant("MAX_LOOKBACK_DAYS") == 365


if __name__ == "__main__":
    main()
