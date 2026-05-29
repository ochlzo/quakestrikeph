#include "../src/zaliapin-ben-zion-clustering/diagnostics.hpp"

#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace {

void write_fixture(const std::filesystem::path& path) {
    std::ofstream out(path);
    out << "Date-Time,Latitude,Longitude,Depth,Magnitude,Location,Month,Year\n";
    out << "\"02 January 2020 - 01:00 AM\",10.0,120.0,5.0,2.4,\"A, Place\",January,2020\n";
    out << "\"01 January 2020 - 11:30 PM\",11.0,121.0,7.0,3.1,B,January,2020\n";
    out << "\"01 January 2020 - 02:00 AM\",10.5,120.5,6.0,2.1,Early,January,2020\n";
    out << "\"01 January 2020 - 01:00 PM\",10.7,120.7,6.0,2.2,Afternoon,January,2020\n";
    out << "bad-date,12.0,122.0,8.0,4.0,C,January,2020\n";
    out << "\"03 January 2021 - 12:00 PM\",13.0,123.0,9.0,not-a-number,D,January,2021\n";
    out << "\"04 January 2021 - 12:00 PM\",14.0,124.0,9.0,1.2,E,January,2021\n";
}

}  // namespace

int main() {
    const auto temp_path = std::filesystem::temp_directory_path() /
                           "phivolcs_magnitude_diagnostics_test.csv";
    write_fixture(temp_path);

    const auto catalog = diagnostics::read_catalog(temp_path);
    assert(catalog.events.size() == 5);
    assert(catalog.report.total_rows == 7);
    assert(catalog.report.valid_rows == 5);
    assert(catalog.report.invalid_date_time == 1);
    assert(catalog.report.invalid_magnitude == 1);
    assert(catalog.events[0].location_text == "Early");
    assert(catalog.events[1].location_text == "Afternoon");
    assert(catalog.events[2].location_text == "B");
    assert(catalog.events[3].location_text == "A, Place");

    const auto bins = diagnostics::magnitude_bins(catalog.events, 0.5);
    assert(bins.size() == 3);
    assert(bins[0].lower == 1.0);
    assert(bins[0].upper == 1.5);
    assert(bins[0].event_count == 1);
    assert(bins[1].lower == 2.0);
    assert(bins[1].upper == 2.5);
    assert(bins[1].event_count == 3);
    assert(bins[2].lower == 3.0);
    assert(bins[2].upper == 3.5);
    assert(bins[2].event_count == 1);

    const auto narrow_bins = diagnostics::magnitude_bins(catalog.events, 0.1);
    assert(narrow_bins[0].lower == 1.2);
    assert(narrow_bins[0].upper == 1.3);

    const std::vector<double> cutoffs{1.0, 2.0, 3.0};
    const auto cumulative = diagnostics::cumulative_cutoff_counts(
        catalog.events, cutoffs);
    assert(cumulative.at(1.0) == 5);
    assert(cumulative.at(2.0) == 4);
    assert(cumulative.at(3.0) == 1);

    const auto yearly = diagnostics::yearly_cutoff_counts(
        catalog.events, cutoffs);
    assert(yearly.at({2020, 1.0}) == 4);
    assert(yearly.at({2020, 3.0}) == 1);
    assert(yearly.at({2021, 1.0}) == 1);
    assert(yearly.at({2021, 2.0}) == 0);

    const auto output_dir = std::filesystem::temp_directory_path() /
                            "phivolcs_magnitude_diagnostics_outputs";
    std::filesystem::remove_all(output_dir);
    diagnostics::write_outputs(catalog, cutoffs, 0.5, output_dir);

    assert(std::filesystem::exists(output_dir / "magnitude_bins.csv"));
    assert(std::filesystem::exists(output_dir / "magnitude_cutoff_counts.csv"));
    assert(std::filesystem::exists(output_dir / "yearly_counts_by_magnitude_cutoff.csv"));
    assert(std::filesystem::exists(output_dir / "input_validation_report.txt"));

    std::filesystem::remove(temp_path);
    std::filesystem::remove_all(output_dir);
}
