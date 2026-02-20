import { useSSE } from '@/hooks/useSSE'
import { getSSEUrl } from '@/lib/api'
import Panel from '@/components/Panel'
import { EventFeedSkeleton } from '@/components/skeletons'
import { Button } from '@/components/ui/button'
import { Pause, Play, Trash2 } from 'lucide-react'

const EVENT_COLORS = {
  'telemetry': 'text-muted-foreground',
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

function isAgentEvent(type) {
  return type.startsWith('agent:')
}

export default function LiveEventFeed() {
  const { events, connected, paused, togglePause, clearEvents } = useSSE(getSSEUrl(), 200)

  const statusLabel = paused ? 'Paused' : connected ? 'Live' : 'Disconnected'
  const statusDot = paused ? 'bg-yellow-500' : connected ? 'bg-green-500' : 'bg-red-500'

  return (
    <Panel
      title="Live Event Feed"
      actions={
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={togglePause}>
            {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          </Button>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={clearEvents}>
            <Trash2 className="h-3 w-3" />
          </Button>
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${statusDot}`} />
            <span className="text-xs text-muted-foreground">{statusLabel}</span>
          </div>
        </div>
      }
    >
      {!connected && events.length === 0 ? (
        <EventFeedSkeleton lines={8} />
      ) : (
        <div className="overflow-auto h-full font-mono text-xs p-2 space-y-0.5 relative">
          {paused && (
            <div className="sticky top-0 z-10 bg-yellow-900/80 text-yellow-200 text-center text-xs py-1 rounded mb-1">
              Feed paused
            </div>
          )}
          {events.length === 0 ? (
            <div className="text-muted-foreground py-4 text-center font-sans text-sm">
              Waiting for events...
            </div>
          ) : (
            events.map((evt, i) => {
              const eventType = evt.event || 'unknown'
              const color = EVENT_COLORS[eventType] || 'text-muted-foreground'
              const data = evt.data || {}
              const isAgent = isAgentEvent(eventType)

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
                <div
                  key={i}
                  className={`${color} truncate ${isAgent ? 'pl-2 border-l-2 border-blue-800/50' : ''}`}
                >
                  <span className="text-muted-foreground/50">{eventType.padEnd(22)}</span> {summary}
                </div>
              )
            })
          )}
        </div>
      )}
    </Panel>
  )
}
