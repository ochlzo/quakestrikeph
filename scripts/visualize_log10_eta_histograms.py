import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from sklearn.mixture import GaussianMixture


DEFAULT_PATTERN = "outputs/nn_diagnostics_mc_*/log10_eta_histogram.csv"
REQUIRED_COLUMNS = {
    "log10_eta_bin_lower",
    "log10_eta_bin_upper",
    "event_count",
}
ETA0_CANDIDATES = [-6.0, -5.5, -5.0, -4.5]


def default_output_path(input_csv):
    return input_csv.parent / "plots" / "log10_eta_histogram.png"


def _plots_dir(input_csv):
    return input_csv.parent / "plots"


def _resolve_inputs(patterns):
    paths = []
    for pattern in patterns:
        matches = sorted(Path().glob(pattern))
        if matches:
            paths.extend(matches)
            continue

        path = Path(pattern)
        if path.exists():
            paths.append(path)

    unique_paths = sorted(set(paths))
    if not unique_paths:
        raise FileNotFoundError("No histogram CSV files matched the input patterns.")

    return unique_paths


def _read_histogram(input_csv):
    df = pd.read_csv(input_csv)
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"{input_csv} is missing columns: {sorted(missing)}")

    df = df.copy()
    df["bin_midpoint"] = (
        df["log10_eta_bin_lower"] + df["log10_eta_bin_upper"]
    ) / 2
    df["bin_width"] = df["log10_eta_bin_upper"] - df["log10_eta_bin_lower"]
    return df


def _read_log10_eta(input_csv):
    df = pd.read_csv(input_csv, usecols=["log10_eta"])
    values = pd.to_numeric(df["log10_eta"], errors="coerce").dropna()
    if values.empty:
        raise ValueError(f"{input_csv} has no valid log10_eta values.")
    return values


def _normal_pdf(x, mean, sigma):
    return (
        np.exp(-0.5 * ((x - mean) / sigma) ** 2)
        / (sigma * math.sqrt(2 * math.pi))
    )


def _component_crossover(components):
    left = components.iloc[0]
    right = components.iloc[1]
    w1, m1, s1 = left["weight"], left["mean_log10_eta"], left["sigma_log10_eta"]
    w2, m2, s2 = right["weight"], right["mean_log10_eta"], right["sigma_log10_eta"]

    a = (1 / (2 * s2**2)) - (1 / (2 * s1**2))
    b = (m1 / s1**2) - (m2 / s2**2)
    c = (m2**2 / (2 * s2**2)) - (m1**2 / (2 * s1**2))
    c += math.log((w1 / s1) / (w2 / s2))

    roots = np.roots([a, b, c]) if abs(a) > 1e-12 else np.roots([b, c])
    real_roots = [root.real for root in roots if abs(root.imag) < 1e-8]
    between = [root for root in real_roots if m1 <= root <= m2]
    if between:
        return between[0]
    return min(real_roots, key=lambda root: abs(root - ((m1 + m2) / 2)))


def fit_gmm_diagnostics(log10_eta, max_components=3):
    values = pd.to_numeric(log10_eta, errors="coerce").dropna().to_numpy()
    sample = values.reshape(-1, 1)

    rows = []
    for components in range(1, max_components + 1):
        model = GaussianMixture(n_components=components, random_state=42)
        model.fit(sample)
        rows.append(
            {
                "components": components,
                "bic": model.bic(sample),
                "aic": model.aic(sample),
            }
        )

    model = GaussianMixture(n_components=2, random_state=42)
    model.fit(sample)
    order = np.argsort(model.means_.ravel())
    labels = ["left_low_eta", "right_high_eta"]
    component_rows = []
    for label, index in zip(labels, order):
        component_rows.append(
            {
                "component": label,
                "weight": model.weights_[index],
                "mean_log10_eta": model.means_[index, 0],
                "sigma_log10_eta": math.sqrt(model.covariances_[index, 0, 0]),
            }
        )

    components = pd.DataFrame(component_rows)
    crossover = _component_crossover(components)
    crossover_row = {
        "recommended_log10_eta0_gmm_crossover": crossover,
        "recommended_eta0_gmm_crossover": 10**crossover,
        "left_component_mean_log10_eta": components.iloc[0]["mean_log10_eta"],
        "right_component_mean_log10_eta": components.iloc[1]["mean_log10_eta"],
        "left_component_weight": components.iloc[0]["weight"],
        "right_component_weight": components.iloc[1]["weight"],
    }

    return {
        "models": pd.DataFrame(rows),
        "components": components,
        "crossover": crossover_row,
    }


