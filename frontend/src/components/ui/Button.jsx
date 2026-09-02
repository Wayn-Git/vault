/** A `.btn`, extracted from the class string every button in the app already
 * built by hand. `busy` disables the button and is a separate concern from
 * `disabled` -- a caller can be mid-request without the control being
 * permanently unusable. */
export default function Button({
  variant, size, pill = false, icon, busy = false, disabled = false, className = '', children, ...rest
}) {
  const cls = [
    'btn',
    variant && `btn--${variant}`,
    size === 'small' && 'btn--small',
    pill && 'btn--pill',
    className,
  ].filter(Boolean).join(' ')

  return (
    <button type="button" className={cls} disabled={disabled || busy} {...rest}>
      {icon}
      {children}
    </button>
  )
}
