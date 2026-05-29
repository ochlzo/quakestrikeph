#include "clustering.hpp"
#include "diagnostics.hpp"
#include "nearest_neighbor.hpp"

#include <exception>
#include <filesystem>
#include <iostream>

namespace {

void print_usage(const char* executable) {
    std::cerr
        << "Usage: " << executable
        << " [input_csv] [output_csv] [m_c] [b] [d_f] [eta_0]\n"
        << "Default input_csv: dataset/phivolcs_earthquake_2018_2026.csv\n"
        << "Default output_csv: outputs/clustered_ml_ready_mc_2_0.csv\n"
        << "Default m_c: 2.0\n"
        << "Default b: 1.0\n"
        << "Default d_f: 1.6\n"
        << "Default eta_0: 3.4245690866683006e-6\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc > 7) {
        print_usage(argv[0]);
        return 2;
    }

    const std::filesystem::path input_csv =
        argc >= 2 ? argv[1] : "dataset/phivolcs_earthquake_2018_2026.csv";
    const std::filesystem::path output_csv =
        argc >= 3 ? argv[2] : "outputs/clustered_ml_ready_mc_2_0.csv";
    const double minimum_magnitude = argc >= 4 ? std::stod(argv[3]) : 2.0;
    const double b_value = argc >= 5 ? std::stod(argv[4]) : 1.0;
    const double fractal_dimension = argc >= 6 ? std::stod(argv[5]) : 1.6;
    const double eta0 = argc >= 7 ? std::stod(argv[6]) : 3.4245690866683006e-6;

    try {
        const auto catalog = diagnostics::read_catalog(input_csv);
        const auto filtered = nearest_neighbor::filter_by_magnitude(
            catalog.events, minimum_magnitude);
        const auto neighbors = nearest_neighbor::compute_nearest_neighbors(
            filtered, b_value, fractal_dimension);
        const auto rows = clustering::cluster_events(filtered, neighbors, eta0);
        clustering::write_clustered_dataset(rows, output_csv);

        std::cout << "Input rows: " << catalog.report.total_rows << "\n";
        std::cout << "Filtered rows: " << filtered.size() << "\n";
        std::cout << "m_c: " << minimum_magnitude << "\n";
        std::cout << "b: " << b_value << "\n";
        std::cout << "d_f: " << fractal_dimension << "\n";
        std::cout << "eta_0: " << eta0 << "\n";
        std::cout << "Clustered dataset written to: "
                  << output_csv.string() << "\n";
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << "\n";
        return 1;
    }
    return 0;
}
