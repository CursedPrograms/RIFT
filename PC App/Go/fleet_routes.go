package main

// The dashboard's read-only routes, as app.py serves them: /fleet, /clock and
// /colour_scheme.css. Ask & do, music and the mission log are still app.py's;
// the page hides those sections on a hub without them.

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// app.py's WEB_PORTS: each robot's usual web page.
var webPorts = map[string]string{"NORA": "5002", "KIDA00": "5003", "KIDA01": "5004", "WHIP": "5005",
	"DREAM": "5009", "MILA": "5010", "ARM": "5011", "NINA": "5012", "NIKA": "5013", "ARIA": "5014"}

var colourPair = regexp.MustCompile(`name="(\w+)"\s+value="(#[0-9A-Fa-f]{6})"`)
var digits = regexp.MustCompile(`^\d+$`)

// capPort finds "<prefix><port>" among a robot's capabilities.
func capPort(caps []string, prefix string) string {
	for _, c := range caps {
		if p, ok := strings.CutPrefix(c, prefix); ok && digits.MatchString(p) {
			return p
		}
	}
	return ""
}

// webURL is app.py's _web_url: a "web:<port>" capability, its usual port, else "talk:<port>".
func webURL(name, ip string, caps []string) any {
	upper := strings.ToUpper(name)
	port := capPort(caps, "web:")
	if port == "" {
		port = webPorts[upper]
	}
	if port == "" {
		port = capPort(caps, "talk:")
	}
	if port == "" {
		return nil
	}
	scheme := "http"
	if upper == "DREAM" { // DREAM serves HTTPS when it has a certificate
		scheme = "https"
	}
	return fmt.Sprintf("%s://%s:%s/", scheme, ip, port)
}

func colourSchemeCSS(xml string) string {
	var css strings.Builder
	css.WriteString(":root {\n")
	for _, m := range colourPair.FindAllStringSubmatch(xml, -1) {
		fmt.Fprintf(&css, "    --%s: %s;\n", strings.ReplaceAll(m[1], "_", "-"), m[2])
	}
	css.WriteString("}\n")
	return css.String()
}

func (s *Server) fleetRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /fleet", func(w http.ResponseWriter, r *http.Request) {
		roster := s.registry.Robots()
		sort.Slice(roster, func(i, j int) bool { return roster[i].Name < roster[j].Name })
		robots := []map[string]any{}
		for _, b := range roster {
			robots = append(robots, map[string]any{"name": b.Name, "ip": b.IP, "type": b.Type,
				"capabilities": b.Capabilities, "url": webURL(b.Name, b.IP, b.Capabilities)})
		}
		writeJSON(w, http.StatusOK, map[string]any{"robots": robots})
	})

	mux.HandleFunc("GET /clock", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]float64{"t": float64(time.Now().UnixMilli()) / 1000})
	})

	mux.HandleFunc("GET /colour_scheme.css", func(w http.ResponseWriter, r *http.Request) {
		xml, _ := os.ReadFile(filepath.Join(s.cfg.Root, "colour_scheme.xml")) // none: an empty :root, as app.py
		w.Header().Set("Content-Type", "text/css")
		w.Header().Set("Cache-Control", "no-cache")
		_, _ = w.Write([]byte(colourSchemeCSS(string(xml))))
	})
}
