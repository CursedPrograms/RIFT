// rift_hub.h - the fleet hub's moving parts: the registry, mDNS peers, the
// NORA fleet-authority heartbeat, and the NetworkManager internet share.
// C++ counterparts of app.py's _fleet dict, _PeerListener/_start_zeroconf,
// Fleet/register.py + Fleet/bt_link.py, and Fleet/internet_share.py.
#pragma once

#include <cctype>
#include <condition_variable>

#include "rift_util.h"

namespace rift {

// ---------------------------------------------------------------------
// Registry: robots/managers that have called POST /register, expiring after
// the TTL unless they keep heartbeating.
// ---------------------------------------------------------------------

struct Robot {
    std::string name, ip, type;
    std::vector<std::string> capabilities;
};

class Registry {
public:
    explicit Registry(double ttlSecs) : ttl_(ttlSecs) {}

    void add(const std::string& name, const std::string& ip, const std::string& type,
             const std::vector<std::string>& caps, Clock::time_point now = Clock::now()) {
        std::lock_guard<std::mutex> lock(mu_);
        if (!members_.count(name)) order_.push_back(name);  // re-registering keeps its position, like a Python dict
        members_[name] = {Robot{name, ip, type, caps}, now};
    }

    // The live roster, dropping anything not heard from within the TTL.
    std::vector<Robot> robots(Clock::time_point now = Clock::now()) {
        std::lock_guard<std::mutex> lock(mu_);
        std::vector<std::string> live;
        std::vector<Robot> roster;
        for (const auto& name : order_) {
            auto& m = members_[name];
            if (std::chrono::duration<double>(now - m.second).count() > ttl_) {
                members_.erase(name);
                continue;
            }
            live.push_back(name);
            roster.push_back(m.first);
        }
        order_ = live;
        return roster;
    }

private:
    double ttl_;
    std::mutex mu_;
    std::map<std::string, std::pair<Robot, Clock::time_point>> members_;
    std::vector<std::string> order_;
};

// name -> "http://ip:port" for every peer seen over mDNS.
class Peers {
public:
    void set(const std::string& name, const std::string& url) {
        std::lock_guard<std::mutex> lock(mu_);
        items_[name] = url;
    }
    void remove(const std::string& name) {
        std::lock_guard<std::mutex> lock(mu_);
        items_.erase(name);
    }
    std::map<std::string, std::string> snapshot() {
        std::lock_guard<std::mutex> lock(mu_);
        return items_;
    }

private:
    std::mutex mu_;
    std::map<std::string, std::string> items_;
};

// ---------------------------------------------------------------------
// NORA fleet-authority heartbeat, over HTTP/WiFi (default) or a Bluetooth
// serial link. While RIFT keeps heartbeating, NORA defers her /robots
// response to point at RIFT; if it stops, the registration simply expires on
// her side.
// ---------------------------------------------------------------------

class Authority {
public:
    explicit Authority(Config cfg) : cfg_(std::move(cfg)) {}
    ~Authority() { stop(); }

    std::pair<std::string, std::string> state() {
        std::lock_guard<std::mutex> lock(mu_);
        return {mode_, btPort_};
    }

    // Retires the current heartbeat (if any) and starts one on the given transport.
    void restart(const std::string& mode, const std::string& btPort) {
        std::lock_guard<std::mutex> lock(mu_);
        stopLocked();
        mode_ = mode;
        btPort_ = btPort;
        if (cfg_.noHeartbeat) return;
        stop_ = std::make_shared<std::atomic<bool>>(false);
        auto stop = stop_;
        thread_ = std::thread([this, mode, btPort, stop] { loop(mode, btPort, stop); });
    }

    void stop() {
        std::lock_guard<std::mutex> lock(mu_);
        stopLocked();
    }

private:
    static constexpr const char* kCaps = "fleet_management,monitoring";

    void stopLocked() {
        if (stop_) *stop_ = true;
        if (thread_.joinable()) thread_.join();
        stop_.reset();
    }

    void announceWifi() {
        httplib::Client client(cfg_.noraHost, cfg_.noraPort);
        client.set_connection_timeout(2, 0);
        client.set_read_timeout(2, 0);
        client.set_write_timeout(2, 0);
        // NORA may not be reachable yet (booting, or not on her AP) - keep retrying.
        client.Post("/register", httplib::Params{{"name", cfg_.name}, {"type", "fleet_manager"}, {"capabilities", kCaps}});
    }

