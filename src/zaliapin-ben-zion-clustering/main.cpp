#include "diagnostics.hpp"

#include <exception>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace {

void print_usage(const char* executable) {
    std::cerr
        << "Usage: " << executable
        << " [input_csv] [output_dir] [bin_width]\n"
        << "Default input_csv: dataset/phivolcs_earthquake_2018_2026.csv\n"
        << "Default output_dir: outputs/mc_diagnostics\n"
        << "Default bin_width: 0.1\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc > 4) {
        print_usage(argv[0]);
        return 2;
    }

    const std::filesystem::path input_csv =
        argc >= 2 ? argv[1] : "dataset/phivolcs_earthquake_2018_2026.csv";
    const std::filesystem::path output_dir =
        argc >= 3 ? argv[2] : "outputs/mc_diagnostics";
    const double bin_width = argc >= 4 ? std::stod(argv[3]) : 0.1;

    try {
        const auto catalog = diagnostics::read_catalog(input_csv);
        const auto cutoffs = diagnostics::default_cutoffs(catalog.events);
        diagnostics::write_outputs(catalog, cutoffs, bin_width, output_dir);

        std::cout << "Input rows: " << catalog.report.total_rows << "\n";
        std::cout << "Valid rows: " << catalog.report.valid_rows << "\n";
        std::cout << "Diagnostics written to: " << output_dir.string() << "\n";
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << "\n";
        return 1;
    }

    return 0;
}
