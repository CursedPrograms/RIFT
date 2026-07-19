#include <iostream>
#include <string>
#include <thread>
#include <map>
#include <mutex>
#include <vector>
#include <chrono>
#include <csignal>
#include <sstream>

#include <httplib.h>
#include <arpa/inet.h>
#include <ifaddrs.h>

#include <avahi-client/client.h>
#include <avahi-client/publish.h>
#include <avahi-client/lookup.h>
#include <avahi-common/thread-watch.h>
#include <avahi-common/alternative.h>
#include <avahi-common/malloc.h>
#include <avahi-common/error.h>

namespace {

const std::string THIS_NAME = "RIFT";
const int THIS_PORT = 5000;
// Must stay well above Fleet/register.py's HEARTBEAT_SECS (10s) or a live
// fleet authority will flap in and out of the registry between heartbeats.
const std::chrono::milliseconds FLEET_TTL{20000};

struct FleetMember {
    std::string ip;
    std::string type;
    std::vector<std::string> capabilities;
    std::chrono::steady_clock::time_point last_seen;
};

std::mutex fleet_mtx;
std::map<std::string, FleetMember> fleet;          // registered robots/managers, keyed by name

std::mutex peers_mtx;
std::map<std::string, std::string> found_servers;  // other RIFT instances seen via mDNS, name -> "ip:port"

httplib::Server svr;

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

std::string get_local_ip() {
    struct ifaddrs *ifap, *ifa;
    struct sockaddr_in *sa;
    std::string ip = "127.0.0.1";

    if (getifaddrs(&ifap) == 0) {
        for (ifa = ifap; ifa; ifa = ifa->ifa_next) {
            if (ifa->ifa_addr && ifa->ifa_addr->sa_family == AF_INET) {
                sa = (struct sockaddr_in *) ifa->ifa_addr;
                std::string temp_ip = inet_ntoa(sa->sin_addr);
                if (temp_ip != "127.0.0.1") {
                    ip = temp_ip;
                    break;
                }
            }
        }
        freeifaddrs(ifap);
    }
    return ip;
}

std::string json_escape(const std::string &s) {
    std::ostringstream out;
    for (char c : s) {
        switch (c) {
            case '"':  out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            default:   out << c;
        }
    }
    return out.str();
}

// ---------------------------------------------------------------------
// Fleet registry — backs /robots and /register, the endpoints
// Fleet/register.py and PC App/App/registration.cpp talk to.
// ---------------------------------------------------------------------

void register_member(const std::string &name, const std::string &ip,
                      const std::string &type, const std::string &caps_csv) {
    std::vector<std::string> caps;
    std::stringstream ss(caps_csv);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (!item.empty()) caps.push_back(item);
    }

    std::lock_guard<std::mutex> lock(fleet_mtx);
    fleet[name] = FleetMember{ip, type, std::move(caps), std::chrono::steady_clock::now()};
}

// Matches NORA's fleet server response shape exactly (see NORA-Robot-v00's
// scripts/esp32/esp32.ino, setupFleetServer()'s /robots handler) so callers
// like registration.cpp and PC App/PyGame/registration.py can scan either
// RIFT or NORA with the same parser instead of needing a shape per node.
std::string robots_json() {
    std::lock_guard<std::mutex> lock(fleet_mtx);
    auto now = std::chrono::steady_clock::now();
    std::ostringstream out;
    out << "{\"authority\":\"" << json_escape(THIS_NAME) << "\",\"robots\":[";
    bool first = true;
    for (auto it = fleet.begin(); it != fleet.end(); ) {
        if (now - it->second.last_seen > FLEET_TTL) {
            it = fleet.erase(it);
            continue;
        }
        if (!first) out << ",";
        first = false;
        out << "{\"name\":\"" << json_escape(it->first) << "\","
            << "\"ip\":\"" << json_escape(it->second.ip) << "\","
            << "\"type\":\"" << json_escape(it->second.type) << "\","
            << "\"capabilities\":[";
        for (size_t i = 0; i < it->second.capabilities.size(); ++i) {
            if (i) out << ",";
            out << "\"" << json_escape(it->second.capabilities[i]) << "\"";
        }
        out << "]}";
        ++it;
    }
    out << "]}";
    return out.str();
}

