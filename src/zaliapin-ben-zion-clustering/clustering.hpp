#pragma once

#include "diagnostics.hpp"
#include "nearest_neighbor.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace clustering {

struct ClusteredEvent {
    diagnostics::Event event;
    std::optional<std::size_t> parent_id;
    double eta{};
    double log10_eta{};
    bool is_strong_link{};
    std::string link_type;
    std::size_t cluster_id{};
    std::string cluster_type;
    std::size_t cluster_size{};
    std::string event_role;
    bool is_single{};
    bool is_family_member{};
    std::optional<std::size_t> mainshock_id;
    std::optional<std::string> mainshock_time;
    std::optional<double> mainshock_magnitude;
    std::size_t foreshock_count_in_family{};
    std::size_t aftershock_count_in_family{};
};

std::vector<ClusteredEvent> cluster_events(
    const std::vector<diagnostics::Event>& events,
    const std::vector<nearest_neighbor::NeighborResult>& neighbors,
    double eta0);

void write_clustered_dataset(
    const std::vector<ClusteredEvent>& rows,
    const std::filesystem::path& output_csv);

}  // namespace clustering
