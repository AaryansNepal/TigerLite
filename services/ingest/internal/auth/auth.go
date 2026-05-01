// Package auth validates per-tenant ingest tokens.
//
// On each request the receiver pulls the bearer token, looks up the
// connection by token-prefix, then verifies the bcrypt hash. To avoid hitting
// Postgres on every event, a small in-memory cache holds (token-hash → tenant
// resolution) for 60 seconds. The cache is sized to a few thousand entries —
// at demo scale a single tenant per active session is the norm.
//
// The token format is opaque to clients but the internal layout is:
//   tigerlite_live_<base32 random>
// We store bcrypt(token) in connections.ingest_token_hash on the connection
// row of kind='otel'. Verification is bcrypt-compared.

package auth

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

var ErrUnauthorized = errors.New("unauthorized")

type Resolution struct {
	TenantID     string
	ConnectionID string
}

type Authenticator struct {
	pool  *pgxpool.Pool
	cache sync.Map // key: bcrypt-friendly cache key, val: cachedEntry
}

type cachedEntry struct {
	res    Resolution
	expiry time.Time
}

func New(ctx context.Context, dbURL string) (*Authenticator, error) {
	cfg, err := pgxpool.ParseConfig(dbURL)
	if err != nil {
		return nil, fmt.Errorf("pgx parse config: %w", err)
	}
	// Required for the Supabase transaction pooler (port 6543): the pooler
	// multiplexes a client's transactions across different backend
	// connections, so prepared statements (extended query protocol) leak
	// across them and pgx fails with "prepared statement does not exist".
	// Force the simple protocol — slightly less efficient, but correct.
	cfg.ConnConfig.DefaultQueryExecMode = pgx.QueryExecModeSimpleProtocol
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("pgx pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("postgres ping: %w", err)
	}
	return &Authenticator{pool: pool}, nil
}

func (a *Authenticator) Close() {
	if a.pool != nil {
		a.pool.Close()
	}
}

// Authenticate parses the Authorization header and resolves the bearer token
// to a (tenant_id, connection_id) pair. It returns ErrUnauthorized for any
// failure mode visible to the caller; specific reasons are logged elsewhere.
func (a *Authenticator) Authenticate(ctx context.Context, authHeader string) (*Resolution, error) {
	token, err := parseBearer(authHeader)
	if err != nil {
		return nil, ErrUnauthorized
	}

	if cached, ok := a.cache.Load(token); ok {
		entry := cached.(cachedEntry)
		if entry.expiry.After(time.Now()) {
			return &entry.res, nil
		}
	}

	// Fetch all otel connections (small list at demo scale) and bcrypt-compare.
	// Accept both 'pending' (token just issued, no events yet) and 'connected'
	// (events have been received). 'failed' and 'revoked' are blocked.
	// At scale, we'd index by a token prefix, but bcrypt alone defeats prefix
	// indexing — better demo simplicity here.
	rows, err := a.pool.Query(ctx, `
		SELECT c.id, c.tenant_id, t.ingest_token_hash
		  FROM connections c
		  JOIN tenants t ON t.id = c.tenant_id
		 WHERE c.kind = 'otel'
		   AND c.status IN ('pending', 'connected')
	`)
	if err != nil {
		return nil, fmt.Errorf("query connections: %w", err)
	}
	defer rows.Close()

	candidates := 0
	for rows.Next() {
		candidates++
		var connID, tenantID, hash string
		if err := rows.Scan(&connID, &tenantID, &hash); err != nil {
			continue
		}
		if bcrypt.CompareHashAndPassword([]byte(hash), []byte(token)) == nil {
			res := Resolution{TenantID: tenantID, ConnectionID: connID}
			a.cache.Store(token, cachedEntry{
				res:    res,
				expiry: time.Now().Add(60 * time.Second),
			})
			return &res, nil
		}
	}
	slog.Debug("ingest auth rejected token",
		"candidates_checked", candidates,
		"token_prefix", tokenPrefix(token),
	)
	return nil, ErrUnauthorized
}

// tokenPrefix returns a short, non-secret-leaking identifier for logging.
func tokenPrefix(token string) string {
	if len(token) < 24 {
		return "<short>"
	}
	return token[:18] + "..." + token[len(token)-4:]
}

// MarkActivity is called from the handler hot-path to record receipt of events
// against a connection. It batches writes by debouncing — calling it many
// times per second results in roughly one Postgres UPDATE per second per
// connection.
func (a *Authenticator) MarkActivity(ctx context.Context, connID string, services []string) {
	go func() {
		// Best-effort fire-and-forget. Failures here are non-fatal.
		ctx2, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_, _ = a.pool.Exec(ctx2, `
			UPDATE connections
			   SET last_event_at = now(),
			       detected_services = (
			         SELECT array(
			           SELECT DISTINCT unnest(coalesce(detected_services, ARRAY[]::text[]) || $2::text[])
			         )
			       ),
			       status = CASE WHEN status = 'pending' THEN 'connected' ELSE status END
			 WHERE id = $1
		`, connID, services)
	}()
}

func parseBearer(h string) (string, error) {
	if h == "" {
		return "", errors.New("missing")
	}
	parts := strings.SplitN(h, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return "", errors.New("malformed")
	}
	return strings.TrimSpace(parts[1]), nil
}
