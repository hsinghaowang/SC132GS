#include "KernelSyncStatus.hpp"
#include <fstream>
#include <cstdlib>
#include <stdexcept>
#include <type_traits>
#include <unistd.h>
int main() {
    using namespace stereo_rtsp::sync;
    static_assert(!std::is_copy_constructible_v<StatusReader>);
    char path[] = "/tmp/sc132gs-status-XXXXXX";
    const int fd = mkstemp(path);
    if (fd < 0) return 1;
    close(fd);
    auto write = [&](const std::string& data) { std::ofstream file(path); file << data; };
    write("abi=2 trigger_hz=30 frame_step=1 locked_mask=3 startup_dropped=1 startup_end0=0 startup_end1=1 node0=0 node1=3 mode=2 running=1 session=7 pulses=123 skipped=0 cpu=7 error=0 error_count=0 source=fsync_host_reference\n");
    auto opened = StatusReader::open(path);
    unlink(path); // The reader owns the descriptor, independently of path lifetime.
    if (!std::holds_alternative<StatusReader>(opened)) return 1;
    auto reader = std::move(std::get<StatusReader>(opened));
    auto status = reader.read();
    if (!std::holds_alternative<Status>(status) || std::get<Status>(status).trigger_id != 123) return 1;
    auto sample=std::get<Status>(status);
    if (!sample.is_startup_buffer(3,0,7) || sample.is_startup_buffer(0,0,7) ||
        sample.is_startup_buffer(3,1,7) || sample.is_startup_buffer(3,0,8)) return 1;
    sample.driver_error=9;
    if (sample.is_startup_buffer(3,0,7)) return 1;
    if (!std::holds_alternative<Error>(std::get<StatusReader>(opened).read())) return 1;
    for (const auto& text : {"abi=1", "abi=2 mode=2", "abi=2 abi=2", "abi=2 mode=-1"}) {
        write(text);
        auto result = StatusReader::open(path);
        if (!std::holds_alternative<Error>(std::get<StatusReader>(result).read())) return 1;
        unlink(path);
    }
    const std::string suffix=" trigger_hz=30 frame_step=1 locked_mask=3 startup_dropped=1 startup_end0=0 startup_end1=1 node0=0 node1=3 mode=2 running=1 session=7 pulses=123 skipped=0 cpu=7 error=0 error_count=0 ";
    auto parse=[&](const std::string& text) {
        write(text);
        auto opened_file=StatusReader::open(path);
        unlink(path);
        return std::get<StatusReader>(opened_file).read();
    };
    auto shifted=parse("abi=3 timestamp_offset_ns=8196429"+suffix+"source=exposure_midpoint_estimate");
    if (!std::holds_alternative<Status>(shifted)) return 1;
    const auto& adjusted=std::get<Status>(shifted);
    if (adjusted.abi!=3 || adjusted.timestamp_offset_ns!=8196429 ||
        adjusted.source!=TimestampSource::exposure_midpoint_estimate || !adjusted.is_startup_buffer(3,0,7)) return 1;
    auto zero=parse("abi=3 timestamp_offset_ns=0"+suffix+"source=fsync_host_reference");
    if (!std::holds_alternative<Status>(zero) || std::get<Status>(zero).timestamp_offset_ns!=0) return 1;
    for (const auto& prefix : {
            "abi=3 timestamp_offset_ns=8196429", "abi=3 timestamp_offset_ns=16666667",
            "abi=3", "abi=3 timestamp_offset_ns=-1", "abi=5 timestamp_offset_ns=0"}) {
        auto bad=parse(std::string(prefix)+suffix+"source=fsync_host_reference");
        if (!std::holds_alternative<Error>(bad)) return 1;
    }
    if (!std::holds_alternative<Error>(parse("abi=3 timestamp_offset_ns=0"+suffix+"source=exposure_midpoint_estimate"))) return 1;
    auto start=parse("abi=4 timestamp_offset_ns=344903"+suffix+"source=exposure_start_estimate");
    if (!std::holds_alternative<Status>(start)) return 1;
    const auto& estimated=std::get<Status>(start);
    if (estimated.abi!=4 || estimated.timestamp_offset_ns!=344903 ||
        estimated.source!=TimestampSource::exposure_start_estimate || !estimated.is_startup_buffer(3,0,7)) return 1;
    if (!std::holds_alternative<Status>(parse("abi=4 timestamp_offset_ns=0"+suffix+"source=fsync_host_reference"))) return 1;
    for (const auto& text : {
            "abi=4 timestamp_offset_ns=0", "abi=4 timestamp_offset_ns=16666667",
            "abi=4 timestamp_offset_ns=-1", "abi=4"})
        if (!std::holds_alternative<Error>(parse(std::string(text)+suffix+"source=exposure_start_estimate"))) return 1;
    if (!std::holds_alternative<Error>(parse("abi=4 timestamp_offset_ns=344903"+suffix+"source=exposure_midpoint_estimate")) ||
        !std::holds_alternative<Error>(parse("abi=3 timestamp_offset_ns=344903"+suffix+"source=exposure_start_estimate"))) return 1;
    return std::holds_alternative<Error>(StatusReader::open(path)) ? 0 : 1;
}
