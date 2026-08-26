import { useEffect, useMemo, useState } from 'react'
import {
  SUPPORTED_SCHEMA,
  byFreshness,
  countriesIn,
  filtersFromPreset,
  matches,
  sinceLabel,
  yearsLabel,
  type BoardData,
  type Filters,
  type Job,
} from './board'

const PAGE = 40

export default function App() {
  const [data, setData] = useState<BoardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)
  const [shown, setShown] = useState(PAGE)

  useEffect(() => {
    fetch('jobs.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: BoardData) => {
        setData(d)
        setFilters(filtersFromPreset(d.default_preset))
      })
      .catch((e) => setError(String(e)))
  }, [])

  const visible = useMemo(() => {
    if (!data || !filters) return []
    return data.jobs.filter((j) => matches(j, filters)).sort(byFreshness)
  }, [data, filters])

  const unclearCount = useMemo(
    () => (data ? data.jobs.filter((j) => !j.country).length : 0),
    [data],
  )

  const countries = useMemo(
    () => (data ? countriesIn(data.jobs) : []),
    [data],
  )

  if (error) return <Notice>Could not load the board — {error}</Notice>
  if (!data || !filters) return <Notice>Loading…</Notice>

  // A frontend rendering a shape it does not understand is worse than one that
  // refuses to. This is what `schema_version` is for.
  if (data.schema_version !== SUPPORTED_SCHEMA) {
    return (
      <Notice>
        This page reads board format {SUPPORTED_SCHEMA} and the data is format{' '}
        {data.schema_version}. Rebuild the site.
      </Notice>
    )
  }

  const set = (patch: Partial<Filters>) => {
    setFilters({ ...filters, ...patch })
    setShown(PAGE)
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto max-w-5xl px-5 py-10">
          <h1 className="text-3xl font-semibold tracking-tight">
            Early-career tech roles
          </h1>
          <p className="mt-2 max-w-2xl text-ink-soft">
            {data.default_preset.description}
          </p>
          <p className="mt-4 text-sm text-ink-faint">
            {data.jobs.length} postings · first seen by this crawler, newest first
          </p>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-5 py-7">
        <Controls
          filters={filters}
          set={set}
          count={visible.length}
          total={data.jobs.length}
          countries={countries}
          unclear={unclearCount}
        />

        {visible.length === 0 ? (
          <p className="py-16 text-center text-ink-soft">
            Nothing matches those filters.
          </p>
        ) : (
          <ul className="mt-6 space-y-2">
            {visible.slice(0, shown).map((job) => (
              <Row key={job.url} job={job} />
            ))}
          </ul>
        )}

        {shown < visible.length && (
          <button
            onClick={() => setShown(shown + PAGE)}
            className="mx-auto mt-6 block rounded-lg border border-line px-5 py-2.5
                       text-sm font-medium transition hover:border-accent hover:text-accent"
          >
            Show {Math.min(PAGE, visible.length - shown)} more
          </button>
        )}

        <footer className="mt-16 border-t border-line pt-6 text-sm text-ink-faint">
          <p>
            Every listing links to the employer's own posting. Requirements are
            read from the posting text and can be wrong — the posting is the
            authority, not this page.
          </p>
        </footer>
      </div>
    </div>
  )
}

