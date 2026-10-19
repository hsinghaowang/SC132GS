#include "KernelSyncStatus.hpp"
#include <cerrno>
#include <charconv>
#include <fcntl.h>
#include <limits>
#include <map>
#include <sstream>
#include <unistd.h>

namespace stereo_rtsp::sync {
bool Status::is_startup_buffer(std::uint32_t node, std::uint32_t sequence,
                              std::uint64_t expected_session) const noexcept {
    if ((abi != 2 && abi != 3 && abi != 4) || mode != 2 || !running || driver_error || session != expected_session)
        return false;
    for (unsigned eye=0; eye<2; ++eye)
        if (node == video_nodes[eye] && sequence < startup_sequence_end[eye]) return true;
    return false;
}
struct StatusReader::Impl {
    explicit Impl(int descriptor) : fd(descriptor) {}
    ~Impl() { if (fd >= 0) ::close(fd); }
    int fd;
};
StatusReader::StatusReader(std::unique_ptr<Impl> impl) noexcept : impl_(std::move(impl)) {}
StatusReader::~StatusReader() = default;
StatusReader::StatusReader(StatusReader&&) noexcept = default;
StatusReader& StatusReader::operator=(StatusReader&&) noexcept = default;
std::variant<StatusReader, Error> StatusReader::open(const std::string& path) {
    const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return Error{ErrorCode::io, errno};
    // Acquire ownership before constructing the public object.
    try { return StatusReader(std::make_unique<Impl>(fd)); }
    catch (...) { ::close(fd); throw; }
}
std::variant<Status, Error> StatusReader::read() const {
    if (!impl_) return Error{ErrorCode::io, EBADF};
    if (::lseek(impl_->fd, 0, SEEK_SET) < 0) return Error{ErrorCode::io, errno};
    char buffer[1024];
    ssize_t size;
    do { size = ::read(impl_->fd, buffer, sizeof(buffer)); } while (size < 0 && errno == EINTR);
    if (size < 0) return Error{ErrorCode::io, errno};
    const Error malformed{ErrorCode::malformed_status};
    if (!size || size == static_cast<ssize_t>(sizeof(buffer))) return malformed;
    std::istringstream input(std::string(buffer, static_cast<std::size_t>(size)));
    std::map<std::string, std::string> fields;
    for (std::string token; input >> token;) {
        const auto at = token.find('=');
        if (at == std::string::npos || !fields.emplace(token.substr(0, at), token.substr(at+1)).second)
            return malformed;
    }
    const auto number = [&](const char* key, std::uint64_t& value) {
        const auto it = fields.find(key);
        if (it == fields.end()) return false;
        const auto& text = it->second;
        const auto result = std::from_chars(text.data(), text.data()+text.size(), value);
        return result.ec == std::errc{} && result.ptr == text.data()+text.size();
    };
    Status status;
    std::uint64_t abi{}, mode{}, running{}, error{};
    if (!number("abi", abi)) return malformed;
    if (abi != 2 && abi != 3 && abi != 4) return Error{ErrorCode::unsupported_abi};
    if (!number("mode", mode) || mode > 2 || !number("running", running) || running > 1 ||
        !number("error", error) || error > std::numeric_limits<std::uint32_t>::max() ||
        !number("session", status.session) || !number("pulses", status.trigger_id) ||
        !number("skipped", status.skipped) || !number("error_count", status.error_count)) return malformed;
    if (abi >= 3 && (!number("timestamp_offset_ns", status.timestamp_offset_ns) ||
                     status.timestamp_offset_ns > 16'666'666)) return malformed;
    if (fields["source"] == "fsync_host_reference" && status.timestamp_offset_ns == 0)
        status.source = TimestampSource::fsync_host_reference;
    else if (abi == 3 && mode == 2 && status.timestamp_offset_ns > 0 &&
             fields["source"] == "exposure_midpoint_estimate")
        status.source = TimestampSource::exposure_midpoint_estimate;
    else if (abi == 4 && mode == 2 && status.timestamp_offset_ns > 0 &&
             fields["source"] == "exposure_start_estimate")
        status.source = TimestampSource::exposure_start_estimate;
    else return malformed;
    std::uint64_t hz{}, step{}, mask{};
    if (!number("trigger_hz", hz) || hz != 30 || !number("frame_step", step) || step != 1)
        return malformed;
    if (!number("locked_mask", mask) || mask > 3 || !number("startup_dropped", status.startup_dropped))
        return malformed;
    status.locked_mask = static_cast<std::uint32_t>(mask);
    for (unsigned eye=0; eye<2; ++eye) {
        std::uint64_t node{}, end{};
        const auto suffix=std::to_string(eye);
        if (!number(("node"+suffix).c_str(), node) || node>std::numeric_limits<std::uint32_t>::max() ||
            !number(("startup_end"+suffix).c_str(), end) || end>std::numeric_limits<std::uint32_t>::max())
            return malformed;
        status.video_nodes[eye]=static_cast<std::uint32_t>(node);
        status.startup_sequence_end[eye]=static_cast<std::uint32_t>(end);
    }
    status.abi = static_cast<std::uint32_t>(abi); status.trigger_hz = 30; status.frame_step = 1;
    status.mode = static_cast<std::uint32_t>(mode);
    status.running = running != 0; status.driver_error = static_cast<std::uint32_t>(error);
    return status;
}
}