    // The fleet-registration half of NORA's Bluetooth protocol: send
    // "H<name>:<cap1,cap2>\n", she replies "OK\n" or "ERR\n".
    bool announceBluetooth(SerialPort& port, const std::string& btPort) {
        if (!port.isOpen() && !port.open(btPort, 115200)) return false;
        port.flushInput();
        if (!port.write("H" + cfg_.name + ":" + kCaps + "\n")) return false;
        std::string reply;
        return port.readLine(reply, 2000) && trim(reply) == "OK";
    }

    void loop(const std::string& mode, const std::string& btPort, std::shared_ptr<std::atomic<bool>> stop) {
        SerialPort port;
        while (!*stop) {
            if (mode == "bluetooth") {
                if (!announceBluetooth(port, btPort)) port.close();  // drop the link and reopen next round
            } else {
                announceWifi();
            }
            interruptibleSleep(cfg_.heartbeatSecs, *stop);
        }
    }

    Config cfg_;
    std::mutex mu_;
    std::string mode_ = "wifi", btPort_;
    std::shared_ptr<std::atomic<bool>> stop_;
    std::thread thread_;
};

// ---------------------------------------------------------------------
// Zeroconf: publish this instance as _rift._tcp and watch for other RIFT
// instances and ComCentre (_flask-link._tcp) - browsing both is what lets
// DREAM show up in this dashboard without ComCentre knowing anything about
// RIFT. A small responder + browser over multicast UDP (224.0.0.251:5353)
// using just the DNS wire format: PTR (service -> instance), SRV (instance ->
// host + port), TXT and A (host -> address). No Avahi/Bonjour needed, so it
// behaves the same on Windows and Linux.
// ---------------------------------------------------------------------

class Mdns {
public:
    Mdns(Config cfg, Peers& peers) : cfg_(std::move(cfg)), peers_(peers) {}
    ~Mdns() { stop(); }

    // Returns an empty string on success, else an error message.
    std::string start() {
        netInit();
        sock_ = ::socket(AF_INET, SOCK_DGRAM, 0);
        if (sock_ == RIFT_INVALID_SOCKET) return "socket() failed";

        int yes = 1;
        setsockopt(sock_, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&yes), sizeof(yes));
#ifdef SO_REUSEPORT
        setsockopt(sock_, SOL_SOCKET, SO_REUSEPORT, reinterpret_cast<const char*>(&yes), sizeof(yes));
#endif
        sockaddr_in bindAddr{};
        bindAddr.sin_family = AF_INET;
        bindAddr.sin_port = htons(5353);
        bindAddr.sin_addr.s_addr = htonl(INADDR_ANY);
        if (::bind(sock_, reinterpret_cast<sockaddr*>(&bindAddr), sizeof(bindAddr)) != 0) {
            rift_closesocket(sock_);
            return "could not bind UDP port 5353";
        }

        in_addr local{};
        inet_pton(AF_INET, cfg_.ip.c_str(), &local);
        ip_mreq mreq{};
        inet_pton(AF_INET, "224.0.0.251", &mreq.imr_multiaddr);
        mreq.imr_interface = local;
        if (setsockopt(sock_, IPPROTO_IP, IP_ADD_MEMBERSHIP, reinterpret_cast<const char*>(&mreq), sizeof(mreq)) != 0) {
            mreq.imr_interface.s_addr = htonl(INADDR_ANY);
            setsockopt(sock_, IPPROTO_IP, IP_ADD_MEMBERSHIP, reinterpret_cast<const char*>(&mreq), sizeof(mreq));
        }
        setsockopt(sock_, IPPROTO_IP, IP_MULTICAST_IF, reinterpret_cast<const char*>(&local), sizeof(local));
        unsigned char loop = 1, ttl = 255;
        setsockopt(sock_, IPPROTO_IP, IP_MULTICAST_LOOP, reinterpret_cast<const char*>(&loop), sizeof(loop));
        setsockopt(sock_, IPPROTO_IP, IP_MULTICAST_TTL, reinterpret_cast<const char*>(&ttl), sizeof(ttl));
#ifdef _WIN32
        DWORD timeout = 500;
        setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
#else
        timeval tv{0, 500000};
        setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif
        running_ = true;
        recvThread_ = std::thread([this] { receiveLoop(); });
        queryThread_ = std::thread([this] { queryLoop(); });
        return "";
    }

