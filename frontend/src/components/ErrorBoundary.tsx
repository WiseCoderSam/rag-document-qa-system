import { Component, type ErrorInfo, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Catches render/lifecycle errors in whatever subtree it wraps so one
 * broken panel shows a fallback instead of blanking the entire console.
 * React error boundaries must be class components — there's no hooks
 * equivalent for getDerivedStateFromError/componentDidCatch.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary] Caught render error:", error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <Card>
          <CardHeader>
            <CardTitle>Something went wrong</CardTitle>
            <CardDescription>
              This panel hit an unexpected error and couldn't render. Try switching tabs and back, or reload the page.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="mb-3 font-mono text-xs text-muted-foreground">{this.state.error.message}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => this.setState({ error: null })}>
              Try again
            </Button>
          </CardContent>
        </Card>
      )
    }

    return this.props.children
  }
}
