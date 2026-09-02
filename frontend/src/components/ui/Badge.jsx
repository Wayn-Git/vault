/** A `.badge`, extracted from the class string repeated across every status
 * pill in the app. */
export default function Badge({ tone, className = '', children, ...rest }) {
  const cls = ['badge', tone && `badge--${tone}`, className].filter(Boolean).join(' ')
  return <span className={cls} {...rest}>{children}</span>
}
