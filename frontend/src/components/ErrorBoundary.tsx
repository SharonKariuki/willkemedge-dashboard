import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
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
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  handleReload = (): void => {
    this.setState({ error: null });
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
        <div className="max-w-md text-center">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-ochre-600">
            Something broke
          </p>
          <h1 className="mt-2 font-display text-3xl font-semibold leading-tight text-ink-900">
            This page hit a snag.
          </h1>
          <p className="mt-3 text-sm text-ink-500">
            We&apos;ve logged the error. Reload to try again, or head back to the dashboard.
          </p>
          <pre className="mt-4 max-h-32 overflow-auto rounded-md bg-ink-50 p-3 text-left text-[11px] text-ink-700">
            {this.state.error.message}
          </pre>
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
