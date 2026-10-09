// What is shown when the editor throws while rendering.
//
// Without it React takes the whole page down and leaves it blank, with no way
// to tell a crash from a page still loading. This keeps the top of the app
// honest: it says the editor stopped, shows the error's own message, and offers
// the one thing that helps, which is loading the page again.
//
// A class, because catching a render error is the one thing React still only
// gives to class components.

import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // For whoever opens the console: the component it happened in.
    console.error(error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div role="alert" className="m-auto flex max-w-md flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm font-medium">The editor ran into a problem and stopped.</p>
        <p className="text-[13px] text-muted-foreground">
          Changes that were not saved are lost. Reloading opens the agent as it was last saved.
        </p>
        <p className="max-w-full text-xs break-words text-muted-foreground/80">{error.message}</p>
        <Button size="sm" onClick={() => window.location.reload()}>
          Reload
        </Button>
      </div>
    )
  }
}
