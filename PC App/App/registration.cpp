#include <iostream>
#include <vector>
#include <string>
#include <thread>
#include <mutex>

#include <curl/curl.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

std::mutex mtx;

struct Robot {
    std::string name;
    std::string ip;
    std::string type;
    std::vector<std::string> capabilities;
};

std::vector<Robot> robots;

// 🔹 CURL response handler
size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* output) {
    size_t totalSize = size * nmemb;
    output->append((char*)contents, totalSize);
    return totalSize;
}

// 🔹 Query /robots endpoint
void scan_ip(const std::string& ip) {
    CURL* curl = curl_easy_init();
    if (!curl) return;

    std::string readBuffer;
    std::string url = "http://" + ip + ":5000/robots";

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &readBuffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 500L);

    CURLcode res = curl_easy_perform(curl);

    if (res == CURLE_OK) {
        try {
            auto data = json::parse(readBuffer);

            for (auto& r : data) {
                Robot robot;
                robot.name = r["name"];
                robot.ip = ip;
                robot.type = r["type"];

                for (auto& cap : r["capabilities"]) {
                    robot.capabilities.push_back(cap);
                }

                std::lock_guard<std::mutex> lock(mtx);
                robots.push_back(robot);
            }
        } catch (...) {
            // ignore bad JSON
        }
    }

    curl_easy_cleanup(curl);
}

// 🔹 Get local subnet base (simple version)
std::string get_base_ip() {
    return "192.168.1"; // change if needed
}

int main() {
    curl_global_init(CURL_GLOBAL_ALL);

    std::string base = get_base_ip();

    std::vector<std::thread> threads;

    std::cout << "Scanning network..." << std::endl;

    for (int i = 1; i < 255; i++) {
        std::string ip = base + "." + std::to_string(i);
        threads.emplace_back(scan_ip, ip);
    }

    for (auto& t : threads) {
        t.join();
    }

    std::cout << "\n=== Robots Found ===\n";

    for (const auto& r : robots) {
        std::cout << r.name << " (" << r.type << ") @ " << r.ip << "\n";
        std::cout << "  Capabilities: ";
        for (const auto& cap : r.capabilities) {
            std::cout << cap << " ";
        }
        std::cout << "\n\n";
    }

    curl_global_cleanup();
    return 0;
}
