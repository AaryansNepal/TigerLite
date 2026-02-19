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

	batcher := NewBatcher(backendURL)
	go batcher.Run()

	handler := NewHandler(batcher)

	mux := http.NewServeMux()
	mux.HandleFunc("POST /ingest", handler.Ingest)
	mux.HandleFunc("GET /health", handler.Health)
	mux.HandleFunc("GET /metrics", handler.Metrics)

	log.Printf("Go ingestion service starting on :%s (forwarding to %s)", port, backendURL)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
