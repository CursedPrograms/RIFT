// RIFT fleet hub, C++ edition: the same fleet registry, dashboard, mDNS
// discovery, NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet
// share as app.py, as one native binary for Windows and Linux (no Avahi, curl
// or nlohmann needed). Speaks the same protocol on the same port as app.py, so
// run one or the other on a given machine, not both.
//
//   network-discovery           start the hub on :5000
//   network-discovery --scan    scan this /24 for hubs/robots serving /robots

#include <csignal>
#include <cstring>
#include <fstream>
#include <memory>
#include <sstream>

#include "minijson.hpp"
#include "rift_hub.h"
#include "rift_scan.h"
#include "rift_util.h"

using namespace rift;

namespace {

httplib::Server* g_server = nullptr;

void handleSignal(int) {
    if (g_server) g_server->stop();
}

std::string readFile(const fs::path& p, bool& ok) {
    std::ifstream f(p, std::ios::binary);
    ok = static_cast<bool>(f);
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

std::string robotJson(const Robot& r) {
    std::vector<std::string> caps;
    for (const auto& c : r.capabilities) caps.push_back(jstr(c));
    return jobj({{"name", jstr(r.name)}, {"ip", jstr(r.ip)}, {"type", jstr(r.type)}, {"capabilities", jarr(caps)}});
}

// A registration or mode change: app.py reads a form body; the Android app's
// Registration.kt sends JSON, so both are accepted. Returns the fields as strings
// (an array such as "capabilities" is joined back into a CSV).
std::map<std::string, std::string> readFields(const httplib::Request& req) {
    std::map<std::string, std::string> fields;
    if (req.get_header_value("Content-Type").rfind("application/json", 0) == 0) {
        try {
            Json body = Json::parse(req.body);
            for (const auto& kv : body.obj_value) {
                if (kv.second.type == Json::Type::String) {
                    fields[kv.first] = kv.second.str_value;
                } else if (kv.second.isArray()) {
                    std::string csv;
                    for (const Json& item : kv.second.arr_value) csv += (csv.empty() ? "" : ",") + item.asString();
                    fields[kv.first] = csv;
                }
            }
        } catch (...) {
        }
    } else {
        for (const auto& p : req.params) fields[p.first] = p.second;
    }
    return fields;
}

std::string field(const std::map<std::string, std::string>& f, const std::string& key) {
    auto it = f.find(key);
    return it == f.end() ? "" : it->second;
}

}  // namespace

int main(int argc, char** argv) {
    Config cfg;
    std::string err = parseConfig(argc, argv, cfg);
    if (!err.empty()) {
        std::fprintf(stderr, "%s\n", err.c_str());
        return 1;
    }
    if (cfg.scan) {
        runScan(cfg.ip, cfg.port);
        return 0;
    }

    std::printf("[RIFT] IP   : %s\n[RIFT] Port : %d\n[RIFT] Root : %s\n", cfg.ip.c_str(), cfg.port, cfg.root.string().c_str());

    Peers peers;
    std::unique_ptr<Mdns> mdns;
    if (!cfg.noMdns) {
        mdns = std::make_unique<Mdns>(cfg, peers);
        std::string mdnsErr = mdns->start();
        if (mdnsErr.empty()) {
            std::printf("[RIFT] Zeroconf registered as %s; watching _rift._tcp and _flask-link._tcp\n", cfg.name.c_str());
        } else {
            std::printf("[RIFT] Continuing without mDNS: %s\n", mdnsErr.c_str());
            mdns.reset();
        }
    }

    Authority authority(cfg);
    authority.restart("wifi", "");
    if (cfg.noHeartbeat) std::printf("[RIFT] Not announcing to NORA (--no-heartbeat)\n");
    else std::printf("[RIFT] Announcing to NORA at %s:%d as fleet authority (mode: wifi)\n", cfg.noraHost.c_str(), cfg.noraPort);

    InternetShare share;
    if (!cfg.noInternetShare) share.start();

    Registry registry(cfg.ttlSecs);
    httplib::Server svr;
    g_server = &svr;

    svr.Get("/ping", [&](const httplib::Request&, httplib::Response& res) { res.set_content(cfg.name + " alive", "text/plain"); });

    svr.Post("/register", [&](const httplib::Request& req, httplib::Response& res) {
        auto f = readFields(req);
        std::string name = field(f, "name");
        if (name.empty()) {
            res.status = 400;
            res.set_content("missing name", "text/plain");
            return;
        }
        std::string type = field(f, "type");
        std::string ip = field(f, "ip");
        registry.add(name, ip.empty() ? req.remote_addr : ip, type.empty() ? "unknown" : type, splitCaps(field(f, "capabilities")));
        res.set_content("OK", "text/plain");
    });

    svr.Get("/robots", [&](const httplib::Request&, httplib::Response& res) {
        std::vector<std::string> items;
        for (const auto& r : registry.robots()) items.push_back(robotJson(r));
        res.set_content(jobj({{"authority", jstr(cfg.name)}, {"robots", jarr(items)}}), "application/json");
    });

    svr.Get("/peers", [&](const httplib::Request&, httplib::Response& res) {
        std::vector<std::pair<std::string, std::string>> fields;
        for (const auto& kv : peers.snapshot()) fields.emplace_back(kv.first, jstr(kv.second));
        res.set_content(jobj(fields), "application/json");
    });

    svr.Get("/mode", [&](const httplib::Request&, httplib::Response& res) {
        auto st = authority.state();
        res.set_content(jobj({{"mode", jstr(st.first)}, {"bt_port", jnullOrStr(st.second)}}), "application/json");
    });

    svr.Post("/mode", [&](const httplib::Request& req, httplib::Response& res) {
        auto f = readFields(req);
        std::string mode = lower(trim(field(f, "mode"))), btPort = trim(field(f, "bt_port"));
        if (mode != "wifi" && mode != "bluetooth") {
            res.status = 400;
            res.set_content(jobj({{"error", jstr("mode must be 'wifi' or 'bluetooth'")}}), "application/json");
            return;
        }
        if (mode == "bluetooth" && btPort.empty()) {
            res.status = 400;
            res.set_content(jobj({{"error", jstr("bt_port is required for Bluetooth mode")}}), "application/json");
            return;
        }
        authority.restart(mode, btPort);
        res.set_content(jobj({{"mode", jstr(mode)}, {"bt_port", jnullOrStr(btPort)}}), "application/json");
    });

    svr.Get("/", [&](const httplib::Request&, httplib::Response& res) {
        bool ok = false;
        std::string tpl = readFile(cfg.root / "templates" / "index.html", ok);
        if (!ok) {
            res.status = 500;
            res.set_content("dashboard template not found", "text/plain");
            return;
        }
        res.set_content(renderTemplate(tpl, {{"this_name", cfg.name}, {"my_ip", cfg.ip}, {"this_port", std::to_string(cfg.port)}}),
                        "text/html; charset=utf-8");
    });

    // httplib refuses paths that try to escape the mounted directory.
    svr.set_mount_point("/static", (cfg.root / "static").string());

    // Wrong method on a known route -> 405, like Flask.
    auto notAllowed = [](const httplib::Request&, httplib::Response& res) {
        res.status = 405;
        res.set_content("Method Not Allowed", "text/plain");
    };
    svr.Get("/register", notAllowed);
    for (const char* path : {"/ping", "/robots", "/peers", "/"}) svr.Post(path, notAllowed);

    svr.set_error_handler([](const httplib::Request&, httplib::Response& res) {
        if (res.status == 404) res.set_content("Not found", "text/plain");
    });

    std::signal(SIGINT, handleSignal);
    std::signal(SIGTERM, handleSignal);

    if (!svr.listen("0.0.0.0", cfg.port)) {
        std::fprintf(stderr, "[RIFT] server error: could not bind port %d (already in use?)\n", cfg.port);
        return 1;
    }

    share.stop();
    authority.stop();
    if (mdns) mdns->stop();
    std::printf("[RIFT] Shut down.\n");
    return 0;
}
