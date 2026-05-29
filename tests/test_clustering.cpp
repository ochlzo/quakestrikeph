#include "../src/zaliapin-ben-zion-clustering/clustering.hpp"

#include <cassert>
#include <filesystem>

namespace {

diagnostics::Event event(
    std::size_t id,
    long long sort_time,
    double magnitude) {
    return {id, "time", 10.0, 120.0, 5.0, magnitude, "", "January",
            2020, sort_time};
}

nearest_neighbor::NeighborResult neighbor(
    std::size_t event_id,
    std::optional<std::size_t> parent_id,
    double eta,
    double log10_eta) {
    return {event_id, parent_id, eta, log10_eta};
}

const clustering::ClusteredEvent& by_id(
    const std::vector<clustering::ClusteredEvent>& rows,
    std::size_t event_id) {
    for (const auto& row : rows) {
        if (row.event.event_id == event_id) {
            return row;
        }
    }
    assert(false);
    return rows[0];
}

}  // namespace

int main() {
    const std::vector<diagnostics::Event> events{
        event(1, 0, 3.0),
        event(2, 10, 2.5),
        event(3, 20, 4.0),
        event(4, 30, 2.2),
    };
    const std::vector<nearest_neighbor::NeighborResult> neighbors{
        neighbor(1, std::nullopt, 0.0, 0.0),
        neighbor(2, 1, 1e-6, -6.0),
        neighbor(3, 2, 1e-6, -6.0),
        neighbor(4, 1, 1e-3, -3.0),
    };

    const auto rows = clustering::cluster_events(events, neighbors, 1e-5);
    assert(rows.size() == 4);

    const auto& one = by_id(rows, 1);
    const auto& two = by_id(rows, 2);
    const auto& three = by_id(rows, 3);
    const auto& four = by_id(rows, 4);

    assert(one.cluster_id == two.cluster_id);
    assert(two.cluster_id == three.cluster_id);
    assert(four.cluster_id != one.cluster_id);
    assert(one.cluster_size == 3);
    assert(four.cluster_size == 1);

    assert(one.event_role == "foreshock");
    assert(two.event_role == "foreshock");
    assert(three.event_role == "mainshock");
    assert(four.event_role == "single");

    assert(one.mainshock_id.value() == 3);
    assert(three.mainshock_id.value() == 3);
    assert(!four.mainshock_id.has_value());
    assert(!four.mainshock_time.has_value());
    assert(!four.mainshock_magnitude.has_value());

    assert(two.is_strong_link);
    assert(two.link_type == "strong");
    assert(!four.is_strong_link);
    assert(four.link_type == "weak");
    assert(one.foreshock_count_in_family == 2);
    assert(one.aftershock_count_in_family == 0);

    const auto output_dir = std::filesystem::temp_directory_path() /
                            "phivolcs_clustered_output_test";
    std::filesystem::remove_all(output_dir);
    clustering::write_clustered_dataset(
        rows, output_dir / "clustered_dataset.csv");
    assert(std::filesystem::exists(output_dir / "clustered_dataset.csv"));
    std::filesystem::remove_all(output_dir);
}
