// Sliding-window anomaly detector — watches per-customer error rates and latency.
//
// Maintains a 60s rolling window of samples per customer_id. Every 5s, checks if
// any customer exceeds 10% error rate or 1000ms avg latency. On threshold breach,
// POSTs to the Python backend's /api/agent/run to trigger an AI investigation.
// Cooldown period (5m) prevents re-triggering for the same customer.
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
	// windowDuration is how far back we look. Only samples from the last 60s
	// count — anything older gets trimmed on each check cycle.
	windowDuration = 60 * time.Second

	// checkInterval is how often the background loop wakes up to evaluate
	// every customer's health. 5s balances responsiveness vs CPU cost.
	checkInterval = 5 * time.Second

	// cooldownPeriod prevents alert storms. Once we fire an alert for a
	// customer, we won't fire again for them until 5 minutes have passed,
	// even if the anomaly persists.
	cooldownPeriod = 5 * time.Minute

	// errorThreshold is the server-error rate (5xx only) that counts as
	// anomalous. 10% means 1-in-10 requests returning 500+.
	errorThreshold = 0.10 // 10% error rate

	// latencyThreshold is the average response time (in ms) above which we
	// consider the customer's traffic unhealthy.
	latencyThreshold = 1000 // ms

	// minSamples is the minimum number of events in the window before we
	// evaluate. With fewer than 10 data points, a single slow request could
	// spike the average and cause a false positive.
	minSamples = 10 // need at least this many events to judge
)

// sample holds the three values we need per request to compute health stats:
//   - timestamp: when we received it (for window trimming)
//   - statusCode: HTTP status to classify as error (500+) or success
//   - latencyMs: response time to compute average latency
type sample struct {
	timestamp  time.Time
	statusCode int
	latencyMs  float64
}

// Detector watches per-customer stats and triggers the agent on anomalies.
//
// Thread-safety: all reads/writes to windows and cooldowns are guarded by mu.
// The two maps partition state by purpose:
//   - windows: the actual data (recent samples per customer)
//   - cooldowns: rate-limiting state (when we last alerted per customer)
//
// Keeping them separate makes it easy to reason about each concern independently.
type Detector struct {
	mu        sync.Mutex
	windows   map[string][]sample  // customer_id → sliding window of recent samples
	cooldowns map[string]time.Time // customer_id → earliest time we can alert again
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
//
// We use time.Now() as the sample timestamp instead of the event's own
// timestamp because the event timestamp reflects when the request happened
// on the origin server, which may be skewed or delayed. Using wall-clock
// time here keeps the sliding window consistent with the check() ticker.
func (d *Detector) Observe(event TelemetryEvent) {
	// Lock for the shortest scope possible — just the map append.
	// defer ensures we unlock even if append somehow panics.
	d.mu.Lock()
	defer d.mu.Unlock()

	d.windows[event.CustomerID] = append(d.windows[event.CustomerID], sample{
		timestamp:  time.Now(),
		statusCode: event.StatusCode,
		latencyMs:  event.LatencyMs,
	})
}

// Run checks for anomalies every checkInterval. Call in a goroutine.
//
// Uses time.NewTicker for a steady cadence that doesn't drift. The loop
// blocks on ticker.C, so this goroutine sleeps between checks and uses
// zero CPU while waiting.
func (d *Detector) Run() {
	ticker := time.NewTicker(checkInterval)
	defer ticker.Stop()

	for range ticker.C {
		d.check()
	}
}

// check is the core detection logic. It runs under the mutex, trims stale
// samples, computes per-customer stats, and fires alerts when thresholds
// are breached.
func (d *Detector) check() {
	d.mu.Lock()
	defer d.mu.Unlock()

	// cutoff is the oldest timestamp we'll keep. Anything before this gets trimmed.
	cutoff := time.Now().Add(-windowDuration)

	for customerID, samples := range d.windows {
		// --- Trim old samples ---
		// samples[:0] reuses the underlying array but sets length to 0.
		// As we append back only the valid (recent) samples, we avoid
		// allocating a new slice every cycle — the backing array is reused
		// in-place, which is important because this runs every 5s for every customer.
		trimmed := samples[:0]
		for _, s := range samples {
			if s.timestamp.After(cutoff) {
				trimmed = append(trimmed, s)
			}
		}
		d.windows[customerID] = trimmed

		// Skip customers with too few data points. With < minSamples events,
		// the stats are unreliable — one bad request out of 3 looks like a
		// 33% error rate, which would be a false positive.
		if len(trimmed) < minSamples {
			continue
		}

		// --- Compute stats ---
		var errors int
		var totalLatency float64
		for _, s := range trimmed {
			// Only 500+ counts as an error. 4xx responses (bad request, not
			// found, etc.) are client-side mistakes, not service health issues,
			// so we deliberately exclude them from the error rate.
			if s.statusCode >= 500 {
				errors++
			}
			totalLatency += s.latencyMs
		}

		errorRate := float64(errors) / float64(len(trimmed))
		avgLatency := totalLatency / float64(len(trimmed))

		// --- Check thresholds ---
		// OR logic: either a high error rate OR high latency is enough to
		// trigger. We don't require both because they represent different
		// failure modes — a service can be slow but returning 200s, or fast
		// but returning 500s.
		anomaly := errorRate > errorThreshold || avgLatency > latencyThreshold
		if !anomaly {
			continue
		}

		// --- Check cooldown ---
		// If we already alerted for this customer recently, skip. This prevents
		// alert storms where the same degraded customer fires every 5s for the
		// duration of the incident.
		if until, ok := d.cooldowns[customerID]; ok && time.Now().Before(until) {
			continue
		}

		log.Printf("ANOMALY: %s — error_rate=%.1f%% avg_latency=%.0fms (%d samples)",
			customerID, errorRate*100, avgLatency, len(trimmed))

		// Record the cooldown so we don't re-alert for this customer
		// until cooldownPeriod has elapsed.
		d.cooldowns[customerID] = time.Now().Add(cooldownPeriod)

		// Fire the agent call in a goroutine so we don't hold the mutex
		// during the HTTP round-trip. The lock is still held by check(),
		// so without the goroutine we'd block all Observe() calls for the
		// duration of the POST (up to 10s on timeout).
		go d.triggerAgent(customerID, errorRate, avgLatency)
	}
}

// triggerAgent POSTs to the Python backend to kick off an AI investigation.
// The payload fields match what the backend's /api/agent/run endpoint expects:
//   - customer_id: which customer to investigate
//   - trigger: "auto" tells the backend this was machine-initiated (vs "manual")
//   - reason: "anomaly_detected" so the agent knows what kind of investigation to run
//   - error_rate: the computed rate so the agent has context without re-querying
//   - avg_latency: same — gives the agent the numbers that triggered the alert
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