    void stop() {
        if (!running_.exchange(false)) return;
        send(announcePacket(0));  // goodbye
        if (recvThread_.joinable()) recvThread_.join();
        if (queryThread_.joinable()) queryThread_.join();
        rift_closesocket(sock_);
    }

private:
    using Bytes = std::vector<uint8_t>;

    static constexpr uint16_t T_A = 1, T_PTR = 12, T_TXT = 16, T_SRV = 33, T_ANY = 255;
    static constexpr uint16_t CLASS_IN = 1, CACHE_FLUSH = 0x8000;

    static void u16(Bytes& b, uint16_t v) { b.push_back(v >> 8); b.push_back(v & 0xff); }
    static void u32(Bytes& b, uint32_t v) { u16(b, v >> 16); u16(b, v & 0xffff); }

    static void name(Bytes& b, const std::string& n) {
        size_t start = 0;
        std::string s = n;
        while (!s.empty() && s.back() == '.') s.pop_back();
        while (start <= s.size() && !s.empty()) {
            size_t dot = s.find('.', start);
            std::string label = s.substr(start, dot == std::string::npos ? std::string::npos : dot - start);
            b.push_back(static_cast<uint8_t>(label.size()));
            b.insert(b.end(), label.begin(), label.end());
            if (dot == std::string::npos) break;
            start = dot + 1;
        }
        b.push_back(0);
    }

    static void record(Bytes& b, const std::string& n, uint16_t type, uint16_t cls, uint32_t ttl, const Bytes& rdata) {
        name(b, n);
        u16(b, type);
        u16(b, cls);
        u32(b, ttl);
        u16(b, static_cast<uint16_t>(rdata.size()));
        b.insert(b.end(), rdata.begin(), rdata.end());
    }

    static Bytes header(uint16_t flags, int qd, int an, int ar) {
        Bytes b;
        u16(b, 0); u16(b, flags); u16(b, qd); u16(b, an); u16(b, 0); u16(b, ar);
        return b;
    }

    Bytes announcePacket(uint32_t ttl) const {
        std::string service = "_rift._tcp.local", instance = cfg_.name + "." + service, host = cfg_.name + ".local";
        Bytes out = header(0x8400, 0, 1, 3);
        Bytes ptr;
        name(ptr, instance);
        record(out, service, T_PTR, CLASS_IN, ttl, ptr);

        Bytes srv;
        u16(srv, 0); u16(srv, 0); u16(srv, static_cast<uint16_t>(cfg_.port));
        name(srv, host);
        record(out, instance, T_SRV, CACHE_FLUSH | CLASS_IN, ttl, srv);

        std::string txtEntry = "role=fleet_manager";
        Bytes txt{static_cast<uint8_t>(txtEntry.size())};
        txt.insert(txt.end(), txtEntry.begin(), txtEntry.end());
        record(out, instance, T_TXT, CACHE_FLUSH | CLASS_IN, ttl, txt);

        Bytes a(4);
        in_addr addr{};
        inet_pton(AF_INET, cfg_.ip.c_str(), &addr);
        std::memcpy(a.data(), &addr, 4);
        record(out, host, T_A, CACHE_FLUSH | CLASS_IN, ttl, a);
        return out;
    }

    static Bytes queryPacket(const std::string& n, uint16_t type) {
        Bytes out = header(0, 1, 0, 0);
        name(out, n);
        u16(out, type);
        u16(out, CLASS_IN);
        return out;
    }

    void send(const Bytes& packet) {
        sockaddr_in dst{};
        dst.sin_family = AF_INET;
        dst.sin_port = htons(5353);
        inet_pton(AF_INET, "224.0.0.251", &dst.sin_addr);
        sendto(sock_, reinterpret_cast<const char*>(packet.data()), static_cast<int>(packet.size()), 0,
               reinterpret_cast<sockaddr*>(&dst), sizeof(dst));
    }

    // ---- parsing ----

    struct Rec {
        std::string name;
        int type = 0, ttl = 0;
        std::string target, addr;  // PTR/SRV target, A address
        int port = 0;
    };

    static int rd16(const Bytes& b, size_t p) {
        if (p + 2 > b.size()) throw std::out_of_range("dns");
        return (b[p] << 8) | b[p + 1];
    }

