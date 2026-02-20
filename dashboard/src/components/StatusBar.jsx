import { usePolling } from '@/hooks/usePolling'
import { getScenarioStatus, triggerBadDeploy, triggerAgent } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

export default function StatusBar({ onAgentStarted }) {
  const { data, isFirstLoad } = usePolling(getScenarioStatus, 2000)

  return (
    <TooltipProvider>
      <div className="flex items-center justify-between border-b bg-card px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold tracking-tight">
            <span className="text-orange-500">Tiger</span>
            <span className="text-foreground">Lite</span>
          </span>
          <span className="text-xs text-muted-foreground border-l pl-3">
            Agentic Observability
          </span>
        </div>

        <div className="flex items-center gap-4 text-sm">
          {isFirstLoad ? (
            <div className="flex items-center gap-4">
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-8 w-24" />
            </div>
          ) : (
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Events:</span>
                    <span className="font-mono text-green-400">
                      {data?.total_events_ingested?.toLocaleString() ?? '0'}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>Total telemetry events ingested</TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Agent:</span>
                    <Badge variant={data?.agent_running ? 'default' : 'secondary'} className={data?.agent_running ? 'bg-yellow-600 text-yellow-100' : ''}>
                      {data?.agent_running ? 'Running' : 'Idle'}
                    </Badge>
                  </div>
                </TooltipTrigger>
                <TooltipContent>AI agent investigation status</TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Deploy:</span>
                    <span className={`font-mono ${data?.bad_deploy_triggered ? 'text-red-400' : 'text-green-400'}`}>
                      {data?.bad_deploy_triggered ? 'v1.2.4 (bad)' : 'v1.2.3'}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>Current deployment version</TooltipContent>
              </Tooltip>

              <Button
                variant="destructive"
                size="sm"
                onClick={triggerBadDeploy}
                disabled={data?.bad_deploy_triggered}
              >
                Trigger Bad Deploy
              </Button>

              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  const result = await triggerAgent()
                  if (result.session_id) onAgentStarted?.(result.session_id)
                }}
                disabled={data?.agent_running}
              >
                Run Agent
              </Button>
            </>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
