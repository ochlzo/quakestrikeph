#include "nearest_neighbor.hpp"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <stdexcept>

namespace nearest_neighbor {
namespace {

void write_nullable_parent(
    std::ostream& out,
    const std::optional<std::size_t>& parent_id) {
    if (parent_id.has_value()) {
        out << parent_id.value();
    }
}

}  // namespace

void write_nearest_neighbor_outputs(
    const std::vector<diagnostics::Event>& events,
    const std::vector<NeighborResult>& results,
    double histogram_bin_width,
    const std::filesystem::path& output_dir) {
    if (events.size() != results.size()) {
        throw std::runtime_error("Event/result count mismatch.");
    }
    std::filesystem::create_directories(output_dir);

    std::ofstream nn_file(output_dir / "nearest_neighbor_diagnostics.csv");
    nn_file << "event_id,origin_time,latitude,longitude,depth_km,magnitude,"
            << "location_text,month,year,parent_id,eta,log10_eta\n";
    nn_file << std::setprecision(12);
    for (std::size_t i = 0; i < events.size(); ++i) {
        const auto& event = events[i];
        const auto& result = results[i];
        nn_file << event.event_id << ",\"" << event.origin_time << "\","
                << event.latitude << "," << event.longitude << ","
                << event.depth_km << "," << event.magnitude << ",\""
                << event.location_text << "\",\"" << event.month << "\","
                << event.year << ",";
        write_nullable_parent(nn_file, result.parent_id);
        nn_file << ",";
        if (result.parent_id.has_value()) {
            nn_file << result.eta << "," << result.log10_eta;
        } else {
            nn_file << ",";
        }
        nn_file << "\n";
    }

    std::ofstream hist_file(output_dir / "log10_eta_histogram.csv");
    hist_file << "log10_eta_bin_lower,log10_eta_bin_upper,event_count\n";
    hist_file << std::fixed << std::setprecision(3);
    for (const auto& bin : log_eta_histogram(results, histogram_bin_width)) {
        hist_file << bin.lower << "," << bin.upper << ","
                  << bin.event_count << "\n";
    }
}

}  // namespace nearest_neighbor
