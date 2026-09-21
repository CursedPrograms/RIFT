package main

// HTTP fleet registry + dashboard. Same wire protocol as app.py's Flask routes
// (and NORA's fleet server), so PC App/PyGame/registration.py,
// PC App/App/registration.cpp and every robot's heartbeat work unchanged.

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type Server struct {
	cfg       *Config
	registry  *Registry
	peers     *Peers
	authority *Authority
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeText(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "text/plain")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}

var templateTag = regexp.MustCompile(`\{\{\s*(.*?)\s*\}\}`)
var urlForStatic = regexp.MustCompile(`^url_for\(\s*'static'\s*,\s*filename\s*=\s*'([^']*)'\s*\)$`)

// renderTemplate fills in the handful of Jinja expressions templates/index.html
// uses: {{ this_name }}, {{ my_ip }}, {{ this_port }} and url_for('static', filename=...).
func renderTemplate(tpl string, vars map[string]string) string {
	return templateTag.ReplaceAllStringFunc(tpl, func(tag string) string {
		expr := templateTag.FindStringSubmatch(tag)[1]
		if v, ok := vars[expr]; ok {
			return v
		}
		if m := urlForStatic.FindStringSubmatch(expr); m != nil {
			return "/static/" + m[1]
		}
		return tag
	})
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /ping", func(w http.ResponseWriter, r *http.Request) {
		writeText(w, http.StatusOK, s.cfg.Name+" alive")
	})

	mux.HandleFunc("POST /register", s.handleRegister)

	mux.HandleFunc("GET /robots", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"authority": s.cfg.Name, "robots": s.registry.Robots()})
	})

	mux.HandleFunc("GET /peers", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, s.peers.Snapshot())
	})

	mux.HandleFunc("GET /mode", func(w http.ResponseWriter, r *http.Request) {
		mode, btPort := s.authority.State()
		writeJSON(w, http.StatusOK, map[string]any{"mode": mode, "bt_port": nilIfEmpty(btPort)})
	})
	mux.HandleFunc("POST /mode", s.handleSetMode)

	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		data, err := os.ReadFile(filepath.Join(s.cfg.Root, "templates", "index.html"))
		if err != nil {
			http.Error(w, "dashboard template not found: "+err.Error(), http.StatusInternalServerError)
			return
		}
		html := renderTemplate(string(data), map[string]string{
			"this_name": s.cfg.Name, "my_ip": s.cfg.IP, "this_port": fmt.Sprint(s.cfg.Port),
		})
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(html))
	})

	// http.Dir + FileServer refuses paths that escape the directory.
	mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServer(http.Dir(filepath.Join(s.cfg.Root, "static")))))
	return mux
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// registration is what a robot sends. app.py reads a form body; the Android
// app's Registration.kt sends JSON, so both are accepted.
type registration struct {
	Name         string          `json:"name"`
	IP           string          `json:"ip"`
	Type         string          `json:"type"`
	Capabilities json.RawMessage `json:"capabilities"`
}

func splitCaps(csv string) []string {
	caps := []string{}
	for _, c := range strings.Split(csv, ",") {
		if c != "" {
			caps = append(caps, c)
		}
	}
	return caps
}

func (s *Server) handleRegister(w http.ResponseWriter, r *http.Request) {
	var reg registration
	if strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		_ = json.NewDecoder(r.Body).Decode(&reg)
	} else {
		reg.Name = r.PostFormValue("name")
		reg.IP = ""
		reg.Type = r.PostFormValue("type")
		reg.Capabilities, _ = json.Marshal(r.PostFormValue("capabilities"))
	}
	if reg.Name == "" {
		writeText(w, http.StatusBadRequest, "missing name")
		return
	}
	if reg.Type == "" {
		reg.Type = "unknown"
	}

	var caps []string
	var asList []string
	if json.Unmarshal(reg.Capabilities, &asList) == nil {
		caps = asList
	} else {
		var asString string
		_ = json.Unmarshal(reg.Capabilities, &asString)
		caps = splitCaps(asString)
	}

	ip := reg.IP
	if ip == "" {
		ip, _, _ = net.SplitHostPort(r.RemoteAddr)
	}
	s.registry.Register(reg.Name, ip, reg.Type, caps)
	writeText(w, http.StatusOK, "OK")
}

func (s *Server) handleSetMode(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Mode   string `json:"mode"`
		BtPort string `json:"bt_port"`
	}
	if strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		_ = json.NewDecoder(r.Body).Decode(&body)
	} else {
		body.Mode, body.BtPort = r.PostFormValue("mode"), r.PostFormValue("bt_port")
	}
	mode := strings.ToLower(strings.TrimSpace(body.Mode))
	btPort := strings.TrimSpace(body.BtPort)

	if mode != "wifi" && mode != "bluetooth" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "mode must be 'wifi' or 'bluetooth'"})
		return
	}
	if mode == "bluetooth" && btPort == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bt_port is required for Bluetooth mode"})
		return
	}
	s.authority.Restart(mode, btPort)
	writeJSON(w, http.StatusOK, map[string]any{"mode": mode, "bt_port": nilIfEmpty(btPort)})
}
