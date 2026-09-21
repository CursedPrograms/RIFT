package main

// Shares this RIFT instance's existing internet connection out to every
// device that joins NORA's isolated WiFi AP. Go counterpart of
// Fleet/internet_share.py: join NORA's AP as a secondary connection over a
// spare WiFi radio, then let NetworkManager's "shared" method (its own DHCP
// server + NAT) hand internet access to NORA and anything else on her AP,
// while RIFT's own default route is left alone. Linux + NetworkManager only;
// anywhere else it quietly does nothing.

import (
	"context"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

const (
	noraSSID      = "NORA"
	noraPassword  = "12345678"
	shareInterval = 30 * time.Second
)

func nmcli(timeout time.Duration, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, "nmcli", args...).Output()
	return string(out), err
}

func lines(s string) []string {
	var out []string
	for _, l := range strings.Split(s, "\n") {
		if l = strings.TrimSpace(l); l != "" {
			out = append(out, l)
		}
	}
	return out
}

func wifiIface() string {
	out, err := nmcli(20*time.Second, "-t", "-f", "DEVICE,TYPE", "device", "status")
	if err != nil {
		return ""
	}
	for _, l := range lines(out) {
		if parts := strings.Split(l, ":"); len(parts) >= 2 && parts[1] == "wifi" {
			return parts[0]
		}
	}
	return ""
}

func activeConnections() []string {
	out, err := nmcli(20*time.Second, "-t", "-f", "NAME", "connection", "show", "--active")
	if err != nil {
		return nil
	}
	return lines(out)
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// ensureInternetShare joins NORA's AP (if not already) and marks it shared.
// Safe to call repeatedly; a no-op once already connected and shared.
func ensureInternetShare() bool {
	iface := wifiIface()
	if iface == "" {
		return false
	}
	if contains(activeConnections(), noraSSID) {
		return true
	}
	known, err := nmcli(20*time.Second, "-t", "-f", "NAME", "connection", "show")
	if err != nil {
		return false
	}
	if !contains(lines(known), noraSSID) {
		_, _ = nmcli(30*time.Second, "device", "wifi", "connect", noraSSID, "password", noraPassword, "ifname", iface)
		_, _ = nmcli(20*time.Second, "connection", "modify", noraSSID, "ipv4.method", "shared")
	} else {
		_, _ = nmcli(30*time.Second, "connection", "up", noraSSID)
	}
	return contains(activeConnections(), noraSSID)
}

// StartInternetShare keeps NORA's AP joined and shared until ctx is cancelled.
func StartInternetShare(ctx context.Context) {
	if runtime.GOOS != "linux" {
		return
	}
	if _, err := exec.LookPath("nmcli"); err != nil {
		return
	}
	go func() {
		for {
			ensureInternetShare()
			select {
			case <-ctx.Done():
				return
			case <-time.After(shareInterval):
			}
		}
	}()
}
