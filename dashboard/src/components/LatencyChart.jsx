/**
 * LatencyChart — p99 latency bar chart colored by health status.
 *
 * Green (<500ms), yellow (500-1000ms), red (>1000ms). Reference line at 200ms
 * shows the SLO target. Shares the same customer health data as the table.
 */

import { usePolling } from '@/hooks/usePolling'
import { getCustomerHealth } from '@/lib/api'
import Panel from '@/components/Panel'
import { ChartSkeleton } from '@/components/skeletons'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts'

const COLORS = {
  healthy: '#22c55e',
  warning: '#eab308',
  critical: '#ef4444',
}

function getColor(p99) {
  if (p99 > 1000) return COLORS.critical
  if (p99 > 500) return COLORS.warning
  return COLORS.healthy
}

export default function LatencyChart() {
  const { data, isFirstLoad } = usePolling(getCustomerHealth, 3000)
  const customers = data?.customers ?? []

  const chartData = customers.map(c => ({
    name: c.customer_name.split(' ')[0],
    p50: c.p50_latency ?? 0,
    p99: c.p99_latency ?? 0,
    fullName: c.customer_name,
  }))

  return (
    <Panel title="Latency by Customer (p99)">
      <div className="p-4 h-64">
        {isFirstLoad ? (
          <ChartSkeleton />
        ) : chartData.length === 0 ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            Waiting for data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(0 0% 14.9%)" />
              <XAxis
                dataKey="name"
                tick={{ fill: 'hsl(0 0% 63.9%)', fontSize: 11 }}
                axisLine={{ stroke: 'hsl(0 0% 14.9%)' }}
              />
              <YAxis
                tick={{ fill: 'hsl(0 0% 63.9%)', fontSize: 11 }}
                axisLine={{ stroke: 'hsl(0 0% 14.9%)' }}
                label={{ value: 'ms', position: 'insideTopLeft', fill: 'hsl(0 0% 63.9%)', fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'hsl(0 0% 7%)',
                  border: '1px solid hsl(0 0% 14.9%)',
                  borderRadius: '8px',
                  color: 'hsl(0 0% 98%)',
                  fontSize: 12,
                }}
                formatter={(value, name) => [`${value?.toFixed(1)} ms`, name.toUpperCase()]}
                labelFormatter={(label, payload) => payload?.[0]?.payload?.fullName ?? label}
              />
              <ReferenceLine y={200} stroke="hsl(0 0% 14.9%)" strokeDasharray="3 3" label={{ value: 'SLO', fill: 'hsl(0 0% 63.9%)', fontSize: 10 }} />
              <Bar dataKey="p99" radius={[4, 4, 0, 0]} className="cursor-pointer">
                {chartData.map((entry, i) => (
                  <Cell key={i} fill={getColor(entry.p99)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </Panel>
  )
}
