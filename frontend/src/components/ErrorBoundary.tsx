/* Containment.
 *
 * React unmounts the whole tree when a render or an effect throws, and an app
 * whose root has unmounted is a blank page -- no message, no navigation, no way
 * back except a manual reload. That is exactly what one bad effect cleanup did
 * here: a single wrong return value blacked out the entire site.
 *
 * A boundary around the routed content turns that into a failed panel with a
 * way out. It is deliberately NOT around the nav: navigation is what a user
 * needs most when something has broken.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Changing this resets the boundary -- navigating away should clear a fault. */
  resetKey?: string;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept: without it the stack is lost and all that survives is a blank page.
    // eslint-disable-next-line no-console
    console.error("Unhandled error in page:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <section className="panel" style={{ padding: "var(--s-6)" }}>
        <h2 style={{ fontSize: "var(--t-lg)", fontWeight: 640, marginBottom: "var(--s-2)" }}>
          This page hit an error
        </h2>
        <p className="prose">
          The rest of the site still works — use the navigation above. If it keeps happening, the
          detail is in the browser console.
        </p>
        <pre
          className="prose"
          style={{
            marginTop: "var(--s-3)",
            padding: "var(--s-3)",
            background: "var(--sunken)",
            borderRadius: "var(--r-1)",
            overflowX: "auto",
            whiteSpace: "pre-wrap",
          }}
        >
          {this.state.error.message}
        </pre>
        <button
          className="control"
          style={{ marginTop: "var(--s-4)" }}
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </section>
    );
  }
}
