#pragma once

#include <cstddef>
#include <filesystem>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace diagnostics {

struct Event {
    std::size_t event_id{};
    std::string origin_time;
    double latitude{};
    double longitude{};
    double depth_km{};
    double magnitude{};
    std::string location_text;
    std::string month;
    int year{};
    long long sort_time{};
};

struct ValidationReport {
    std::size_t total_rows{};
    std::size_t valid_rows{};
    std::size_t invalid_date_time{};
    std::size_t invalid_latitude{};
    std::size_t invalid_longitude{};
    std::size_t invalid_depth{};
    std::size_t invalid_magnitude{};
    std::size_t invalid_year{};
};

struct ParsedCatalog {
    std::vector<Event> events;
    ValidationReport report;
};

struct MagnitudeBin {
    double lower{};
    double upper{};
    std::size_t event_count{};
};

using CutoffCounts = std::map<double, std::size_t>;
using YearCutoffKey = std::pair<int, double>;
using YearlyCutoffCounts = std::map<YearCutoffKey, std::size_t>;

ParsedCatalog read_catalog(const std::filesystem::path& input_csv);
std::vector<MagnitudeBin> magnitude_bins(
    const std::vector<Event>& events,
    double bin_width);
std::vector<double> default_cutoffs(const std::vector<Event>& events);
CutoffCounts cumulative_cutoff_counts(
    const std::vector<Event>& events,
    const std::vector<double>& cutoffs);
YearlyCutoffCounts yearly_cutoff_counts(
    const std::vector<Event>& events,
    const std::vector<double>& cutoffs);
void write_outputs(
    const ParsedCatalog& catalog,
    const std::vector<double>& cutoffs,
    double bin_width,
    const std::filesystem::path& output_dir);

}  // namespace diagnostics
