package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"
)

const (
	windowDuration = 60 * time.Second
	checkInterval  = 5 * time.Second
	cooldownPeriod = 5 * time.Minute
	errorThreshold = 0.10  // 10% error rate
	latencyThreshold = 1000 // ms
	minSamples     = 10    // need at least this many events to judge
)

type sample struct {
	timestamp  time.Time
	statusCode int
	latencyMs  float64
}

// Detector watches per-customer stats and triggers the agent on anomalies.
type Detector struct {
	mu        sync.Mutex
	windows   map[string][]sample    // customer_id → sliding window
	cooldowns map[string]time.Time   // customer_id → don't re-trigger until
	client    *http.Client
	agentURL  string
}

func NewDetector(backendURL string) *Detector {
	return &Detector{
		windows:   make(map[string][]sample),
		cooldowns: make(map[string]time.Time),
		client:    &http.Client{Timeout: 10 * time.Second},
		agentURL:  backendURL + "/api/agent/run",
	}
}

// Observe records one event. Called from the ingest handler.
func (d *Detector) Observe(event TelemetryEvent) {
	d.mu.Lock()
	defer d.mu.Unlock()

	d.windows[event.CustomerID] = append(d.windows[event.CustomerID], sample{
		timestamp:  time.Now(),
		statusCode: event.StatusCode,
		latencyMs:  event.LatencyMs,
	})
}

// Run checks for anomalies every checkInterval. Call in a goroutine.
func (d *Detector) Run() {
	ticker := time.NewTicker(checkInterval)
	defer ticker.Stop()

	for range ticker.C {
		d.check()
	}
}

func (d *Detector) check() {
	d.mu.Lock()
	defer d.mu.Unlock()

	cutoff := time.Now().Add(-windowDuration)

	for customerID, samples := range d.windows {
		// Trim old samples
		trimmed := samples[:0]
		for _, s := range samples {
			if s.timestamp.After(cutoff) {
				trimmed = append(trimmed, s)
			}
		}
		d.windows[customerID] = trimmed

		if len(trimmed) < minSamples {
			continue
		}

		// Compute stats
		var errors int
		var totalLatency float64
		for _, s := range trimmed {
			if s.statusCode >= 500 {
				errors++
			}
			totalLatency += s.latencyMs
		}

		errorRate := float64(errors) / float64(len(trimmed))
		avgLatency := totalLatency / float64(len(trimmed))

		// Check thresholds
		anomaly := errorRate > errorThreshold || avgLatency > latencyThreshold
		if !anomaly {
			continue
		}

		// Check cooldown
		if until, ok := d.cooldowns[customerID]; ok && time.Now().Before(until) {
			continue
		}

		log.Printf("ANOMALY: %s — error_rate=%.1f%% avg_latency=%.0fms (%d samples)",
			customerID, errorRate*100, avgLatency, len(trimmed))

		d.cooldowns[customerID] = time.Now().Add(cooldownPeriod)

		go d.triggerAgent(customerID, errorRate, avgLatency)
	}
}

func (d *Detector) triggerAgent(customerID string, errorRate, avgLatency float64) {
	payload, _ := json.Marshal(map[string]any{
		"customer_id": customerID,
		"trigger":     "auto",
		"reason":      "anomaly_detected",
		"error_rate":  errorRate,
		"avg_latency": avgLatency,
	})

	resp, err := d.client.Post(d.agentURL, "application/json", bytes.NewReader(payload))
	if err != nil {
		log.Printf("ERROR: failed to trigger agent for %s: %v", customerID, err)
		return
	}
	resp.Body.Close()
	log.Printf("Agent triggered for %s (status=%d)", customerID, resp.StatusCode)
}