package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"sync/atomic"
	"time"
)

const (
	maxBatchSize  = 50
	flushInterval = 2 * time.Second
)

// Batcher collects telemetry events and flushes them to the Python backend in batches.
// Uses a channel + select + ticker pattern — idiomatic Go concurrency.
type Batcher struct {
	backendURL string
	events     chan TelemetryEvent
	client     *http.Client

	// Atomic counters for the /metrics endpoint
	received atomic.Int64
	flushed  atomic.Int64
	errors   atomic.Int64
}

func NewBatcher(backendURL string) *Batcher {
	return &Batcher{
		backendURL: backendURL,
		events:     make(chan TelemetryEvent, 1000),
		client: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// Submit enqueues an event for batching (non-blocking).
func (b *Batcher) Submit(event TelemetryEvent) {
	b.received.Add(1)
	select {
	case b.events <- event:
	default:
		// Channel full — drop event rather than block the HTTP handler.
		// In production I'd add backpressure or a dead-letter queue here.
		b.errors.Add(1)
		log.Println("WARN: event channel full, dropping event")
	}
}

// Run is the main batching loop. Call this in a goroutine.
func (b *Batcher) Run() {
	ticker := time.NewTicker(flushInterval)
	defer ticker.Stop()

	batch := make([]TelemetryEvent, 0, maxBatchSize)

	for {
		select {
		case event := <-b.events:
			batch = append(batch, event)
			if len(batch) >= maxBatchSize {
				b.flush(batch)
				batch = make([]TelemetryEvent, 0, maxBatchSize)
			}

		case <-ticker.C:
			if len(batch) > 0 {
				b.flush(batch)
				batch = make([]TelemetryEvent, 0, maxBatchSize)
			}
		}
	}
}

// flush sends a batch of events to the Python backend one at a time.
// The Python /ingest endpoint expects a single event, so we forward individually.
// This keeps compatibility simple — the batching value is in reducing goroutine overhead
// and giving us a place to add bulk forwarding later.
func (b *Batcher) flush(batch []TelemetryEvent) {
	for _, event := range batch {
		body, err := json.Marshal(event)
		if err != nil {
			b.errors.Add(1)
			log.Printf("ERROR: marshal failed: %v", err)
			continue
		}

		resp, err := b.client.Post(
			b.backendURL+"/ingest",
			"application/json",
			bytes.NewReader(body),
		)
		if err != nil {
			b.errors.Add(1)
			log.Printf("ERROR: forward to backend failed: %v", err)
			continue
		}
		resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			b.errors.Add(1)
			log.Printf("WARN: backend returned %d", resp.StatusCode)
			continue
		}

		b.flushed.Add(1)
	}
}

// Stats returns the current metric counters.
func (b *Batcher) Stats() (received, flushed, errors int64) {
	return b.received.Load(), b.flushed.Load(), b.errors.Load()
}
