package main

// Announces this RIFT instance to a NORA hub as the fleet authority, over
// HTTP/WiFi (default) or a Bluetooth serial link. Go counterpart of
// Fleet/register.py + Fleet/bt_link.py: while RIFT keeps heartbeating, NORA
// defers her /robots response to point at RIFT; if it stops, the
// registration simply expires on her side.

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"go.bug.st/serial"
)

const btBaud = 115200

type Authority struct {
	cfg *Config

	mu     sync.Mutex
	mode   string
	btPort string
	cancel context.CancelFunc
	done   chan struct{}
}

func NewAuthority(cfg *Config) *Authority { return &Authority{cfg: cfg, mode: "wifi"} }

func (a *Authority) State() (mode, btPort string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.mode, a.btPort
}

// Restart retires the current heartbeat (if any) and starts one on the given transport.
func (a *Authority) Restart(mode, btPort string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.cancel != nil {
		a.cancel()
		select {
		case <-a.done:
		case <-time.After(2 * time.Second):
		}
	}
	a.mode, a.btPort = mode, btPort
	if a.cfg.NoHeartbeat {
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.cancel, a.done = cancel, make(chan struct{})
	go a.loop(ctx, a.done, mode, btPort)
}

func (a *Authority) Stop() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.cancel != nil {
		a.cancel()
	}
}

func (a *Authority) loop(ctx context.Context, done chan struct{}, mode, btPort string) {
	defer close(done)
	var bt *btLink
	defer func() {
		if bt != nil {
			bt.close()
		}
	}()

	for {
		if mode == "bluetooth" {
			var err error
			if bt == nil {
				bt, err = openBtLink(btPort)
			}
			if err == nil {
				_, err = bt.register(a.cfg.Name, authorityCaps)
			}
			if err != nil && bt != nil {
				bt.close()
				bt = nil
			}
		} else {
			a.announceWifi()
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(a.cfg.HeartbeatEvery):
		}
	}
}

var authorityCaps = []string{"fleet_management", "monitoring"}

func (a *Authority) announceWifi() {
	client := &http.Client{Timeout: 2 * time.Second}
	target := fmt.Sprintf("http://%s:%d/register", a.cfg.NoraHost, a.cfg.NoraPort)
	resp, err := client.PostForm(target, url.Values{
		"name":         {a.cfg.Name},
		"type":         {"fleet_manager"},
		"capabilities": {strings.Join(authorityCaps, ",")},
	})
	if err == nil {
		resp.Body.Close()
	}
	// NORA may not be reachable yet (booting, or not on her AP) - keep retrying.
}

// btLink speaks the fleet-registration half of NORA's Bluetooth protocol:
// send "H<name>:<cap1,cap2>\n", she replies "OK\n" or "ERR\n".
type btLink struct {
	port serial.Port
}

func openBtLink(name string) (*btLink, error) {
	p, err := serial.Open(name, &serial.Mode{BaudRate: btBaud})
	if err != nil {
		return nil, err
	}
	_ = p.SetReadTimeout(2 * time.Second)
	return &btLink{port: p}, nil
}

func (b *btLink) register(name string, caps []string) (bool, error) {
	_ = b.port.ResetInputBuffer()
	if _, err := b.port.Write([]byte(fmt.Sprintf("H%s:%s\n", name, strings.Join(caps, ",")))); err != nil {
		return false, err
	}
	line, err := b.readLine()
	if err != nil {
		return false, err
	}
	return strings.TrimSpace(line) == "OK", nil
}

// readLine reads up to a newline; the port's read timeout returns 0 bytes,
// which we treat as "no reply".
func (b *btLink) readLine() (string, error) {
	var line []byte
	buf := make([]byte, 1)
	for {
		n, err := b.port.Read(buf)
		if err != nil {
			return "", err
		}
		if n == 0 {
			return "", errors.New("timed out waiting for NORA's reply")
		}
		if buf[0] == '\n' {
			return string(line), nil
		}
		line = append(line, buf[0])
	}
}

func (b *btLink) close() { _ = b.port.Close() }
