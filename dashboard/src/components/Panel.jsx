import { Card, CardHeader, CardContent } from "@/components/ui/card"

export default function Panel({ title, actions, children, className }) {
  return (
    <Card className={`h-full flex flex-col overflow-hidden ${className ?? ''}`}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 px-4 py-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          {title}
        </h2>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </CardHeader>
      <CardContent className="flex-1 min-h-0 p-0">
        {children}
      </CardContent>
    </Card>
  )
}
