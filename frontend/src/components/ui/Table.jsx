/** Compound wrapper around the `.log-table` markup, structural only -- every
 * column's own styling (colour, width, truncation) stays exactly where it
 * was, passed straight through via props. */
export default function Table({ className = '', children, ...rest }) {
  return (
    <table className={['log-table', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </table>
  )
}

Table.Head = function Head({ children }) {
  return <thead><tr>{children}</tr></thead>
}

Table.Body = function Body({ children }) {
  return <tbody>{children}</tbody>
}

Table.Row = function Row({ children, ...rest }) {
  return <tr {...rest}>{children}</tr>
}

Table.Cell = function Cell({ children, ...rest }) {
  return <td {...rest}>{children}</td>
}
