// rift_scan.h - the subnet-scanning client shared by `registration` and the
// hub's --scan flag: queries every host on this machine's /24 for
// :<port>/robots and prints whatever answers.
#pragma once

#include "minijson.hpp"
#include "rift_util.h"

namespace rift {

struct ScanRobot {
    std::string name, type, ip;
    std::vector<std::string> capabilities;
};

// Both RIFT and NORA serve {"authority": "...", "robots": [...]}, not a bare array.
inline std::vector<ScanRobot> scanHost(const std::string& ip, int port) {
    std::vector<ScanRobot> found;
    httplib::Client client(ip, port);
    client.set_connection_timeout(0, 500000);
    client.set_read_timeout(0, 500000);
    auto res = client.Get("/robots");
    if (!res || res->status != 200) return found;
    try {
        Json body = Json::parse(res->body);
        const Json* robots = body.find("robots");
        if (!robots || !robots->isArray()) return found;
        for (const Json& r : robots->arr_value) {
            ScanRobot robot{r.get("name", std::string()), r.get("type", std::string()), ip, {}};
            if (const Json* caps = r.find("capabilities"))
                for (const Json& c : caps->arr_value) robot.capabilities.push_back(c.asString());
            found.push_back(std::move(robot));
        }
    } catch (...) {
        // ignore bad JSON
    }
    return found;
}

inline void runScan(const std::string& localIpAddr, int port) {
    std::string base = localIpAddr.substr(0, localIpAddr.rfind('.'));  // assumes a /24
    std::printf("Scanning %s.1-254 on port %d...\n", base.c_str(), port);

    std::mutex mu;
    std::vector<ScanRobot> all;
    std::atomic<int> next{1};
    std::vector<std::thread> workers;
    for (int w = 0; w < 50; w++) {
        workers.emplace_back([&] {
            for (int i = next++; i <= 254; i = next++) {
                auto found = scanHost(base + "." + std::to_string(i), port);
                std::lock_guard<std::mutex> lock(mu);
                all.insert(all.end(), found.begin(), found.end());
            }
        });
    }
    for (auto& t : workers) t.join();

    std::printf("\n=== Robots Found ===\n");
    for (const auto& r : all) {
        std::printf("%s (%s) @ %s\n  Capabilities:", r.name.c_str(), r.type.c_str(), r.ip.c_str());
        for (const auto& c : r.capabilities) std::printf(" %s", c.c_str());
        std::printf("\n\n");
    }
}

}  // namespace rift
