import {
  ArrowDown,
  ArrowsClockwise,
  Books,
  CaretRight,
  ChatTeardropText,
  Check,
  Circuitry,
  ClockCountdown,
  Copy,
  FolderOpen,
  GlobeHemisphereWest,
  Info,
  Key,
  Keyboard,
  Link,
  ListChecks,
  MagnifyingGlass,
  NotePencil,
  Paperclip,
  Plus,
  PlugsConnected,
  PaperPlaneRight,
  SidebarSimple,
  SlidersHorizontal,
  SquaresFour,
  Sparkle,
  Stop,
  Terminal,
  Trash,
  X,
} from '@phosphor-icons/react'

/* One icon set, one stroke weight, one grid.

   The marks used to be hand-drawn paths, and it showed: strokes disagreed by a
   third of a pixel, optical sizes drifted, and every new one was a small act of
   invention. Phosphor is a real family drawn on a 24px grid, so a row of icons
   lines up because the typeface-equivalent says so, not because each path was
   nudged until it looked close.

   The `<Icon name="…">` API is deliberately unchanged: the names describe what
   the thing does in PSOK -- `plug`, `spark`, `logs` -- not what the drawing is
   called upstream, so swapping the family again would touch this file only. */

const MARKS = {
  book: Books,
  chat: ChatTeardropText,
  check: Check,
  chevron: CaretRight,
  clock: ClockCountdown,
  copy: Copy,
  cpu: Circuitry,
  down: ArrowDown,
  edit: NotePencil,
  info: Info,
  key: Key,
  keyboard: Keyboard,
  link: Link,
  logs: ListChecks,
  paperclip: Paperclip,
  plug: PlugsConnected,
  plus: Plus,
  refresh: ArrowsClockwise,
  search: MagnifyingGlass,
  send: PaperPlaneRight,
  sidebar: SidebarSimple,
  sliders: SlidersHorizontal,
  spark: Sparkle,
  grid: SquaresFour,
  folder: FolderOpen,
  globe: GlobeHemisphereWest,
  stop: Stop,
  term: Terminal,
  trash: Trash,
  x: X,
}

// Phosphor's own default weight is too light against a dark panel; `regular`
// at 1.5px reads at 13-16px, which is where nearly every icon here sits.
export default function Icon({ name, size = 18, weight = 'regular', ...rest }) {
  const Mark = MARKS[name]
  if (!Mark) return null
  return <Mark size={size} weight={weight} aria-hidden="true" {...rest} />
}
