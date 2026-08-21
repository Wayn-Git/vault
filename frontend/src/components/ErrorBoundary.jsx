import { Component } from 'react'

/* A render failure in one view must not take the window with it.

   Without this, a malformed message or a null field somewhere deep in the
   transcript unmounts the whole tree and leaves a blank page with the reason
   only in the console -- the one place a user will not look. */

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('[psok] render failed', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="crash">
        <h2>That view stopped rendering.</h2>
        <p className="crash-detail">{String(this.state.error?.message || this.state.error)}</p>
        <div className="crash-actions">
          <button type="button" className="btn btn--primary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
        <p className="crash-note">
          Your conversations are on the server, not in this page — nothing was lost.
        </p>
      </div>
    )
  }
}
