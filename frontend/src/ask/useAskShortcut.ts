// ⌘J (Ctrl+J elsewhere) opens and closes Ask Prosper AI, wherever the focus is.

import { useEffect } from 'react'

/** Toggle the panel on ⌘J or Ctrl+J, wherever the focus is. */
export function useAskShortcut(onToggle: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'j') {
        event.preventDefault()
        onToggle()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onToggle])
}
