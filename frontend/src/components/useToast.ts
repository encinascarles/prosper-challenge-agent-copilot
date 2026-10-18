// The state of the toast (components/Toast.tsx): what it says, and showing a
// new line, which replaces the one on screen and starts its clock again.

import { useCallback, useEffect, useRef, useState } from 'react'

const SHOWN_FOR = 6000

export function useToast() {
  const [text, setText] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const show = useCallback((next: string) => {
    if (timer.current) clearTimeout(timer.current)
    setText(next)
    timer.current = setTimeout(() => setText(null), SHOWN_FOR)
  }, [])
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])
  return { text, show }
}
