import { useSSE } from '../hooks/useSSE'
import { getSSEUrl } from '../lib/api'

const EVENT_COLORS = {
  'telemetry': 'text-gray-400',
  'agent:cycle_start': 'text-blue-400',
  'agent:cycle_complete': 'text-green-400',
  'agent:tool_call': 'text-yellow-400',
  'agent:finding': 'text-red-400',
  'agent:llm_call': 'text-purple-400',
  'agent:agent_message': 'text-blue-300',
  'agent:status': 'text-cyan-400',
  'agent:error': 'text-red-500',
  'scenario': 'text-orange-400',
}

export default function LiveEventFeed() {
  const { events, connected } = useSSE(getSSEUrl(), 50)

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Live Event Feed
        </h2>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-xs text-gray-500">{connected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>

      <div className="overflow-auto max-h-60 font-mono text-xs p-2 space-y-0.5">
        {events.length === 0 ? (
          <div className="text-gray-500 py-4 text-center font-sans text-sm">
            Waiting for events...
          </div>
        ) : (
          events.map((evt, i) => {
            const eventType = evt.event || 'unknown'
            const color = EVENT_COLORS[eventType] || 'text-gray-500'
            const data = evt.data || {}

            let summary = ''
            if (eventType === 'telemetry') {
              summary = `${data.customer_name} ${data.endpoint} ${data.status_code} ${data.latency_ms?.toFixed(0)}ms`
            } else if (eventType === 'agent:tool_call') {
              summary = `${data.tool}${data.sql ? ': ' + data.sql.slice(0, 60) + '...' : ''}`
            } else if (eventType === 'agent:finding') {
              summary = `[${data.severity}] ${data.title}`
            } else if (eventType === 'agent:llm_call') {
              summary = `iteration ${data.iteration}`
            } else {
              summary = JSON.stringify(data).slice(0, 80)
            }

            return (
              <div key={i} className={`${color} truncate`}>
                <span className="text-gray-600">{eventType.padEnd(22)}</span> {summary}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