function Controls({
  filters,
  set,
  count,
  total,
  countries,
  unclear,
}: {
  filters: Filters
  set: (p: Partial<Filters>) => void
  count: number
  total: number
  countries: Array<{ name: string; count: number }>
  unclear: number
}) {
  return (
    <div className="rounded-xl border border-line bg-card p-4">
      <input
        value={filters.search}
        onChange={(e) => set({ search: e.target.value })}
        placeholder="Search title, company or location"
        className="w-full rounded-lg border border-line bg-page px-3.5 py-2.5 text-sm
                   outline-none transition placeholder:text-ink-faint
                   focus:border-accent"
      />

      <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
        {/* Years leads, because it is the facet that actually knows things:
            60 of 107 postings state a floor, where level is unspecified on
            43% of them. */}
        <label className="flex items-center gap-2">
          <span className="text-ink-soft">Max experience</span>
          <select
            value={filters.maxYears ?? ''}
            onChange={(e) =>
              set({ maxYears: e.target.value === '' ? null : Number(e.target.value) })
            }
            className="rounded-lg border border-line bg-page px-2.5 py-1.5 outline-none
                       transition focus:border-accent"
          >
            <option value="">any</option>
            {[0, 1, 2, 3, 5, 8].map((n) => (
              <option key={n} value={n}>
                {n === 0 ? 'none required' : `${n} years`}
              </option>
            ))}
          </select>
        </label>

        <Toggle
          checked={filters.includeUnknownYears}
          onChange={(v) => set({ includeUnknownYears: v })}
          label="Include postings that don't say"
          hint="Their requirements could not be read. Hiding them would drop jobs on a parser failure."
        />
        <Toggle
          checked={filters.hideEntryExclusions}
          onChange={(v) => set({ hideEntryExclusions: v })}
          label="Hide ones that exclude new grads"
        />
        <Toggle
          checked={filters.hideClearance}
          onChange={(v) => set({ hideClearance: v })}
          label="Hide clearance-required"
        />
        <Toggle
          checked={filters.remoteOnly}
          onChange={(v) => set({ remoteOnly: v })}
          label="Remote only"
        />

        <label className="flex items-center gap-2">
          <span className="text-ink-soft">Country</span>
          <select
            value={filters.country ?? ''}
            onChange={(e) => set({ country: e.target.value || null })}
            className="rounded-lg border border-line bg-page px-2.5 py-1.5 outline-none
                       transition focus:border-accent"
          >
            <option value="">anywhere</option>
            {countries.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.count})
              </option>
            ))}
          </select>
        </label>

        {filters.country && (
          <Toggle
            checked={filters.includeUnclearLocation}
            onChange={(v) => set({ includeUnclearLocation: v })}
            label={`Include ${unclear} with an unclear location`}
            hint="Their location text named no country. Most are US roles written as '*HQ - San Francisco, CA', but a bare 'São Paulo' looks the same."
          />
        )}
      </div>

      <p className="mt-4 border-t border-line pt-3 text-sm text-ink-faint">
        Showing {count} of {total}
      </p>
    </div>
  )
}

function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  hint?: string
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2" title={hint}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-[var(--color-accent)]"
      />
      <span className="text-ink-soft">{label}</span>
    </label>
  )
}

function Row({ job }: { job: Job }) {
  const years = yearsLabel(job)

  return (
    <li className="group rounded-xl border border-line bg-card p-4 transition hover:border-accent">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="font-medium leading-snug">
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="transition group-hover:text-accent"
          >
            {job.title}
          </a>
        </h2>
        <span className="shrink-0 text-xs text-ink-faint">
          {sinceLabel(job.first_seen)}
        </span>
      </div>

      <p className="mt-1 text-sm text-ink-soft">
        {job.company}
        {job.location ? ` · ${job.location}` : ''}
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {job.remote && <Tag>Remote</Tag>}
        {job.level !== 'unspecified' && <Tag>{job.level}</Tag>}
        {/* Years is neutral, not amber. Amber means "this rules you out", and
            a floor you are already filtering within rules nobody out — if
            every tag is a warning, none of them is. */}
        {years && <Tag>{years}</Tag>}
        {job.excludes_entry_level && <Tag flag>excludes new grads</Tag>}
        {job.demands.clearance_held && <Tag flag>clearance required</Tag>}
        {job.demands.us_person && <Tag flag>US person only</Tag>}
        {job.demands.no_sponsorship && <Tag flag>no visa sponsorship</Tag>}
      </div>
    </li>
  )
}

function Tag({ children, flag = false }: { children: React.ReactNode; flag?: boolean }) {
  return (
    <span
      className={
        'rounded-md px-2 py-0.5 text-xs font-medium ' +
        (flag
          ? 'bg-flag-soft text-flag'
          : 'bg-accent-soft text-accent')
      }
    >
      {children}
    </span>
  )
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-5xl px-5 py-24 text-center text-ink-soft">
      {children}
    </div>
  )
}
