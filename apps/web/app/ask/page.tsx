import { AppShell } from "@/components/layout/app-shell"
import { ChatPanel } from "@/components/ask/chat-panel"

export default function AskPage() {
  return (
    <AppShell>
      <div className="h-full">
        <ChatPanel />
      </div>
    </AppShell>
  )
}
