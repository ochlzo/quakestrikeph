#include "diagnostics.hpp"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <ostream>

namespace diagnostics {
namespace {

void write_double(std::ostream& out, double value) {
    out << std::fixed << std::setprecision(1) << value;
}

}  // namespace

void write_outputs(const ParsedCatalog& catalog,
                   const std::vector<double>& cutoffs,
                   double bin_width,
                   const std::filesystem::path& output_dir) {
    std::filesystem::create_directories(output_dir);

    std::ofstream bins_file(output_dir / "magnitude_bins.csv");
    bins_file << "magnitude_bin_lower,magnitude_bin_upper,event_count\n";
    for (const auto& bin : magnitude_bins(catalog.events, bin_width)) {
        write_double(bins_file, bin.lower);
        bins_file << ",";
        write_double(bins_file, bin.upper);
        bins_file << "," << bin.event_count << "\n";
    }

    std::ofstream cutoff_file(output_dir / "magnitude_cutoff_counts.csv");
    cutoff_file << "magnitude_cutoff,event_count_at_or_above\n";
    for (const auto& [cutoff, count] :
         cumulative_cutoff_counts(catalog.events, cutoffs)) {
        write_double(cutoff_file, cutoff);
        cutoff_file << "," << count << "\n";
    }

    std::ofstream yearly_file(
        output_dir / "yearly_counts_by_magnitude_cutoff.csv");
    yearly_file << "year,magnitude_cutoff,event_count_at_or_above\n";
    for (const auto& [key, count] :
         yearly_cutoff_counts(catalog.events, cutoffs)) {
        yearly_file << key.first << ",";
        write_double(yearly_file, key.second);
        yearly_file << "," << count << "\n";
    }

    const auto& report = catalog.report;
    std::ofstream report_file(output_dir / "input_validation_report.txt");
    report_file << "total_rows=" << report.total_rows << "\n";
    report_file << "valid_rows=" << report.valid_rows << "\n";
    report_file << "invalid_date_time=" << report.invalid_date_time << "\n";
    report_file << "invalid_latitude=" << report.invalid_latitude << "\n";
    report_file << "invalid_longitude=" << report.invalid_longitude << "\n";
    report_file << "invalid_depth=" << report.invalid_depth << "\n";
    report_file << "invalid_magnitude=" << report.invalid_magnitude << "\n";
    report_file << "invalid_year=" << report.invalid_year << "\n";
}

}  // namespace diagnostics
