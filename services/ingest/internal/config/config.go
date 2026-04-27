package config

import (
	"errors"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	ListenAddr         string
	DatabaseURL        string
	ControlPlaneURL    string
	BatchMaxSize       int
	BatchFlushInterval time.Duration
	LogLevel           slog.Level
}

func Load() (*Config, error) {
	c := &Config{
		ListenAddr:         envDefault("INGEST_LISTEN_ADDR", ":8080"),
		DatabaseURL:        os.Getenv("DATABASE_URL"),
		ControlPlaneURL:    envDefault("CONTROL_PLANE_URL", "http://localhost:8000"),
		BatchMaxSize:       envInt("INGEST_BATCH_MAX_SIZE", 500),
		BatchFlushInterval: envDuration("INGEST_BATCH_FLUSH_INTERVAL", 2*time.Second),
		LogLevel:           parseLogLevel(envDefault("LOG_LEVEL", "info")),
	}
	if c.DatabaseURL == "" {
		return nil, errors.New("DATABASE_URL is required")
	}
	return c, nil
}

func envDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envDuration(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

func parseLogLevel(s string) slog.Level {
	switch strings.ToLower(s) {
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}
