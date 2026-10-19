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
    return std::holds_alternative<Error>(StatusReader::open(path)) ? 0 : 1;
}
