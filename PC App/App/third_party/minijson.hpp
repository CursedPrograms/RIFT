// json.hpp - Minimal, dependency-free JSON value type: parse() and dump().
//
// Supports the subset of JSON this project needs (config.json, saved macro
// files, and the Fleet HTTP API's request/response bodies): null, bool,
// number, string, array, and object (objects preserve insertion order).
// Not a general-purpose/standards-exhaustive parser - just enough to avoid
// pulling in a third-party JSON library for a handful of small, known shapes.
#pragma once

#include <cctype>
#include <cmath>
#include <cstdio>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

class Json {
public:
    enum class Type { Null, Bool, Number, String, Array, Object };

    Type type = Type::Null;
    bool bool_value = false;
    double num_value = 0.0;
    std::string str_value;
    std::vector<Json> arr_value;
    std::vector<std::pair<std::string, Json>> obj_value;

    Json() = default;

    static Json makeNull() { return Json(); }
    static Json makeBool(bool v) { Json j; j.type = Type::Bool; j.bool_value = v; return j; }
    static Json makeNumber(double v) { Json j; j.type = Type::Number; j.num_value = v; return j; }
    static Json makeString(std::string v) { Json j; j.type = Type::String; j.str_value = std::move(v); return j; }
    static Json makeArray() { Json j; j.type = Type::Array; return j; }
    static Json makeObject() { Json j; j.type = Type::Object; return j; }

    bool isNull() const { return type == Type::Null; }
    bool isObject() const { return type == Type::Object; }
    bool isArray() const { return type == Type::Array; }

    // ---- Object helpers ----
    Json* find(const std::string& key) {
        for (auto& kv : obj_value) if (kv.first == key) return &kv.second;
        return nullptr;
    }
    const Json* find(const std::string& key) const {
        for (auto& kv : obj_value) if (kv.first == key) return &kv.second;
        return nullptr;
    }
    // Inserts (or replaces) a key, preserving first-seen order.
    Json& set(const std::string& key, Json value) {
        if (Json* existing = find(key)) { *existing = std::move(value); return *existing; }
        obj_value.emplace_back(key, std::move(value));
        return obj_value.back().second;
    }

    void push_back(Json v) { arr_value.push_back(std::move(v)); }

    // ---- Scalar accessors with fallback defaults ----
    double asDouble(double def = 0.0) const { return type == Type::Number ? num_value : def; }
    int asInt(int def = 0) const { return type == Type::Number ? static_cast<int>(std::lround(num_value)) : def; }
    bool asBool(bool def = false) const { return type == Type::Bool ? bool_value : def; }
    std::string asString(const std::string& def = "") const { return type == Type::String ? str_value : def; }

    double get(const std::string& key, double def) const {
        const Json* v = find(key);
        return v ? v->asDouble(def) : def;
    }
    int get(const std::string& key, int def) const {
        const Json* v = find(key);
        return v ? v->asInt(def) : def;
    }
    bool get(const std::string& key, bool def) const {
        const Json* v = find(key);
        return v ? v->asBool(def) : def;
    }
    std::string get(const std::string& key, const std::string& def) const {
        const Json* v = find(key);
        return v ? v->asString(def) : def;
    }

    // ---- Serialization ----
    std::string dump() const {
        std::ostringstream out;
        dumpTo(out);
        return out.str();
    }

    // ---- Parsing ----
    static Json parse(const std::string& text) {
        Parser p(text);
        p.skipWs();
        Json v = p.parseValue();
        p.skipWs();
        return v;
    }

private:
    void dumpTo(std::ostringstream& out) const {
        switch (type) {
            case Type::Null: out << "null"; break;
            case Type::Bool: out << (bool_value ? "true" : "false"); break;
            case Type::Number: dumpNumber(out); break;
            case Type::String: dumpString(out, str_value); break;
            case Type::Array: {
                out << '[';
                for (size_t i = 0; i < arr_value.size(); i++) {
                    if (i) out << ',';
                    arr_value[i].dumpTo(out);
                }
                out << ']';
                break;
            }
            case Type::Object: {
                out << '{';
                for (size_t i = 0; i < obj_value.size(); i++) {
                    if (i) out << ',';
                    dumpString(out, obj_value[i].first);
                    out << ':';
                    obj_value[i].second.dumpTo(out);
                }
                out << '}';
                break;
            }
        }
    }

    void dumpNumber(std::ostringstream& out) const {
        double rounded = std::round(num_value);
        if (std::fabs(num_value - rounded) < 1e-9 && std::fabs(num_value) < 1e15) {
            out << static_cast<long long>(rounded);
        } else {
            char buf[64];
            std::snprintf(buf, sizeof(buf), "%.6g", num_value);
            out << buf;
        }
    }

