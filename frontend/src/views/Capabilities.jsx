import { useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import SkillsTab from './capabilities/SkillsTab.jsx'
import ConnectorsTab from './capabilities/ConnectorsTab.jsx'

/* Skills and connectors, one page, two tabs.

   They were two rail entries and a third overlay that browsed both, which meant
   a connector had a page for managing it and a different card for adding it,
   and a skill could be listed twice with different controls in each place. They
   are the same kind of thing — something the agent is given — so they are one
   page, and adding is done where managing is done. */

const TABS = [
  { id: 'skills', label: 'Skills' },
  { id: 'connectors', label: 'Connectors' },
]

export default function Capabilities() {
  const rootRef = useRef(null)
  const { capabilitiesTab, setCapabilitiesTab } = useApp()
  const [query, setQuery] = useState('')
  // The primary action lives in the title row, so the page owns it and hands
  // each tab the switch it turns.
  const [newOpen, setNewOpen] = useState(false)
  useViewEntrance(rootRef)

  // Neither the search nor a half-open form means anything on the other side.
  useEffect(() => { setQuery(''); setNewOpen(false) }, [capabilitiesTab])

  const skills = capabilitiesTab === 'skills'

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="cap-head" data-enter>
          <h1>Skills and connectors</h1>
          <button
            type="button"
            className={`btn btn--pill${newOpen ? ' btn--ghost' : ' btn--primary'}`}
            onClick={() => setNewOpen((o) => !o)}
            aria-expanded={newOpen}
          >
            <Icon name={newOpen ? 'x' : 'plus'} size={14} />
            {skills ? 'New skill' : 'New connector'}
          </button>
        </header>

        <div className="cap-bar" data-enter>
          <div className="cap-tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={capabilitiesTab === t.id}
                className={`cap-tab${capabilitiesTab === t.id ? ' active' : ''}`}
                onClick={() => setCapabilitiesTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="cap-search">
            <Icon name="search" size={14} />
            <input
              value={query}
              placeholder="Search…"
              aria-label={skills ? 'Search skills' : 'Search connectors'}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape' && query) { e.stopPropagation(); setQuery('') } }}
            />
            {query && (
              <button type="button" className="icon-btn" onClick={() => setQuery('')} aria-label="Clear">
                <Icon name="x" size={13} />
              </button>
            )}
          </div>
        </div>

        {skills
          ? <SkillsTab query={query} newOpen={newOpen} setNewOpen={setNewOpen} />
          : <ConnectorsTab query={query} newOpen={newOpen} setNewOpen={setNewOpen} />}
      </div>
    </div>
  )
}
