#include "diagnostics.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace diagnostics {
namespace {
std::string strip_bom(std::string value) {
    if (value.size() >= 3 &&
        static_cast<unsigned char>(value[0]) == 0xEF &&
        static_cast<unsigned char>(value[1]) == 0xBB &&
        static_cast<unsigned char>(value[2]) == 0xBF) {
        return value.substr(3);
    }
    return value;
}

std::vector<std::string> parse_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string field;
    bool in_quotes = false;

    for (std::size_t i = 0; i < line.size(); ++i) {
        const char ch = line[i];
        if (ch == '"') {
            if (in_quotes && i + 1 < line.size() && line[i + 1] == '"') {
                field.push_back('"');
                ++i;
            } else {
                in_quotes = !in_quotes;
            }
        } else if (ch == ',' && !in_quotes) {
            fields.push_back(field);
            field.clear();
        } else {
            field.push_back(ch);
        }
    }
    fields.push_back(field);
    return fields;
}

bool parse_double(const std::string& text, double& value) {
    try {
        std::size_t pos = 0;
        value = std::stod(text, &pos);
        return pos == text.size() && std::isfinite(value);
    } catch (...) {
        return false;
    }
}

bool parse_int(const std::string& text, int& value) {
    try {
        std::size_t pos = 0;
        value = std::stoi(text, &pos);
        return pos == text.size();
    } catch (...) {
        return false;
    }
}

int month_number(const std::string& month) {
    static const std::unordered_map<std::string, int> months{
        {"January", 1},   {"February", 2}, {"March", 3},
        {"April", 4},     {"May", 5},      {"June", 6},
        {"July", 7},      {"August", 8},   {"September", 9},
        {"October", 10},  {"November", 11}, {"December", 12},
    };
    const auto found = months.find(month);
    return found == months.end() ? 0 : found->second;
}

long long days_from_civil(int year, unsigned month, unsigned day) {
    year -= month <= 2;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yoe = static_cast<unsigned>(year - era * 400);
    const unsigned doy =
        (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
    const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097LL + static_cast<long long>(doe) - 719468LL;
}

bool parse_clock(const std::string& text, int& hour, int& minute) {
    const auto colon = text.find(':');
    if (colon == std::string::npos) {
        return false;
    }
    return parse_int(text.substr(0, colon), hour) &&
           parse_int(text.substr(colon + 1), minute);
}

bool parse_origin_time(const std::string& text, long long& sort_time) {
    int day = 0;
    int year = 0;
    int hour = 0;
    int minute = 0;
    std::string month_text;
    std::string dash;
    std::string clock_text;
    std::string am_pm;
    std::istringstream input(text);
    input >> day >> month_text >> year >> dash >> clock_text >> am_pm;

    const int month = month_number(month_text);
    if (!input || dash != "-" || month == 0 ||
        !parse_clock(clock_text, hour, minute)) {
        return false;
    }

    for (auto& ch : am_pm) {
        ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
    }
    if (am_pm == "AM") {
        if (hour == 12) {
            hour = 0;
        }
    } else if (am_pm == "PM") {
        if (hour != 12) {
            hour += 12;
        }
    } else {
        return false;
    }

    if (day < 1 || day > 31 || hour < 0 || hour > 23 ||
        minute < 0 || minute > 59) {
        return false;
    }

    const long long days = days_from_civil(
        year, static_cast<unsigned>(month), static_cast<unsigned>(day));
    sort_time = days * 86400LL + hour * 3600LL + minute * 60LL;
    return true;
}

std::string get_field(
    const std::vector<std::string>& fields,
    const std::unordered_map<std::string, std::size_t>& index,
    const std::string& name) {
    const auto found = index.find(name);
    if (found == index.end() || found->second >= fields.size()) {
        return "";
    }
    return fields[found->second];
}

void require_columns(
    const std::unordered_map<std::string, std::size_t>& index,
    const std::vector<std::string>& names) {
    for (const auto& name : names) {
        if (index.find(name) == index.end()) {
            throw std::runtime_error("Missing required CSV column: " + name);
        }
    }
}

double round_one_decimal(double value) {
    return std::round(value * 10.0) / 10.0;
}
}  // namespace

