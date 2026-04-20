"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"
import type { AskMessage } from "@/lib/api"
import { SourceCards } from "./source-cards"

interface MessageBubbleProps {
  message: AskMessage
  index: number
}

/**
 * Rewrite bare `[N]` (and `[N][M]` clusters) the LLM emitted into the
 * markdown inline-link syntax `[[N]](#cite-N)`. A custom `a` renderer
 * below intercepts `#cite-N` hrefs and turns them into clickable
 * superscript citations that deep-link to the corresponding decision.
 *
 * Two guards:
 * - Skip numbers outside the available citation range so we don't
 *   hallucinate links for tokens like `[2024]` in a year reference.
 * - Don't match inside fenced code blocks (``` ... ```), inline code
 *   (`...`), or existing markdown links `[text](url)`.
 */
function injectCitationLinks(
  content: string,
  citationIds: readonly string[] | undefined
): string {
  if (!citationIds || citationIds.length === 0) return content
  const maxN = citationIds.length

  // Split the content on code-fence boundaries and only process the
  // prose regions. Each odd-indexed segment is a fenced code block and
  // left untouched.
  const fenceParts = content.split(/(```[\s\S]*?```)/g)

  for (let fi = 0; fi < fenceParts.length; fi++) {
    if (fi % 2 === 1) continue

    // Inline-code segments next (single-backtick spans).
    const codeParts = fenceParts[fi].split(/(`[^`\n]*`)/g)
    for (let ci = 0; ci < codeParts.length; ci++) {
      if (ci % 2 === 1) continue
      const region = codeParts[ci]

      // Walk manually so we can avoid matching `[N]` when it is already
      // part of a markdown link (e.g. `[1](https://...)`) or when N is
      // out of range.
      let out = ""
      let i = 0
      while (i < region.length) {
        const m = region.slice(i).match(/\[(\d+)\]/)
        if (!m) {
          out += region.slice(i)
          break
        }
        const bracketStart = i + (m.index ?? 0)
        const bracketEnd = bracketStart + m[0].length
        out += region.slice(i, bracketStart)

        const n = parseInt(m[1], 10)
        const alreadyLinked = region[bracketEnd] === "("
        if (!alreadyLinked && n >= 1 && n <= maxN) {
          out += `[${m[0]}](#cite-${n})`
        } else {
          out += m[0]
        }
        i = bracketEnd
      }
      codeParts[ci] = out
    }
    fenceParts[fi] = codeParts.join("")
  }

  return fenceParts.join("")
}

/**
 * Editorial-style message row. No avatars, no rounded bubbles — speaker is
 * marked via an uppercase mono kicker and a thin accent rule. The user's
 * question reads as a pull quote; the assistant's answer as body text.
 */
export function MessageBubble({ message, index }: MessageBubbleProps) {
  const isUser = message.role === "user"
  const kicker = isUser
    ? `you · q${String(index).padStart(2, "0")}`
    : `graph-rag · a${String(index).padStart(2, "0")}`

  if (isUser) {
    return (
      <div className="group relative pl-6">
        <div
          aria-hidden
          className="absolute left-0 top-[0.6rem] h-[calc(100%-1.2rem)] w-px bg-gradient-to-b from-primary via-primary/40 to-transparent"
        />
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-primary">
          {kicker}
        </p>
        <blockquote
          className="mt-2 text-[22px] leading-[1.3] text-foreground/95"
          style={{ fontFamily: "var(--font-serif)", fontStyle: "italic" }}
        >
          {message.content}
        </blockquote>
      </div>
    )
  }

  const streaming = !message.content

  return (
    <div className="relative">
      <div className="mb-3 flex items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
          {kicker}
        </span>
        <span aria-hidden className="h-px flex-1 bg-gradient-to-r from-border to-transparent" />
      </div>

      <div
        className={cn(
          "prose prose-sm dark:prose-invert max-w-none",
          "prose-p:leading-[1.75] prose-p:text-[15px] prose-p:text-foreground/90",
          "prose-p:my-3",
          "prose-strong:text-foreground prose-strong:font-semibold",
          "prose-em:text-foreground/95",
          "prose-li:leading-[1.7] prose-li:text-[15px] prose-li:text-foreground/90",
          "prose-li:my-1",
          "prose-ol:my-3 prose-ul:my-3",
          "prose-headings:font-serif prose-headings:font-normal prose-headings:tracking-tight",
          "prose-headings:text-foreground",
          "prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg",
          "prose-code:font-mono prose-code:text-[0.85em] prose-code:text-primary",
          "prose-code:bg-primary/10 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded",
          "prose-code:before:content-none prose-code:after:content-none",
          "prose-pre:bg-muted/60 prose-pre:border prose-pre:border-border",
          "prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
          "prose-blockquote:border-primary prose-blockquote:text-foreground/80"
        )}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children, ...props }) => {
              if (
                href &&
                href.startsWith("#cite-") &&
                message.sources?.citation_ids
              ) {
                const n = parseInt(href.slice("#cite-".length), 10)
                const decisionId =
                  Number.isFinite(n) && n >= 1 && n <= message.sources.citation_ids.length
                    ? message.sources.citation_ids[n - 1]
                    : undefined
                if (decisionId) {
                  const sourceNode = message.sources.nodes.find(
                    (node) => node.id === decisionId
                  )
                  const preview = sourceNode?.data?.trigger
                  const tooltip = preview
                    ? `[${n}] ${preview}  —  click to jump to the source card; shift-click to open the full trace`
                    : `Citation ${n}`

                  const onCiteClick = (
                    evt: React.MouseEvent<HTMLAnchorElement>
                  ) => {
                    // Shift-click (or ctrl/cmd-click) still opens the full
                    // decision trace in a new page — power-user escape hatch.
                    if (evt.shiftKey || evt.metaKey || evt.ctrlKey) {
                      window.open(`/decisions/${decisionId}`, "_blank")
                      evt.preventDefault()
                      return
                    }
                    evt.preventDefault()
                    const target = document.getElementById(`cite-${n}`)
                    if (!target) {
                      // Card isn't in this message's strip for some reason —
                      // fall through to full trace so the claim is still verifiable.
                      window.location.href = `/decisions/${decisionId}`
                      return
                    }
                    target.scrollIntoView({ behavior: "smooth", block: "center" })
                    target.classList.add("citation-flash")
                    window.setTimeout(
                      () => target.classList.remove("citation-flash"),
                      1400
                    )
                  }

                  return (
                    <a
                      href={`#cite-${n}`}
                      onClick={onCiteClick}
                      title={tooltip}
                      aria-label={tooltip}
                      className={cn(
                        "inline-flex mx-0.5 px-1.5 py-[1px]",
                        "align-super text-[0.72em] font-medium font-mono no-underline",
                        "rounded-md border border-primary/30 bg-primary/10 text-primary",
                        "hover:bg-primary/20 hover:border-primary/60",
                        "transition-colors"
                      )}
                    >
                      {children}
                    </a>
                  )
                }
              }
              return <a href={href} {...props}>{children}</a>
            },
          }}
        >
          {injectCitationLinks(message.content, message.sources?.citation_ids)}
        </ReactMarkdown>
        {streaming && (
          <span className="ml-1 inline-block h-[1.1em] w-[2px] translate-y-[0.18em] animate-pulse bg-primary align-baseline" />
        )}
      </div>

      {message.sources && message.sources.nodes.length > 0 && (
        <div className="mt-8">
          <SourceCards sources={message.sources} />
        </div>
      )}
    </div>
  )
}