// ---------------------------------------------------------------------
// Avahi/mDNS: publish this instance as _rift._tcp and browse for peers
// ---------------------------------------------------------------------

AvahiClient *avahi_client_ptr = nullptr;
AvahiEntryGroup *avahi_group = nullptr;
AvahiThreadedPoll *avahi_poll = nullptr;
AvahiServiceBrowser *avahi_browser = nullptr;
std::string service_name = THIS_NAME;

void create_service(AvahiClient *c);

void entry_group_callback(AvahiEntryGroup *g, AvahiEntryGroupState state, void *) {
    if (state == AVAHI_ENTRY_GROUP_COLLISION) {
        char *alt = avahi_alternative_service_name(service_name.c_str());
        service_name = alt;
        avahi_free(alt);
        create_service(avahi_entry_group_get_client(g));
    } else if (state == AVAHI_ENTRY_GROUP_FAILURE) {
        std::cerr << "Entry group failure: "
                  << avahi_strerror(avahi_client_errno(avahi_entry_group_get_client(g)))
                  << std::endl;
    }
}

void create_service(AvahiClient *c) {
    if (!avahi_group) {
        avahi_group = avahi_entry_group_new(c, entry_group_callback, nullptr);
        if (!avahi_group) {
            std::cerr << "avahi_entry_group_new failed: "
                      << avahi_strerror(avahi_client_errno(c)) << std::endl;
            return;
        }
    }

    if (!avahi_entry_group_is_empty(avahi_group)) return;

    int ret = avahi_entry_group_add_service(
        avahi_group, AVAHI_IF_UNSPEC, AVAHI_PROTO_UNSPEC,
        (AvahiPublishFlags)0, service_name.c_str(),
        "_rift._tcp", nullptr, nullptr, THIS_PORT, nullptr);

    if (ret == AVAHI_ERR_COLLISION) {
        char *alt = avahi_alternative_service_name(service_name.c_str());
        service_name = alt;
        avahi_free(alt);
        create_service(c);
        return;
    }
    if (ret < 0) {
        std::cerr << "Failed to add _rift._tcp service: " << avahi_strerror(ret) << std::endl;
        return;
    }

    ret = avahi_entry_group_commit(avahi_group);
    if (ret < 0) {
        std::cerr << "Failed to commit entry group: " << avahi_strerror(ret) << std::endl;
    }
}

void resolve_callback(
    AvahiServiceResolver *r,
    AvahiIfIndex /*interface*/,
    AvahiProtocol /*protocol*/,
    AvahiResolverEvent event,
    const char *name,
    const char * /*type*/,
    const char * /*domain*/,
    const char * /*host_name*/,
    const AvahiAddress *address,
    uint16_t port,
    AvahiStringList * /*txt*/,
    AvahiLookupResultFlags /*flags*/,
    void * /*userdata*/) {

    if (event == AVAHI_RESOLVER_FOUND && name != service_name) {
        char addr[AVAHI_ADDRESS_STR_MAX];
        avahi_address_snprint(addr, sizeof(addr), address);
        std::lock_guard<std::mutex> lock(peers_mtx);
        found_servers[name] = std::string(addr) + ":" + std::to_string(port);
    }
    avahi_service_resolver_free(r);
}

void browse_callback(
    AvahiServiceBrowser *b,
    AvahiIfIndex iface,
    AvahiProtocol proto,
    AvahiBrowserEvent event,
    const char *name,
    const char *type,
    const char *domain,
    AvahiLookupResultFlags /*flags*/,
    void *userdata) {

    AvahiClient *c = static_cast<AvahiClient *>(userdata);

    switch (event) {
        case AVAHI_BROWSER_NEW:
            avahi_service_resolver_new(c, iface, proto, name, type, domain,
                                        AVAHI_PROTO_UNSPEC, (AvahiLookupFlags)0,
                                        resolve_callback, nullptr);
            break;
        case AVAHI_BROWSER_REMOVE: {
            std::lock_guard<std::mutex> lock(peers_mtx);
            found_servers.erase(name);
            break;
        }
        case AVAHI_BROWSER_FAILURE:
            std::cerr << "Service browser failure: "
                      << avahi_strerror(avahi_client_errno(avahi_service_browser_get_client(b)))
                      << std::endl;
            break;
        default:
            break;
    }
}

