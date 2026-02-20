/**
 * AgentFindingsList — displays AI-generated findings from the agent's investigations.
 *
 * Each finding has a severity badge (critical/warning/info), summary, and
 * expandable evidence queries showing the actual SQL the agent ran.
 */

import { usePolling } from '@/hooks/usePolling'
import { getFindings } from '@/lib/api'
import Panel from '@/components/Panel'
import { FindingsSkeleton } from '@/components/skeletons'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'

const SEVERITY_STYLES = {
  critical: 'bg-red-900/20 border-red-800/50',
  warning: 'bg-yellow-900/20 border-yellow-800/50',
  info: 'bg-blue-900/20 border-blue-800/50',
}

export default function AgentFindingsList() {
  const { data, isFirstLoad } = usePolling(getFindings, 5000)
  const findings = data?.findings ?? []

  return (
    <Panel
      title="Agent Findings"
      actions={
        findings.length > 0 && (
          <Badge variant="secondary">{findings.length}</Badge>
        )
      }
    >
      {isFirstLoad ? (
        <FindingsSkeleton count={3} />
      ) : (
        <ScrollArea className="h-full">
          <div className="p-3 space-y-3">
            {findings.length === 0 ? (
              <div className="text-muted-foreground text-sm py-4 text-center">
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
                      <Badge
                        variant={f.severity === 'critical' ? 'destructive' : f.severity === 'warning' ? 'default' : 'secondary'}
                        className={f.severity === 'warning' ? 'bg-yellow-600 text-yellow-100' : f.severity === 'info' ? 'bg-blue-600 text-blue-100' : ''}
                      >
                        {f.severity}
                      </Badge>
                      <span className="font-medium text-sm">{f.title}</span>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      {f.customer_name}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mb-2">{f.summary}</p>
                  {f.evidence_queries?.length > 0 && (
                    <details className="text-xs">
                      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                        Evidence queries ({f.evidence_queries.length})
                      </summary>
                      <div className="mt-2 space-y-1">
                        {f.evidence_queries.map((q, i) => (
                          <pre key={i} className="bg-black/30 rounded p-2 font-mono text-muted-foreground whitespace-pre-wrap break-all">
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
        </ScrollArea>
      )}
    </Panel>
  )
}