    static void dumpString(std::ostringstream& out, const std::string& s) {
        out << '"';
        for (unsigned char c : s) {
            switch (c) {
                case '"': out << "\\\""; break;
                case '\\': out << "\\\\"; break;
                case '\n': out << "\\n"; break;
                case '\r': out << "\\r"; break;
                case '\t': out << "\\t"; break;
                default:
                    if (c < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                        out << buf;
                    } else {
                        out << static_cast<char>(c);
                    }
            }
        }
        out << '"';
    }

    struct Parser {
        const std::string& text;
        size_t pos = 0;
        explicit Parser(const std::string& t) : text(t) {}

        char peek() const { return pos < text.size() ? text[pos] : '\0'; }
        char next() { return pos < text.size() ? text[pos++] : '\0'; }

        void skipWs() {
            while (pos < text.size() && std::isspace(static_cast<unsigned char>(text[pos]))) pos++;
        }

        void expect(char c) {
            if (next() != c) throw std::runtime_error(std::string("json: expected '") + c + "'");
        }

        Json parseValue() {
            skipWs();
            switch (peek()) {
                case '{': return parseObject();
                case '[': return parseArray();
                case '"': return Json::makeString(parseString());
                case 't': expectLiteral("true"); return Json::makeBool(true);
                case 'f': expectLiteral("false"); return Json::makeBool(false);
                case 'n': expectLiteral("null"); return Json::makeNull();
                default: return Json::makeNumber(parseNumber());
            }
        }

        void expectLiteral(const char* lit) {
            for (const char* p = lit; *p; p++) expect(*p);
        }

        Json parseObject() {
            Json obj = Json::makeObject();
            expect('{');
            skipWs();
            if (peek() == '}') { next(); return obj; }
            while (true) {
                skipWs();
                std::string key = parseString();
                skipWs();
                expect(':');
                Json value = parseValue();
                obj.obj_value.emplace_back(std::move(key), std::move(value));
                skipWs();
                char c = next();
                if (c == ',') continue;
                if (c == '}') break;
                throw std::runtime_error("json: expected ',' or '}' in object");
            }
            return obj;
        }

        Json parseArray() {
            Json arr = Json::makeArray();
            expect('[');
            skipWs();
            if (peek() == ']') { next(); return arr; }
            while (true) {
                arr.arr_value.push_back(parseValue());
                skipWs();
                char c = next();
                if (c == ',') continue;
                if (c == ']') break;
                throw std::runtime_error("json: expected ',' or ']' in array");
            }
            return arr;
        }

        std::string parseString() {
            expect('"');
            std::string out;
            while (true) {
                char c = next();
                if (c == '\0') throw std::runtime_error("json: unterminated string");
                if (c == '"') break;
                if (c == '\\') {
                    char esc = next();
                    switch (esc) {
                        case '"': out += '"'; break;
                        case '\\': out += '\\'; break;
                        case '/': out += '/'; break;
                        case 'b': out += '\b'; break;
                        case 'f': out += '\f'; break;
                        case 'n': out += '\n'; break;
                        case 'r': out += '\r'; break;
                        case 't': out += '\t'; break;
                        case 'u': {
                            unsigned code = 0;
                            for (int i = 0; i < 4; i++) {
                                char h = next();
                                code <<= 4;
                                if (h >= '0' && h <= '9') code |= (h - '0');
                                else if (h >= 'a' && h <= 'f') code |= (h - 'a' + 10);
                                else if (h >= 'A' && h <= 'F') code |= (h - 'A' + 10);
                            }
                            // Basic BMP-only encode to UTF-8 (macros/config never contain
                            // non-ASCII text in this project, so surrogate pairs aren't handled).
                            if (code < 0x80) {
                                out += static_cast<char>(code);
                            } else if (code < 0x800) {
                                out += static_cast<char>(0xC0 | (code >> 6));
                                out += static_cast<char>(0x80 | (code & 0x3F));
                            } else {
                                out += static_cast<char>(0xE0 | (code >> 12));
                                out += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
                                out += static_cast<char>(0x80 | (code & 0x3F));
                            }
                            break;
                        }
                        default: out += esc;
                    }
                } else {
                    out += c;
                }
            }
            return out;
        }

        double parseNumber() {
            size_t start = pos;
            if (peek() == '-') next();
            while (std::isdigit(static_cast<unsigned char>(peek()))) next();
            if (peek() == '.') { next(); while (std::isdigit(static_cast<unsigned char>(peek()))) next(); }
            if (peek() == 'e' || peek() == 'E') {
                next();
                if (peek() == '+' || peek() == '-') next();
                while (std::isdigit(static_cast<unsigned char>(peek()))) next();
            }
            if (pos == start) throw std::runtime_error("json: expected number");
            return std::stod(text.substr(start, pos - start));
        }
    };
};