void client_callback(AvahiClient *c, AvahiClientState state, void *) {
    avahi_client_ptr = c;

    if (state == AVAHI_CLIENT_S_RUNNING) {
        create_service(c);
        if (!avahi_browser) {
            avahi_browser = avahi_service_browser_new(
                c, AVAHI_IF_UNSPEC, AVAHI_PROTO_UNSPEC, "_rift._tcp",
                nullptr, (AvahiLookupFlags)0, browse_callback, c);
        }
    } else if (state == AVAHI_CLIENT_FAILURE) {
        std::cerr << "Avahi client failure: " << avahi_strerror(avahi_client_errno(c)) << std::endl;
    } else if (state == AVAHI_CLIENT_S_COLLISION || state == AVAHI_CLIENT_S_REGISTERING) {
        if (avahi_group) avahi_entry_group_reset(avahi_group);
    }
}

bool start_mdns() {
    avahi_poll = avahi_threaded_poll_new();
    if (!avahi_poll) {
        std::cerr << "Failed to create avahi threaded poll" << std::endl;
        return false;
    }

    int error;
    avahi_client_ptr = avahi_client_new(avahi_threaded_poll_get(avahi_poll),
                                         (AvahiClientFlags)0, client_callback, nullptr, &error);
    if (!avahi_client_ptr) {
        std::cerr << "Failed to create avahi client: " << avahi_strerror(error) << std::endl;
        avahi_threaded_poll_free(avahi_poll);
        avahi_poll = nullptr;
        return false;
    }

    avahi_threaded_poll_start(avahi_poll);
    return true;
}

void stop_mdns() {
    if (avahi_poll) avahi_threaded_poll_stop(avahi_poll);
    if (avahi_browser) avahi_service_browser_free(avahi_browser);
    if (avahi_client_ptr) avahi_client_free(avahi_client_ptr);
    if (avahi_poll) avahi_threaded_poll_free(avahi_poll);
}

// ---------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------

void start_server() {
    svr.Get("/", [](const httplib::Request&, httplib::Response& res) {
        std::string html = "<h1>RIFT Fleet Manager</h1><p>My IP: " + get_local_ip() + "</p>";
        html += "<p><b>" + service_name + "</b> (Self)</p>";

        {
            std::lock_guard<std::mutex> lock(peers_mtx);
            for (auto &kv : found_servers) {
                html += "<p><b>" + kv.first + "</b> Online at " + kv.second + "</p>";
            }
        }

        html += "<h2>Registered fleet</h2><pre>" + robots_json() + "</pre>";
        html += "<script>setTimeout(() => location.reload(), 3000);</script>";
        res.set_content(html, "text/html");
    });

    svr.Get("/ping", [](const httplib::Request&, httplib::Response& res) {
        res.set_content(THIS_NAME + " alive", "text/plain");
    });

    // What PC App/App/registration.cpp and PC App/PyGame/registration.py
    // scan for, and what Fleet/register.py's fleet authority stands in for.
    svr.Get("/robots", [](const httplib::Request&, httplib::Response& res) {
        res.set_content(robots_json(), "application/json");
    });

    svr.Post("/register", [](const httplib::Request& req, httplib::Response& res) {
        if (!req.has_param("name")) {
            res.status = 400;
            res.set_content("missing name", "text/plain");
            return;
        }
        std::string name = req.get_param_value("name");
        std::string type = req.has_param("type") ? req.get_param_value("type") : "unknown";
        std::string caps = req.has_param("capabilities") ? req.get_param_value("capabilities") : "";
        register_member(name, req.remote_addr, type, caps);
        res.set_content("OK", "text/plain");
    });

    svr.listen("0.0.0.0", THIS_PORT);
}

} // namespace

void handle_signal(int) {
    svr.stop();
}

int main() {
    std::cout << "Starting " << THIS_NAME << " on " << get_local_ip() << ":" << THIS_PORT << std::endl;

    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);

    if (!start_mdns()) {
        std::cerr << "Continuing without mDNS discovery" << std::endl;
    }

    std::thread server_thread(start_server);
    server_thread.join();

    stop_mdns();
    std::cout << "Shutting down..." << std::endl;
    return 0;
}
