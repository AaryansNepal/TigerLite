// Package otlpconv converts OTLP pdata types into row-shaped maps that
// match the Iceberg schemas in docs/DATA_MODEL.md.
//
// The shapes deliberately mirror the columns the agent will SELECT against,
// with a few common attributes promoted out of the attributes map for fast
// filtering (http_route, http_status_code, db_system, etc.).

package otlpconv

import (
	"encoding/json"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

// TracesToRows flattens a ptrace.Traces value into rows matching the traces
// Iceberg table. Returns the rows and the set of distinct service.name
// values seen, which the receiver feeds into connections.detected_services.
func TracesToRows(tenantID string, td ptrace.Traces) ([]map[string]interface{}, []string) {
	rows := make([]map[string]interface{}, 0, td.SpanCount())
	services := newStringSet()

	rss := td.ResourceSpans()
	for i := 0; i < rss.Len(); i++ {
		rs := rss.At(i)
		resAttrs := attrMap(rs.Resource().Attributes())
		serviceName := getString(resAttrs, "service.name")
		serviceVersion := getString(resAttrs, "service.version")
		if serviceName != "" {
			services.add(serviceName)
		}

		sss := rs.ScopeSpans()
		for j := 0; j < sss.Len(); j++ {
			ss := sss.At(j)
			scopeName := ss.Scope().Name()
			scopeVersion := ss.Scope().Version()

			spans := ss.Spans()
			for k := 0; k < spans.Len(); k++ {
				sp := spans.At(k)
				attrs := attrMap(sp.Attributes())
				start := sp.StartTimestamp().AsTime()
				end := sp.EndTimestamp().AsTime()
				durationMs := float64(end.Sub(start).Microseconds()) / 1000.0

				row := map[string]interface{}{
					"tenant_id":           tenantID,
					"trace_id":            sp.TraceID().String(),
					"span_id":             sp.SpanID().String(),
					"parent_span_id":      sp.ParentSpanID().String(),
					"trace_state":         sp.TraceState().AsRaw(),
					"start_time":          start.UTC().Format(time.RFC3339Nano),
					"end_time":            end.UTC().Format(time.RFC3339Nano),
					"duration_ms":         durationMs,
					"service_name":        serviceName,
					"service_version":     serviceVersion,
					"scope_name":          scopeName,
					"scope_version":       scopeVersion,
					"span_name":           sp.Name(),
					"span_kind":           sp.Kind().String(),
					"status_code":         sp.Status().Code().String(),
					"status_message":      sp.Status().Message(),
					"attributes":          attrs,
					"resource_attributes": resAttrs,
					"http_method":         getString(attrs, "http.request.method", "http.method"),
					"http_route":          getString(attrs, "http.route", "url.path"),
					"http_status_code":    getInt(attrs, "http.response.status_code", "http.status_code"),
					"http_url":            getString(attrs, "http.url", "url.full"),
					"rpc_method":          getString(attrs, "rpc.method"),
					"rpc_service":         getString(attrs, "rpc.service"),
					"db_system":           getString(attrs, "db.system"),
					"db_statement":        getString(attrs, "db.statement"),
					"events":              eventsToJSON(sp.Events()),
					"links":               linksToJSON(sp.Links()),
					"ingested_at":         time.Now().UTC().Format(time.RFC3339Nano),
					"day":                 start.UTC().Format("2006-01-02"),
				}
				rows = append(rows, row)
			}
		}
	}
	return rows, services.values()
}

// LogsToRows flattens plog.Logs into the logs Iceberg row shape.
func LogsToRows(tenantID string, ld plog.Logs) ([]map[string]interface{}, []string) {
	rows := make([]map[string]interface{}, 0, ld.LogRecordCount())
	services := newStringSet()

	rls := ld.ResourceLogs()
	for i := 0; i < rls.Len(); i++ {
		rl := rls.At(i)
		resAttrs := attrMap(rl.Resource().Attributes())
		serviceName := getString(resAttrs, "service.name")
		if serviceName != "" {
			services.add(serviceName)
		}

		sls := rl.ScopeLogs()
		for j := 0; j < sls.Len(); j++ {
			sl := sls.At(j)
			scopeName := sl.Scope().Name()

			records := sl.LogRecords()
			for k := 0; k < records.Len(); k++ {
				rec := records.At(k)
				attrs := attrMap(rec.Attributes())
				body, bodyType := bodyToString(rec.Body())

				row := map[string]interface{}{
					"tenant_id":           tenantID,
					"trace_id":            rec.TraceID().String(),
					"span_id":             rec.SpanID().String(),
					"time":                rec.Timestamp().AsTime().UTC().Format(time.RFC3339Nano),
					"observed_time":       rec.ObservedTimestamp().AsTime().UTC().Format(time.RFC3339Nano),
					"severity_text":       rec.SeverityText(),
					"severity_number":     int32(rec.SeverityNumber()),
					"service_name":        serviceName,
					"scope_name":          scopeName,
					"body":                body,
					"body_type":           bodyType,
					"attributes":          attrs,
					"resource_attributes": resAttrs,
					"ingested_at":         time.Now().UTC().Format(time.RFC3339Nano),
					"day":                 rec.Timestamp().AsTime().UTC().Format("2006-01-02"),
				}
				rows = append(rows, row)
			}
		}
	}
	return rows, services.values()
}

// MetricsToRows flattens pmetric.Metrics into the metrics Iceberg row shape.
// We unroll each metric's data point into its own row so DuckDB can
// SELECT WHERE metric_name = ... cleanly.
func MetricsToRows(tenantID string, md pmetric.Metrics) ([]map[string]interface{}, []string) {
	rows := make([]map[string]interface{}, 0, md.DataPointCount())
	services := newStringSet()

	rms := md.ResourceMetrics()
	for i := 0; i < rms.Len(); i++ {
		rm := rms.At(i)
		resAttrs := attrMap(rm.Resource().Attributes())
		serviceName := getString(resAttrs, "service.name")
		if serviceName != "" {
			services.add(serviceName)
		}

		sms := rm.ScopeMetrics()
		for j := 0; j < sms.Len(); j++ {
			sm := sms.At(j)
			scopeName := sm.Scope().Name()

			metrics := sm.Metrics()
			for k := 0; k < metrics.Len(); k++ {
				m := metrics.At(k)
				common := map[string]interface{}{
					"tenant_id":           tenantID,
					"metric_name":         m.Name(),
					"metric_unit":         m.Unit(),
					"metric_description":  m.Description(),
					"service_name":        serviceName,
					"scope_name":          scopeName,
					"resource_attributes": resAttrs,
				}
				switch m.Type() {
				case pmetric.MetricTypeGauge:
					rows = append(rows, expandGauge(common, m.Gauge())...)
				case pmetric.MetricTypeSum:
					rows = append(rows, expandSum(common, m.Sum())...)
				case pmetric.MetricTypeHistogram:
					rows = append(rows, expandHistogram(common, m.Histogram())...)
				}
			}
		}
	}
	return rows, services.values()
}

// ----------------------------------------------------------
// helpers
// ----------------------------------------------------------

func attrMap(m pcommon.Map) map[string]string {
	out := make(map[string]string, m.Len())
	m.Range(func(k string, v pcommon.Value) bool {
		out[k] = v.AsString()
		return true
	})
	return out
}

func getString(m map[string]string, keys ...string) string {
	for _, k := range keys {
		if v, ok := m[k]; ok && v != "" {
			return v
		}
	}
	return ""
}

func getInt(m map[string]string, keys ...string) int64 {
	for _, k := range keys {
		if v, ok := m[k]; ok && v != "" {
			if n, err := strconv.ParseInt(v, 10, 64); err == nil {
				return n
			}
		}
	}
	return 0
}

func eventsToJSON(events ptrace.SpanEventSlice) string {
	if events.Len() == 0 {
		return ""
	}
	type evt struct {
		Time       string            `json:"time"`
		Name       string            `json:"name"`
		Attributes map[string]string `json:"attributes,omitempty"`
	}
	out := make([]evt, 0, events.Len())
	for i := 0; i < events.Len(); i++ {
		e := events.At(i)
		out = append(out, evt{
			Time:       e.Timestamp().AsTime().UTC().Format(time.RFC3339Nano),
			Name:       e.Name(),
			Attributes: attrMap(e.Attributes()),
		})
	}
	b, _ := json.Marshal(out)
	return string(b)
}

func linksToJSON(links ptrace.SpanLinkSlice) string {
	if links.Len() == 0 {
		return ""
	}
	type lnk struct {
		TraceID    string            `json:"trace_id"`
		SpanID     string            `json:"span_id"`
		Attributes map[string]string `json:"attributes,omitempty"`
	}
	out := make([]lnk, 0, links.Len())
	for i := 0; i < links.Len(); i++ {
		l := links.At(i)
		out = append(out, lnk{
			TraceID:    l.TraceID().String(),
			SpanID:     l.SpanID().String(),
			Attributes: attrMap(l.Attributes()),
		})
	}
	b, _ := json.Marshal(out)
	return string(b)
}

func bodyToString(v pcommon.Value) (string, string) {
	switch v.Type() {
	case pcommon.ValueTypeStr:
		return v.AsString(), "string"
	case pcommon.ValueTypeMap, pcommon.ValueTypeSlice:
		return v.AsString(), "kvlist"
	default:
		s := v.AsString()
		if strings.HasPrefix(s, "{") || strings.HasPrefix(s, "[") {
			return s, "json"
		}
		return s, "string"
	}
}

func expandGauge(common map[string]interface{}, g pmetric.Gauge) []map[string]interface{} {
	dps := g.DataPoints()
	out := make([]map[string]interface{}, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		row := cloneRow(common)
		row["metric_type"] = "gauge"
		row["time"] = dp.Timestamp().AsTime().UTC().Format(time.RFC3339Nano)
		row["start_time"] = dp.StartTimestamp().AsTime().UTC().Format(time.RFC3339Nano)
		row["gauge_value"] = numberValue(dp)
		row["attributes"] = attrMap(dp.Attributes())
		row["ingested_at"] = time.Now().UTC().Format(time.RFC3339Nano)
		row["day"] = dp.Timestamp().AsTime().UTC().Format("2006-01-02")
		out = append(out, row)
	}
	return out
}

func expandSum(common map[string]interface{}, s pmetric.Sum) []map[string]interface{} {
	dps := s.DataPoints()
	out := make([]map[string]interface{}, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		row := cloneRow(common)
		row["metric_type"] = "sum"
		row["time"] = dp.Timestamp().AsTime().UTC().Format(time.RFC3339Nano)
		row["start_time"] = dp.StartTimestamp().AsTime().UTC().Format(time.RFC3339Nano)
		row["sum_value"] = numberValue(dp)
		row["sum_is_monotonic"] = s.IsMonotonic()
		row["attributes"] = attrMap(dp.Attributes())
		row["ingested_at"] = time.Now().UTC().Format(time.RFC3339Nano)
		row["day"] = dp.Timestamp().AsTime().UTC().Format("2006-01-02")
		out = append(out, row)
	}
	return out
}

func expandHistogram(common map[string]interface{}, h pmetric.Histogram) []map[string]interface{} {
	dps := h.DataPoints()
	out := make([]map[string]interface{}, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		buckets := make([]map[string]interface{}, 0, dp.ExplicitBounds().Len())
		for b := 0; b < dp.ExplicitBounds().Len(); b++ {
			var count uint64
			if b < dp.BucketCounts().Len() {
				count = dp.BucketCounts().At(b)
			}
			buckets = append(buckets, map[string]interface{}{
				"bound": dp.ExplicitBounds().At(b),
				"count": count,
			})
		}
		bucketsJSON, _ := json.Marshal(buckets)

		row := cloneRow(common)
		row["metric_type"] = "histogram"
		row["time"] = dp.Timestamp().AsTime().UTC().Format(time.RFC3339Nano)
		row["start_time"] = dp.StartTimestamp().AsTime().UTC().Format(time.RFC3339Nano)
		row["histogram_count"] = int64(dp.Count())
		row["histogram_sum"] = dp.Sum()
		row["histogram_buckets"] = string(bucketsJSON)
		row["attributes"] = attrMap(dp.Attributes())
		row["ingested_at"] = time.Now().UTC().Format(time.RFC3339Nano)
		row["day"] = dp.Timestamp().AsTime().UTC().Format("2006-01-02")
		out = append(out, row)
	}
	return out
}

func cloneRow(in map[string]interface{}) map[string]interface{} {
	out := make(map[string]interface{}, len(in)+8)
	for k, v := range in {
		out[k] = v
	}
	return out
}

func numberValue(dp pmetric.NumberDataPoint) float64 {
	switch dp.ValueType() {
	case pmetric.NumberDataPointValueTypeDouble:
		return dp.DoubleValue()
	case pmetric.NumberDataPointValueTypeInt:
		return float64(dp.IntValue())
	}
	return 0
}

// ----------------------------------------------------------
// stringSet — small helper.
// ----------------------------------------------------------

type stringSet struct {
	m map[string]struct{}
}

func newStringSet() *stringSet { return &stringSet{m: map[string]struct{}{}} }

func (s *stringSet) add(v string) { s.m[v] = struct{}{} }

func (s *stringSet) values() []string {
	out := make([]string, 0, len(s.m))
	for k := range s.m {
		out = append(out, k)
	}
	return out
}
