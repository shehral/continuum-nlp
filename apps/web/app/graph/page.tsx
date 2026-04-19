"use client"

import { useState, useCallback } from "react"
import { useQuery } from "@tanstack/react-query"

import { AppShell } from "@/components/layout/app-shell"
import { KnowledgeGraph } from "@/components/graph/knowledge-graph"
import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/error-state"
import { GraphSkeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { RefreshCw } from "lucide-react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

// Read-only knowledge graph view. Delete / reset / project-management
// surfaces from the original Continuum product are intentionally not exposed.

export default function GraphPage() {
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [projectFilter, setProjectFilter] = useState<string | null>(null)

  const {
    data: graphData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["graph", sourceFilter, projectFilter],
    queryFn: () =>
      api.getGraph({
        include_similarity: true,
        include_temporal: true,
        include_entity_relations: true,
        source_filter: sourceFilter as "claude_logs" | "interview" | "manual" | "unknown" | undefined,
        project_filter: projectFilter || undefined,
      }),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })

  const { data: sourceCounts } = useQuery({
    queryKey: ["graph-sources"],
    queryFn: () => api.getDecisionSources(),
    staleTime: 5 * 60 * 1000,
  })

  const { data: projectCounts } = useQuery({
    queryKey: ["project-counts"],
    queryFn: () => api.getProjectCounts(),
    staleTime: 5 * 60 * 1000,
  })

  const handleSourceFilterChange = useCallback((source: string | null) => {
    setSourceFilter(source)
  }, [])

  const handleProjectFilterChange = useCallback((project: string | null) => {
    setProjectFilter(project)
  }, [])

  return (
    <AppShell>
      <div className="h-full flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] bg-slate-900/80 backdrop-blur-xl animate-in fade-in slide-in-from-top-4 duration-500">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Knowledge Graph</h1>
            <p className="text-sm text-muted-foreground">
              Explore decisions and their relationships
              {sourceFilter && (
                <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">
                  Filtered: {sourceFilter === "claude_logs" ? "AI Extracted" :
                            sourceFilter === "interview" ? "Human Captured" :
                            sourceFilter === "manual" ? "Manual Entry" : "Legacy"}
                </span>
              )}
              {projectFilter && (
                <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-primary/20 text-primary border border-primary/30">
                  Project: {projectFilter}
                </span>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetch()}
                    disabled={isFetching}
                    className="border-border text-foreground hover:bg-muted hover:scale-105 transition-all"
                    aria-label="Refresh graph"
                  >
                    <RefreshCw
                      className={`h-4 w-4 mr-2 ${isFetching ? "animate-spin" : ""}`}
                      aria-hidden="true"
                    />
                    Refresh
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Reload graph data</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>

        <div className="flex-1" role="main" aria-label="Knowledge graph visualization area">
          {isLoading ? (
            <div aria-live="polite" aria-busy="true" className="h-full">
              <GraphSkeleton />
            </div>
          ) : error ? (
            <ErrorState
              title="Failed to load graph"
              message="We couldn't load the knowledge graph. Please try again."
              error={error instanceof Error ? error : null}
              retry={() => refetch()}
            />
          ) : (
            <KnowledgeGraph
              data={graphData}
              sourceFilter={sourceFilter}
              onSourceFilterChange={handleSourceFilterChange}
              sourceCounts={sourceCounts || {}}
              projectFilter={projectFilter}
              onProjectFilterChange={handleProjectFilterChange}
              projectCounts={projectCounts || {}}
              // No onDeleteDecision — graph is read-only in this build.
            />
          )}
        </div>
      </div>
    </AppShell>
  )
}
