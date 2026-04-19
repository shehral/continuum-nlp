"use client"

import { useState, useMemo } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Search, FileText, ArrowRight, Loader2 } from "lucide-react"

import { AppShell } from "@/components/layout/app-shell"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ErrorState } from "@/components/ui/error-state"
import { api, type Decision } from "@/lib/api"
import { cn } from "@/lib/utils"

// Read-only browse of all extracted decisions. Each card links into
// /decisions/[id] for the full trace. No edit / delete / create — those
// flows are not part of the demo build.

export default function DecisionsListPage() {
  const [query, setQuery] = useState("")

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["decisions-list-all"],
    queryFn: () => api.getDecisions(500, 0), // 386 decisions in graph; fetch all
    staleTime: 5 * 60 * 1000,
  })

  const filtered = useMemo(() => {
    const all: Decision[] = data ?? []
    if (!query.trim()) return all
    const q = query.toLowerCase()
    return all.filter(
      (d) =>
        (d.trigger || "").toLowerCase().includes(q) ||
        (d.agent_decision || "").toLowerCase().includes(q) ||
        (d.agent_rationale || "").toLowerCase().includes(q) ||
        (d.entities || []).some((e) => e.name.toLowerCase().includes(q))
    )
  }, [data, query])

  return (
    <AppShell>
      <div className="h-full flex flex-col">
        <header className="border-b border-border/40 bg-background/70 backdrop-blur-xl">
          <div className="mx-auto flex max-w-5xl items-baseline justify-between px-8 py-5">
            <div className="flex items-baseline gap-3">
              <span aria-hidden className="text-primary">◇</span>
              <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                decisions browser
              </span>
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              <span className="text-primary">{filtered.length}</span> of{" "}
              <span className="text-primary">{data?.length ?? 0}</span> decisions
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-5xl px-8 py-8 space-y-6">
            <div className="relative">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter by trigger, decision, rationale, or involved entity…"
                className="pl-10 h-11"
              />
            </div>

            {isLoading && (
              <div className="flex items-center gap-3 text-muted-foreground py-12 justify-center">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>Loading decisions…</span>
              </div>
            )}

            {error && (
              <ErrorState
                title="Couldn't load the decisions list"
                message={(error as Error).message}
                retry={() => refetch()}
              />
            )}

            {data && (
              <div className="grid gap-3">
                {filtered.map((d) => (
                  <Link
                    key={d.id}
                    href={`/decisions/${d.id}`}
                    aria-label={`Open decision: ${d.trigger}`}
                  >
                    <Card
                      className={cn(
                        "group relative px-5 py-4 transition-all cursor-pointer",
                        "border-border hover:border-primary/60",
                        "hover:shadow-[0_0_28px_-12px_hsl(var(--primary)/0.45)] hover:-translate-y-0.5"
                      )}
                    >
                      <div className="flex items-start gap-4">
                        <FileText className="h-4 w-4 text-primary shrink-0 mt-1" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline gap-3 mb-1.5">
                            <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-muted-foreground">
                              decision
                            </span>
                            {typeof d.confidence === "number" && (
                              <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-muted-foreground">
                                conf {(d.confidence * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                          <p
                            className="text-[16px] leading-snug text-foreground"
                            style={{
                              fontFamily: "var(--font-serif)",
                              fontStyle: "italic",
                            }}
                          >
                            {d.trigger || "(untitled)"}
                          </p>
                          {d.agent_decision && (
                            <p className="mt-2 text-sm text-foreground/85 line-clamp-2">
                              <span className="text-muted-foreground">
                                Decision:{" "}
                              </span>
                              {d.agent_decision}
                            </p>
                          )}
                          {d.entities && d.entities.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-1.5">
                              {d.entities.slice(0, 6).map((e) => (
                                <Badge
                                  key={e.id}
                                  variant="outline"
                                  className="text-[10px] font-mono uppercase tracking-wider border-border text-muted-foreground"
                                >
                                  {e.name}
                                </Badge>
                              ))}
                              {d.entities.length > 6 && (
                                <Badge
                                  variant="outline"
                                  className="text-[10px] font-mono uppercase tracking-wider border-border/50 text-muted-foreground/70"
                                >
                                  +{d.entities.length - 6}
                                </Badge>
                              )}
                            </div>
                          )}
                        </div>
                        <ArrowRight
                          aria-hidden
                          className="h-4 w-4 shrink-0 self-center text-muted-foreground/50 group-hover:text-primary group-hover:translate-x-0.5 transition-all"
                        />
                      </div>
                    </Card>
                  </Link>
                ))}
                {filtered.length === 0 && !isLoading && (
                  <div className="text-center py-16 text-muted-foreground text-sm">
                    No decisions match <span className="font-mono text-primary">{query}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}
