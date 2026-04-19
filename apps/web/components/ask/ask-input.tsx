"use client"

import { useState, useRef, useEffect } from "react"
import { cn } from "@/lib/utils"

interface AskInputProps {
  onSubmit: (query: string) => void
  isLoading: boolean
}

export function AskInput({ onSubmit, isLoading }: AskInputProps) {
  const [value, setValue] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-grow the textarea up to a cap, then let it scroll.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [value])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (trimmed && !isLoading) {
      onSubmit(trimmed)
      setValue("")
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const canSubmit = !isLoading && value.trim().length > 0

  return (
    <form onSubmit={handleSubmit} className="group relative">
      <div className="flex items-start gap-4">
        <span className="mt-[14px] shrink-0 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground group-focus-within:text-primary transition-colors">
          query
        </span>

        <div className="relative flex-1">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Probe the graph…"
            disabled={isLoading}
            className={cn(
              "w-full resize-none bg-transparent py-3 text-[17px] leading-[1.5]",
              "font-[var(--font-serif)] italic tracking-tight",
              "text-foreground placeholder:text-muted-foreground placeholder:italic",
              "border-0 outline-none focus:ring-0 focus-visible:ring-0",
              isLoading && "opacity-60"
            )}
            style={{ fontFamily: "var(--font-serif)" }}
            autoFocus
          />
          <span
            aria-hidden
            className={cn(
              "absolute bottom-0 left-0 h-px w-full bg-border transition-all duration-300",
              "group-focus-within:bg-gradient-to-r group-focus-within:from-primary group-focus-within:via-[hsl(var(--nebula-rose))] group-focus-within:to-transparent"
            )}
          />
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className={cn(
            "group/btn mt-1 flex h-11 shrink-0 items-center gap-2 rounded-full border px-5 font-mono text-[10px] uppercase tracking-[0.22em] transition-all",
            canSubmit
              ? "border-primary/60 bg-primary/10 text-primary hover:border-primary hover:bg-primary hover:text-primary-foreground hover:shadow-[0_0_24px_-6px_hsl(var(--primary)/0.7)]"
              : "border-border bg-muted/40 text-muted-foreground/60 cursor-not-allowed"
          )}
          aria-label="Send query"
        >
          {isLoading ? (
            <>
              <span className="h-[6px] w-[6px] animate-pulse rounded-full bg-primary" />
              <span>thinking</span>
            </>
          ) : (
            <>
              <span>ask</span>
              <span aria-hidden className="text-base transition-transform group-hover/btn:translate-x-0.5">
                →
              </span>
            </>
          )}
        </button>
      </div>

      <div className="mt-3 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
        <span>Grounded answers · every claim carries a citation</span>
        <span className="hidden sm:inline">
          <kbd className="rounded border border-border px-1.5 py-0.5 text-muted-foreground">↵</kbd>{" "}
          send · <kbd className="rounded border border-border px-1.5 py-0.5 text-muted-foreground">⇧↵</kbd>{" "}
          newline
        </span>
      </div>
    </form>
  )
}
