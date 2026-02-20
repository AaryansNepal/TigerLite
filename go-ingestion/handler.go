// HTTP handler — validates incoming telemetry, fans out to batcher + detector.
//
// Each POST /ingest does two things: queues the event for batch forwarding to
// the Python backend (Iceberg storage) and feeds it to the anomaly detector.
// The struct mirrors backend/src/schema.py exactly for zero-translation forwarding.
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// TelemetryEvent mirrors the Python Pydantic model exactly.
type TelemetryEvent struct {
	Timestamp     string  `json:"timestamp"`
	TraceID       string  `json:"trace_id"`
	CustomerID    string  `json:"customer_id"`
	CustomerName  string  `json:"customer_name"`
	Endpoint      string  `json:"endpoint"`
	Method        string  `json:"method"`
	StatusCode    int     `json:"status_code"`
	LatencyMs     float64 `json:"latency_ms"`
	DeployVersion string  `json:"deploy_version"`
	Region        string  `json:"region"`
	ErrorMessage  *string `json:"error_message"`
}

type Handler struct {
	batcher  *Batcher
	detector *Detector
}

func NewHandler(b *Batcher, d *Detector) *Handler {
	return &Handler{batcher: b, detector: d}
}

func (e *TelemetryEvent) validate() error {
	var missing []string
	if e.Timestamp == "" {
		missing = append(missing, "timestamp")
	}
	if e.TraceID == "" {
		missing = append(missing, "trace_id")
	}
	if e.CustomerID == "" {
		missing = append(missing, "customer_id")
	}
	if e.Endpoint == "" {
		missing = append(missing, "endpoint")
	}
	if e.Method == "" {
		missing = append(missing, "method")
	}
	if e.DeployVersion == "" {
		missing = append(missing, "deploy_version")
	}
	if e.Region == "" {
		missing = append(missing, "region")
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required fields: %s", strings.Join(missing, ", "))
	}
	return nil
}

func (h *Handler) Ingest(w http.ResponseWriter, r *http.Request) {
	var event TelemetryEvent
	if err := json.NewDecoder(r.Body).Decode(&event); err != nil {
		http.Error(w, `{"error":"invalid JSON"}`, http.StatusBadRequest)
		return
	}

	if err := event.validate(); err != nil {
		http.Error(w, fmt.Sprintf(`{"error":"%s"}`, err.Error()), http.StatusBadRequest)
		return
	}

	// Job A: queue for Iceberg storage
	h.batcher.Submit(event)

	// Job B: feed the anomaly detector
	h.detector.Observe(event)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	fmt.Fprintf(w, `{"status":"accepted","timestamp":"%s"}`, time.Now().UTC().Format(time.RFC3339))
}

func (h *Handler) Health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprint(w, `{"status":"ok","service":"go-ingestion"}`)
}

func (h *Handler) Metrics(w http.ResponseWriter, r *http.Request) {
	received, flushed, errors := h.batcher.Stats()
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"events_received":%d,"events_flushed":%d,"flush_errors":%d}`,
		received, flushed, errors)
}