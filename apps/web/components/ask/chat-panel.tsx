"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import type { AskMessage, AskSubgraph } from "@/lib/api"
import { MessageBubble } from "./message-bubble"
import { AskInput } from "./ask-input"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

/**
 * Starter prompts tuned to what's actually in the CS 6120 graph.
 * Each references a decision pattern that exists with enough supporting
 * context for Graph-RAG to produce a grounded answer.
 */
const STARTER_PROMPTS: { kicker: string; query: string }[] = [
  {
    kicker: "Comparative",
    query: "What are the trade-offs between PostgREST, Hasura, and Supabase?",
  },
  {
    kicker: "Architecture",
    query: "Why might a team pick Marten on Postgres for event sourcing?",
  },
  {
    kicker: "Summary",
    query: "Summarize the decisions that involve FastAPI.",
  },
  {
    kicker: "Traversal",
    query: "Which decisions involve Amazon SQS and what were the alternatives?",
  },
  {
    kicker: "Exploration",
    query: "Show me Rust-related architectural decisions.",
  },
  {
    kicker: "Pattern",
    query: "What patterns show up around caching with Redis?",
  },
]

export function ChatPanel() {
  const [messages, setMessages] = useState<AskMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const messageIdRef = useRef(0)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSubmit = useCallback(async (query: string) => {
    const userMsgId = `msg-${++messageIdRef.current}`
    const assistantMsgId = `msg-${++messageIdRef.current}`

    const userMessage: AskMessage = { id: userMsgId, role: "user", content: query }
    const assistantMessage: AskMessage = { id: assistantMsgId, role: "assistant", content: "" }

    // Capture the prior turn (most recent assistant message + the user query
    // that produced it) so the API can resolve referential follow-ups like
    // "tell me more about decision 5". Computed BEFORE we append the new
    // turn to state.
    let prevQ: string | undefined
    let prevA: string | undefined
    setMessages((prev) => {
      const lastAssistant = [...prev].reverse().find(
        (m) => m.role === "assistant" && m.content.trim().length > 0
      )
      if (lastAssistant) {
        const idx = prev.indexOf(lastAssistant)
        const lastUser = idx > 0 ? prev[idx - 1] : null
        if (lastUser && lastUser.role === "user") {
          prevQ = lastUser.content
          prevA = lastAssistant.content
        }
      }
      return [...prev, userMessage, assistantMessage]
    })
    setIsLoading(true)

    try {
      const params = new URLSearchParams({ q: query })
      if (prevQ && prevA) {
        params.set("prev_q", prevQ)
        // Cap to 4000 chars to match the API's max_length on prev_a.
        params.set("prev_a", prevA.slice(0, 4000))
      }
      const response = await fetch(`${API_URL}/api/ask?${params}`)
      if (!response.ok) throw new Error(`API error: ${response.status}`)

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No response body")

      const decoder = new TextDecoder()
      let buffer = ""
      // Keep eventType at the outer scope so an `event:` line in one TCP
      // chunk stays associated with its `data:` line in the next. The context
      // payload (~8 KB for a 40-node subgraph) routinely straddles chunks.
      let eventType = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data)

              if (eventType === "context") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId ? { ...m, sources: parsed as AskSubgraph } : m
                  )
                )
              } else if (eventType === "token") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId ? { ...m, content: m.content + parsed.text } : m
                  )
                )
              } else if (eventType === "error") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId ? { ...m, content: `⚠ ${parsed.detail}` } : m
                  )
                )
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    } catch (error) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: `⚠ Failed to get response: ${
                  error instanceof Error ? error.message : "Unknown error"
                }`,
              }
            : m
        )
      )
    } finally {
      setIsLoading(false)
    }
  }, [])

  const sessionKicker = messages.length
    ? `observation / ${String(Math.ceil(messages.length / 2)).padStart(3, "0")}`
    : "observation / 000"

  return (
    <div className="relative flex h-full flex-col bg-background">
      {/* Grain + nebula background wash */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.35]"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 10% 0%, rgba(139,92,246,0.12), transparent 60%), radial-gradient(ellipse 60% 40% at 95% 100%, rgba(236,72,153,0.10), transparent 60%)",
        }}
      />

      {/* Header strip */}
      <header className="border-b border-border/40 bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-baseline justify-between px-8 py-5">
          <div className="flex items-baseline gap-3">
            <span aria-hidden className="text-primary">◎</span>
            <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
              graph-rag observatory
            </span>
          </div>
          <div className="flex items-baseline gap-6 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
            <span>
              <span className="text-primary">386</span> decisions
            </span>
            <span className="hidden sm:inline">
              <span className="text-primary">847</span> entities
            </span>
            <span className="hidden md:inline">llama3.2 · nomic-768</span>
            <span>{sessionKicker}</span>
          </div>
        </div>
      </header>

      {/* Messages / hero area */}
      <div className="flex-1 overflow-y-auto" ref={scrollRef}>
        <div className="mx-auto max-w-3xl px-8 py-10">
          {messages.length === 0 ? (
            <EmptyState onPick={handleSubmit} />
          ) : (
            <div className="space-y-14">
              <AnimatePresence initial={false}>
                {messages.map((message, i) => (
                  <motion.div
                    key={message.id}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.45, delay: i === messages.length - 1 ? 0 : 0 }}
                  >
                    <MessageBubble message={message} index={Math.ceil((i + 1) / 2)} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border/40 bg-background/80 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl px-8 py-5">
          <AskInput onSubmit={handleSubmit} isLoading={isLoading} />
        </div>
      </div>
    </div>
  )
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="pt-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7 }}
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-primary">
          — prompt the graph
        </p>
        <h1
          className="mt-4 font-serif text-[clamp(2.6rem,6vw,4.25rem)] leading-[1.02] tracking-[-0.015em] text-foreground"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          What do you want
          <br />
          <em className="text-primary">to know?</em>
        </h1>
        <p className="mt-5 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Every answer below is grounded in a subgraph of decisions pulled live from the
          knowledge store. Click a decision citation to open its full trace.
        </p>
      </motion.div>

      <motion.ol
        className="mt-14 grid grid-cols-1 gap-0 divide-y divide-border/40 border-y border-border/40 md:grid-cols-2 md:divide-x md:divide-y-0"
        initial="hidden"
        animate="visible"
        variants={{
          hidden: {},
          visible: { transition: { staggerChildren: 0.08, delayChildren: 0.2 } },
        }}
      >
        {STARTER_PROMPTS.map((p, i) => (
          <motion.li
            key={p.query}
            variants={{
              hidden: { opacity: 0, y: 10 },
              visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
            }}
            className={
              i >= 2
                ? "md:border-t md:border-border/40"
                : undefined
            }
          >
            <button
              type="button"
              onClick={() => onPick(p.query)}
              className="group relative flex w-full items-start gap-5 px-4 py-6 text-left transition-colors hover:bg-primary/5 focus-visible:bg-primary/5 focus-visible:outline-none"
            >
              <span className="shrink-0 pt-0.5 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground group-hover:text-primary transition-colors">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="flex-1">
                <span className="block font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground group-hover:text-primary transition-colors">
                  {p.kicker}
                </span>
                <span
                  className="mt-2 block text-[17px] leading-snug text-foreground/90"
                  style={{ fontFamily: "var(--font-serif)", fontStyle: "italic" }}
                >
                  {p.query}
                </span>
              </span>
              <span
                aria-hidden
                className="shrink-0 self-center text-xl text-muted-foreground/60 transition-all group-hover:translate-x-1 group-hover:text-primary"
              >
                →
              </span>
            </button>
          </motion.li>
        ))}
      </motion.ol>
    </div>
  )
}
