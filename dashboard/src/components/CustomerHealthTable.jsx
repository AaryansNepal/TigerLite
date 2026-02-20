/**
 * CustomerHealthTable — sortable per-customer metrics with drill-down drawer.
 *
 * The centerpiece UX: click any row to open a Sheet showing that customer's
 * metrics (p50, p99, error rate, request count) alongside agent findings filtered
 * to that customer. Connects raw observability data to AI analysis in one view.
 * Column headers are clickable for ascending/descending sort.
 */

import { useState, useMemo } from 'react'
import { usePolling } from '@/hooks/usePolling'
import { getCustomerHealth, getFindings } from '@/lib/api'
import Panel from '@/components/Panel'
import { TableSkeleton } from '@/components/skeletons'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Card, CardContent } from '@/components/ui/card'
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'

function healthStatus(p99, errorRate) {
  if (p99 > 1000 || errorRate > 10) return 'critical'
  if (p99 > 500 || errorRate > 5) return 'warning'
  return 'healthy'
}

const STATUS_DOT = {
  critical: 'bg-red-500',
  warning: 'bg-yellow-500',
  healthy: 'bg-green-500',
}

const STATUS_TEXT = {
  critical: 'text-red-400',
  warning: 'text-yellow-400',
  healthy: 'text-green-400',
}

const SORT_KEYS = {
  customer: (c) => c.customer_name.toLowerCase(),
  requests: (c) => c.request_count,
  p50: (c) => c.p50_latency ?? 0,
  p99: (c) => c.p99_latency ?? 0,
  error: (c) => c.error_rate ?? 0,
}

