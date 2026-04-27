// services/ingest is TigerLite v2's OTLP/HTTP receiver.
//
// Responsibilities (Phase 0):
//   - Accept OTLP/HTTP at /v1/traces, /v1/logs, /v1/metrics.
//   - Authenticate the per-tenant ingest token (Authorization: Bearer <token>)
//     against the connections table in Postgres.
//   - Convert OTLP messages into row batches keyed by tenant_id.
//   - Write batches to Apache Iceberg tables on S3-compatible storage,
//     partitioned by (tenant_id, day).
//   - Update connections.last_event_at and connections.detected_services so
//     the dashboard can flip the "Connected" state.
//
// Hot path:
//   request → auth.Authenticate → batcher.Push → batcher.flush →
//   iceberg.Append (transactional commit per batch).
//
// The Iceberg writer in this MVP shells out to a sidecar Python helper for the
// commit because Go's Iceberg ecosystem is still maturing. The sidecar is the
// control-plane FastAPI service exposing /internal/iceberg/append. This
// keeps the hot path Go-fast and the Iceberg-correctness Python-clean.

package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/AaryansNepal/TigerLite/services/ingest/internal/auth"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/batcher"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/config"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/handler"
	"github.com/AaryansNepal/TigerLite/services/ingest/internal/iceberg"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Error("config load failed", "err", err)
		os.Exit(1)
	}

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: cfg.LogLevel}))
	slog.SetDefault(logger)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	authn, err := auth.New(ctx, cfg.DatabaseURL)
	if err != nil {
		slog.Error("auth init failed", "err", err)
		os.Exit(1)
	}
	defer authn.Close()

	writer := iceberg.NewHTTPWriter(cfg.ControlPlaneURL + "/internal/iceberg/append")

	b := batcher.New(batcher.Config{
		MaxBatchSize:  cfg.BatchMaxSize,
		FlushInterval: cfg.BatchFlushInterval,
		Writer:        writer,
	})
	go b.Run(ctx)

	mux := handler.NewMux(authn, b)

	srv := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		slog.Info("ingest listening", "addr", cfg.ListenAddr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("server error", "err", err)
			cancel()
		}
	}()

	<-ctx.Done()
	slog.Info("shutdown signal received, flushing batcher")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	_ = srv.Shutdown(shutdownCtx)
	b.Drain(shutdownCtx)
	slog.Info("clean shutdown complete")
}
