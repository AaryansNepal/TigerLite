// Go ingestion service — high-throughput HTTP frontend for telemetry events.
//
// Sits in front of the Python backend to handle burst traffic. Events flow through
// two goroutines: batcher (buffers → forwards to Python) and detector (sliding-window
// anomaly detection → auto-triggers the agent). Uses Go 1.22 method-pattern routing.
package main

import (
	"log"
	"net/http"
	"os"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	backendURL := os.Getenv("BACKEND_URL")
	if backendURL == "" {
		backendURL = "http://localhost:8000"
	}

	// Both run as background goroutines for the lifetime of the process
	batcher := NewBatcher(backendURL)
	go batcher.Run()

	detector := NewDetector(backendURL)
	go detector.Run()

	handler := NewHandler(batcher, detector)

	// Go 1.22 method-pattern routing — no external router needed
	mux := http.NewServeMux()
	mux.HandleFunc("POST /ingest", handler.Ingest)
	mux.HandleFunc("GET /health", handler.Health)
	mux.HandleFunc("GET /metrics", handler.Metrics)

	log.Printf("Go ingestion service starting on :%s (forwarding to %s)", port, backendURL)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}