export default function CustomerHealthTable() {
  const { data, isFirstLoad } = usePolling(getCustomerHealth, 3000)
  const { data: findingsData } = usePolling(getFindings, 5000)
  const [sortKey, setSortKey] = useState('p99')
  const [sortAsc, setSortAsc] = useState(false)
  const [selectedCustomer, setSelectedCustomer] = useState(null)

  const customers = data?.customers ?? []
  const findings = findingsData?.findings ?? []

  const sorted = useMemo(() => {
    const fn = SORT_KEYS[sortKey]
    if (!fn) return customers
    return [...customers].sort((a, b) => {
      const av = fn(a)
      const bv = fn(b)
      if (av < bv) return sortAsc ? -1 : 1
      if (av > bv) return sortAsc ? 1 : -1
      return 0
    })
  }, [customers, sortKey, sortAsc])

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortAsc(prev => !prev)
    } else {
      setSortKey(key)
      setSortAsc(false)
    }
  }

  const SortIcon = ({ column }) => {
    if (sortKey !== column) return <ArrowUpDown className="h-3 w-3 text-muted-foreground/50" />
    return sortAsc ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
  }

  const customerFindings = selectedCustomer
    ? findings.filter(f =>
        f.customer_id === selectedCustomer.customer_id ||
        f.customer_name === selectedCustomer.customer_name
      )
    : []

  const selectedStatus = selectedCustomer
    ? healthStatus(selectedCustomer.p99_latency, selectedCustomer.error_rate)
    : 'healthy'

  return (
    <>
      <Panel title="Customer Health">
        {isFirstLoad ? (
          <TableSkeleton rows={5} cols={6} />
        ) : customers.length === 0 ? (
          <div className="p-4 text-muted-foreground text-sm">Waiting for telemetry data...</div>
        ) : (
          <ScrollArea className="h-full">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8"></TableHead>
                  <TableHead>
                    <button onClick={() => handleSort('customer')} className="flex items-center gap-1 hover:text-foreground transition-colors">
                      Customer <SortIcon column="customer" />
                    </button>
                  </TableHead>
                  <TableHead className="text-right">
                    <button onClick={() => handleSort('requests')} className="flex items-center gap-1 ml-auto hover:text-foreground transition-colors">
                      Requests <SortIcon column="requests" />
                    </button>
                  </TableHead>
                  <TableHead className="text-right">
                    <button onClick={() => handleSort('p50')} className="flex items-center gap-1 ml-auto hover:text-foreground transition-colors">
                      p50 (ms) <SortIcon column="p50" />
                    </button>
                  </TableHead>
                  <TableHead className="text-right">
                    <button onClick={() => handleSort('p99')} className="flex items-center gap-1 ml-auto hover:text-foreground transition-colors">
                      p99 (ms) <SortIcon column="p99" />
                    </button>
                  </TableHead>
                  <TableHead className="text-right">
                    <button onClick={() => handleSort('error')} className="flex items-center gap-1 ml-auto hover:text-foreground transition-colors">
                      Error % <SortIcon column="error" />
                    </button>
                  </TableHead>
                  <TableHead className="text-right">Deploy</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((c) => {
                  const status = healthStatus(c.p99_latency, c.error_rate)
                  const color = STATUS_TEXT[status]
                  return (
                    <TableRow
                      key={c.customer_id}
                      className="cursor-pointer"
                      onClick={() => setSelectedCustomer(c)}
                    >
                      <TableCell>
                        <div className={`w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{c.customer_name}</div>
                        <div className="text-xs text-muted-foreground font-mono">{c.customer_id}</div>
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {c.request_count}
                      </TableCell>
                      <TableCell className={`text-right font-mono ${color}`}>
                        {c.p50_latency?.toFixed(1)}
                      </TableCell>
                      <TableCell className={`text-right font-mono font-bold ${color}`}>
                        {c.p99_latency?.toFixed(1)}
                      </TableCell>
                      <TableCell className={`text-right font-mono ${c.error_rate > 5 ? 'text-red-400' : 'text-muted-foreground'}`}>
                        {c.error_rate?.toFixed(1)}%
                      </TableCell>
                      <TableCell className="text-right font-mono text-muted-foreground text-xs">
                        {c.latest_deploy}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </ScrollArea>
        )}
      </Panel>

      <Sheet open={!!selectedCustomer} onOpenChange={(open) => { if (!open) setSelectedCustomer(null) }}>
        <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
          {selectedCustomer && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-3">
                  {selectedCustomer.customer_name}
                  <Badge
                    variant={selectedStatus === 'critical' ? 'destructive' : selectedStatus === 'warning' ? 'default' : 'secondary'}
                    className={selectedStatus === 'warning' ? 'bg-yellow-600 text-yellow-100' : ''}
                  >
                    {selectedStatus}
                  </Badge>
                </SheetTitle>
                <SheetDescription className="font-mono text-xs">
                  {selectedCustomer.customer_id}
                </SheetDescription>
              </SheetHeader>

              <div className="grid grid-cols-2 gap-3 mt-6">
                <Card>
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">p50 Latency</div>
                    <div className={`text-2xl font-mono font-bold ${STATUS_TEXT[selectedStatus]}`}>
                      {selectedCustomer.p50_latency?.toFixed(1)}<span className="text-sm font-normal text-muted-foreground ml-1">ms</span>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">p99 Latency</div>
                    <div className={`text-2xl font-mono font-bold ${STATUS_TEXT[selectedStatus]}`}>
                      {selectedCustomer.p99_latency?.toFixed(1)}<span className="text-sm font-normal text-muted-foreground ml-1">ms</span>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">Error Rate</div>
                    <div className={`text-2xl font-mono font-bold ${selectedCustomer.error_rate > 5 ? 'text-red-400' : 'text-green-400'}`}>
                      {selectedCustomer.error_rate?.toFixed(1)}<span className="text-sm font-normal text-muted-foreground ml-1">%</span>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <div className="text-xs text-muted-foreground mb-1">Requests</div>
                    <div className="text-2xl font-mono font-bold text-foreground">
                      {selectedCustomer.request_count}
                    </div>
                  </CardContent>
                </Card>
              </div>

              <Separator className="my-6" />

              <div>
                <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                  Agent Findings
                  {customerFindings.length > 0 && (
                    <Badge variant="secondary" className="ml-2 normal-case">{customerFindings.length}</Badge>
                  )}
                </h3>
                {customerFindings.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No agent findings for this customer.</p>
                ) : (
                  <div className="space-y-3">
                    {customerFindings.map((f) => (
                      <div
                        key={f.id}
                        className={`rounded-lg border p-3 ${
                          f.severity === 'critical' ? 'border-red-800/50 bg-red-900/20' :
                          f.severity === 'warning' ? 'border-yellow-800/50 bg-yellow-900/20' :
                          'border-blue-800/50 bg-blue-900/20'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2">
                            <Badge variant={f.severity === 'critical' ? 'destructive' : f.severity === 'warning' ? 'default' : 'secondary'}
                              className={f.severity === 'warning' ? 'bg-yellow-600 text-yellow-100' : f.severity === 'info' ? 'bg-blue-600 text-blue-100' : ''}>
                              {f.severity}
                            </Badge>
                            <span className="font-medium text-sm">{f.title}</span>
                          </div>
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
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  )
}