    // Reads a (possibly compressed) name at p; advances p past it.
    static std::string readName(const Bytes& b, size_t& p) {
        std::string out;
        size_t pos = p;
        bool jumped = false;
        int hops = 0;
        while (true) {
            if (pos >= b.size()) throw std::out_of_range("dns");
            uint8_t len = b[pos];
            if (len == 0) {
                pos++;
                break;
            }
            if ((len & 0xc0) == 0xc0) {
                if (pos + 1 >= b.size() || ++hops > 32) throw std::out_of_range("dns");
                size_t target = ((len & 0x3f) << 8) | b[pos + 1];
                if (!jumped) p = pos + 2;
                jumped = true;
                pos = target;
            } else {
                if (pos + 1 + len > b.size()) throw std::out_of_range("dns");
                if (!out.empty()) out += '.';
                out.append(reinterpret_cast<const char*>(&b[pos + 1]), len);
                pos += 1 + len;
            }
        }
        if (!jumped) p = pos;
        return out;
    }

    static void parse(const Bytes& b, std::vector<std::pair<std::string, int>>& questions, std::vector<Rec>& recs) {
        int qd = rd16(b, 4), total = rd16(b, 6) + rd16(b, 8) + rd16(b, 10);
        size_t p = 12;
        for (int i = 0; i < qd; i++) {
            std::string n = readName(b, p);
            questions.emplace_back(n, rd16(b, p));
            p += 4;
        }
        for (int i = 0; i < total; i++) {
            Rec r;
            r.name = readName(b, p);
            r.type = rd16(b, p);
            r.ttl = (rd16(b, p + 4) << 16) | rd16(b, p + 6);
            int rdlen = rd16(b, p + 8);
            size_t rd = p + 10;
            if (rd + rdlen > b.size()) throw std::out_of_range("dns");
            if (r.type == T_PTR) {
                size_t q = rd;
                r.target = readName(b, q);
            } else if (r.type == T_SRV) {
                r.port = rd16(b, rd + 4);
                size_t q = rd + 6;
                r.target = readName(b, q);
            } else if (r.type == T_A && rdlen == 4) {
                r.addr = std::to_string(b[rd]) + "." + std::to_string(b[rd + 1]) + "." + std::to_string(b[rd + 2]) + "." +
                         std::to_string(b[rd + 3]);
            }
            recs.push_back(std::move(r));
            p = rd + rdlen;
        }
    }

    static bool isBrowsedService(const std::string& lname) {
        return lname == "_rift._tcp.local" || lname == "_flask-link._tcp.local";
    }
    static bool isBrowsedInstance(const std::string& lname) {
        return lname.find("._rift._tcp.local") != std::string::npos || lname.find("._flask-link._tcp.local") != std::string::npos;
    }

    void publishPeers() {
        for (const auto& kv : srv_) {
            const std::string& instance = instances_[kv.first];
            std::string shortName = instance.substr(0, instance.find('.'));
            if (shortName == cfg_.name) continue;
            auto a = addrs_.find(lower(kv.second.second));
            if (a == addrs_.end()) continue;
            peers_.set(shortName, "http://" + a->second + ":" + std::to_string(kv.second.first));
        }
    }

    void handle(const Bytes& packet) {
        std::vector<std::pair<std::string, int>> questions;
        std::vector<Rec> recs;
        parse(packet, questions, recs);

        std::string service = "_rift._tcp.local", instance = lower(cfg_.name + "." + service), host = lower(cfg_.name + ".local");
        for (const auto& q : questions) {
            std::string n = lower(q.first);
            int t = q.second;
            if ((n == service && (t == T_PTR || t == T_ANY)) || (n == instance && (t == T_SRV || t == T_TXT || t == T_ANY)) ||
                (n == host && (t == T_A || t == T_ANY))) {
                send(announcePacket(120));  // someone is asking about us
                break;
            }
        }

        for (const auto& r : recs) {
            std::string lname = lower(r.name);
            if (r.type == T_PTR && isBrowsedService(lname)) {
                std::string shortName = r.target.substr(0, r.target.find('.'));
                if (r.ttl == 0) {
                    peers_.remove(shortName);  // goodbye
                } else if (shortName != cfg_.name) {
                    instances_[lower(r.target)] = r.target;
                    if (!srv_.count(lower(r.target))) send(queryPacket(r.target, T_SRV));
                }
            } else if (r.type == T_SRV && isBrowsedInstance(lname)) {
                instances_[lname] = r.name;
                srv_[lname] = {r.port, r.target};
                if (!addrs_.count(lower(r.target))) send(queryPacket(r.target, T_A));
            } else if (r.type == T_A && !r.addr.empty()) {
                addrs_[lname] = r.addr;
            }
        }
        publishPeers();
    }

