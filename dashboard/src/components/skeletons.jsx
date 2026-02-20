/**
 * Skeleton loading presets — one per panel type.
 *
 * Each skeleton matches the real layout shape of its panel so there's no
 * layout shift when data arrives. Shown only during isFirstLoad.
 */

import { Skeleton } from "@/components/ui/skeleton"

export function TableSkeleton({ rows = 5, cols = 6 }) {
  return (
    <div className="p-4 space-y-3">
      <div className="flex gap-4">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-4 items-center">
          <Skeleton className="h-2 w-2 rounded-full" />
          <Skeleton className="h-4 flex-[2]" />
          {Array.from({ length: cols - 2 }).map((_, c) => (
            <Skeleton key={c} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function ChartSkeleton() {
  return (
    <div className="p-4 h-64 flex items-end gap-3">
      {[40, 65, 30, 80, 55, 45, 70, 35].map((h, i) => (
        <Skeleton
          key={i}
          className="flex-1 rounded-t"
          style={{ height: `${h}%` }}
        />
      ))}
    </div>
  )
}

export function FindingsSkeleton({ count = 3 }) {
  return (
    <div className="p-3 space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border p-3 space-y-2">
          <div className="flex items-center gap-2">
            <Skeleton className="h-5 w-16 rounded" />
            <Skeleton className="h-4 flex-1" />
          </div>
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      ))}
    </div>
  )
}

export function TimelineSkeleton({ count = 4 }) {
  return (
    <div className="p-3 pl-9 space-y-4 relative">
      <div className="absolute left-5 top-3 bottom-3 w-0.5 bg-border" />
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="relative">
          <Skeleton className="absolute -left-6 top-1 h-3 w-3 rounded-full" />
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-12" />
              <Skeleton className="h-3 w-16" />
            </div>
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function EventFeedSkeleton({ lines = 8 }) {
  return (
    <div className="p-2 space-y-1.5">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="h-3 w-36" />
          <Skeleton className="h-3 flex-1" />
        </div>
      ))}
    </div>
  )
}
