#include "diagnostics.hpp"
#include "nearest_neighbor.hpp"

#include <exception>
#include <filesystem>
#include <iostream>
#include <string>

namespace {

void print_usage(const char* executable) {
    std::cerr
        << "Usage: " << executable
        << " [input_csv] [output_dir] [m_c] [b] [d_f] [hist_bin_width]\n"
        << "Default input_csv: dataset/phivolcs_earthquake_2018_2026.csv\n"
        << "Default output_dir: outputs/nn_diagnostics_mc_2_0\n"
        << "Default m_c: 2.0\n"
        << "Default b: 1.0\n"
        << "Default d_f: 1.6\n"
        << "Default hist_bin_width: 0.1\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc > 7) {
        print_usage(argv[0]);
        return 2;
    }

    const std::filesystem::path input_csv =
        argc >= 2 ? argv[1] : "dataset/phivolcs_earthquake_2018_2026.csv";
    const std::filesystem::path output_dir =
        argc >= 3 ? argv[2] : "outputs/nn_diagnostics_mc_2_0";
    const double minimum_magnitude = argc >= 4 ? std::stod(argv[3]) : 2.0;
    const double b_value = argc >= 5 ? std::stod(argv[4]) : 1.0;
    const double fractal_dimension = argc >= 6 ? std::stod(argv[5]) : 1.6;
    const double hist_bin_width = argc >= 7 ? std::stod(argv[6]) : 0.1;

    try {
        const auto catalog = diagnostics::read_catalog(input_csv);
        const auto filtered = nearest_neighbor::filter_by_magnitude(
            catalog.events, minimum_magnitude);
        const auto results = nearest_neighbor::compute_nearest_neighbors(
            filtered, b_value, fractal_dimension);
        nearest_neighbor::write_nearest_neighbor_outputs(
            filtered, results, hist_bin_width, output_dir);

        std::cout << "Input rows: " << catalog.report.total_rows << "\n";
        std::cout << "Filtered rows: " << filtered.size() << "\n";
        std::cout << "m_c: " << minimum_magnitude << "\n";
        std::cout << "b: " << b_value << "\n";
        std::cout << "d_f: " << fractal_dimension << "\n";
        std::cout << "Diagnostics written to: " << output_dir.string() << "\n";
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << "\n";
        return 1;
    }

    return 0;
}