ParsedCatalog read_catalog(const std::filesystem::path& input_csv) {
    std::ifstream input(input_csv);
    if (!input) {
        throw std::runtime_error("Unable to open input CSV: " + input_csv.string());
    }

    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("Input CSV is empty: " + input_csv.string());
    }

    const auto headers = parse_csv_line(line);
    std::unordered_map<std::string, std::size_t> index;
    for (std::size_t i = 0; i < headers.size(); ++i) {
        index[strip_bom(headers[i])] = i;
    }
    require_columns(index, {"Date-Time", "Latitude", "Longitude", "Depth",
                            "Magnitude", "Location", "Month", "Year"});

    ParsedCatalog catalog;
    std::size_t next_event_id = 1;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }
        ++catalog.report.total_rows;
        const auto fields = parse_csv_line(line);

        long long sort_time = 0;
        double latitude = 0.0;
        double longitude = 0.0;
        double depth = 0.0;
        double magnitude = 0.0;
        int year = 0;
        bool valid = true;

        const auto date_text = get_field(fields, index, "Date-Time");
        if (!parse_origin_time(date_text, sort_time)) {
            ++catalog.report.invalid_date_time;
            valid = false;
        }
        if (!parse_double(get_field(fields, index, "Latitude"), latitude)) {
            ++catalog.report.invalid_latitude;
            valid = false;
        }
        if (!parse_double(get_field(fields, index, "Longitude"), longitude)) {
            ++catalog.report.invalid_longitude;
            valid = false;
        }
        if (!parse_double(get_field(fields, index, "Depth"), depth)) {
            ++catalog.report.invalid_depth;
            valid = false;
        }
        if (!parse_double(get_field(fields, index, "Magnitude"), magnitude)) {
            ++catalog.report.invalid_magnitude;
            valid = false;
        }
        if (!parse_int(get_field(fields, index, "Year"), year)) {
            ++catalog.report.invalid_year;
            valid = false;
        }
        if (!valid) {
            continue;
        }

        catalog.events.push_back(
            {next_event_id++, date_text, latitude, longitude, depth, magnitude,
             get_field(fields, index, "Location"),
             get_field(fields, index, "Month"), year, sort_time});
    }

    std::sort(catalog.events.begin(), catalog.events.end(),
              [](const Event& lhs, const Event& rhs) {
                  return lhs.sort_time < rhs.sort_time;
              });
    catalog.report.valid_rows = catalog.events.size();
    return catalog;
}

std::vector<MagnitudeBin> magnitude_bins(const std::vector<Event>& events,
                                         double bin_width) {
    if (bin_width <= 0.0) {
        throw std::runtime_error("Magnitude bin width must be positive.");
    }

    std::map<double, std::size_t> counts;
    for (const auto& event : events) {
        const auto index = static_cast<long long>(
            std::floor((event.magnitude + 1e-9) / bin_width));
        const double lower = std::round(index * bin_width * 1000.0) / 1000.0;
        counts[lower]++;
    }

    std::vector<MagnitudeBin> bins;
    for (const auto& [lower, count] : counts) {
        bins.push_back({lower, lower + bin_width, count});
    }
    return bins;
}

std::vector<double> default_cutoffs(const std::vector<Event>& events) {
    if (events.empty()) {
        return {};
    }
    double min_mag = std::numeric_limits<double>::infinity();
    double max_mag = -std::numeric_limits<double>::infinity();
    for (const auto& event : events) {
        min_mag = std::min(min_mag, event.magnitude);
        max_mag = std::max(max_mag, event.magnitude);
    }

    std::vector<double> cutoffs;
    for (double cutoff = std::floor(min_mag * 10.0) / 10.0;
         cutoff <= max_mag + 1e-9; cutoff += 0.1) {
        cutoffs.push_back(round_one_decimal(cutoff));
    }
    return cutoffs;
}

CutoffCounts cumulative_cutoff_counts(const std::vector<Event>& events,
                                      const std::vector<double>& cutoffs) {
    CutoffCounts counts;
    for (const double cutoff : cutoffs) {
        counts[cutoff] = 0;
        for (const auto& event : events) {
            if (event.magnitude >= cutoff) {
                ++counts[cutoff];
            }
        }
    }
    return counts;
}

YearlyCutoffCounts yearly_cutoff_counts(const std::vector<Event>& events,
                                        const std::vector<double>& cutoffs) {
    YearlyCutoffCounts counts;
    std::set<int> years;
    for (const auto& event : events) {
        years.insert(event.year);
    }
    for (const int year : years) {
        for (const double cutoff : cutoffs) {
            counts[{year, cutoff}] = 0;
        }
    }
    for (const auto& event : events) {
        for (const double cutoff : cutoffs) {
            if (event.magnitude >= cutoff) {
                ++counts[{event.year, cutoff}];
            }
        }
    }
    return counts;
}

}  // namespace diagnostics
