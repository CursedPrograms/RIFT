// rift_util.h - shared plumbing for the C++ fleet hub: command-line config,
// repo-root discovery, JSON output helpers, the dashboard template renderer
// and a tiny serial-port wrapper (Windows + Linux) for the Bluetooth heartbeat.
#pragma once

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#endif

#include <httplib.h>

#ifdef _WIN32
#include <iphlpapi.h>
#include <windows.h>
#include <ws2tcpip.h>
using sock_t = SOCKET;
#define RIFT_INVALID_SOCKET INVALID_SOCKET
#define rift_closesocket closesocket
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <termios.h>
#include <unistd.h>
using sock_t = int;
#define RIFT_INVALID_SOCKET (-1)
#define rift_closesocket close
#endif

#include <atomic>
#include <cctype>
#include <cstring>
#include <memory>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace rift {

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;

struct Config {
    std::string name = "RIFT";
    int port = 5000;
    std::string ip;
    fs::path root;
    double ttlSecs = 20;
    std::string noraHost = "192.168.4.1";
    int noraPort = 5000;
    double heartbeatSecs = 10;
    bool noHeartbeat = false;
    bool noMdns = false;
    bool noInternetShare = false;
    bool scan = false;
};

inline void netInit() {
#ifdef _WIN32
    static bool done = false;
    if (!done) {
        WSADATA wsa;
        WSAStartup(MAKEWORD(2, 2), &wsa);
        done = true;
    }
#endif
}