def _candidate_link_counts(log10_eta, crossover):
    thresholds = ETA0_CANDIDATES[:2] + [crossover] + ETA0_CANDIDATES[2:]
    total = len(log10_eta)
    rows = []
    for threshold in thresholds:
        strong = int((log10_eta < threshold).sum())
        rows.append(
            {
                "log10_eta0": threshold,
                "eta0": 10**threshold,
                "strong_links_eta_lt_eta0": strong,
                "weak_links_eta_ge_eta0": total - strong,
                "strong_percent": (strong / total * 100) if total else 0.0,
            }
        )
    return pd.DataFrame(rows)


def write_gmm_diagnostics(input_dir):
    input_dir = Path(input_dir)
    log10_eta = _read_log10_eta(input_dir / "nearest_neighbor_diagnostics.csv")
    diagnostics = fit_gmm_diagnostics(log10_eta)
    crossover = diagnostics["crossover"]["recommended_log10_eta0_gmm_crossover"]

    diagnostics["models"].to_csv(input_dir / "gmm_model_scores.csv", index=False)
    diagnostics["components"].to_csv(
        input_dir / "gmm_2_component_params.csv", index=False
    )
    pd.DataFrame([diagnostics["crossover"]]).to_csv(
        input_dir / "eta0_gmm_crossover.csv", index=False
    )
    _candidate_link_counts(log10_eta, crossover).to_csv(
        input_dir / "eta0_candidate_link_counts.csv", index=False
    )
    return diagnostics


def plot_histogram(input_csv, output_png=None, title=None):
    input_csv = Path(input_csv)
    output_png = Path(output_png) if output_png else default_output_path(input_csv)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    df = _read_histogram(input_csv)
    label = title or input_csv.parent.name

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(
        df["bin_midpoint"],
        df["event_count"],
        width=df["bin_width"],
        align="center",
        color="#3b82f6",
        edgecolor="#1e3a8a",
        linewidth=0.5,
    )
    ax.set_title(f"log10 eta histogram - {label}")
    ax.set_xlabel("log10 eta")
    ax.set_ylabel("Event count")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_png, dpi=160)
    plt.close(fig)
    return output_png


def plot_smoothed_histogram(input_csv, output_png=None, sigma=1.2):
    input_csv = Path(input_csv)
    output_png = Path(output_png) if output_png else (
        _plots_dir(input_csv) / "log10_eta_histogram_smoothed.png"
    )
    output_png.parent.mkdir(parents=True, exist_ok=True)
    df = _read_histogram(input_csv)
    smoothed = gaussian_filter1d(df["event_count"].to_numpy(float), sigma=sigma)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(
        df["bin_midpoint"],
        df["event_count"],
        width=df["bin_width"],
        color="#93c5fd",
        edgecolor="none",
        alpha=0.45,
        label="Histogram",
    )
    ax.plot(
        df["bin_midpoint"],
        smoothed,
        color="#b91c1c",
        linewidth=2,
        label="Smoothed",
    )
    ax.set_title(f"smoothed log10 eta histogram - {input_csv.parent.name}")
    ax.set_xlabel("log10 eta")
    ax.set_ylabel("Event count")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_png, dpi=160)
    plt.close(fig)
    return output_png


