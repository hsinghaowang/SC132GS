// SPDX-License-Identifier: GPL-2.0-only
#include <cerrno>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include "sc132gs-mode.hpp"

namespace {

constexpr std::string_view kSocketPath = "/run/sc132gs-ae.sock";

void usage() {
    std::cerr << "usage: sc132gs-ctl status | set-brightness <1..90> | "
                 "auto off | max-exposure-us <0..40000> | mode | set-mode hdr|linear\n";
}

class ModeProgress final : public sc132gs::ModeController::Observer {
public:
    void on_phase(sc132gs::ModeController::Phase phase) noexcept override {
        constexpr const char* names[]{"inspecting","stopping","configuring","starting",
                                     "verifying","persisting","restoring","ready"};
        std::cerr << "camera_mode phase=" << names[static_cast<int>(phase)] << '\n';
    }
};
const char* error_name(sc132gs::ModeErrorCode code) {
    using sc132gs::ModeErrorCode;
    switch (code) {
    case ModeErrorCode::none: return "none";
    case ModeErrorCode::busy: return "busy";
    case ModeErrorCode::permission: return "permission";
    case ModeErrorCode::device: return "device";
    case ModeErrorCode::service: return "service";
    case ModeErrorCode::verification: return "verification";
    case ModeErrorCode::persistence: return "persistence";
    case ModeErrorCode::internal: return "internal";
    }
    return "internal";
}
int mode_command(int argc, char** argv) {
    using namespace sc132gs;
    const bool changing=std::string_view(argv[1])=="set-mode";
    if ((changing && (argc!=3 || (std::string_view(argv[2])!="hdr" && std::string_view(argv[2])!="linear"))) ||
        (!changing && argc!=2)) { usage(); return 2; }
    try {
        LinuxModeBackend backend(changing);
        if (changing) {
            ModeProgress progress;
            ModeController controller(backend,&progress);
            const auto result=controller.set_mode(std::string_view(argv[2])=="hdr"?CameraMode::hdr:CameraMode::linear);
            if (!result.success) {
                std::cerr << "error code=mode_switch reason=" << error_name(result.error.code)
                          << " errno=" << result.error.system_error << " restored=" << result.restored
                          << " restore_reason=" << error_name(result.restore_error.code)
                          << " restore_errno=" << result.restore_error.system_error << '\n';
                return 1;
            }
        }
        const auto state=backend.inspect();
        std::cout << "ok camera_mode=" << (state.mode==CameraMode::hdr?"hdr":"linear")
                  << " fps=" << state.fps << " running=" << state.running << '\n';
        return 0;
    } catch (const ModeFailure& e) {
        std::cerr << "error code=mode_operation reason=" << error_name(e.error.code)
                  << " errno=" << e.error.system_error << '\n';
        return 1;
    } catch (const std::exception&) { std::cerr << "error code=mode_internal\n"; return 1; }
}

} // namespace

int main(int argc, char** argv) {
    if (argc>=2 && (std::string_view(argv[1])=="mode" || std::string_view(argv[1])=="set-mode"))
        return mode_command(argc,argv);
    std::string request;
    if (argc == 2 && std::string_view(argv[1]) == "status") {
        request = "status";
    } else if (argc == 3 &&
               std::string_view(argv[1]) == "set-brightness") {
        request = std::string("set-brightness ") + argv[2];
    } else if (argc == 3 && std::string_view(argv[1]) == "auto" &&
               std::string_view(argv[2]) == "off") {
        request = "auto-off";
    } else if (argc == 3 &&
               std::string_view(argv[1]) == "max-exposure-us") {
        request = std::string("max-exposure-us ") + argv[2];
    } else {
        usage();
        return 2;
    }

    const int fd = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        std::cerr << "error code=socket errno=" << errno << '\n';
        return 1;
    }
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    std::strncpy(address.sun_path, kSocketPath.data(),
                 sizeof(address.sun_path) - 1);
    if (::connect(fd, reinterpret_cast<sockaddr*>(&address),
                  sizeof(address)) < 0) {
        std::cerr << "error code=not_running errno=" << errno
                  << " detail=" << std::strerror(errno) << '\n';
        ::close(fd);
        return 1;
    }
    if (::send(fd, request.data(), request.size(), MSG_NOSIGNAL) < 0) {
        std::cerr << "error code=send errno=" << errno << '\n';
        ::close(fd);
        return 1;
    }
    char reply[512]{};
    const ssize_t count = ::recv(fd, reply, sizeof(reply) - 1, 0);
    ::close(fd);
    if (count <= 0) {
        std::cerr << "error code=no_reply\n";
        return 1;
    }
    std::cout.write(reply, count);
    return std::string_view(reply, static_cast<std::size_t>(count))
                   .starts_with("ok ")
               ? 0
               : 1;
}
