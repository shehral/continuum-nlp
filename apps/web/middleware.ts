import { auth } from "./auth"
import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

// Demo-mode public routes. The full graph + chat are read-only and
// intentionally open for the CS6120 demo grader flow.
const publicPaths = [
  "/login",
  "/register",
  "/ask",
  "/graph",
  "/decisions",
]

export default async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Landing page is public
  if (pathname === "/") {
    return NextResponse.next()
  }

  // Other public paths
  if (publicPaths.some((path) => pathname.startsWith(path))) {
    return NextResponse.next()
  }

  // Everything else requires auth
  return (auth as any)(request)
}

export const config = {
  matcher: [
    "/((?!api/auth|_next/static|_next/image|favicon.ico|media).*)",
  ],
}
