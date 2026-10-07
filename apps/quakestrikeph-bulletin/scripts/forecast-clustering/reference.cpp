// Research-only bridge to the neighboring corrected implementation. No scoring rules are copied here.
#include "zaliapin/cluster/cluster.hpp"
#include "zaliapin/diagnose/diagnose.hpp"
#include <exception>
#include <iomanip>
#include <iostream>

int main() {
    try {
        zaliapin::DiagnoseParameters settings;
        double threshold;
        std::size_t count;
        if (!(std::cin >> settings.catalog_minimum_magnitude >> settings.b_value
            >> settings.fractal_dimension >> settings.distance_floor_km >> threshold >> count)) {
            throw std::runtime_error("Invalid reference input settings");
        }
        std::vector<zaliapin::Event> events(count);
        for (auto& event : events) {
            std::string precision;
            if (!(std::cin >> event.event_id >> event.origin_time_seconds >> precision
                >> event.latitude >> event.longitude >> event.depth_km >> event.magnitude)) {
                throw std::runtime_error("Invalid reference event");
            }
            event.origin_time_precision = precision == "minute"
                ? zaliapin::TimePrecision::minute : zaliapin::TimePrecision::second;
        }
        const auto result = zaliapin::cluster_diagnosis(zaliapin::diagnose_catalog(events, settings), threshold);
        std::cout << "eventId,parentId,log10Eta,measuredDistanceKm,effectiveDistanceKm,linkType,groupId,groupSize\n"
                  << std::setprecision(17);
        for (const auto& row : result.events) {
            const auto& diagnosed = row.diagnosed;
            std::cout << diagnosed.event.event_id << ',';
            if (diagnosed.parent_index) std::cout << result.events[*diagnosed.parent_index].diagnosed.event.event_id;
            std::cout << ',';
            if (diagnosed.log10_eta) std::cout << *diagnosed.log10_eta;
            std::cout << ',';
            if (diagnosed.measured_distance_km) std::cout << *diagnosed.measured_distance_km;
            std::cout << ',';
            if (diagnosed.effective_distance_km) std::cout << *diagnosed.effective_distance_km;
            std::cout << ',' << zaliapin::to_string(row.link_type) << ',' << row.cluster_id << ',' << row.cluster_size << '\n';
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
