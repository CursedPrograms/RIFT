// RIFT fleet hub, Go edition: the same fleet registry, dashboard, mDNS
// discovery, NORA fleet-authority heartbeat (WiFi or Bluetooth) and internet
// share as app.py, as one native binary. Speaks the same protocol on the same
// port as app.py and the C++ server, so run one or the other on a given
// machine, not both.
//
//	rift-go                       start the hub on :5000
//	rift-go --scan                scan this /24 for hubs/robots serving /robots
package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

type Config struct {
	Name           string
	Port           int
	IP             string
	Root           string
	TTL            time.Duration
	NoraHost       string
	NoraPort       int
	HeartbeatEvery time.Duration
	NoHeartbeat    bool
}

// Same trick as app.py's _get_ip(): "connect" a UDP socket (no traffic is sent)
// and read back which local address the OS would use.
func localIP() string {
	conn, err := net.Dial("udp", "10.255.255.255:1")
	if err != nil {
		return "127.0.0.1"
	}
	defer conn.Close()
	return conn.LocalAddr().(*net.UDPAddr).IP.String()
}

// findRoot walks up from the executable / working directory until it finds the
// RIFT repo root (app.py next to templates/), so it works from PC App/Go, from
// the repo root, or from a built binary anywhere below it.
func findRoot() string {
	var starts []string
	if exe, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		starts = append(starts, wd)
	}
	for _, start := range starts {
		for dir := start; ; {
			_, errApp := os.Stat(filepath.Join(dir, "app.py"))
			_, errTpl := os.Stat(filepath.Join(dir, "templates", "index.html"))
			if errApp == nil && errTpl == nil {
				return dir
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	wd, _ := os.Getwd()
	return wd
}

func main() {
	cfg := &Config{}
	var (
		scan          = flag.Bool("scan", false, "scan this machine's /24 for hubs/robots serving /robots, then exit")
		noMDNS        = flag.Bool("no-mdns", false, "don't publish/browse mDNS")
		noShare       = flag.Bool("no-internet-share", false, "don't join NORA's AP and share internet to it (Linux/NetworkManager only)")
		heartbeatSecs = flag.Float64("heartbeat-secs", 10, "seconds between heartbeats to NORA (must stay well under her 20s TTL)")
		ttlSecs       = flag.Float64("ttl-secs", 20, "seconds before a silent robot drops out of /robots")
	)
	flag.StringVar(&cfg.Name, "name", "RIFT", "this instance's fleet/mDNS name")
	flag.IntVar(&cfg.Port, "port", 5000, "HTTP port")
	flag.StringVar(&cfg.NoraHost, "nora-host", "192.168.4.1", "NORA's fleet-registry address")
	flag.IntVar(&cfg.NoraPort, "nora-port", 5000, "NORA's fleet-registry port")
	flag.BoolVar(&cfg.NoHeartbeat, "no-heartbeat", false, "don't announce to NORA")
	flag.StringVar(&cfg.Root, "root", "", "RIFT repo root (contains app.py, templates/, static/); auto-detected if omitted")
	flag.Parse()

	if cfg.Root == "" {
		cfg.Root = findRoot()
	}
	cfg.IP = localIP()
	cfg.TTL = time.Duration(*ttlSecs * float64(time.Second))
	cfg.HeartbeatEvery = time.Duration(*heartbeatSecs * float64(time.Second))

	if *scan {
		runScan(cfg.IP, cfg.Port)
		return
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	fmt.Printf("[RIFT] IP   : %s\n[RIFT] Port : %d\n[RIFT] Root : %s\n", cfg.IP, cfg.Port, cfg.Root)

	peers := NewPeers()
	if !*noMDNS {
		stopMDNS, err := StartMDNS(ctx, cfg, peers)
		if err != nil {
			fmt.Println("[RIFT] Continuing without mDNS:", err)
		} else {
			defer stopMDNS()
			fmt.Printf("[RIFT] Zeroconf registered as %s; watching %v\n", cfg.Name, browseTypes)
		}
	}

	authority := NewAuthority(cfg)
	authority.Restart("wifi", "")
	if cfg.NoHeartbeat {
		fmt.Println("[RIFT] Not announcing to NORA (--no-heartbeat)")
	} else {
		fmt.Printf("[RIFT] Announcing to NORA at %s:%d as fleet authority (mode: wifi)\n", cfg.NoraHost, cfg.NoraPort)
	}
	defer authority.Stop()

	if !*noShare {
		StartInternetShare(ctx)
	}

	srv := &Server{cfg: cfg, registry: NewRegistry(cfg.TTL), peers: peers, authority: authority}
	httpServer := &http.Server{Addr: fmt.Sprintf("0.0.0.0:%d", cfg.Port), Handler: srv.Handler()}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(shutdownCtx)
	}()
	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		fmt.Fprintln(os.Stderr, "[RIFT] server error:", err)
		os.Exit(1)
	}
	fmt.Println("[RIFT] Shut down.")
}
