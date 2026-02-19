import { usePolling } from '../hooks/usePolling'
import { getCustomerHealth } from '../lib/api'

function healthColor(p99, errorRate) {
  if (p99 > 1000 || errorRate > 10) return 'text-red-400'
  if (p99 > 500 || errorRate > 5) return 'text-yellow-400'
  return 'text-green-400'
}

function statusDot(p99, errorRate) {
  if (p99 > 1000 || errorRate > 10) return 'bg-red-500'
  if (p99 > 500 || errorRate > 5) return 'bg-yellow-500'
  return 'bg-green-500'
}

export default function CustomerHealthTable() {
  const { data, loading } = usePolling(getCustomerHealth, 3000)
  const customers = data?.customers ?? []

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Customer Health
        </h2>
      </div>

      {loading ? (
        <div className="p-4 text-gray-500 text-sm">Loading...</div>
      ) : customers.length === 0 ? (
        <div className="p-4 text-gray-500 text-sm">Waiting for telemetry data...</div>
      ) : (
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase tracking-wider">
                <th className="px-4 py-2 text-left"></th>
                <th className="px-4 py-2 text-left">Customer</th>
                <th className="px-4 py-2 text-right">Requests</th>
                <th className="px-4 py-2 text-right">p50 (ms)</th>
                <th className="px-4 py-2 text-right">p99 (ms)</th>
                <th className="px-4 py-2 text-right">Error %</th>
                <th className="px-4 py-2 text-right">Deploy</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => {
                const color = healthColor(c.p99_latency, c.error_rate)
                const dot = statusDot(c.p99_latency, c.error_rate)
                return (
                  <tr key={c.customer_id} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-4 py-2">
                      <div className={`w-2 h-2 rounded-full ${dot}`} />
                    </td>
                    <td className="px-4 py-2">
                      <div className="font-medium text-gray-200">{c.customer_name}</div>
                      <div className="text-xs text-gray-500 font-mono">{c.customer_id}</div>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-gray-300">
                      {c.request_count}
                    </td>
                    <td className={`px-4 py-2 text-right font-mono ${color}`}>
                      {c.p50_latency?.toFixed(1)}
                    </td>
                    <td className={`px-4 py-2 text-right font-mono font-bold ${color}`}>
                      {c.p99_latency?.toFixed(1)}
                    </td>
                    <td className={`px-4 py-2 text-right font-mono ${c.error_rate > 5 ? 'text-red-400' : 'text-gray-400'}`}>
                      {c.error_rate?.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-gray-500 text-xs">
                      {c.latest_deploy}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
