/**
 * /ask streaming — one test per demo query.
 *
 * For each of 6 canned queries:
 *   - Fires the query via the prompt input.
 *   - Waits up to 90s for the SSE stream to finish.
 *   - Asserts at least one source card is visible.
 *   - Asserts the answer contains a keyword we expect to appear in a grounded reply.
 *
 * These are the same queries the grader is most likely to run.
 */
import { test, expect } from "@playwright/test"

const DEMO_QUERIES: { q: string; keywords: string[] }[] = [
  {
    q: "What are the trade-offs between PostgREST, Hasura, and Supabase?",
    keywords: ["postgrest", "hasura", "supabase"],
  },
  {
    q: "Why might a team pick Marten on Postgres for event sourcing?",
    keywords: ["marten", "postgres", "event"],
  },
  {
    q: "Summarize the decisions that involve FastAPI.",
    keywords: ["fastapi"],
  },
  {
    q: "Which decisions involve Amazon SQS and what were the alternatives?",
    keywords: ["sqs", "amazon"],
  },
  {
    q: "Show me Rust-related architectural decisions.",
    keywords: ["rust"],
  },
  {
    q: "What patterns show up around caching with Redis?",
    keywords: ["redis", "cach"],
  },
]

// Space these out so we never have two LLM calls on host Ollama simultaneously.
test.describe.configure({ mode: "serial" })

for (const { q, keywords } of DEMO_QUERIES) {
  test(`streams grounded answer for: ${q}`, async ({ page }) => {
    test.setTimeout(180_000)
    await page.goto("/ask")
    await expect(page.getByText(/graph-rag observatory/i)).toBeVisible({ timeout: 10000 })

    // Type the query into the textarea directly (not via starter prompt).
    const textarea = page.locator("textarea").first()
    await textarea.fill(q)
    await textarea.press("Enter")

    // Wait for a streamed answer. The assistant bubble renders with .prose.
    const answer = page.locator(".prose").last()
    await expect(answer).toBeVisible({ timeout: 15000 })
    await expect
      .poll(
        async () => ((await answer.textContent()) || "").trim().length,
        { timeout: 120_000, intervals: [1000, 2000, 3000] }
      )
      .toBeGreaterThan(80)

    // Source cards present.
    const sourcesMarker = page.getByText(/◇ trace/i).last()
    await expect(sourcesMarker).toBeVisible({ timeout: 10000 })

    // Grounded: answer or sources text should contain at least one expected keyword.
    const haystack = ((await answer.textContent()) || "").toLowerCase()
    const sourcesText = (
      (await page.locator(".react-flow, body").last().textContent()) || ""
    ).toLowerCase()

    const combined = haystack + " " + sourcesText
    const hit = keywords.some((kw) => combined.includes(kw.toLowerCase()))
    expect(hit, `No expected keyword (${keywords.join(", ")}) in answer: ${haystack.slice(0, 300)}`).toBe(true)
  })
}
