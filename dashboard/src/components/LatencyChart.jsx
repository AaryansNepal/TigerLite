import { usePolling } from '../hooks/usePolling'
import { getCustomerHealth } from '../lib/api'
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
  const { data } = usePolling(getCustomerHealth, 3000)
  const customers = data?.customers ?? []

  const chartData = customers.map(c => ({
    name: c.customer_name.split(' ')[0],
    p50: c.p50_latency ?? 0,
    p99: c.p99_latency ?? 0,
    fullName: c.customer_name,
  }))

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Latency by Customer (p99)
        </h2>
      </div>

      <div className="p-4 h-64">
        {chartData.length === 0 ? (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            Waiting for data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="name"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                axisLine={{ stroke: '#4b5563' }}
              />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                axisLine={{ stroke: '#4b5563' }}
                label={{ value: 'ms', position: 'insideTopLeft', fill: '#6b7280', fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid #374151',
                  borderRadius: '8px',
                  color: '#e5e7eb',
                  fontSize: 12,
                }}
                formatter={(value, name) => [`${value?.toFixed(1)} ms`, name.toUpperCase()]}
                labelFormatter={(label, payload) => payload?.[0]?.payload?.fullName ?? label}
              />
              <ReferenceLine y={200} stroke="#4b5563" strokeDasharray="3 3" label={{ value: 'SLO', fill: '#6b7280', fontSize: 10 }} />
              <Bar dataKey="p99" radius={[4, 4, 0, 0]}>
                {chartData.map((entry, i) => (
                  <Cell key={i} fill={getColor(entry.p99)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