def plot_gmm_2_component(input_csv, diagnostics, output_png=None):
    input_csv = Path(input_csv)
    output_png = Path(output_png) if output_png else (
        _plots_dir(input_csv) / "log10_eta_gmm_2_component.png"
    )
    output_png.parent.mkdir(parents=True, exist_ok=True)

    hist = _read_histogram(input_csv)
    log10_eta = _read_log10_eta(input_csv.parent / "nearest_neighbor_diagnostics.csv")
    components = diagnostics["components"]
    crossover = diagnostics["crossover"]["recommended_log10_eta0_gmm_crossover"]
    x = np.linspace(hist["log10_eta_bin_lower"].min(), hist["log10_eta_bin_upper"].max(), 500)
    bin_width = hist["bin_width"].median()
    scale = len(log10_eta) * bin_width

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(
        hist["bin_midpoint"],
        hist["event_count"],
        width=hist["bin_width"],
        color="#dbeafe",
        edgecolor="#bfdbfe",
        linewidth=0.5,
        label="Histogram",
    )

    total_density = np.zeros_like(x)
    colors = ["#2563eb", "#dc2626"]
    for color, (_, row) in zip(colors, components.iterrows()):
        density = row["weight"] * _normal_pdf(
            x, row["mean_log10_eta"], row["sigma_log10_eta"]
        ) * scale
        total_density += density
        ax.plot(x, density, color=color, linewidth=2, label=row["component"])

    ax.plot(x, total_density, color="#111827", linewidth=2, label="GMM total")
    ax.axvline(
        crossover,
        color="#f59e0b",
        linestyle="--",
        linewidth=2,
        label=f"eta0 log10={crossover:.3f}",
    )
    ax.set_title(f"2-component GMM over log10 eta - {input_csv.parent.name}")
    ax.set_xlabel("log10 eta")
    ax.set_ylabel("Event count")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_png, dpi=160)
    plt.close(fig)
    return output_png


def generate_all_outputs(input_csv):
    input_csv = Path(input_csv)
    written = [
        plot_histogram(input_csv),
        plot_smoothed_histogram(input_csv),
    ]

    nearest_csv = input_csv.parent / "nearest_neighbor_diagnostics.csv"
    if nearest_csv.exists():
        diagnostics = write_gmm_diagnostics(input_csv.parent)
        written.append(plot_gmm_2_component(input_csv, diagnostics))

    return written


def plot_overlay(input_csvs, output_png):
    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    for input_csv in input_csvs:
        input_csv = Path(input_csv)
        df = _read_histogram(input_csv)
        ax.plot(
            df["bin_midpoint"],
            df["event_count"],
            marker="o",
            markersize=3,
            linewidth=1.5,
            label=input_csv.parent.name,
        )

    ax.set_title("log10 eta histogram comparison")
    ax.set_xlabel("log10 eta")
    ax.set_ylabel("Event count")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_png, dpi=160)
    plt.close(fig)
    return output_png


def main():
    parser = argparse.ArgumentParser(
        description="Plot nearest-neighbor log10_eta histogram CSV files."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=[DEFAULT_PATTERN],
        help=(
            "Histogram CSV paths or glob patterns. Defaults to "
            f"{DEFAULT_PATTERN}."
        ),
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="Also write a comparison line plot for all matched inputs.",
    )
    parser.add_argument(
        "--overlay-output",
        default="outputs/nn_histogram_comparison.png",
        help="Output PNG path for --overlay.",
    )
    args = parser.parse_args()

    input_csvs = _resolve_inputs(args.inputs)
    for input_csv in input_csvs:
        for output_png in generate_all_outputs(input_csv):
            print(f"Wrote {output_png}")

    if args.overlay and len(input_csvs) > 1:
        output_png = plot_overlay(input_csvs, args.overlay_output)
        print(f"Wrote {output_png}")


if __name__ == "__main__":
    main()
