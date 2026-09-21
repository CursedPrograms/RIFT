package main

// Fleet registry: robots/managers that have called POST /register, expiring
// after the TTL unless they keep heartbeating. Go counterpart of app.py's
// _fleet dict + _prune_fleet().

import (
	"sync"
	"time"
)

type member struct {
	IP           string
	Type         string
	Capabilities []string
	LastSeen     time.Time
}

// Robot is one entry of the /robots response (same shape NORA and app.py serve).
type Robot struct {
	Name         string   `json:"name"`
	IP           string   `json:"ip"`
	Type         string   `json:"type"`
	Capabilities []string `json:"capabilities"`
}

type Registry struct {
	mu      sync.Mutex
	ttl     time.Duration
	now     func() time.Time
	members map[string]member
	order   []string // insertion order, like a Python dict
}

func NewRegistry(ttl time.Duration) *Registry {
	return &Registry{ttl: ttl, now: time.Now, members: map[string]member{}}
}

func (r *Registry) Register(name, ip, typ string, caps []string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.members[name]; !exists {
		r.order = append(r.order, name)
	}
	if caps == nil {
		caps = []string{}
	}
	r.members[name] = member{IP: ip, Type: typ, Capabilities: caps, LastSeen: r.now()}
}

// Robots returns the live roster, dropping anything not heard from within the TTL.
func (r *Registry) Robots() []Robot {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := r.now()
	live := r.order[:0]
	roster := []Robot{}
	for _, name := range r.order {
		m := r.members[name]
		if now.Sub(m.LastSeen) > r.ttl {
			delete(r.members, name)
			continue
		}
		live = append(live, name)
		roster = append(roster, Robot{Name: name, IP: m.IP, Type: m.Type, Capabilities: m.Capabilities})
	}
	r.order = live
	return roster
}
