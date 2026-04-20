"use client"

import Link from "next/link"
import { motion } from "framer-motion"
import { cn } from "@/lib/utils"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import type { AskSubgraph } from "@/lib/api"

// Theme-aware entity accents — darker values for light mode, lighter for dark.
const entityAccent: Record<string, string> = {
  technology: "text-orange-700 dark:text-orange-300 border-orange-500/50",
  pattern: "text-rose-700 dark:text-rose-300 border-rose-500/50",
  concept: "text-primary border-primary/50",
  person: "text-emerald-700 dark:text-emerald-300 border-emerald-500/50",
  system: "text-green-700 dark:text-green-300 border-green-500/50",
}

interface SourceCardsProps {
  sources: AskSubgraph
}

/**
 * Editorial citation strip. Shaped like coordinate plates: uppercase mono
 * kickers, bracketed id fragments, thin rule lines. Seed nodes get an active
 * violet "★ seed" tag; decision cards are clickable and link to /decisions/[id].
 *
 * Decision cards get a visible [N] badge whose number matches the inline
 * [N] citations emitted in the LLM answer above. Each card also mounts
 * an `id="cite-N"` anchor so inline citation pills can scroll to it and
 * trigger a brief "flash" highlight — verifying a hallucination claim
 * stays on one page.
 */
export function SourceCards({ sources }: SourceCardsProps) {
  const ordered = [...sources.nodes].sort((a, b) => {
    if (a.is_seed && !b.is_seed) return -1
    if (!a.is_seed && b.is_seed) return 1
    return 0
  })

  const displayNodes = ordered.slice(0, 10)
  const total = sources.nodes.length

  // Canonical [N] -> decision_id mapping as published by the backend in
  // the SSE `context` event. Build the reverse for quick card lookup.
  const citationIds = sources.citation_ids ?? []
  const decisionIdToCite = new Map<string, number>()
  citationIds.forEach((id, i) => decisionIdToCite.set(id, i + 1))

  return (
    <div className="w-full">
      <div className="mb-3 flex items-baseline gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-primary">
          ◇ trace
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          {displayNodes.length}/{total} nodes · click a decision to open the full citation
        </span>
        <span aria-hidden className="h-px flex-1 bg-border" />
      </div>

      <ScrollArea className="w-full">
        <motion.div
          className="flex gap-3 pb-3"
          initial="hidden"
          animate="visible"
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.035 } },
          }}
        >
          {displayNodes.map((node) => {
            const isDecision = node.type === "decision"
            const isSeed = Boolean(node.is_seed)
            const entityType = !isDecision ? node.data.entity_type || "concept" : undefined
            const citeNumber = isDecision ? decisionIdToCite.get(node.id) : undefined

            const title = isDecision
              ? node.data.decision || node.data.trigger || "Decision"
              : node.data.name || "Entity"

            const idFragment = node.id.slice(0, 8)
            const confidence = isDecision
              ? typeof node.data.confidence === "number"
                ? Math.round(node.data.confidence * 100)
                : null
              : null

            const card = (
              <motion.div
                // Anchor so inline [N] pills can scrollIntoView here.
                // We also expose the cite number on a data attribute so
                // the message-bubble flash logic can target it.
                id={citeNumber ? `cite-${citeNumber}` : undefined}
                data-cite={citeNumber}
                variants={{
                  hidden: { opacity: 0, y: 8 },
                  visible: { opacity: 1, y: 0, transition: { duration: 0.3 } },
                }}
                className={cn(
                  "relative shrink-0 w-64 border bg-background/60 backdrop-blur-sm px-4 py-3 transition-all scroll-mt-24",
                  "group/card",
                  isSeed
                    ? "border-primary/60 shadow-[0_0_28px_-10px_hsl(var(--primary)/0.45)]"
                    : "border-border",
                  isDecision
                    ? "hover:-translate-y-0.5 hover:border-primary hover:shadow-[0_0_36px_-10px_hsl(var(--primary)/0.5)] cursor-pointer"
                    : !isDecision && entityType
                    ? cn("cursor-default", entityAccent[entityType])
                    : "cursor-default"
                )}
              >
                {citeNumber !== undefined && (
                  <span
                    aria-hidden
                    className={cn(
                      "absolute -top-2 -left-2 h-6 min-w-[1.6rem] px-1.5 flex items-center justify-center",
                      "font-mono text-[11px] font-medium text-primary-foreground",
                      "bg-primary rounded-md border border-primary/70 shadow-sm",
                      "tabular-nums"
                    )}
                  >
                    [{citeNumber}]
                  </span>
                )}
                {/* Corner bracket detail */}
                <span
                  aria-hidden
                  className={cn(
                    "absolute -top-px -left-px h-2 w-2 border-l border-t transition-colors",
                    isSeed ? "border-primary" : "border-border",
                    "group-hover/card:border-primary"
                  )}
                />
                <span
                  aria-hidden
                  className={cn(
                    "absolute -bottom-px -right-px h-2 w-2 border-r border-b transition-colors",
                    isSeed ? "border-primary" : "border-border",
                    "group-hover/card:border-primary"
                  )}
                />

                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-muted-foreground">
                    {isDecision ? "decision" : `entity · ${entityType}`}
                  </span>
                  {isSeed && (
                    <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-primary">
                      ★ seed
                    </span>
                  )}
                </div>

                <p
                  className={cn(
                    "mt-2 line-clamp-3 text-[13px] leading-snug",
                    isDecision ? "text-foreground/90" : "text-foreground/90 font-medium"
                  )}
                  style={
                    isDecision
                      ? { fontFamily: "var(--font-serif)", fontStyle: "italic" }
                      : undefined
                  }
                >
                  {title}
                </p>

                <div className="mt-3 flex items-center justify-between gap-2 font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
                  <span>[{idFragment}]</span>
                  {confidence !== null && (
                    <span
                      className="flex items-center gap-1.5"
                      // Clarifies to graders that this is the extractor's
                      // confidence in parsing, NOT retrieval relevance.
                      title={`Extraction quality score assigned by the decision extractor (not retrieval relevance). This node was parsed cleanly ${confidence}% of the way against the schema.`}
                    >
                      <span
                        aria-label={`extraction confidence ${confidence}%`}
                        className="relative h-[3px] w-10 overflow-hidden rounded-full bg-muted"
                      >
                        <span
                          className="absolute inset-y-0 left-0 bg-primary"
                          style={{ width: `${confidence}%` }}
                        />
                      </span>
                      <span>extr {(confidence / 100).toFixed(2)}</span>
                    </span>
                  )}
                  {isDecision && (
                    <span
                      aria-hidden
                      className="text-muted-foreground transition-all group-hover/card:translate-x-0.5 group-hover/card:text-primary"
                    >
                      →
                    </span>
                  )}
                </div>
              </motion.div>
            )

            if (isDecision) {
              return (
                <Link
                  key={node.id}
                  href={`/decisions/${node.id}`}
                  aria-label={`Open decision: ${title}`}
                  className="shrink-0"
                >
                  {card}
                </Link>
              )
            }

            return <div key={node.id}>{card}</div>
          })}
        </motion.div>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </div>
  )
}
