package main

// Zeroconf: publish this instance as _rift._tcp and watch for other RIFT
// instances and ComCentre (_flask-link._tcp). Go counterpart of app.py's
// _start_zeroconf() / _PeerListener - browsing both is what lets DREAM show
// up in this dashboard without ComCentre knowing anything about RIFT.

import (
	"context"
	"fmt"
	"strings"
	"sync"

	"github.com/grandcat/zeroconf"
)

var browseTypes = []string{"_rift._tcp", "_flask-link._tcp"}

// Peers is name -> "http://ip:port" for every peer seen over mDNS.
type Peers struct {
	mu    sync.Mutex
	items map[string]string
}

func NewPeers() *Peers { return &Peers{items: map[string]string{}} }

func (p *Peers) set(name, url string) {
	p.mu.Lock()
	p.items[name] = url
	p.mu.Unlock()
}

func (p *Peers) remove(name string) {
	p.mu.Lock()
	delete(p.items, name)
	p.mu.Unlock()
}

func (p *Peers) Snapshot() map[string]string {
	p.mu.Lock()
	defer p.mu.Unlock()
	cp := make(map[string]string, len(p.items))
	for k, v := range p.items {
		cp[k] = v
	}
	return cp
}

// StartMDNS publishes the service and starts browsing. The returned function
// unregisters everything.
func StartMDNS(ctx context.Context, cfg *Config, peers *Peers) (stop func(), err error) {
	server, err := zeroconf.Register(cfg.Name, "_rift._tcp", "local.", cfg.Port, []string{"role=fleet_manager"}, nil)
	if err != nil {
		return nil, fmt.Errorf("mDNS register: %w", err)
	}

	for _, service := range browseTypes {
		resolver, err := zeroconf.NewResolver(nil)
		if err != nil {
			server.Shutdown()
			return nil, fmt.Errorf("mDNS browse: %w", err)
		}
		entries := make(chan *zeroconf.ServiceEntry)
		go func() {
			for e := range entries {
				short := strings.Split(e.Instance, ".")[0]
				if short == cfg.Name {
					continue
				}
				if e.TTL == 0 { // goodbye packet
					peers.remove(short)
					continue
				}
				if len(e.AddrIPv4) > 0 {
					peers.set(short, fmt.Sprintf("http://%s:%d", e.AddrIPv4[0], e.Port))
				}
			}
		}()
		if err := resolver.Browse(ctx, service, "local.", entries); err != nil {
			server.Shutdown()
			return nil, fmt.Errorf("mDNS browse %s: %w", service, err)
		}
	}
	return server.Shutdown, nil
}
