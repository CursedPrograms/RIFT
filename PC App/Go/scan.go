package main

// --scan: the subnet-scanning client (Go counterpart of PC App/App/registration.cpp
// and PC App/PyGame/registration.py). Queries every host on this machine's /24
// for :<port>/robots and prints whatever answers.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

type scanResult struct {
	IP     string
	Robots []Robot
}

func scanSubnet(base string, port int) []scanResult {
	client := &http.Client{Timeout: 500 * time.Millisecond}
	var (
		mu      sync.Mutex
		wg      sync.WaitGroup
		results []scanResult
		sem     = make(chan struct{}, 50)
	)
	for i := 1; i < 255; i++ {
		ip := fmt.Sprintf("%s.%d", base, i)
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			resp, err := client.Get(fmt.Sprintf("http://%s:%d/robots", ip, port))
			if err != nil {
				return
			}
			defer resp.Body.Close()
			// RIFT and NORA both serve {"authority": "...", "robots": [...]}, not a bare array.
			var body struct {
				Robots []Robot `json:"robots"`
			}
			if resp.StatusCode == http.StatusOK && json.NewDecoder(resp.Body).Decode(&body) == nil {
				mu.Lock()
				results = append(results, scanResult{IP: ip, Robots: body.Robots})
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	return results
}

func runScan(localIP string, port int) {
	base := localIP[:strings.LastIndex(localIP, ".")] // assumes a /24
	fmt.Printf("Scanning %s.1-254 on port %d...\n", base, port)
	results := scanSubnet(base, port)
	fmt.Println("\n=== Robots Found ===")
	for _, res := range results {
		for _, r := range res.Robots {
			fmt.Printf("%s (%s) @ %s\n  Capabilities: %s\n\n", r.Name, r.Type, res.IP, strings.Join(r.Capabilities, " "))
		}
	}
}
