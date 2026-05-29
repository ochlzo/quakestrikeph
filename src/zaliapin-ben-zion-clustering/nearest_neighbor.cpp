#include "nearest_neighbor.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <stdexcept>

namespace nearest_neighbor {
namespace {

constexpr double kEarthRadiusKm = 6371.0088;
constexpr double kSecondsPerYear = 365.25 * 24.0 * 60.0 * 60.0;
constexpr double kPi = 3.14159265358979323846;

double radians(double degrees) {
    return degrees * kPi / 180.0;
}

struct EventTerms {
    double lat_rad{};
    double lon_rad{};
    double cos_lat{};
    double magnitude_term{};
};

std::vector<EventTerms> precompute_terms(
    const std::vector<diagnostics::Event>& events,
    double b_value) {
    std::vector<EventTerms> terms;
    terms.reserve(events.size());
    for (const auto& event : events) {
        const double lat = radians(event.latitude);
        terms.push_back(
            {lat, radians(event.longitude), std::cos(lat),
             b_value * event.magnitude});
    }
    return terms;
}

double surface_distance_km(
    const EventTerms& first,
    const EventTerms& second) {
    const double dlat = second.lat_rad - first.lat_rad;
    const double dlon = second.lon_rad - first.lon_rad;
    const double sin_lat = std::sin(dlat / 2.0);
    const double sin_lon = std::sin(dlon / 2.0);
    const double a = sin_lat * sin_lat +
                     first.cos_lat * second.cos_lat * sin_lon * sin_lon;
    const double clamped = std::min(1.0, std::max(0.0, a));
    return 2.0 * kEarthRadiusKm * std::asin(std::sqrt(clamped));
}

}  // namespace

std::vector<diagnostics::Event> filter_by_magnitude(
    const std::vector<diagnostics::Event>& events,
    double minimum_magnitude) {
    std::vector<diagnostics::Event> filtered;
    for (const auto& event : events) {
        if (event.magnitude >= minimum_magnitude) {
            filtered.push_back(event);
        }
    }
    return filtered;
}

double seconds_to_years(long long seconds) {
    return static_cast<double>(seconds) / kSecondsPerYear;
}

double surface_distance_km(
    const diagnostics::Event& first,
    const diagnostics::Event& second) {
    const double lat1 = radians(first.latitude);
    const double lat2 = radians(second.latitude);
    const double dlat = lat2 - lat1;
    const double dlon = radians(second.longitude - first.longitude);
    const double sin_lat = std::sin(dlat / 2.0);
    const double sin_lon = std::sin(dlon / 2.0);
    const double a = sin_lat * sin_lat +
                     std::cos(lat1) * std::cos(lat2) * sin_lon * sin_lon;
    const double clamped = std::min(1.0, std::max(0.0, a));
    return 2.0 * kEarthRadiusKm * std::asin(std::sqrt(clamped));
}

std::vector<NeighborResult> compute_nearest_neighbors(
    const std::vector<diagnostics::Event>& events,
    double b_value,
    double fractal_dimension) {
    std::vector<NeighborResult> results(events.size());
    const auto terms = precompute_terms(events, b_value);
    for (std::size_t j = 0; j < events.size(); ++j) {
        results[j].event_id = events[j].event_id;
        if (j == 0) {
            continue;
        }

        double best_log_eta = std::numeric_limits<double>::infinity();
        std::optional<std::size_t> best_parent;
        for (std::size_t i = 0; i < j; ++i) {
            const long long seconds = events[j].sort_time - events[i].sort_time;
            if (seconds <= 0) {
                continue;
            }
            const double years = seconds_to_years(seconds);
            const double distance = surface_distance_km(terms[i], terms[j]);
            if (distance <= 0.0) {
                continue;
            }
            const double log_eta = std::log10(years) +
                                   fractal_dimension * std::log10(distance) -
                                   terms[i].magnitude_term;
            if (log_eta < best_log_eta) {
                best_log_eta = log_eta;
                best_parent = events[i].event_id;
            }
        }

        results[j].parent_id = best_parent;
        if (best_parent.has_value()) {
            results[j].log10_eta = best_log_eta;
            results[j].eta = std::pow(10.0, best_log_eta);
        }
    }
    return results;
}

std::vector<LogEtaBin> log_eta_histogram(
    const std::vector<NeighborResult>& results,
    double bin_width) {
    if (bin_width <= 0.0) {
        throw std::runtime_error("log10_eta bin width must be positive.");
    }

    std::map<double, std::size_t> counts;
    for (const auto& result : results) {
        if (!result.parent_id.has_value()) {
            continue;
        }
        const auto index = static_cast<long long>(
            std::floor((result.log10_eta + 1e-9) / bin_width));
        const double lower = std::round(index * bin_width * 1000.0) / 1000.0;
        counts[lower]++;
    }

    std::vector<LogEtaBin> bins;
    for (const auto& [lower, count] : counts) {
        bins.push_back({lower, lower + bin_width, count});
    }
    return bins;
}

}  // namespace nearest_neighbor
