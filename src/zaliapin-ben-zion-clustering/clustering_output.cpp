#include "clustering.hpp"

#include <fstream>
#include <iomanip>
#include <sstream>

namespace clustering {
namespace {

long long days_from_civil(int year, unsigned month, unsigned day) {
    year -= month <= 2;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yoe = static_cast<unsigned>(year - era * 400);
    const unsigned doy =
        (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
    const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097LL + static_cast<long long>(doe) - 719468LL;
}

double origin_time_years(const diagnostics::Event& event) {
    const long long start = days_from_civil(event.year, 1, 1) * 86400LL;
    const long long next = days_from_civil(event.year + 1, 1, 1) * 86400LL;
    return event.year +
           static_cast<double>(event.sort_time - start) /
               static_cast<double>(next - start);
}

std::string csv_escape(const std::string& value) {
    std::string escaped = "\"";
    for (const char ch : value) {
        if (ch == '"') {
            escaped += "\"\"";
        } else {
            escaped += ch;
        }
    }
    escaped += "\"";
    return escaped;
}

void write_optional_id(
    std::ostream& out,
    const std::optional<std::size_t>& value) {
    if (value.has_value()) {
        out << value.value();
    }
}

void write_optional_double(
    std::ostream& out,
    const std::optional<double>& value) {
    if (value.has_value()) {
        out << value.value();
    }
}

}  // namespace

void write_clustered_dataset(
    const std::vector<ClusteredEvent>& rows,
    const std::filesystem::path& output_csv) {
    std::filesystem::create_directories(output_csv.parent_path());
    std::ofstream out(output_csv);
    out << "event_id,origin_time,origin_time_years,latitude,longitude,"
        << "depth_km,magnitude,location_text,month,year,parent_id,eta,"
        << "log10_eta,is_strong_link,link_type,cluster_id,cluster_type,"
        << "cluster_size,event_role,is_single,is_family_member,mainshock_id,"
        << "mainshock_time,mainshock_magnitude,foreshock_count_in_family,"
        << "aftershock_count_in_family\n";
    out << std::setprecision(12);

    for (const auto& row : rows) {
        const auto& event = row.event;
        out << event.event_id << ","
            << csv_escape(event.origin_time) << ","
            << origin_time_years(event) << ","
            << event.latitude << ","
            << event.longitude << ","
            << event.depth_km << ","
            << event.magnitude << ","
            << csv_escape(event.location_text) << ","
            << csv_escape(event.month) << ","
            << event.year << ",";
        write_optional_id(out, row.parent_id);
        out << ",";
        if (row.parent_id.has_value()) {
            out << row.eta << "," << row.log10_eta;
        } else {
            out << ",";
        }
        out << "," << (row.is_strong_link ? "true" : "false")
            << "," << row.link_type
            << "," << row.cluster_id
            << "," << row.cluster_type
            << "," << row.cluster_size
            << "," << row.event_role
            << "," << (row.is_single ? "true" : "false")
            << "," << (row.is_family_member ? "true" : "false")
            << ",";
        write_optional_id(out, row.mainshock_id);
        out << ",";
        if (row.mainshock_time.has_value()) {
            out << csv_escape(row.mainshock_time.value());
        }
        out << ",";
        write_optional_double(out, row.mainshock_magnitude);
        out << "," << row.foreshock_count_in_family
            << "," << row.aftershock_count_in_family << "\n";
    }
}

}  // namespace clustering
