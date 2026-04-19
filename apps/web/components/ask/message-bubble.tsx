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
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {message.content}
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
