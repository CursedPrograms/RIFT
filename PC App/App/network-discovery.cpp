#include <iostream>
#include <string>
#include <thread>
#include <map>
#include <atomic>
#include <chrono>
#include <httplib.h>
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <avahi-client/client.h>
#include <avahi-client/publish.h>
#include <avahi-common/error.h>
#include <avahi-common/defs.h>

std::string THIS_NAME = "RIFT";
int THIS_PORT = 5000;
std::atomic<bool> running(true);
std::map<std::string, std::string> found_servers;

// Helper: get local IP address
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

// Zeroconf / Avahi registration
AvahiEntryGroup *group = nullptr;
AvahiClient *client = nullptr;

void create_service() {
    int error;
    group = avahi_entry_group_new(client, nullptr, nullptr);
    if (!group) {
        std::cerr << "Failed to create entry group: " << avahi_strerror(error) << std::endl;
        return;
    }

    std::string ip = get_local_ip();
    AvahiAddress addr{};
    inet_pton(AF_INET, ip.c_str(), &addr.data);

    avahi_entry_group_add_service(
        group,
        AVAHI_IF_UNSPEC,
        AVAHI_PROTO_UNSPEC,
        AvahiPublishFlags(0),
        THIS_NAME.c_str(),
        "_rift._tcp",
        nullptr,
        nullptr,
        THIS_PORT,
        nullptr
    );

    if ((error = avahi_entry_group_commit(group)) < 0) {
        std::cerr << "Failed to commit group: " << avahi_strerror(error) << std::endl;
    }
}

// Minimal HTTP server with httplib
void start_server() {
    httplib::Server svr;

    svr.Get("/", [&](const httplib::Request&, httplib::Response& res){
        std::string html = "<h1>Active Network</h1><p>My IP: " + get_local_ip() + "</p>";
        html += "<p><b>" + THIS_NAME + "</b> (Self)</p>";

        for (auto &kv : found_servers) {
            html += "<p><b>" + kv.first + "</b> Online at " + kv.second + "</p>";
        }
        html += "<script>setTimeout(() => location.reload(), 3000);</script>";
        res.set_content(html, "text/html");
    });

    svr.Get("/ping", [&](const httplib::Request&, httplib::Response& res){
        res.set_content(THIS_NAME + " alive", "text/plain");
    });

    svr.listen("0.0.0.0", THIS_PORT);
}

int main() {
    std::cout << "Starting " << THIS_NAME << " on " << get_local_ip() << ":" << THIS_PORT << std::endl;

    // Start HTTP server in a separate thread
    std::thread server_thread(start_server);

    // TODO: Implement service discovery to populate found_servers map

    server_thread.join();
    running = false;
    std::cout << "Shutting down..." << std::endl;
    return 0;
}