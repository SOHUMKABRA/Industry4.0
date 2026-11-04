import { Component, ReactNode } from "react";

/** Contains a crashing page so the shell (navigation, other pages) keeps working. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel" style={{ margin: 24 }}>
        <div className="empty">
          <h3>This page hit an unexpected error</h3>
          <p className="muted small mono">{this.state.error.message}</p>
          <button className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      </div>
    );
  }
}
