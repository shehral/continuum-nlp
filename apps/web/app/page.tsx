"use client"

import React, { useState, useEffect, useRef } from "react"
import Link from "next/link"
import { GitBranch, MessageSquare, Scan, Network, Sun, Moon } from "lucide-react"
import { useTheme } from "next-themes"
import { Button } from "@/components/ui/button"
import { HeroConductor } from "@/components/landing/hero-conductor"
import { PulsingNetwork } from "@/components/landing/pulsing-network"
import { ConversationExtract } from "@/components/landing/conversation-extract"
import { FileScan } from "@/components/landing/file-scan"
import { ChatAnimation, ScanAnimation, MergeAnimation, GraphAnimation } from "@/components/landing/step-animations"
import { AmbientParticles } from "@/components/landing/ambient-particles"

// ─── Hooks ───────────────────────────────────────────────

function useScrollAnimation() {
  const ref = useRef<HTMLDivElement>(null)
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true)
          observer.unobserve(el)
        }
      },
      { threshold: 0.15 }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return { ref, isVisible }
}

function useCountUp(target: number, isVisible: boolean, duration = 2000) {
  const [count, setCount] = useState(0)

  useEffect(() => {
    if (!isVisible) return

    const start = performance.now()
    function tick(now: number) {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setCount(Math.floor(eased * target))
      if (progress < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, [isVisible, target, duration])

  return count
}

// ─── Feature Section Component ───────────────────────────

const glowColors = {
  violet: "from-violet-500/20 to-violet-500/5",
  rose: "from-rose-500/20 to-rose-500/5",
  orange: "from-orange-500/20 to-orange-500/5",
} as const

function FeatureSection({
  title,
  description,
  imageSrc,
  imageAlt,
  glowColor,
  imagePosition,
  animation,
}: {
  title: string
  description: string
  imageSrc?: string
  imageAlt?: string
  glowColor: keyof typeof glowColors
  imagePosition: "left" | "right"
  animation?: (isVisible: boolean) => React.ReactNode
}) {
  const { ref, isVisible } = useScrollAnimation()

  const textBlock = (
    <div className="flex flex-col justify-center">
      <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight mb-6">
        <span className="gradient-text">{title}</span>
      </h2>
      <p className="text-lg text-slate-400 leading-relaxed">{description}</p>
    </div>
  )

  const imageBlock = (
    <div className="relative">
      <div
        className={`absolute -inset-4 bg-gradient-to-br ${glowColors[glowColor]} rounded-3xl blur-2xl`}
        aria-hidden="true"
      />
      <div className="relative space-y-4">
        {animation && (
          <div className="rounded-2xl border border-border overflow-hidden shadow-lg dark:shadow-[0_16px_48px_rgba(0,0,0,0.4)] bg-card p-4 md:p-6">
            {animation(isVisible)}
          </div>
        )}
        {imageSrc && (
          <div className="rounded-2xl border border-border overflow-hidden shadow-lg dark:shadow-[0_16px_48px_rgba(0,0,0,0.4)]">
            <img src={imageSrc} alt={imageAlt} className="w-full h-auto" loading="lazy" />
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div
      ref={ref}
      className={`max-w-7xl mx-auto px-6 py-16 md:py-24 grid md:grid-cols-2 gap-12 md:gap-16 items-center transition-all duration-700 ${
        isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
      }`}
    >
      {imagePosition === "left" ? (
        <>
          {imageBlock}
          {textBlock}
        </>
      ) : (
        <>
          {textBlock}
          {imageBlock}
        </>
      )}
    </div>
  )
}

// ─── How It Works Component ──────────────────────────────

const steps = [
  {
    number: "01",
    icon: MessageSquare,
    title: "Synthetic Corpus",
    description:
      "200 synthetic developer-AI conversations spanning backend, ML, and infra decisions form the source dataset.",
  },
  {
    number: "02",
    icon: Scan,
    title: "Extract Once",
    description:
      "A one-shot LLM pipeline pulls 386 decision traces — trigger, context, options, decision, rationale — from the corpus.",
  },
  {
    number: "03",
    icon: GitBranch,
    title: "Resolve & Graph",
    description:
      "A 7-stage entity resolver canonicalizes 847 technologies and patterns, then writes the graph into Neo4j.",
  },
  {
    number: "04",
    icon: Network,
    title: "Serve via GraphRAG",
    description:
      "Hybrid lexical + vector retrieval expands seeds across the graph; a local Llama 3.1 8B answers with citations.",
  },
]

const stepAnimationComponents = [ChatAnimation, ScanAnimation, MergeAnimation, GraphAnimation]

function HowItWorks() {
  const { ref, isVisible } = useScrollAnimation()

  return (
    <section ref={ref} className="relative py-32 overflow-hidden">
      <div className="max-w-7xl mx-auto px-6">
        <div
          className={`text-center mb-16 transition-all duration-700 ${
            isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
          }`}
        >
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight mb-4">
            How It <span className="gradient-text">Works</span>
          </h2>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto">
            From synthetic conversations to a queryable knowledge graph in four steps.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {steps.map((step, i) => (
            <div
              key={step.number}
              className={`relative p-6 rounded-2xl bg-white/[0.02] border border-white/[0.06] backdrop-blur-sm transition-all duration-700 hover:border-violet-500/30 hover:-translate-y-1 ${
                isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
              }`}
              style={{ transitionDelay: isVisible ? `${i * 150}ms` : "0ms" }}
            >
              <span className="text-5xl font-bold text-foreground/[0.06] absolute top-4 right-4 select-none">
                {step.number}
              </span>

              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/10 border border-violet-500/20 flex items-center justify-center mb-4">
                {(() => {
                  const StepAnim = stepAnimationComponents[i]
                  return StepAnim ? <StepAnim isVisible={isVisible} /> : <step.icon className="w-5 h-5 text-violet-400" />
                })()}
              </div>

              <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
              <p className="text-sm text-slate-400 leading-relaxed">{step.description}</p>

              {i < steps.length - 1 && (
                <div
                  className="hidden lg:block absolute top-1/2 -right-3 w-6 h-px bg-gradient-to-r from-violet-500/40 to-transparent"
                  aria-hidden="true"
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── By the Numbers Component ────────────────────────────

const stats = [
  { value: 200, suffix: "", label: "Synthetic Conversations" },
  { value: 386, suffix: "", label: "Decision Traces" },
  { value: 847, suffix: "", label: "Resolved Entities" },
  { value: 7, suffix: "-Stage", label: "Entity Resolution" },
]

const techStack = [
  "Llama 3.1 8B",
  "Ollama",
  "nomic-embed-text",
  "Neo4j",
  "PostgreSQL",
  "FastAPI",
  "Next.js",
  "React",
  "Docker",
]

function StatCard({ stat, isVisible }: { stat: (typeof stats)[number]; isVisible: boolean }) {
  const count = useCountUp(stat.value, isVisible)

  return (
    <div className="p-6 rounded-2xl bg-white/[0.02] border border-white/[0.06] text-center hover:border-violet-500/30 transition-all">
      <div className="stat-number text-3xl md:text-4xl mb-1">
        {count.toLocaleString()}
        {stat.suffix}
      </div>
      <div className="text-sm text-slate-400">{stat.label}</div>
    </div>
  )
}

function TechCredibility() {
  const { ref, isVisible } = useScrollAnimation()

  return (
    <section ref={ref} className="relative py-32">
      <div className="max-w-5xl mx-auto px-6">
        <div
          className={`text-center mb-16 transition-all duration-700 ${
            isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
          }`}
        >
          <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight mb-4">
            By the <span className="gradient-text">Numbers</span>
          </h2>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto">
            A pre-extracted knowledge graph served by a fully self-hosted local stack.
          </p>
        </div>

        <div
          className={`grid grid-cols-2 md:grid-cols-4 gap-4 mb-16 transition-all duration-700 ${
            isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
          }`}
          style={{ transitionDelay: isVisible ? "200ms" : "0ms" }}
        >
          {stats.map((stat) => (
            <StatCard key={stat.label} stat={stat} isVisible={isVisible} />
          ))}
        </div>

        <div
          className={`flex flex-wrap justify-center gap-4 transition-all duration-700 ${
            isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8"
          }`}
          style={{ transitionDelay: isVisible ? "400ms" : "0ms" }}
        >
          {techStack.map((tech) => (
            <div
              key={tech}
              className="px-4 py-2 rounded-xl bg-white/[0.02] border border-white/[0.06] text-sm text-slate-400 hover:text-foreground hover:border-violet-500/30 transition-all"
            >
              {tech}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Main Landing Page ───────────────────────────────────

export default function LandingPage() {
  const [mounted, setMounted] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    setMounted(true)
    const handleScroll = () => setScrolled(window.scrollY > 50)
    window.addEventListener("scroll", handleScroll, { passive: true })
    return () => window.removeEventListener("scroll", handleScroll)
  }, [])

  return (
    <div className="min-h-screen bg-background text-foreground overflow-x-clip">
      {/* Nebula background */}
      <div className="nebula-bg" aria-hidden="true" />
      {mounted && <AmbientParticles />}

      {/* Navigation */}
      <nav
        className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
          scrolled
            ? "bg-background/80 backdrop-blur-xl border-b border-border"
            : "bg-transparent"
        }`}
      >
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="relative w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/20 to-fuchsia-500/10 border border-violet-500/30 flex items-center justify-center">
              <GitBranch className="w-4 h-4 text-violet-400" />
            </div>
            <span className="text-lg font-bold gradient-text">Continuum</span>
          </Link>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              className="text-muted-foreground hover:text-foreground"
              aria-label={mounted ? (theme === "dark" ? "Switch to light mode" : "Switch to dark mode") : "Toggle theme"}
            >
              {mounted ? (
                theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )
              ) : (
                <Sun className="h-4 w-4 opacity-0" />
              )}
            </Button>
            <Link href="/graph">
              <Button variant="ghost" className="text-muted-foreground hover:text-foreground">
                Graph
              </Button>
            </Link>
            <Link href="/ask">
              <Button variant="gradient">
                Ask the graph
              </Button>
            </Link>
            <Link href="/login">
              <Button variant="ghost" className="text-muted-foreground hover:text-foreground">
                Sign In
              </Button>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero — scroll-driven conductor scene */}
      {mounted && <HeroConductor />}

      {/* Features */}
      <section className="relative py-32">
        <FeatureSection
          title="Cited GraphRAG Answers"
          description="Every answer is grounded in the knowledge graph. Hybrid lexical + vector retrieval seeds a subgraph around your query, and the local LLM responds with inline citations to the exact decision nodes it drew from — click any citation to read the full trace."
          glowColor="violet"
          imagePosition="right"
          animation={(visible) => <PulsingNetwork isVisible={visible} />}
        />

        <FeatureSection
          title="Navigable Knowledge Graph"
          description="Pan, zoom, and explore the full extracted graph: 386 decisions linked to 847 canonical entities through INVOLVES and SIMILAR_TO edges. Filter by domain or technology, and trace how one architectural choice connects to dozens of downstream decisions."
          glowColor="rose"
          imagePosition="left"
          animation={(visible) => <ConversationExtract isVisible={visible} />}
        />

        <FeatureSection
          title="Local-First Inference"
          description="No cloud LLM dependency. Llama 3.1 8B serves answers via Ollama on a single T4 GPU; nomic-embed-text generates 768-d embeddings locally; Neo4j and PostgreSQL run in Docker. The whole stack boots with one command and works without an internet connection."
          glowColor="orange"
          imagePosition="right"
          animation={(visible) => <FileScan isVisible={visible} />}
        />
      </section>

      {/* How It Works */}
      <HowItWorks />

      {/* By the Numbers */}
      <TechCredibility />

      {/* Footer */}
      <footer className="border-t border-border py-12">
        <div className="max-w-7xl mx-auto px-6 flex flex-col items-center gap-4 text-center">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-violet-500/20 to-fuchsia-500/10 border border-violet-500/30 flex items-center justify-center">
              <GitBranch className="w-3 h-3 text-violet-400" />
            </div>
            <span className="font-semibold gradient-text">Continuum</span>
          </div>
          <p className="text-sm text-slate-500 max-w-md">
            Local-first GraphRAG over a knowledge graph of 386 software decisions — Llama 3.1 via Ollama, Neo4j, FastAPI, Next.js.
          </p>
          <p className="text-xs text-slate-500 max-w-md">
            CS 6120 Final Project · Northeastern University
          </p>
          <div className="flex items-center gap-6 text-sm text-slate-500">
            <a
              href="mailto:shehral.m@northeastern.edu"
              className="hover:text-violet-400 transition-colors"
            >
              Contact
            </a>
            <Link href="/login" className="hover:text-violet-400 transition-colors">
              Sign In
            </Link>
          </div>
          <p className="text-xs text-slate-600 mt-4">&copy; 2026 Ali Shehral</p>
        </div>
      </footer>
    </div>
  )
}
