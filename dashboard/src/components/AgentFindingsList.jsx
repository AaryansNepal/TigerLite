import { usePolling } from '../hooks/usePolling'
import { getFindings } from '../lib/api'

const SEVERITY_STYLES = {
  critical: 'bg-red-900/30 border-red-800/50 text-red-300',
  warning: 'bg-yellow-900/30 border-yellow-800/50 text-yellow-300',
  info: 'bg-blue-900/30 border-blue-800/50 text-blue-300',
}

const BADGE_STYLES = {
  critical: 'bg-red-600 text-white',
  warning: 'bg-yellow-600 text-black',
  info: 'bg-blue-600 text-white',
}

export default function AgentFindingsList() {
  const { data } = usePolling(getFindings, 5000)
  const findings = data?.findings ?? []

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Agent Findings
        </h2>
      </div>

      <div className="overflow-auto max-h-80 p-3 space-y-3">
        {findings.length === 0 ? (
          <div className="text-gray-500 text-sm py-4 text-center">
            No findings yet. The agent will investigate after detecting anomalies.
          </div>
        ) : (
          findings.map((f) => (
            <div
              key={f.id}
              className={`rounded-lg border p-3 ${SEVERITY_STYLES[f.severity] || SEVERITY_STYLES.info}`}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded uppercase ${BADGE_STYLES[f.severity] || BADGE_STYLES.info}`}>
                    {f.severity}
                  </span>
                  <span className="font-medium text-sm">{f.title}</span>
                </div>
                <span className="text-xs text-gray-500 whitespace-nowrap">
                  {f.customer_name}
                </span>
              </div>
              <p className="text-xs text-gray-400 mb-2">{f.summary}</p>
              {f.evidence_queries?.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-gray-500 hover:text-gray-300">
                    Evidence queries ({f.evidence_queries.length})
                  </summary>
                  <div className="mt-2 space-y-1">
                    {f.evidence_queries.map((q, i) => (
                      <pre key={i} className="bg-black/30 rounded p-2 font-mono text-gray-400 overflow-x-auto">
                        {q}
                      </pre>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
