import { useState } from 'react'
import StatusBar from '@/components/StatusBar'
import CustomerHealthTable from '@/components/CustomerHealthTable'
import LatencyChart from '@/components/LatencyChart'
import AgentFindingsList from '@/components/AgentFindingsList'
import SnapshotTimeline from '@/components/SnapshotTimeline'
import LiveEventFeed from '@/components/LiveEventFeed'

export default function App() {
  const [forceSessionId, setForceSessionId] = useState(null)

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <StatusBar onAgentStarted={setForceSessionId} />

      <div className="flex-1 p-4 grid grid-cols-3 grid-rows-2 gap-4 min-h-0">
        {/* Row 1 */}
        <div className="col-span-2">
          <CustomerHealthTable />
        </div>
        <div>
          <AgentFindingsList />
        </div>

        {/* Row 2 */}
        <div>
          <LatencyChart />
        </div>
        <div>
          <SnapshotTimeline forceSessionId={forceSessionId} />
        </div>
        <div>
          <LiveEventFeed />
        </div>
      </div>
    </div>
  )
}
