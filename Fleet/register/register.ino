#include <iostream>
#include <string>
#include <vector>

struct RobotRegistration {
    std::string name;
    std::string ip;
    std::string type;
    std::vector<std::string> capabilities;
};

int main() {
    RobotRegistration robot;

    robot.name = "KIDA_v00";
    robot.ip = "192.168.1.50";
    robot.type = "tank";
    robot.capabilities = {"camera", "line_follow"};

    // Print to verify
    std::cout << "Robot Name: " << robot.name << std::endl;
    std::cout << "IP: " << robot.ip << std::endl;
    std::cout << "Type: " << robot.type << std::endl;

    std::cout << "Capabilities:" << std::endl;
    for (const auto& cap : robot.capabilities) {
        std::cout << "- " << cap << std::endl;
    }

    return 0;
} 
