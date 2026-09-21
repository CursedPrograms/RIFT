package main

import (
	"testing"
	"time"
)

func TestRegisterAndExpire(t *testing.T) {
	now := time.Unix(1000, 0)
	r := NewRegistry(20 * time.Second)
	r.now = func() time.Time { return now }

	r.Register("ARM", "10.0.0.5", "robot", []string{"servo_control", "arm"})
	r.Register("KIDA", "10.0.0.6", "robot", nil)
	if got := r.Robots(); len(got) != 2 || got[0].Name != "ARM" || got[1].Name != "KIDA" {
		t.Fatalf("roster = %+v", got)
	}

	now = now.Add(15 * time.Second)
	r.Register("ARM", "10.0.0.5", "robot", []string{"servo_control", "arm"}) // heartbeat keeps ARM alive
	now = now.Add(10 * time.Second)                                          // KIDA is now 25s stale, ARM 10s
	got := r.Robots()
	if len(got) != 1 || got[0].Name != "ARM" {
		t.Fatalf("after expiry roster = %+v", got)
	}
}

func TestReRegisterKeepsPosition(t *testing.T) {
	r := NewRegistry(time.Minute)
	r.Register("A", "1", "t", nil)
	r.Register("B", "2", "t", nil)
	r.Register("A", "3", "t", nil)
	got := r.Robots()
	if got[0].Name != "A" || got[0].IP != "3" || got[1].Name != "B" {
		t.Fatalf("roster = %+v", got)
	}
}
