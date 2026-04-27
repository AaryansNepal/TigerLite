// Package iceberg writes row batches to Iceberg tables.
//
// Phase 0 implementation: ship the batch as JSON to the control-plane's
// /internal/iceberg/append endpoint, which uses PyIceberg to commit. This
// keeps Go responsible only for hot-path receive/auth/batch and Python
// responsible for Iceberg metadata correctness.
//
// A future variant could embed Iceberg directly via the Apache Iceberg Go
// project (github.com/apache/iceberg-go) once it stabilises.

package iceberg

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type SignalKind string

const (
	SignalTraces  SignalKind = "traces"
	SignalLogs    SignalKind = "logs"
	SignalMetrics SignalKind = "metrics"
)

// Batch is the JSON payload posted to the control plane.
type Batch struct {
	TenantID  string                   `json:"tenant_id"`
	Signal    SignalKind               `json:"signal"`
	Rows      []map[string]interface{} `json:"rows"`
	Generated time.Time                `json:"generated_at"`
}

type Writer interface {
	Write(ctx context.Context, batch Batch) error
}

type HTTPWriter struct {
	endpoint string
	client   *http.Client
}

func NewHTTPWriter(endpoint string) *HTTPWriter {
	return &HTTPWriter{
		endpoint: endpoint,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (w *HTTPWriter) Write(ctx context.Context, batch Batch) error {
	body, err := json.Marshal(batch)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, w.endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Tigerlite-Internal", "1")

	resp, err := w.client.Do(req)
	if err != nil {
		return fmt.Errorf("post: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("control plane returned %s", resp.Status)
	}
	return nil
}
