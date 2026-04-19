/**
 * MessageBubble — user = italic pull quote, assistant = prose + kicker + streaming cursor.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "../../utils/test-utils"
import { MessageBubble } from "@/components/ask/message-bubble"
import type { AskMessage } from "@/lib/api"

describe("MessageBubble", () => {
  it("renders user messages as a blockquote with italic serif styling", () => {
    const msg: AskMessage = {
      id: "m1",
      role: "user",
      content: "What decisions involve FastAPI?",
    }
    const { container } = render(<MessageBubble message={msg} index={1} />)

    const bq = container.querySelector("blockquote")
    expect(bq).not.toBeNull()
    expect(bq?.textContent).toContain("What decisions involve FastAPI?")
    // Expect italic serif inline style (per message-bubble.tsx).
    expect(bq?.getAttribute("style") || "").toMatch(/italic/)

    // User kicker matches `you · qNN` pattern.
    expect(screen.getByText(/you · q01/i)).toBeInTheDocument()
  })

  it("renders assistant messages as prose with kicker", () => {
    const msg: AskMessage = {
      id: "m2",
      role: "assistant",
      content: "Postgres is the canonical choice because ...",
    }
    const { container } = render(<MessageBubble message={msg} index={1} />)

    expect(screen.getByText(/graph-rag · a01/i)).toBeInTheDocument()
    // Prose container is present.
    const prose = container.querySelector(".prose")
    expect(prose).not.toBeNull()
    expect(prose?.textContent).toContain("Postgres is the canonical choice")
  })

  it("shows the streaming cursor when assistant content is empty", () => {
    const msg: AskMessage = {
      id: "m3",
      role: "assistant",
      content: "",
    }
    const { container } = render(<MessageBubble message={msg} index={1} />)

    // The streaming cursor is a `<span class="animate-pulse">` at the end.
    const cursor = container.querySelector(".animate-pulse")
    expect(cursor).not.toBeNull()
  })

  it("does NOT show the streaming cursor when assistant content is non-empty", () => {
    const msg: AskMessage = {
      id: "m4",
      role: "assistant",
      content: "An answer",
    }
    const { container } = render(<MessageBubble message={msg} index={1} />)
    expect(container.querySelector(".animate-pulse")).toBeNull()
  })
})
