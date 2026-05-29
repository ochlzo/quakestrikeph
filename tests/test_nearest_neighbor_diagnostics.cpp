#include "../src/zaliapin-ben-zion-clustering/nearest_neighbor.hpp"

#include <cassert>
#include <cmath>
#include <filesystem>

namespace {

diagnostics::Event event(
    std::size_t id,
    long long sort_time,
    double lat,
    double lon,
    double magnitude) {
    return {id, "", lat, lon, 0.0, magnitude, "", "", 2020, sort_time};
}

bool near(double lhs, double rhs) {
    return std::abs(lhs - rhs) < 1e-9;
}

}  // namespace

int main() {
    const std::vector<diagnostics::Event> events{
        event(1, 0, 0.0, 0.0, 3.0),
        event(2, 86400, 0.0, 1.0, 2.5),
        event(3, 172800, 0.0, 0.1, 2.0),
        event(4, 259200, 10.0, 10.0, 1.9),
    };

    const auto filtered = nearest_neighbor::filter_by_magnitude(events, 2.0);
    assert(filtered.size() == 3);
    assert(filtered[0].event_id == 1);
    assert(filtered[2].event_id == 3);

    const double years = nearest_neighbor::seconds_to_years(31557600);
    assert(near(years, 1.0));

    const auto results = nearest_neighbor::compute_nearest_neighbors(
        filtered, 1.0, 1.6);
    assert(results.size() == 3);
    assert(!results[0].parent_id.has_value());
    assert(results[0].eta == 0.0);
    assert(results[0].log10_eta == 0.0);
    assert(results[1].parent_id.value() == 1);
    assert(results[1].eta > 0.0);
    assert(results[1].log10_eta < 0.0);
    assert(results[2].parent_id.value() == 1);

    const auto histogram = nearest_neighbor::log_eta_histogram(results, 0.5);
    assert(!histogram.empty());

    const auto output_dir = std::filesystem::temp_directory_path() /
                            "phivolcs_nearest_neighbor_outputs";
    std::filesystem::remove_all(output_dir);
    nearest_neighbor::write_nearest_neighbor_outputs(
        filtered, results, 0.5, output_dir);
    assert(std::filesystem::exists(
        output_dir / "nearest_neighbor_diagnostics.csv"));
    assert(std::filesystem::exists(
        output_dir / "log10_eta_histogram.csv"));
    std::filesystem::remove_all(output_dir);
}
