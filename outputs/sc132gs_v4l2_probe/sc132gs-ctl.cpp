// SPDX-License-Identifier: GPL-2.0-only
#include <cerrno>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace {

constexpr std::string_view kSocketPath = "/run/sc132gs-ae.sock";

void usage() {
    std::cerr << "usage: sc132gs-ctl status | set-brightness <1..90> | "
                 "auto off | max-exposure-us <0..40000>\n";
}

} // namespace

int main(int argc, char** argv) {
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