// Same trick as app.py's _get_ip(): "connect" a UDP socket (no traffic is
// sent) and read back which local address the OS would use.
inline std::string localIp() {
    netInit();
    for (const char* target : {"10.255.255.255", "8.8.8.8"}) {
        sock_t s = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (s == RIFT_INVALID_SOCKET) continue;
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(1);
        inet_pton(AF_INET, target, &addr.sin_addr);
        std::string result;
        if (::connect(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0) {
            sockaddr_in local{};
            socklen_t len = sizeof(local);
            if (::getsockname(s, reinterpret_cast<sockaddr*>(&local), &len) == 0) {
                char buf[INET_ADDRSTRLEN] = {};
                inet_ntop(AF_INET, &local.sin_addr, buf, sizeof(buf));
                result = buf;
            }
        }
        rift_closesocket(s);
        if (!result.empty() && result != "0.0.0.0") return result;
    }
    return "127.0.0.1";
}

inline fs::path exeDir() {
#ifdef _WIN32
    char buf[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, buf, MAX_PATH);
    return n ? fs::path(std::string(buf, n)).parent_path() : fs::path();
#else
    std::error_code ec;
    fs::path p = fs::read_symlink("/proc/self/exe", ec);
    return ec ? fs::path() : p.parent_path();
#endif
}

// Walks up from the executable / working directory until it finds the RIFT
// repo root (app.py next to templates/), so it works from PC App/App/bin, from
// the repo root, or from anywhere below it.
inline fs::path findRoot() {
    std::error_code ec;
    for (fs::path start : {exeDir(), fs::current_path(ec)}) {
        for (fs::path dir = fs::absolute(start, ec); !dir.empty(); dir = dir.parent_path()) {
            if (fs::exists(dir / "app.py", ec) && fs::exists(dir / "templates" / "index.html", ec)) return dir;
            if (dir == dir.parent_path()) break;
        }
    }
    return fs::current_path(ec);
}

inline const char* usage() {
    return "usage: network-discovery [--name RIFT] [--port 5000] [--nora-host 192.168.4.1] [--nora-port 5000]\n"
           "                         [--heartbeat-secs 10] [--ttl-secs 20] [--no-heartbeat] [--no-mdns]\n"
           "                         [--no-internet-share] [--root <repo>] [--scan]";
}

// Returns an empty string on success, else an error/usage message.
inline std::string parseConfig(int argc, char** argv, Config& cfg) {
    std::string root;
    for (int i = 1; i < argc; i++) {
        std::string flag = argv[i];
        while (!flag.empty() && flag[0] == '-') flag.erase(0, 1);
        auto value = [&](std::string& out) {
            if (i + 1 >= argc) return false;
            out = argv[++i];
            return true;
        };
        std::string v;
        auto number = [&](double& out) {
            if (!value(v)) return false;
            char* end = nullptr;
            out = std::strtod(v.c_str(), &end);
            return end && *end == 0 && !v.empty();
        };
        double n = 0;
        if (flag == "scan") cfg.scan = true;
        else if (flag == "no-mdns") cfg.noMdns = true;
        else if (flag == "no-heartbeat") cfg.noHeartbeat = true;
        else if (flag == "no-internet-share") cfg.noInternetShare = true;
        else if (flag == "help" || flag == "h") return usage();
        else if (flag == "name") { if (!value(cfg.name)) return "--name requires a value"; }
        else if (flag == "nora-host") { if (!value(cfg.noraHost)) return "--nora-host requires a value"; }
        else if (flag == "root") { if (!value(root)) return "--root requires a value"; }
        else if (flag == "port") { if (!number(n)) return "--port requires a number"; cfg.port = static_cast<int>(n); }
        else if (flag == "nora-port") { if (!number(n)) return "--nora-port requires a number"; cfg.noraPort = static_cast<int>(n); }
        else if (flag == "heartbeat-secs") { if (!number(cfg.heartbeatSecs)) return "--heartbeat-secs requires a number"; }
        else if (flag == "ttl-secs") { if (!number(cfg.ttlSecs)) return "--ttl-secs requires a number"; }
        else return std::string("unknown argument: ") + argv[i] + "\n" + usage();
    }
    cfg.ip = localIp();
    cfg.root = root.empty() ? findRoot() : fs::path(root);
    return "";
}

// ---- JSON output, built by hand so key order matches every other RIFT implementation ----

inline std::string jstr(const std::string& s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    return out + "\"";
}

inline std::string jobj(const std::vector<std::pair<std::string, std::string>>& fields) {
    std::string out = "{";
    for (size_t i = 0; i < fields.size(); i++) {
        if (i) out += ",";
        out += jstr(fields[i].first) + ":" + fields[i].second;
    }
    return out + "}";
}

inline std::string jarr(const std::vector<std::string>& items) {
    std::string out = "[";
    for (size_t i = 0; i < items.size(); i++) out += (i ? "," : "") + items[i];
    return out + "]";
}

inline std::string jnullOrStr(const std::string& s) { return s.empty() ? "null" : jstr(s); }

inline std::vector<std::string> splitCaps(const std::string& csv) {
    std::vector<std::string> caps;
    size_t start = 0;
    while (start <= csv.size()) {
        size_t comma = csv.find(',', start);
        std::string item = csv.substr(start, comma == std::string::npos ? std::string::npos : comma - start);
        if (!item.empty()) caps.push_back(item);
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return caps;
}

inline std::string trim(std::string s) {
    size_t a = s.find_first_not_of(" \t\r\n");
    size_t b = s.find_last_not_of(" \t\r\n");
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

inline std::string lower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// Fills in the handful of Jinja expressions templates/index.html uses:
// {{ this_name }}, {{ my_ip }}, {{ this_port }} and url_for('static', filename=...).
inline std::string renderTemplate(const std::string& tpl, const std::map<std::string, std::string>& vars) {
    std::string out;
    size_t pos = 0;
    while (true) {
        size_t start = tpl.find("{{", pos);
        if (start == std::string::npos) break;
        size_t end = tpl.find("}}", start + 2);
        if (end == std::string::npos) break;
        out.append(tpl, pos, start - pos);
        std::string expr = trim(tpl.substr(start + 2, end - start - 2));
        auto it = vars.find(expr);
        if (it != vars.end()) {
            out += it->second;
        } else if (expr.rfind("url_for(", 0) == 0 && expr.find("'static'") != std::string::npos) {
            size_t q1 = expr.find('\'', expr.find("filename"));
            size_t q2 = q1 == std::string::npos ? q1 : expr.find('\'', q1 + 1);
            if (q2 != std::string::npos) out += "/static/" + expr.substr(q1 + 1, q2 - q1 - 1);
            else out.append(tpl, start, end + 2 - start);
        } else {
            out.append(tpl, start, end + 2 - start);
        }
        pos = end + 2;
    }
    out.append(tpl, pos, std::string::npos);
    return out;
}

// ---- serial port (Bluetooth heartbeat to NORA) ----

class SerialPort {
public:
    ~SerialPort() { close(); }

    bool open(const std::string& name, int baud) {
        close();
#ifdef _WIN32
        std::string path = name.rfind("\\\\.\\", 0) == 0 ? name : "\\\\.\\" + name;
        h_ = CreateFileA(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (h_ == INVALID_HANDLE_VALUE) return false;
        DCB dcb{};
        dcb.DCBlength = sizeof(dcb);
        if (!GetCommState(h_, &dcb)) { close(); return false; }
        dcb.BaudRate = baud;
        dcb.ByteSize = 8;
        dcb.Parity = NOPARITY;
        dcb.StopBits = ONESTOPBIT;
        if (!SetCommState(h_, &dcb)) { close(); return false; }
        COMMTIMEOUTS to{};
        to.ReadTotalTimeoutConstant = 2000;
        to.WriteTotalTimeoutConstant = 2000;
        SetCommTimeouts(h_, &to);
        return true;
#else
        fd_ = ::open(name.c_str(), O_RDWR | O_NOCTTY);
        if (fd_ < 0) return false;
        termios tio{};
        if (tcgetattr(fd_, &tio) != 0) { close(); return false; }
        cfmakeraw(&tio);
        speed_t speed = baud == 9600 ? B9600 : baud == 57600 ? B57600 : B115200;
        cfsetispeed(&tio, speed);
        cfsetospeed(&tio, speed);
        tio.c_cflag |= (CLOCAL | CREAD);
        tcsetattr(fd_, TCSANOW, &tio);
        return true;
#endif
    }

    bool isOpen() const {
#ifdef _WIN32
        return h_ != INVALID_HANDLE_VALUE;
#else
        return fd_ >= 0;
#endif
    }

    void flushInput() {
#ifdef _WIN32
        if (isOpen()) PurgeComm(h_, PURGE_RXCLEAR);
#else
        if (isOpen()) tcflush(fd_, TCIFLUSH);
#endif
    }

    bool write(const std::string& data) {
#ifdef _WIN32
        DWORD n = 0;
        return isOpen() && WriteFile(h_, data.data(), static_cast<DWORD>(data.size()), &n, nullptr) && n == data.size();
#else
        return isOpen() && ::write(fd_, data.data(), data.size()) == static_cast<ssize_t>(data.size());
#endif
    }

    // Reads up to '\n' (not included); false on timeout or error.
    bool readLine(std::string& line, int timeoutMs) {
        line.clear();
        auto deadline = Clock::now() + std::chrono::milliseconds(timeoutMs);
        while (Clock::now() < deadline) {
            char c;
#ifdef _WIN32
            DWORD n = 0;
            if (!ReadFile(h_, &c, 1, &n, nullptr)) return false;
            if (n == 0) continue;
#else
            fd_set set;
            FD_ZERO(&set);
            FD_SET(fd_, &set);
            timeval tv{0, 100000};
            if (select(fd_ + 1, &set, nullptr, nullptr, &tv) <= 0) continue;
            if (::read(fd_, &c, 1) != 1) return false;
#endif
            if (c == '\n') return true;
            line += c;
        }
        return false;
    }

    void close() {
#ifdef _WIN32
        if (h_ != INVALID_HANDLE_VALUE) CloseHandle(h_);
        h_ = INVALID_HANDLE_VALUE;
#else
        if (fd_ >= 0) ::close(fd_);
        fd_ = -1;
#endif
    }

private:
#ifdef _WIN32
    HANDLE h_ = INVALID_HANDLE_VALUE;
#else
    int fd_ = -1;
#endif
};

// Sleeps up to `secs`, waking early when `stop` becomes true.
inline void interruptibleSleep(double secs, const std::atomic<bool>& stop) {
    auto end = Clock::now() + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(secs));
    while (!stop && Clock::now() < end) std::this_thread::sleep_for(std::chrono::milliseconds(50));
}

}  // namespace rift
