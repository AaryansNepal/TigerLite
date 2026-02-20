/**
 * SnapshotTimeline — visualizes the agent's reasoning chain as a Git-like timeline.
 *
 * Each dot is an immutable snapshot version. Click to expand and see the stored
 * objects (messages, tool calls, function responses). Session picker lets you
 * switch between different investigation sessions.
 */

import { useState, useEffect } from 'react'
import { usePolling } from '@/hooks/usePolling'
import { getSessions, getSessionSnapshots, getSnapshot } from '@/lib/api'
import Panel from '@/components/Panel'
import { TimelineSkeleton } from '@/components/skeletons'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'

export default function SnapshotTimeline({ forceSessionId }) {
  const { data: sessionsData, isFirstLoad } = usePolling(getSessions, 5000)
  const [selectedSession, setSelectedSession] = useState(null)
  const [snapshots, setSnapshots] = useState([])
  const [expandedVersion, setExpandedVersion] = useState(null)
  const [versionObjects, setVersionObjects] = useState({})

  const sessions = sessionsData?.sessions ?? []

  useEffect(() => {
    if (forceSessionId) {
      setSelectedSession(forceSessionId)
      setExpandedVersion(null)
      setVersionObjects({})
    }
  }, [forceSessionId])

  useEffect(() => {
    if (sessions.length > 0) {
      const latest = sessions[sessions.length - 1]
      setSelectedSession(prev => {
        if (!prev || !sessions.includes(prev) || prev === latest) return latest
        return prev
      })
    }
  }, [sessions])

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
    <Panel
      title="Snapshot Timeline"
      actions={
        sessions.length > 1 && (
          <select
            className="bg-secondary text-foreground text-xs rounded px-2 py-1 border border-border"
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
        )
      }
    >
      {isFirstLoad ? (
        <TimelineSkeleton count={4} />
      ) : (
        <ScrollArea className="h-full">
          <div className="p-3">
            {snapshots.length === 0 ? (
              <div className="text-muted-foreground text-sm py-4 text-center">
                No agent sessions yet.
              </div>
            ) : (
              <div className="relative pl-6">
                <div className="absolute left-2 top-0 bottom-0 w-0.5 bg-border" />

                {snapshots.map((snap) => (
                  <div key={snap.version} className="relative mb-4">
                    <div className={`absolute -left-4 top-1 w-3 h-3 rounded-full border-2 ${
                      snap.status === 'completed' ? 'bg-green-500 border-green-400' :
                      snap.status === 'error' ? 'bg-red-500 border-red-400' :
                      'bg-yellow-500 border-yellow-400'
                    }`} />

                    <button
                      onClick={() => toggleVersion(snap.version)}
                      className="w-full text-left hover:bg-muted/50 rounded p-2 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">
                          v{snap.version}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {snap.metadata?.timestamp?.slice(11, 19) ?? ''}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2">
                        {snap.descriptors?.length ?? 0} objects
                        <Badge variant={snap.status === 'completed' ? 'secondary' : snap.status === 'error' ? 'destructive' : 'default'}
                          className={`text-[10px] px-1.5 py-0 ${snap.status !== 'completed' && snap.status !== 'error' ? 'bg-yellow-600 text-yellow-100' : ''}`}>
                          {snap.status}
                        </Badge>
                      </div>
                    </button>

                    {expandedVersion === snap.version && versionObjects[snap.version] && (
                      <div className="ml-2 mt-2 space-y-2">
                        {versionObjects[snap.version].map((obj, i) => {
                          const msg = obj.message
                          const role = msg?.role
                          const textContent = msg?.content || msg?.text || ''
                          const toolCalls = msg?.tool_calls || msg?.function_calls
                          const fnResponses = msg?.responses

                          return (
                            <div key={i} className="bg-muted/50 rounded p-2 text-xs">
                              {obj.type === 'message' ? (
                                <div>
                                  <Badge variant="secondary" className={`text-[10px] px-1.5 py-0 ${
                                    role === 'assistant' || role === 'model' ? 'bg-blue-900/50 text-blue-400' :
                                    role === 'tool' || role === 'function_response' ? 'bg-green-900/50 text-green-400' :
                                    ''
                                  }`}>
                                    {role}
                                  </Badge>
                                  {textContent && (
                                    <pre className="mt-1 text-muted-foreground font-mono whitespace-pre-wrap break-words max-h-32 overflow-auto">
                                      {typeof textContent === 'string'
                                        ? textContent.slice(0, 500)
                                        : JSON.stringify(textContent, null, 2).slice(0, 500)}
                                    </pre>
                                  )}
                                  {toolCalls && (
                                    <div className="mt-1 text-yellow-400">
                                      Tools: {toolCalls.map(tc => tc.function?.name || tc.name).join(', ')}
                                    </div>
                                  )}
                                  {fnResponses && (
                                    <div className="mt-1 space-y-1">
                                      {fnResponses.map((r, j) => (
                                        <div key={j}>
                                          <span className="text-green-400 font-bold">{r.name}</span>
                                          <pre className="mt-0.5 text-muted-foreground font-mono whitespace-pre-wrap break-words max-h-24 overflow-auto">
                                            {typeof r.response?.result === 'string'
                                              ? r.response.result.slice(0, 400)
                                              : JSON.stringify(r.response, null, 2).slice(0, 400)}
                                          </pre>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <pre className="font-mono text-muted-foreground whitespace-pre-wrap">
                                  {JSON.stringify(obj, null, 2).slice(0, 300)}
                                </pre>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </ScrollArea>
      )}
    </Panel>
  )
}
