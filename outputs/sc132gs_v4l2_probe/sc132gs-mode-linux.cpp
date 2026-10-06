// SPDX-License-Identifier: GPL-2.0-only
#include "sc132gs-mode.hpp"
#include <linux/videodev2.h>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <filesystem>
#include <map>
#include <poll.h>
#include <sstream>
#include <string>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace sc132gs {
namespace {
constexpr const char* unit = "sc132gs-hdr-rtsp.service";
constexpr const char* script = "/home/ubuntu/stereo-h265-rtsp/run-stereo-rtsp.sh";
constexpr const char* mode_config = "/etc/modprobe.d/sc132gs-external-trigger.conf";
constexpr const char* stream_config = "/etc/sc132gs-stereo.env";
struct Fd {
    int value{-1};
    explicit Fd(int v) : value(v) {}
    ~Fd() { if (value >= 0) ::close(value); }
    Fd(const Fd&) = delete;
    Fd& operator=(const Fd&) = delete;
};
[[noreturn]] void fail(ModeErrorCode code, int value = errno) { throw ModeFailure({code, value}); }
std::string trim(std::string text) {
    const auto first = text.find_first_not_of(" \t\r\n");
    return first == std::string::npos ? "" : text.substr(first, text.find_last_not_of(" \t\r\n")-first+1);
}
struct Command { int status; std::string output; };
Command run(std::vector<std::string> args) {
    int pipefd[2];
    if (::pipe2(pipefd, O_CLOEXEC) < 0) fail(ModeErrorCode::service);
    Fd input(pipefd[0]), output(pipefd[1]);
    std::vector<char*> argv;
    for (auto& a : args) argv.push_back(a.data());
    argv.push_back(nullptr);
    const auto pid = ::fork();
    if (pid < 0) fail(ModeErrorCode::service);
    if (pid == 0) {
        ::setpgid(0, 0);
        ::dup2(output.value, STDOUT_FILENO);
        ::dup2(output.value, STDERR_FILENO);
        ::execvp(argv[0], argv.data());
        ::_exit(127);
    }
    ::setpgid(pid, pid);
    ::close(output.value); output.value = -1;
    std::string text;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
    bool ended = false;
    while (!ended) {
        if (std::chrono::steady_clock::now() >= deadline) {
            ::kill(-pid, SIGKILL);
            while (::waitpid(pid, nullptr, 0) < 0 && errno == EINTR) {}
            fail(ModeErrorCode::service, ETIMEDOUT);
        }
        pollfd descriptor{input.value, POLLIN | POLLHUP, 0};
        const int ready = ::poll(&descriptor, 1, 100);
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0) { ::kill(-pid, SIGKILL); ::waitpid(pid, nullptr, 0); fail(ModeErrorCode::service); }
        if (ready > 0) {
            std::array<char, 4096> buffer;
            const auto count = ::read(input.value, buffer.data(), buffer.size());
            if (count > 0) text.append(buffer.data(), count);
            else if (count == 0) ended = true;
            else if (errno != EINTR) { ::kill(-pid, SIGKILL); ::waitpid(pid, nullptr, 0); fail(ModeErrorCode::service); }
        }
    }
    int status;
    while (::waitpid(pid, &status, 0) < 0) if (errno != EINTR) fail(ModeErrorCode::service);
    return {WIFEXITED(status) ? WEXITSTATUS(status) : 128, trim(text)};
}
std::string checked(std::vector<std::string> args) {
    auto result = run(std::move(args));
    if (result.status != 0) fail(ModeErrorCode::service, result.status);
    return result.output;
}
std::string request(const char* command) {
    Fd fd(::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0));
    if (fd.value < 0) fail(ModeErrorCode::service);
    sockaddr_un address{}; address.sun_family = AF_UNIX;
    std::strcpy(address.sun_path, "/run/sc132gs-ae.sock");
    timeval timeout{1, 0};
    ::setsockopt(fd.value, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    ::setsockopt(fd.value, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    if (::connect(fd.value, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0)
        fail(ModeErrorCode::service);
    if (::send(fd.value, command, std::strlen(command), MSG_NOSIGNAL) < 0) fail(ModeErrorCode::service);
    std::array<char, 1024> text{};
    const auto count = ::recv(fd.value, text.data(), text.size(), 0);
    if (count <= 0) fail(ModeErrorCode::service);
    std::string result(text.data(), count);
    if (!result.starts_with("ok ")) fail(ModeErrorCode::service, EPROTO);
    return result;
}
std::map<std::string, std::string> fields(const std::string& text) {
    std::istringstream input(text); std::string token; std::map<std::string,std::string> result;
    while (input >> token) {
        const auto equal = token.find('=');
        if (equal != std::string::npos) result[token.substr(0,equal)] = token.substr(equal+1);
    }
    return result;
}
int number(const std::map<std::string,std::string>& values, const char* key) {
    const auto found = values.find(key);
    if (found == values.end()) fail(ModeErrorCode::verification, EPROTO);
    try { return std::stoi(found->second); } catch (...) { fail(ModeErrorCode::verification, EPROTO); }
}
void atomic_write(const char* path, const std::string& text) {
    const std::string temporary=std::string(path)+".tmp."+std::to_string(::getpid());
    Fd fd(::open(temporary.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0644));
    if (fd.value<0) fail(ModeErrorCode::persistence);
    std::size_t offset=0;
    while (offset<text.size()) {
        const auto count=::write(fd.value,text.data()+offset,text.size()-offset);
        if (count<0 && errno==EINTR) continue;
        if (count<=0) { const auto error=count==0?EIO:errno; ::unlink(temporary.c_str()); fail(ModeErrorCode::persistence,error); }
        offset+=count;
    }
    if (::fsync(fd.value)<0 || ::rename(temporary.c_str(),path)<0) {
        const auto error=errno; ::unlink(temporary.c_str()); fail(ModeErrorCode::persistence,error);
    }
}
std::array<std::string,2> sensors() {
    const auto media = checked({"/usr/local/sbin/sc132gs-discover", "media"});
    const auto topology = checked({"media-ctl", "-d", media, "-p"});
    std::array<std::string,2> names;
    std::istringstream input(topology); std::string line;
    while (std::getline(input,line)) {
        const auto begin=line.find(": sc132gs ");
        if (!line.starts_with("- entity ") || begin==std::string::npos) continue;
        const auto end=line.find(" (",begin);
        auto name=line.substr(begin+2,end-begin-2);
        if (name.ends_with("-0032")) names[0]=name;
        if (name.ends_with("-0030")) names[1]=name;
    }
    for (auto& name:names) {
        if (name.empty()) fail(ModeErrorCode::device, ENODEV);
        name=checked({"media-ctl","-d",media,"-e",name});
    }
    return names;
}
int get(const std::string& path) {
    Fd fd(::open(path.c_str(), O_RDWR | O_CLOEXEC));
    if (fd.value < 0) fail(ModeErrorCode::device);
    v4l2_control value{}; value.id=V4L2_CID_WIDE_DYNAMIC_RANGE;
    if (::ioctl(fd.value, VIDIOC_G_CTRL, &value)<0) fail(ModeErrorCode::device);
    return value.value;
}
void set(const std::string& path, CameraMode mode) {
    Fd fd(::open(path.c_str(), O_RDWR | O_CLOEXEC));
    if (fd.value<0) fail(ModeErrorCode::device);
    v4l2_control value{}; value.id=V4L2_CID_WIDE_DYNAMIC_RANGE; value.value=mode==CameraMode::hdr;
    if (::ioctl(fd.value, VIDIOC_S_CTRL, &value)<0) fail(ModeErrorCode::device);
}
} // namespace
struct LinuxModeBackend::Impl {
    Fd lock{-1};
    bool writable;
    bool auto_exposure{true};
    std::map<std::string,std::string> environment;
    std::string original_config;
    void require_writable() const {
        if (!writable) fail(ModeErrorCode::permission, EPERM);
    }
    explicit Impl(bool write):writable(write) {
        if (write) {
            if (::geteuid()!=0) fail(ModeErrorCode::permission, EPERM);
            lock.value=::open("/run/sc132gs-mode.lock",O_CREAT|O_RDWR|O_CLOEXEC,0600);
            if (lock.value<0) fail(ModeErrorCode::busy);
            if (::flock(lock.value,LOCK_EX|LOCK_NB)<0) fail(ModeErrorCode::busy);
        }
    }
};
LinuxModeBackend::LinuxModeBackend(bool writable):impl_(std::make_unique<Impl>(writable)) {}
LinuxModeBackend::~LinuxModeBackend()=default;
LinuxModeBackend::LinuxModeBackend(LinuxModeBackend&&) noexcept=default;
LinuxModeBackend& LinuxModeBackend::operator=(LinuxModeBackend&&) noexcept=default;
ModeState LinuxModeBackend::inspect() {
    // This board deliberately blacklists automatic CAMSS loading. A command
    // after reboot must bring up the receiver before discovering its graph.
    // Loading an already present module is harmless; never unload it here.
    if (impl_->writable) checked({"modprobe", "qcom_camss"});
    const auto paths=sensors();
    const int a=get(paths[0]), b=get(paths[1]);
    if (a!=b) fail(ModeErrorCode::verification, EPROTO);
    ModeState state{a?CameraMode::hdr:CameraMode::linear,a?30:60,false,true};
    state.running=run({"systemctl","is-active","--quiet",unit}).status==0;
    const auto unit_environment=run({"systemctl","show",unit,"--property=Environment","--value"});
    std::ifstream saved(stream_config);
    const std::string saved_text{std::istreambuf_iterator<char>(saved),{}};
    impl_->environment=fields(saved_text);
    if (unit_environment.status==0)
        for (const auto& [key,value]:fields(unit_environment.output)) impl_->environment[key]=value;
    if (auto f=impl_->environment.find("FPS"); f!=impl_->environment.end()) state.fps=std::stoi(f->second);
    if (!impl_->writable) return state;
    if (state.running) {
        std::map<std::string,std::string> status;
        for (int attempt=0;;++attempt) {
            try { status=fields(request("status")); break; }
            catch (const ModeFailure&) {
                if (attempt==11) throw;
                std::this_thread::sleep_for(std::chrono::milliseconds(250));
            }
        }
        impl_->environment["BRIGHTNESS"]=std::to_string(number(status,"target_percent"));
        state.auto_exposure=status.at("mode")=="auto";
    } else if (auto f=impl_->environment.find("AUTO_EXPOSURE"); f!=impl_->environment.end()) {
        state.auto_exposure=f->second=="1";
    }
    impl_->auto_exposure=state.auto_exposure;
    std::ifstream config(mode_config);
    if (!config) fail(ModeErrorCode::persistence, ENOENT);
    impl_->original_config.assign(std::istreambuf_iterator<char>(config),{});
    // Do not interrupt a stream driven by a legacy read-only driver.
    for (const auto& path:paths) {
        Fd fd(::open(path.c_str(),O_RDWR|O_CLOEXEC));
        v4l2_queryctrl query{}; query.id=V4L2_CID_WIDE_DYNAMIC_RANGE;
        if (fd.value<0 || ::ioctl(fd.value,VIDIOC_QUERYCTRL,&query)<0 ||
            (query.flags&V4L2_CTRL_FLAG_READ_ONLY)) fail(ModeErrorCode::device, EOPNOTSUPP);
    }
    return state;
}
void LinuxModeBackend::stop() {
    impl_->require_writable();
    const auto result=run({"systemctl","stop",unit});
    if (result.status!=0 && run({"systemctl","is-active","--quiet",unit}).status==0)
        fail(ModeErrorCode::service,result.status);
    (void)run({"systemctl","reset-failed",unit});
    // The board VPU driver can retain closed firmware sessions. Reset only
    // after the capture unit releases it and every codec endpoint is idle.
    // Discover by driver identity rather than fixed /dev/video numbers.
    std::vector<std::string> users{"fuser", "-s"};
    for (const auto& entry : std::filesystem::directory_iterator("/sys/class/video4linux")) {
        std::error_code error;
        const auto driver = std::filesystem::canonical(entry.path()/"device/driver", error);
        if (!error && driver.filename()=="msm_vidc_v4l2")
            users.push_back("/dev/"+entry.path().filename().string());
    }
    if (users.size()>2) {
        const auto result=run(std::move(users));
        if (result.status==0) fail(ModeErrorCode::busy,EBUSY);
        if (result.status!=1) fail(ModeErrorCode::service,result.status);
        checked({"modprobe","-r","iris_vpu"});
    }
    checked({"modprobe","iris_vpu"});
}
void LinuxModeBackend::configure(CameraMode mode) {
    impl_->require_writable();
    const auto paths=sensors();
    for (const auto& path:paths) set(path,mode);
    for (const auto& path:paths) if (get(path)!=(mode==CameraMode::hdr)) fail(ModeErrorCode::verification, EIO);
}
void LinuxModeBackend::start(const ModeState& state) {
    impl_->require_writable();
    checked({"/usr/local/sbin/configure-sc132gs-dual-pipeline"});
    std::vector<std::string> args{"systemd-run","--unit=sc132gs-hdr-rtsp","--property=Restart=on-failure"};
    for (const char* name:{"BIND","PORT","DOWNSCALE","BRIGHTNESS"}) {
        auto f=impl_->environment.find(name);
        if (f!=impl_->environment.end()) args.push_back("--setenv="+std::string(name)+"="+f->second);
    }
    args.push_back("--setenv=FPS="+std::to_string(state.fps));
    args.push_back("--setenv=AUTO_EXPOSURE="+std::to_string(state.auto_exposure));
    args.insert(args.end(),{"/bin/bash",script});
    checked(std::move(args));
}
void LinuxModeBackend::verify(const ModeState& state) {
    impl_->require_writable();
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
    int consecutive=0;
    while (std::chrono::steady_clock::now()<deadline) {
        try {
            const auto paths=sensors();
            const auto status=fields(request("status"));
            if (get(paths[0])!=(state.mode==CameraMode::hdr) || get(paths[1])!=get(paths[0]))
                fail(ModeErrorCode::verification, EPROTO);
            const int fps=number(status,"fps_x10");
            const auto ae_mode=status.find("mode");
            if (number(status,"hdr_enabled")==int(state.mode==CameraMode::hdr) &&
                number(status,"error_errno")==0 && fps>=state.fps*9 && fps<=state.fps*11 &&
                ae_mode!=status.end() && ae_mode->second==(state.auto_exposure?"auto":"off")) {
                if (++consecutive==3) {
                    return;
                }
            } else consecutive=0;
        } catch (const ModeFailure&) { consecutive=0; }
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
    fail(ModeErrorCode::verification,ETIMEDOUT);
}
void LinuxModeBackend::persist(CameraMode mode) {
    impl_->require_writable();
    auto text=impl_->original_config;
    const auto pos=text.find("hdr=");
    if (pos==std::string::npos || pos+4>=text.size() || (text[pos+4]!='0' && text[pos+4]!='1'))
        fail(ModeErrorCode::persistence,EINVAL);
    text[pos+4]=mode==CameraMode::hdr?'1':'0';
    std::string settings;
    for (const char* name:{"BIND","PORT","DOWNSCALE","BRIGHTNESS"})
        if (auto f=impl_->environment.find(name); f!=impl_->environment.end())
            settings+=std::string(name)+"="+f->second+"\n";
    settings+="AUTO_EXPOSURE="+std::to_string(impl_->auto_exposure)+"\n";
    // Common stream preferences do not select a sensor mode; preserve them first.
    atomic_write(stream_config,settings);
    atomic_write(mode_config,text);
}
} // namespace sc132gs
