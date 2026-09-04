import Icon from '../Icon.jsx'
import EmptyState from './EmptyState.jsx'

/** The persistent error card every view's fetch failure should show instead
 * of quietly rendering the same copy as a genuinely empty list. */
export default function ErrorState({ message, onRetry, retryLabel = 'Retry' }) {
  return (
    <EmptyState
      icon="alert"
      message={message}
      action={
        <button type="button" className="btn btn--small" onClick={onRetry}>
          <Icon name="refresh" size={13} /> {retryLabel}
        </button>
      }
    />
  )
}
