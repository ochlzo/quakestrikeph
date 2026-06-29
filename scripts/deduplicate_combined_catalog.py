import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

def haversine_km(lat1, lon1, lat2, lon2):
    """
    Compute distance in kilometers between two points on the Earth.
    Supports scalars and numpy arrays.
    """
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return 6371.0 * c

def deduplicate_catalog(
    input_csv: Path,
    output_csv: Path,
    time_window_min: float = 2.0,
    dist_window_km: float = 75.0,
    verbose: bool = True
):
    """
    Deduplicates a combined earthquake catalog.
    If a USGS event and a PHIVOLCS event are within time_window_min and dist_window_km,
    the USGS event is considered a duplicate and is removed.
    """
    if verbose:
        print(f"Reading catalog from {input_csv}...")
    df = pd.read_csv(input_csv, low_memory=False)
    n_initial = len(df)
    if verbose:
        print(f"Loaded {n_initial} rows.")
        print(df['catalog_source'].value_counts())

    # Parse date-time for sorting and comparison
    df['parsed_datetime'] = pd.to_datetime(df['Date-Time'], format="%d %B %Y - %I:%M %p", errors='coerce')
    
    # Sort catalog chronologically to enable fast rolling comparisons
    df_sorted = df.dropna(subset=['parsed_datetime']).sort_values('parsed_datetime').copy()
    n_valid_time = len(df_sorted)
    
    if n_valid_time < n_initial and verbose:
        print(f"Warning: {n_initial - n_valid_time} rows have unparseable dates and will be kept (not evaluated for duplicates).")

    times = df_sorted['parsed_datetime'].values
    lats = df_sorted['Latitude'].values
    lons = df_sorted['Longitude'].values
    sources = df_sorted['catalog_source'].values
    orig_indices = df_sorted.index.values

    # Find duplicates to remove
    to_remove_indices = set()
    max_time_diff = np.timedelta64(int(time_window_min * 60), 's')

    if verbose:
        print(f"Scanning for cross-catalog duplicates (time diff <= {time_window_min}m, distance <= {dist_window_km}km)...")

    # Fast sliding window search
    for i in range(n_valid_time):
        t_i = times[i]
        lat_i = lats[i]
        lon_i = lons[i]
        src_i = sources[i]
        idx_i = orig_indices[i]

        # Only evaluate if this is a USGS event
        # If it's a USGS event, we look forward in time for any PHIVOLCS event
        # If it's a PHIVOLCS event, we look forward in time for any USGS event
        # This covers all pairs without double-counting comparisons.
        j = i + 1
        while j < n_valid_time and (times[j] - t_i) <= max_time_diff:
            src_j = sources[j]
            idx_j = orig_indices[j]

            if src_i != src_j:  # Cross-catalog overlap
                # Calculate distance
                dist = haversine_km(lat_i, lon_i, lats[j], lons[j])
                if dist <= dist_window_km:
                    # Identify the USGS index to remove
                    usgs_idx = idx_i if src_i == 'USGS' else idx_j
                    to_remove_indices.add(usgs_idx)
            j += 1

    if verbose:
        print(f"Identified {len(to_remove_indices)} USGS events as duplicates of PHIVOLCS events.")

    # Drop identified duplicate rows
    # We drop them from the original df to preserve the original ordering and any unparseable rows
    df_cleaned = df.drop(index=list(to_remove_indices))
    
    # Drop the temporary helper column
    df_cleaned = df_cleaned.drop(columns=['parsed_datetime'], errors='ignore')

    if verbose:
        print(f"Saving cleaned catalog to {output_csv}...")
    df_cleaned.to_csv(output_csv, index=False)
    
    n_final = len(df_cleaned)
    if verbose:
        print(f"Deduplication completed successfully!")
        print(f"Initial row count: {n_initial}")
        print(f"Removed row count: {len(to_remove_indices)}")
        print(f"Final row count: {n_final}")
        print("\nFinal catalog source counts:")
        print(df_cleaned['catalog_source'].value_counts())
        
    return df_cleaned

def main():
    parser = argparse.ArgumentParser(description="Deduplicate a combined PHIVOLCS-USGS earthquake catalog.")
    parser.add_argument("--input-csv", type=Path, default=Path("dataset/phivolcs_usgs_philippines_m1_combined.csv"),
                        help="Path to the combined input CSV file.")
    parser.add_argument("--output-csv", type=Path, default=Path("dataset/phivolcs_usgs_philippines_m1_combined_clean.csv"),
                        help="Path to the output cleaned CSV file.")
    parser.add_argument("--time-window", type=float, default=2.0,
                        help="Time window in minutes to search for duplicates (default: 2.0).")
    parser.add_argument("--dist-window", type=float, default=75.0,
                        help="Distance window in km to search for duplicates (default: 75.0).")
    
    args = parser.parse_args()
    
    deduplicate_catalog(
        input_csv=args.input_csv,
        output_csv=args.output_csv,
        time_window_min=args.time_window,
        dist_window_km=args.dist_window,
        verbose=True
    )

if __name__ == "__main__":
    main()
