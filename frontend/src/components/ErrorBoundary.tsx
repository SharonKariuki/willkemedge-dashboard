import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /**
   * When set, the boundary shows a compact, inline-friendly panel and a
   * "Try again" affordance that clears the error in place (instead of a full
   * reload). Used to wrap routed page content so one page's render error does
   * not blank the whole shell.
   */
  inline?: boolean;
  /** Notified after the error is cleared via "Try again". */
  onReset?: () => void;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the technical detail in the console for debugging only — never
    // surface raw error text to the reader.
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  handleReload = (): void => {
    this.setState({ error: null });
    window.location.reload();
  };

  handleReset = (): void => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render(): ReactNode {
    if (!this.state.error) return this.props.children;

    if (this.props.inline) {
      return (
        <div className="flex min-h-[50vh] items-center justify-center px-6">
          <div className="max-w-md text-center">
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-ochre-600">
              Something went wrong
            </p>
            <h2 className="mt-2 font-display text-2xl font-semibold leading-tight text-ink-900">
              This view ran into a problem.
            </h2>
            <p className="mt-3 text-sm text-ink-500">
              The page could not finish loading. You can try again, and the rest of
              the dashboard remains available.
            </p>
            <div className="mt-5 flex justify-center gap-2">
              <button
                type="button"
                onClick={this.handleReset}
                className="rounded-md bg-ink-900 px-4 py-2 text-sm font-medium text-white"
              >
                Try again
              </button>
              <a
                href="/dashboard"
                className="rounded-md bg-ink-100 px-4 py-2 text-sm font-medium text-ink-900"
              >
                Dashboard
              </a>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
        <div className="max-w-md text-center">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-ochre-600">
            Something went wrong
          </p>
          <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-900">
            This page hit a snag.
          </h1>
          <p className="mt-3 text-sm text-ink-500">
            The error has been logged. Reload to try again, or head back to the dashboard.
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <button
              type="button"
              onClick={this.handleReload}
              className="rounded-md bg-ink-900 px-4 py-2 text-sm font-medium text-white"
            >
              Reload
            </button>
            <a
              href="/"
              className="rounded-md bg-ink-100 px-4 py-2 text-sm font-medium text-ink-900"
            >
              Dashboard
            </a>
          </div>
        </div>
      </div>
    );
  }
}
