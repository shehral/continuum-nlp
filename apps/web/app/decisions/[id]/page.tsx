"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { use } from "react"
import { ArrowLeft, FileText, Sparkles, GitBranch, Tag } from "lucide-react"

import { AppShell } from "@/components/layout/app-shell"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/error-state"
import { api } from "@/lib/api"
import { getEntityStyle } from "@/lib/constants"

export default function DecisionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)

  const { data: decision, isLoading, error, refetch } = useQuery({
    queryKey: ["decision", id],
    queryFn: () => api.getDecision(id),
    retry: 1,
  })

  return (
    <AppShell>
      <div className="max-w-4xl mx-auto py-10 px-6 space-y-6">
        <div className="flex items-center justify-between">
          <Link href="/ask">
            <Button variant="ghost" size="sm" className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to Ask
            </Button>
          </Link>
          <Link href="/graph">
            <Button variant="ghost" size="sm" className="gap-2">
              <GitBranch className="h-4 w-4" />
              View in graph
            </Button>
          </Link>
        </div>

        {isLoading && (
          <Card className="animate-pulse">
            <CardHeader>
              <div className="h-6 w-2/3 rounded bg-muted" />
              <div className="h-4 w-1/3 mt-2 rounded bg-muted" />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="h-20 rounded bg-muted" />
              <div className="h-20 rounded bg-muted" />
            </CardContent>
          </Card>
        )}

        {error && (
          <ErrorState
            title="Couldn't load this decision"
            message={(error as Error).message}
            retry={() => refetch()}
          />
        )}

        {decision && (
          <>
            <Card variant="glass">
              <CardHeader>
                <div className="flex items-start gap-3">
                  <FileText className="h-5 w-5 text-primary mt-1 shrink-0" />
                  <div>
                    <p className="text-xs uppercase tracking-widest text-muted-foreground">
                      Trigger
                    </p>
                    <CardTitle className="text-xl leading-tight mt-1">
                      {decision.trigger || "Untitled decision"}
                    </CardTitle>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 mt-3">
                  <Badge
                    variant="outline"
                    className="bg-primary/10 text-primary border-primary/30"
                  >
                    confidence {(decision.confidence ?? 0).toFixed(2)}
                  </Badge>
                  {decision.source && (
                    <Badge variant="outline" className="text-muted-foreground">
                      source: {decision.source}
                    </Badge>
                  )}
                  {decision.project_name && (
                    <Badge variant="outline" className="text-muted-foreground">
                      project: {decision.project_name}
                    </Badge>
                  )}
                </div>
              </CardHeader>
            </Card>

            {decision.context && (
              <Section title="Context" body={decision.context} />
            )}

            {decision.options?.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
                    Options considered
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    {decision.options.map((opt, idx) => (
                      <li
                        key={idx}
                        className="flex items-start gap-2 text-sm"
                      >
                        <span className="mt-1 h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                        <span>{opt}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}

            <Card variant="glow">
              <CardHeader>
                <CardTitle className="text-sm font-semibold tracking-wide text-muted-foreground uppercase flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Decision
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-base leading-relaxed">
                  {decision.agent_decision ||
                    decision.human_decision ||
                    "—"}
                </p>
              </CardContent>
            </Card>

            <Section
              title="Rationale"
              body={
                decision.agent_rationale || decision.human_rationale || "—"
              }
            />

            {decision.entities?.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-semibold tracking-wide text-muted-foreground uppercase flex items-center gap-2">
                    <Tag className="h-4 w-4" />
                    Involved entities ({decision.entities.length})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    {decision.entities.map((e) => {
                      const style = getEntityStyle(e.type)
                      return (
                        <Badge
                          key={e.id}
                          variant="outline"
                          className={`${style.bg} ${style.text} ${style.border}`}
                        >
                          {e.name}
                          <span className="ml-1 opacity-60 text-[10px]">
                            {e.type}
                          </span>
                        </Badge>
                      )
                    })}
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </AppShell>
  )
}

function Section({ title, body }: { title: string; body: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{body}</p>
      </CardContent>
    </Card>
  )
}
