#include "clustering.hpp"

#include <algorithm>
#include <numeric>
#include <stdexcept>
#include <unordered_map>

namespace clustering {
namespace {

class DisjointSet {
public:
    explicit DisjointSet(std::size_t size) : parent_(size), size_(size, 1) {
        std::iota(parent_.begin(), parent_.end(), 0);
    }

    std::size_t find(std::size_t value) {
        if (parent_[value] != value) {
            parent_[value] = find(parent_[value]);
        }
        return parent_[value];
    }

    void unite(std::size_t left, std::size_t right) {
        left = find(left);
        right = find(right);
        if (left == right) {
            return;
        }
        if (size_[left] < size_[right]) {
            std::swap(left, right);
        }
        parent_[right] = left;
        size_[left] += size_[right];
    }

private:
    std::vector<std::size_t> parent_;
    std::vector<std::size_t> size_;
};

std::size_t choose_mainshock(
    const std::vector<std::size_t>& members,
    const std::vector<diagnostics::Event>& events) {
    return *std::max_element(
        members.begin(), members.end(),
        [&](std::size_t left, std::size_t right) {
            if (events[left].magnitude != events[right].magnitude) {
                return events[left].magnitude < events[right].magnitude;
            }
            return events[left].sort_time > events[right].sort_time;
        });
}

}  // namespace

std::vector<ClusteredEvent> cluster_events(
    const std::vector<diagnostics::Event>& events,
    const std::vector<nearest_neighbor::NeighborResult>& neighbors,
    double eta0) {
    if (events.size() != neighbors.size()) {
        throw std::runtime_error("Event/nearest-neighbor count mismatch.");
    }

    std::unordered_map<std::size_t, std::size_t> index_by_id;
    for (std::size_t i = 0; i < events.size(); ++i) {
        index_by_id[events[i].event_id] = i;
    }

    DisjointSet sets(events.size());
    std::vector<ClusteredEvent> rows(events.size());
    for (std::size_t i = 0; i < events.size(); ++i) {
        const auto& neighbor = neighbors[i];
        const bool strong =
            neighbor.parent_id.has_value() && neighbor.eta < eta0;
        rows[i].event = events[i];
        rows[i].parent_id = neighbor.parent_id;
        rows[i].eta = neighbor.eta;
        rows[i].log10_eta = neighbor.log10_eta;
        rows[i].is_strong_link = strong;
        rows[i].link_type = strong ? "strong" : "weak";

        if (strong) {
            const auto parent = index_by_id.find(neighbor.parent_id.value());
            if (parent == index_by_id.end()) {
                throw std::runtime_error("Nearest-neighbor parent not found.");
            }
            sets.unite(i, parent->second);
        }
    }

    std::unordered_map<std::size_t, std::vector<std::size_t>> components;
    for (std::size_t i = 0; i < events.size(); ++i) {
        components[sets.find(i)].push_back(i);
    }

    std::vector<std::vector<std::size_t>> ordered_components;
    ordered_components.reserve(components.size());
    for (auto& [_, members] : components) {
        std::sort(members.begin(), members.end());
        ordered_components.push_back(members);
    }
    std::sort(ordered_components.begin(), ordered_components.end(),
              [&](const auto& left, const auto& right) {
                  return events[left.front()].sort_time <
                         events[right.front()].sort_time;
              });

    for (std::size_t cid = 0; cid < ordered_components.size(); ++cid) {
        const auto& members = ordered_components[cid];
        const bool single = members.size() == 1;
        std::size_t mainshock = members.front();
        if (!single) {
            mainshock = choose_mainshock(members, events);
        }

        std::size_t foreshocks = 0;
        std::size_t aftershocks = 0;
        for (const auto member : members) {
            if (single) {
                continue;
            }
            if (member == mainshock) {
                continue;
            }
            if (events[member].sort_time < events[mainshock].sort_time) {
                ++foreshocks;
            } else {
                ++aftershocks;
            }
        }

        for (const auto member : members) {
            auto& row = rows[member];
            row.cluster_id = cid + 1;
            row.cluster_size = members.size();
            row.cluster_type = single ? "single" : "family";
            row.is_single = single;
            row.is_family_member = !single;
            row.foreshock_count_in_family = foreshocks;
            row.aftershock_count_in_family = aftershocks;

            if (single) {
                row.event_role = "single";
                continue;
            }

            row.mainshock_id = events[mainshock].event_id;
            row.mainshock_time = events[mainshock].origin_time;
            row.mainshock_magnitude = events[mainshock].magnitude;
            if (member == mainshock) {
                row.event_role = "mainshock";
            } else if (events[member].sort_time < events[mainshock].sort_time) {
                row.event_role = "foreshock";
            } else {
                row.event_role = "aftershock";
            }
        }
    }

    return rows;
}

}  // namespace clustering
