import { usePolling } from '../hooks/usePolling'
import { getScenarioStatus, triggerBadDeploy, triggerAgent } from '../lib/api'

export default function StatusBar({ onAgentStarted }) {
  const { data } = usePolling(getScenarioStatus, 2000)

  return (
    <div className="flex items-center justify-between bg-gray-900 border-b border-gray-800 px-6 py-3">
      <div className="flex items-center gap-3">
        <span className="text-xl font-bold tracking-tight">
          <span className="text-orange-500">Tiger</span>
          <span className="text-white">Lite</span>
        </span>
        <span className="text-xs text-gray-500 border-l border-gray-700 pl-3">
          Agentic Observability
        </span>
      </div>

      <div className="flex items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <span className="text-gray-400">Events:</span>
          <span className="font-mono text-green-400">
            {data?.total_events_ingested?.toLocaleString() ?? '...'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-gray-400">Agent:</span>
          <span className={`font-mono ${data?.agent_running ? 'text-yellow-400' : 'text-gray-500'}`}>
            {data?.agent_running ? 'Running' : 'Idle'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-gray-400">Deploy:</span>
          <span className={`font-mono ${data?.bad_deploy_triggered ? 'text-red-400' : 'text-green-400'}`}>
            {data?.bad_deploy_triggered ? 'v1.2.4 (bad)' : 'v1.2.3'}
          </span>
        </div>

        <button
          onClick={triggerBadDeploy}
          disabled={data?.bad_deploy_triggered}
          className="px-3 py-1 bg-red-900/50 hover:bg-red-800/50 disabled:opacity-30 disabled:cursor-not-allowed text-red-300 rounded text-xs font-medium border border-red-800/50 transition-colors"
        >
          Trigger Bad Deploy
        </button>

        <button
          onClick={async () => {
            const result = await triggerAgent()
            if (result.session_id) onAgentStarted?.(result.session_id)
          }}
          disabled={data?.agent_running}
          className="px-3 py-1 bg-blue-900/50 hover:bg-blue-800/50 disabled:opacity-30 disabled:cursor-not-allowed text-blue-300 rounded text-xs font-medium border border-blue-800/50 transition-colors"
        >
          Run Agent
        </button>
      </div>
    </div>
  )
}
