// Diagnostic: hold the observed TLMM FSYNC lines as inputs; generate no pulses.
#include <linux/gpio.h>
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {
volatile std::sig_atomic_t stopped = 0;
void stop(int) noexcept { stopped = 1; }
enum class ErrorCode { Open, Request };
struct Error { ErrorCode code; int number; };
class File final {
public:
    explicit File(int fd) noexcept : fd_(fd) {}
    ~File() { if (fd_ >= 0) ::close(fd_); }
    File(const File&) = delete;
    File& operator=(const File&) = delete;
    int get() const noexcept { return fd_; }
private:
    int fd_;
};
}

int main() {
    try {
        File chip(::open("/dev/gpiochip4", O_RDONLY | O_CLOEXEC));
        if (chip.get() < 0) throw Error{ErrorCode::Open, errno};
        gpio_v2_line_request request{};
        request.offsets[0] = 18;
        request.offsets[1] = 19;
        request.num_lines = 2;
        request.config.flags = GPIO_V2_LINE_FLAG_INPUT;
        std::strncpy(request.consumer, "hdr-no-fsync-input", sizeof(request.consumer)-1);
        if (::ioctl(chip.get(), GPIO_V2_GET_LINE_IOCTL, &request) < 0)
            throw Error{ErrorCode::Request, errno};
        File lines(request.fd);
        std::signal(SIGTERM, stop);
        std::signal(SIGINT, stop);
        std::puts("FSYNC source disabled: gpiochip4 18,19 held as inputs; no output writes");
        std::fflush(stdout);
        while (!stopped) ::usleep(100000);
        return 0;
    } catch (const Error& error) {
        std::fprintf(stderr, "error code=%d errno=%d\n", int(error.code), error.number);
        return 1;
    }
}
