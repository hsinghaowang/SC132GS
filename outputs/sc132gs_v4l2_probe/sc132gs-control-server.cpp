// SPDX-License-Identifier: GPL-2.0-only
#include "sc132gs-control-server.hpp"
#include "sc132gs-ae.hpp"

#include <cerrno>
#include <cstring>
#include <poll.h>
#include <sstream>
#include <stdexcept>
#include <stop_token>
#include <string_view>
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>

namespace {

std::string report(const AutoExposure::Snapshot& state) {
    std::ostringstream out;
    out << "ok mode=" << (state.enabled ? "auto" : "off")
        << " target_percent=" << state.target_percent
        << " cam0_percent=" << state.cam0_percent
        << " cam1_percent=" << state.cam1_percent
        << " exposure_lines=" << state.exposure_lines
        << " gain_index=" << state.analogue_gain_index
        << " fps_x10=" << state.fps_x10
        << " max_exposure_lines=" << state.max_exposure_lines
        << " brightness_limited=" << (state.brightness_limited ? 1 : 0)
        << " error_errno=" << state.last_error << '\n';
    return out.str();
}

bool read_single_number(std::istringstream& input, int& value) {
    std::string trailing;
    return static_cast<bool>(input >> value) && !(input >> trailing);
}

std::string handle(AutoExposure& exposure, std::string_view request) {
    std::istringstream input{std::string(request)};
    std::string command;
    input >> command;
    try {
        if (command == "status") {
            std::string trailing;
            if (input >> trailing) {
                return "error code=invalid_argument\n";
            }
        } else if (command == "set-brightness") {
            int target;
            if (!read_single_number(input, target)) {
                return "error code=invalid_argument\n";
            }
            exposure.set_target(target);
        } else if (command == "auto-off") {
            std::string trailing;
            if (input >> trailing) {
                return "error code=invalid_argument\n";
            }
            exposure.disable();
        } else if (command == "max-exposure-us") {
            int microseconds;
            if (!read_single_number(input, microseconds)) {
                return "error code=invalid_argument\n";
            }
            exposure.set_max_exposure_us(microseconds);
        } else {
            return "error code=unknown_command\n";
        }
        return report(exposure.snapshot());
    } catch (const AeError& error) {
        std::ostringstream out;
        out << "error code="
            << (error.code == AeErrorCode::invalid_argument
                    ? "invalid_argument"
                    : "control_failure")
            << " errno=" << error.system_error << '\n';
        return out.str();
    } catch (const std::exception&) {
        return "error code=internal\n";
    }
}

} // namespace

struct ControlServer::Impl {
    AutoExposure& exposure;
    std::string path;
    int fd{-1};
    std::jthread worker;

    Impl(AutoExposure& exposure, std::string path)
        : exposure(exposure), path(std::move(path)) {
        if (this->path.size() >= sizeof(sockaddr_un::sun_path)) {
            throw std::runtime_error("control socket path too long");
        }
        fd = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
        if (fd < 0) {
            throw std::runtime_error("create control socket");
        }
        sockaddr_un address{};
        address.sun_family = AF_UNIX;
        std::strncpy(address.sun_path, this->path.c_str(),
                     sizeof(address.sun_path) - 1);

        // A previous process may have left the pathname behind.
        const int probe = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
        if (probe >= 0) {
            const bool active = ::connect(probe,
                reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0;
            ::close(probe);
            if (active) {
                ::close(fd);
                throw std::runtime_error("control socket already in use");
            }
        }
        ::unlink(this->path.c_str());
        if (::bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0 ||
            ::listen(fd, 4) < 0) {
            const int saved_errno = errno;
            ::close(fd);
            ::unlink(this->path.c_str());
            throw std::runtime_error("bind control socket: " +
                                     std::string(std::strerror(saved_errno)));
        }
        worker = std::jthread([this](std::stop_token stop) { run(stop); });
    }

    ~Impl() {
        worker.request_stop();
        worker.join();
        ::close(fd);
        ::unlink(path.c_str());
    }

    void run(std::stop_token stop) {
        while (!stop.stop_requested()) {
            pollfd descriptor{fd, POLLIN, 0};
            const int ready = ::poll(&descriptor, 1, 200);
            if (ready <= 0) {
                continue;
            }
            const int client = ::accept4(fd, nullptr, nullptr, SOCK_CLOEXEC);
            if (client < 0) {
                continue;
            }
            timeval timeout{1, 0};
            (void)::setsockopt(client, SOL_SOCKET, SO_RCVTIMEO,
                               &timeout, sizeof(timeout));
            char buffer[256]{};
            const ssize_t length = ::recv(client, buffer, sizeof(buffer) - 1, 0);
            if (length > 0) {
                const auto response = handle(
                    exposure, std::string_view(buffer, static_cast<std::size_t>(length)));
                (void)::send(client, response.data(), response.size(), MSG_NOSIGNAL);
            }
            ::close(client);
        }
    }
};

ControlServer::ControlServer(AutoExposure& exposure, std::string path)
    : impl_(std::make_unique<Impl>(exposure, std::move(path))) {}

ControlServer::~ControlServer() = default;
