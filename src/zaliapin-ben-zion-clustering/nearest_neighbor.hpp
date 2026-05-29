#pragma once

#include "diagnostics.hpp"

#include <filesystem>
#include <optional>
#include <vector>

namespace nearest_neighbor {

struct NeighborResult {
    std::size_t event_id{};
    std::optional<std::size_t> parent_id;
    double eta{};
    double log10_eta{};
};

struct LogEtaBin {
    double lower{};
    double upper{};
    std::size_t event_count{};
};

std::vector<diagnostics::Event> filter_by_magnitude(
    const std::vector<diagnostics::Event>& events,
    double minimum_magnitude);
double seconds_to_years(long long seconds);
double surface_distance_km(
    const diagnostics::Event& first,
    const diagnostics::Event& second);
std::vector<NeighborResult> compute_nearest_neighbors(
    const std::vector<diagnostics::Event>& events,
    double b_value,
    double fractal_dimension);
std::vector<LogEtaBin> log_eta_histogram(
    const std::vector<NeighborResult>& results,
    double bin_width);
void write_nearest_neighbor_outputs(
    const std::vector<diagnostics::Event>& events,
    const std::vector<NeighborResult>& results,
    double histogram_bin_width,
    const std::filesystem::path& output_dir);

}  // namespace nearest_neighbor
