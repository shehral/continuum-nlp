import { redirect } from "next/navigation"

// /decisions has no list view in the demo build — the only entry into a
// decision is via a citation card on /ask. Redirect to /ask for sanity.
export default function DecisionsIndex() {
  redirect("/ask")
}
