// Prosper's logo mark.
import { cn } from '@/lib/utils'

export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="57 63 171 259" className={cn('h-[18px] w-auto shrink-0', className)} aria-hidden>
      <polygon points="57,113 132,159 132,277 57,322" fill="var(--foreground)" />
      <polygon points="153,104 228,63 228,173 153,216" fill="#ee5428" />
    </svg>
  )
}