    void receiveLoop() {
        Bytes buf(9000);
        while (running_) {
            int n = static_cast<int>(recv(sock_, reinterpret_cast<char*>(buf.data()), static_cast<int>(buf.size()), 0));
            if (n <= 0) continue;  // timeout (or transient error): re-check running_
            try {
                handle(Bytes(buf.begin(), buf.begin() + n));
            } catch (...) {
                // A malformed packet from someone else must never take the responder down.
            }
        }
    }

    void queryLoop() {
        int announced = 0;
        while (running_) {
            send(queryPacket("_rift._tcp.local", T_PTR));
            send(queryPacket("_flask-link._tcp.local", T_PTR));
            if (announced < 3) {
                send(announcePacket(120));
                announced++;
            }
            for (int i = 0; i < (announced < 3 ? 10 : 100) && running_; i++) std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }

    Config cfg_;
    Peers& peers_;
    sock_t sock_ = RIFT_INVALID_SOCKET;
    std::atomic<bool> running_{false};
    std::thread recvThread_, queryThread_;
    // Only touched from the receive thread.
    std::map<std::string, std::pair<int, std::string>> srv_;  // lowercase instance -> (port, target host)
    std::map<std::string, std::string> addrs_;                // lowercase host -> IPv4
    std::map<std::string, std::string> instances_;            // lowercase instance -> original case
};

// ---------------------------------------------------------------------
// Internet share for NORA's isolated WiFi AP: join her AP as a secondary
// connection over a spare WiFi radio, then let NetworkManager's "shared"
// method (its own DHCP server + NAT) hand internet access to NORA and anything
// else on her AP, while RIFT's own default route is left alone. Linux +
// NetworkManager only; anywhere else it quietly does nothing.
// ---------------------------------------------------------------------

class InternetShare {
public:
    ~InternetShare() { stop(); }

    void start() {
#ifdef __linux__
        if (!nmcli("--version", 5).first) return;
        thread_ = std::thread([this] {
            while (!stop_) {
                ensure();
                interruptibleSleep(30, stop_);
            }
        });
#endif
    }

    void stop() {
        stop_ = true;
        if (thread_.joinable()) thread_.join();
    }

private:
#ifdef __linux__
    static constexpr const char* kSsid = "NORA";
    static constexpr const char* kPassword = "12345678";

    // Runs nmcli with a timeout (via coreutils timeout); returns {succeeded, stdout}.
    static std::pair<bool, std::string> nmcli(const std::string& args, int timeoutSecs) {
        std::string cmd = "timeout " + std::to_string(timeoutSecs) + " nmcli " + args + " 2>/dev/null";
        FILE* p = popen(cmd.c_str(), "r");
        if (!p) return {false, ""};
        std::string out;
        char buf[512];
        while (fgets(buf, sizeof(buf), p)) out += buf;
        return {pclose(p) == 0, out};
    }

    static std::vector<std::string> lines(const std::string& s) {
        std::vector<std::string> out;
        size_t start = 0;
        while (start < s.size()) {
            size_t nl = s.find('\n', start);
            std::string l = trim(s.substr(start, nl == std::string::npos ? std::string::npos : nl - start));
            if (!l.empty()) out.push_back(l);
            if (nl == std::string::npos) break;
            start = nl + 1;
        }
        return out;
    }

    static bool contains(const std::vector<std::string>& v, const std::string& s) {
        for (auto& x : v) if (x == s) return true;
        return false;
    }

    static std::string wifiIface() {
        for (auto& l : lines(nmcli("-t -f DEVICE,TYPE device status", 20).second)) {
            size_t c = l.find(':');
            if (c != std::string::npos && l.substr(c + 1) == "wifi") return l.substr(0, c);
        }
        return "";
    }

    static std::vector<std::string> active() { return lines(nmcli("-t -f NAME connection show --active", 20).second); }

    void ensure() {
        std::string iface = wifiIface();
        if (iface.empty() || contains(active(), kSsid)) return;
        auto known = nmcli("-t -f NAME connection show", 20);
        if (!known.first) return;
        if (!contains(lines(known.second), kSsid)) {
            nmcli(std::string("device wifi connect ") + kSsid + " password " + kPassword + " ifname " + iface, 30);
            nmcli(std::string("connection modify ") + kSsid + " ipv4.method shared", 20);
        } else {
            nmcli(std::string("connection up ") + kSsid, 30);
        }
    }
#endif
    std::atomic<bool> stop_{false};
    std::thread thread_;
};

}  // namespace rift
