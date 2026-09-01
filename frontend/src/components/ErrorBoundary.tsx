import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** A blank white page is the worst possible failure mode for a demo — this turns any
 * uncaught render error into a visible, readable message instead. React requires a class
 * component for error boundaries (no hook equivalent exists). */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("RecoveryOS UI crashed:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="m-6 max-w-2xl rounded-lg border border-rose-800 bg-rose-950 p-6 text-rose-200">
          <h2 className="text-lg font-semibold">Something went wrong rendering this page</h2>
          <p className="mt-2 text-sm">{this.state.error.message}</p>
          <p className="mt-2 text-xs text-rose-400">
            Check the browser console for the full stack trace.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
