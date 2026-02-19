import { useState, useEffect } from 'react'
import { usePolling } from '../hooks/usePolling'
import { getSessions, getSessionSnapshots, getSnapshot } from '../lib/api'

export default function SnapshotTimeline() {
  const { data: sessionsData } = usePolling(getSessions, 5000)
  const [selectedSession, setSelectedSession] = useState(null)
  const [snapshots, setSnapshots] = useState([])
  const [expandedVersion, setExpandedVersion] = useState(null)
  const [versionObjects, setVersionObjects] = useState({})

  const sessions = sessionsData?.sessions ?? []

  // Auto-select first session
  useEffect(() => {
    if (sessions.length > 0 && !selectedSession) {
      setSelectedSession(sessions[sessions.length - 1])
    }
  }, [sessions, selectedSession])

  // Load snapshots when session changes
  useEffect(() => {
    if (!selectedSession) return
    const load = async () => {
      try {
        const data = await getSessionSnapshots(selectedSession)
        setSnapshots(data.snapshots ?? [])
      } catch {
        setSnapshots([])
      }
    }
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [selectedSession])

  const toggleVersion = async (version) => {
    if (expandedVersion === version) {
      setExpandedVersion(null)
      return
    }
    setExpandedVersion(version)
    if (!versionObjects[version] && selectedSession) {
      try {
        const data = await getSnapshot(selectedSession, version)
        setVersionObjects(prev => ({ ...prev, [version]: data.objects ?? [] }))
      } catch {
        // ignore
      }
    }
  }

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Snapshot Timeline
        </h2>
        {sessions.length > 1 && (
          <select
            className="bg-gray-800 text-gray-300 text-xs rounded px-2 py-1 border border-gray-700"
            value={selectedSession || ''}
            onChange={(e) => {
              setSelectedSession(e.target.value)
              setExpandedVersion(null)
              setVersionObjects({})
            }}
          >
            {sessions.map(s => (
              <option key={s} value={s}>{s.slice(0, 8)}...</option>
            ))}
          </select>
        )}
      </div>

      <div className="overflow-auto max-h-80 p-3">
        {snapshots.length === 0 ? (
          <div className="text-gray-500 text-sm py-4 text-center">
            No agent sessions yet.
          </div>
        ) : (
          <div className="relative pl-6">
            {/* Vertical line */}
            <div className="absolute left-2 top-0 bottom-0 w-0.5 bg-gray-700" />

            {snapshots.map((snap) => (
              <div key={snap.version} className="relative mb-4">
                {/* Dot */}
                <div className={`absolute -left-4 top-1 w-3 h-3 rounded-full border-2 ${
                  snap.status === 'completed' ? 'bg-green-500 border-green-400' :
                  snap.status === 'error' ? 'bg-red-500 border-red-400' :
                  'bg-yellow-500 border-yellow-400'
                }`} />

                <button
                  onClick={() => toggleVersion(snap.version)}
                  className="w-full text-left hover:bg-gray-800/50 rounded p-2 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-300">
                      v{snap.version}
                    </span>
                    <span className="text-xs text-gray-500">
                      {snap.metadata?.timestamp?.slice(11, 19) ?? ''}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {snap.descriptors?.length ?? 0} objects &middot; {snap.status}
                  </div>
                </button>

                {expandedVersion === snap.version && versionObjects[snap.version] && (
                  <div className="ml-2 mt-2 space-y-2">
                    {versionObjects[snap.version].map((obj, i) => (
                      <div key={i} className="bg-gray-800/50 rounded p-2 text-xs">
                        {obj.type === 'message' ? (
                          <div>
                            <span className={`font-bold ${
                              obj.message?.role === 'assistant' ? 'text-blue-400' :
                              obj.message?.role === 'tool' ? 'text-green-400' :
                              'text-gray-400'
                            }`}>
                              {obj.message?.role}
                            </span>
                            {obj.message?.content && (
                              <pre className="mt-1 text-gray-400 font-mono whitespace-pre-wrap break-words max-h-32 overflow-auto">
                                {typeof obj.message.content === 'string'
                                  ? obj.message.content.slice(0, 500)
                                  : JSON.stringify(obj.message.content, null, 2).slice(0, 500)}
                              </pre>
                            )}
                            {obj.message?.tool_calls && (
                              <div className="mt-1 text-yellow-400">
                                Tools: {obj.message.tool_calls.map(tc => tc.function?.name).join(', ')}
                              </div>
                            )}
                          </div>
                        ) : (
                          <pre className="font-mono text-gray-400 whitespace-pre-wrap">
                            {JSON.stringify(obj, null, 2).slice(0, 300)}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
