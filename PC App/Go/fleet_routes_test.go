package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestWebURL(t *testing.T) {
	cases := []struct {
		name string
		caps []string
		want any
	}{
		{"KIDA01", nil, "http://1.2.3.4:5004/"},
		{"KIDA01", []string{"web:8000"}, "http://1.2.3.4:8000/"},
		{"DREAM", nil, "https://1.2.3.4:5009/"},
		{"TINA", []string{"talk:5008"}, "http://1.2.3.4:5008/"},
		{"TINA", []string{"web:x"}, nil},
	}
	for _, c := range cases {
		if got := webURL(c.name, "1.2.3.4", c.caps); got != c.want {
			t.Errorf("%s %v = %v, want %v", c.name, c.caps, got, c.want)
		}
	}
}

func TestColourSchemeCSS(t *testing.T) {
	got := colourSchemeCSS(`<color name="panel_bg" value="#0A0B0C"/><color name="bad" value="red"/>`)
	if want := ":root {\n    --panel-bg: #0A0B0C;\n}\n"; got != want {
		t.Fatalf("css = %q", got)
	}
}

func TestFleetAndClockRoutes(t *testing.T) {
	s := &Server{cfg: &Config{Root: t.TempDir()}, registry: NewRegistry(time.Minute)}
	s.registry.Register("WHIP", "10.0.0.2", "robot", nil)
	s.registry.Register("ARM", "10.0.0.3", "robot", nil)
	mux := http.NewServeMux()
	s.fleetRoutes(mux)

	get := func(path string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		return w
	}
	var fleet struct {
		Robots []struct{ Name, URL string }
	}
	if err := json.Unmarshal(get("/fleet").Body.Bytes(), &fleet); err != nil {
		t.Fatal(err)
	}
	if len(fleet.Robots) != 2 || fleet.Robots[0].Name != "ARM" || fleet.Robots[1].URL != "http://10.0.0.2:5005/" {
		t.Fatalf("fleet = %+v", fleet)
	}
	var clock struct{ T float64 }
	_ = json.Unmarshal(get("/clock").Body.Bytes(), &clock)
	if now := float64(time.Now().Unix()); clock.T < now-5 || clock.T > now+5 {
		t.Fatalf("clock = %v, now %v", clock.T, now)
	}
	if w := get("/colour_scheme.css"); w.Code != 200 || w.Body.String() != ":root {\n}\n" {
		t.Fatalf("css %d %q", w.Code, w.Body.String())
	}
}
