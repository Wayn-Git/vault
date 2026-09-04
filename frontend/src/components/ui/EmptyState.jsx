import Icon from '../Icon.jsx'

/** A `.card.empty-state`, extracted from the shape Memory and Logs already
 * had right: an icon, a message, and — only when there's something to do
 * about it — a small action row below. */
export default function EmptyState({ icon = 'info', message, children, action }) {
  const body = message ?? children
  if (!action) {
    return (
      <div className="card empty-state" data-enter>
        <Icon name={icon} size={22} />
        {body}
      </div>
    )
  }
  return (
    <div className="card empty-state" data-enter>
      <Icon name={icon} size={22} />
      <div>
        <div>{body}</div>
        <div className="empty-actions">{action}</div>
      </div>
    </div>
  )
}
