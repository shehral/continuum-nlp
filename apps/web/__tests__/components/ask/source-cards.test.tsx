/**
 * SourceCards — decisions vs entities, seed stars, deep-linking.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "../../utils/test-utils"
import { SourceCards } from "@/components/ask/source-cards"
import type { AskSubgraph } from "@/lib/api"

function buildSources(overrides: Partial<AskSubgraph> = {}): AskSubgraph {
  return {
    nodes: [
      {
        id: "dec-abc12345-6789-0000-ffff-000000000000",
        type: "decision",
        is_seed: true,
        data: {
          decision: "Use Postgres for event sourcing",
          trigger: "Need durable event log",
          confidence: 0.87,
        },
      },
      {
        id: "ent-def67890-1111-2222-3333-444444444444",
        type: "entity",
        is_seed: false,
        data: {
          name: "PostgreSQL",
          entity_type: "technology",
        },
      },
    ],
    edges: [],
    seed_ids: ["dec-abc12345-6789-0000-ffff-000000000000"],
    ...overrides,
  }
}

describe("SourceCards", () => {
  it("renders decision nodes wrapped in /decisions/[id] links", () => {
    const sources = buildSources()
    render(<SourceCards sources={sources} />)

    // Decision card is wrapped in an anchor to /decisions/[id].
    const decisionLink = screen.getByRole("link", {
      name: /open decision/i,
    })
    expect(decisionLink).toBeInTheDocument()
    expect(decisionLink.getAttribute("href")).toBe(
      "/decisions/dec-abc12345-6789-0000-ffff-000000000000"
    )
    expect(decisionLink.textContent).toContain("Use Postgres for event sourcing")
  })

  it("does NOT wrap entity nodes in a link", () => {
    const sources: AskSubgraph = {
      nodes: [
        {
          id: "ent-xyz11111-2222-3333-4444-555555555555",
          type: "entity",
          is_seed: false,
          data: { name: "Redis", entity_type: "technology" },
        },
      ],
      edges: [],
      seed_ids: [],
    }
    render(<SourceCards sources={sources} />)

    // No anchor to /decisions/ from an entity card.
    expect(screen.queryAllByRole("link")).toHaveLength(0)
    expect(screen.getByText("Redis")).toBeInTheDocument()
  })

  it("renders ★ seed marker only for seed nodes", () => {
    const sources = buildSources()
    render(<SourceCards sources={sources} />)

    // is_seed=true node shows the ★ seed marker.
    const seedMarkers = screen.getAllByText(/★ seed/i)
    // Exactly one seed marker for one seed node.
    expect(seedMarkers).toHaveLength(1)
  })

  it("shows trace kicker with node count summary", () => {
    const sources = buildSources()
    render(<SourceCards sources={sources} />)
    expect(screen.getByText(/◇ trace/i)).toBeInTheDocument()
    // "2/2 nodes · click a decision..."
    expect(screen.getByText(/2\/2 nodes/i)).toBeInTheDocument()
  })
})
