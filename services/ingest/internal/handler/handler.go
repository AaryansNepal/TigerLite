// Package handler implements the OTLP/HTTP endpoints.
//
// Three signals → /v1/traces, /v1/logs, /v1/metrics. We accept both
// application/x-protobuf (the OTLP standard) and application/json (which
// most OTel SDKs can be configured for in dev). The protobuf path uses
// the official collector pdata package to unmarshal.
//
// The decoded rows are pushed into the batcher; success returns 200 with an
// empty body (acceptable for the clients we target).

package handler

import (
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"

	"github.com/AaryansNepal/TigerLite/services/ingest/internal/auth"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/batcher"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/iceberg"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/otlpconv"
)

type server struct {
	auth    *auth.Authenticator
	batcher *batcher.Batcher
}

func NewMux(authn *auth.Authenticator, b *batcher.Batcher) http.Handler {
	s := &server{auth: authn, batcher: b}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", healthHandler)
	mux.HandleFunc("GET /metrics", metricsHandler)
	mux.HandleFunc("POST /v1/traces", s.protect(s.handleTraces))
	mux.HandleFunc("POST /v1/logs", s.protect(s.handleLogs))
	mux.HandleFunc("POST /v1/metrics", s.protect(s.handleMetrics))
	return mux
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"service": "tigerlite-ingest",
		"status":  "ok",
		"version": "2.0.0-dev",
		"now":     time.Now().UTC().Format(time.RFC3339),
	})
}

func metricsHandler(w http.ResponseWriter, r *http.Request) {
	// Phase 0 placeholder; wire prometheus or expvar later if useful.
	w.Header().Set("Content-Type", "text/plain")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("# tigerlite-ingest metrics placeholder\n"))
}

type tenantHandler func(w http.ResponseWriter, r *http.Request, res *auth.Resolution)

func (s *server) protect(h tenantHandler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		res, err := s.auth.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			if errors.Is(err, auth.ErrUnauthorized) {
				http.Error(w, "unauthorized", http.StatusUnauthorized)
				return
			}
			slog.Error("auth error", "err", err)
			http.Error(w, "internal error", http.StatusInternalServerError)
			return
		}
		h(w, r, res)
	}
}

func (s *server) handleTraces(w http.ResponseWriter, r *http.Request, res *auth.Resolution) {
	body, err := readRequestBody(w, r)
	if err != nil {
		http.Error(w, "read body: "+err.Error(), http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	var td ptrace.Traces
	if isJSON(r) {
		td, err = (&ptrace.JSONUnmarshaler{}).UnmarshalTraces(body)
	} else {
		td, err = (&ptrace.ProtoUnmarshaler{}).UnmarshalTraces(body)
	}
	if err != nil {
		slog.Warn("traces decode failed",
			"err", err,
			"content_type", r.Header.Get("Content-Type"),
			"content_encoding", r.Header.Get("Content-Encoding"),
			"bytes", len(body),
		)
		http.Error(w, "decode error: "+err.Error(), http.StatusBadRequest)
		return
	}

	rows, services := otlpconv.TracesToRows(res.TenantID, td)
	s.batcher.Push(res.TenantID, iceberg.SignalTraces, rows)
	s.auth.MarkActivity(r.Context(), res.ConnectionID, services)
	w.WriteHeader(http.StatusOK)
}

func (s *server) handleLogs(w http.ResponseWriter, r *http.Request, res *auth.Resolution) {
	body, err := readRequestBody(w, r)
	if err != nil {
		http.Error(w, "read body: "+err.Error(), http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	var ld plog.Logs
	if isJSON(r) {
		ld, err = (&plog.JSONUnmarshaler{}).UnmarshalLogs(body)
	} else {
		ld, err = (&plog.ProtoUnmarshaler{}).UnmarshalLogs(body)
	}
	if err != nil {
		slog.Warn("logs decode failed",
			"err", err,
			"content_type", r.Header.Get("Content-Type"),
			"content_encoding", r.Header.Get("Content-Encoding"),
			"bytes", len(body),
		)
		http.Error(w, "decode error: "+err.Error(), http.StatusBadRequest)
		return
	}

	rows, services := otlpconv.LogsToRows(res.TenantID, ld)
	s.batcher.Push(res.TenantID, iceberg.SignalLogs, rows)
	s.auth.MarkActivity(r.Context(), res.ConnectionID, services)
	w.WriteHeader(http.StatusOK)
}

func (s *server) handleMetrics(w http.ResponseWriter, r *http.Request, res *auth.Resolution) {
	body, err := readRequestBody(w, r)
	if err != nil {
		http.Error(w, "read body: "+err.Error(), http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	var md pmetric.Metrics
	if isJSON(r) {
		md, err = (&pmetric.JSONUnmarshaler{}).UnmarshalMetrics(body)
	} else {
		md, err = (&pmetric.ProtoUnmarshaler{}).UnmarshalMetrics(body)
	}
	if err != nil {
		slog.Warn("metrics decode failed",
			"err", err,
			"content_type", r.Header.Get("Content-Type"),
			"content_encoding", r.Header.Get("Content-Encoding"),
			"bytes", len(body),
		)
		http.Error(w, "decode error: "+err.Error(), http.StatusBadRequest)
		return
	}

	rows, services := otlpconv.MetricsToRows(res.TenantID, md)
	s.batcher.Push(res.TenantID, iceberg.SignalMetrics, rows)
	s.auth.MarkActivity(r.Context(), res.ConnectionID, services)
	w.WriteHeader(http.StatusOK)
}

func isJSON(r *http.Request) bool {
	return strings.Contains(strings.ToLower(r.Header.Get("Content-Type")), "json")
}

// readRequestBody reads up to maxBytes from r.Body, decompressing transparently
// if Content-Encoding is gzip (the OTel collector's default). Returns the raw
// bytes ready to feed to ptrace/plog/pmetric Unmarshaler.
func readRequestBody(w http.ResponseWriter, r *http.Request) ([]byte, error) {
	const maxBytes = 16 << 20

	var reader io.Reader = http.MaxBytesReader(w, r.Body, maxBytes)

	enc := strings.ToLower(strings.TrimSpace(r.Header.Get("Content-Encoding")))
	switch enc {
	case "", "identity":
		// no decompression
	case "gzip":
		gz, err := gzip.NewReader(reader)
		if err != nil {
			return nil, fmt.Errorf("gzip header: %w", err)
		}
		defer gz.Close()
		// Cap decompressed size too — gzip bombs are a thing.
		reader = io.LimitReader(gz, maxBytes*8)
	default:
		return nil, fmt.Errorf("unsupported Content-Encoding %q", enc)
	}

	body, err := io.ReadAll(reader)
	if err != nil {
		return nil, err
	}
	return body, nil
}
