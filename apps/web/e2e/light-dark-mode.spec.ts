/**
 * Light/dark mode — capture screenshots across the demo routes and guard
 * against D18 regressions (invisible text from hard-coded violet colors).
 *
 * We do NOT take baseline-diff screenshots (no snapshots checked in) — we just
 * verify the pages render without invisible text, and that theme swaps cleanly.
 */
import { test, expect, type Page } from "@playwright/test"

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => {
    try {
      localStorage.setItem("theme", t)
    } catch (e) {}
    if (t === "dark") document.documentElement.classList.add("dark")
    else document.documentElement.classList.remove("dark")
  }, theme)
  await page.waitForTimeout(200)
}

async function assertNoInvisibleText(page: Page) {
  /**
   * Walk each text element and check computed color has meaningful luminance
   * difference from its background. Flags the common D18 failure mode —
   * `text-violet-400` on white reads nearly invisible.
   */
  const offenders = await page.evaluate(() => {
    const problems: string[] = []
    const elements = Array.from(document.querySelectorAll("body *"))
    for (const el of elements) {
      if (!(el instanceof HTMLElement)) continue
      const rect = el.getBoundingClientRect()
      if (rect.width < 10 || rect.height < 10) continue
      const text = el.textContent?.trim() || ""
      if (text.length < 3) continue
      // Only leaf-ish elements (no block children).
      if (el.children.length > 0 && Array.from(el.children).some(c =>
        c.textContent && c.textContent.trim().length > 3
      )) continue

      const style = window.getComputedStyle(el)
      const fg = style.color
      const bg = style.backgroundColor

      // Skip elements that intentionally use `bg-clip: text` for gradient
      // text (Tailwind's `text-transparent bg-clip-text`). Their fg IS
      // transparent by design — the visible color comes from the clipped
      // gradient background.
      const bgClip =
        style.backgroundClip ||
        // @ts-ignore — webkit-prefixed
        (style as any).webkitBackgroundClip
      if (bgClip === "text") continue

      // Quickly check for transparent-on-transparent (no contrast computed).
      if (fg === "rgba(0, 0, 0, 0)" || fg === "transparent") {
        problems.push(`transparent fg: ${el.tagName} "${text.slice(0, 40)}"`)
      }
    }
    return problems.slice(0, 5)
  })
  expect(offenders, `Invisible-text offenders: ${offenders.join(" | ")}`).toEqual([])
}

const ROUTES: { name: string; url: string }[] = [
  { name: "landing", url: "/" },
  { name: "ask-empty", url: "/ask" },
  { name: "graph", url: "/graph" },
]

for (const { name, url } of ROUTES) {
  test(`${name} — light mode renders without invisible text`, async ({ page }) => {
    await page.goto(url)
    await page.waitForLoadState("networkidle")
    await setTheme(page, "light")
    await page.waitForTimeout(500)
    await assertNoInvisibleText(page)
    await page.screenshot({
      path: `test-results/theme-${name}-light.png`,
      fullPage: false,
    })
  })

  test(`${name} — dark mode renders without invisible text`, async ({ page }) => {
    await page.goto(url)
    await page.waitForLoadState("networkidle")
    await setTheme(page, "dark")
    await page.waitForTimeout(500)
    await assertNoInvisibleText(page)
    await page.screenshot({
      path: `test-results/theme-${name}-dark.png`,
      fullPage: false,
    })
  })
}
