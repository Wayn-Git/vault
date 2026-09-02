/** A `.field` label + control + optional note, extracted from the shape
 * repeated across every form in the app. */
export default function Field({ label, id, hint, children }) {
  return (
    <div className="field">
      {label && <label htmlFor={id}>{label}</label>}
      {children}
      {hint && <span className="field-note">{hint}</span>}
    </div>
  )
}
