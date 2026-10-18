// A short line at the foot of the screen that says what just happened
// somewhere you were not looking: a pull request opened for your edit, a merge
// that went live. It goes away on its own; nothing in it needs an answer.

import { GitPullRequestArrow } from 'lucide-react'

export function Toast({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <div
      role="status"
      className="pointer-events-none fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-full bg-foreground px-4 py-2 text-[12.5px] whitespace-nowrap text-background shadow-lg animate-in fade-in slide-in-from-bottom-2"
    >
      <GitPullRequestArrow className="size-3.5" /> {text}
    </div>
  )
}
