/**
 * The shape `scripts/export_board.py` writes, and the filtering over it.
 *
 * Kept apart from the components so the rules are testable and so the one
 * thing that must not drift — what `unknown` means — is stated once.
 */

export const SUPPORTED_SCHEMA = 1

export type YearsBasis = 'stated' | 'none_stated' | 'unknown'
export type DemandsBasis = 'read' | 'unknown'
export type Level = 'entry' | 'mid' | 'senior' | 'unspecified'

export interface Demands {
  clearance_held: boolean
  us_person: boolean
  no_sponsorship: boolean
}

export interface Job {
  url: string
  title: string
  company: string
  location: string
  source: string
  /** When this crawler first saw it — NOT when the employer posted it. See Q23. */
  first_seen: string
  years_required: number | null
  years_basis: YearsBasis
  excludes_entry_level: boolean
  demands: Demands
  demands_basis: DemandsBasis
  country: string | null
  state: string | null
  remote: boolean
  level: Level
}

export interface Preset {
  name: string
  description: string
  max_years_required: number
  include_unknown_years: boolean
  exclude_entry_level_exclusions: boolean
  exclude_clearance_required: boolean
}

export interface BoardData {
  schema_version: number
  generated_at: string
  default_preset: Preset
  facet_summary: Record<string, unknown>
  jobs: Job[]
}

export interface Filters {
  maxYears: number | null
  includeUnknownYears: boolean
  hideEntryExclusions: boolean
  hideClearance: boolean
  remoteOnly: boolean
  country: string | null
  includeUnclearLocation: boolean
  search: string
}

export function filtersFromPreset(preset: Preset): Filters {
  return {
    maxYears: preset.max_years_required,
    includeUnknownYears: preset.include_unknown_years,
    hideEntryExclusions: preset.exclude_entry_level_exclusions,
    hideClearance: preset.exclude_clearance_required,
    remoteOnly: false,
    country: null,
    includeUnclearLocation: true,
    search: '',
  }
}

/** Countries the data actually resolved, commonest first, with counts. */
export function countriesIn(jobs: Job[]): Array<{ name: string; count: number }> {
  const counts = new Map<string, number>()
  for (const job of jobs) {
    if (job.country) counts.set(job.country, (counts.get(job.country) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
}

/**
 * A posting is only excluded on a requirement the export actually read.
 *
 * `years_basis: 'unknown'` means the floor could not be determined, not that
 * there isn't one — so hiding those by default would silently drop postings on
 * the strength of a parser failure. They stay in unless the reader turns them
 * off, and the count is shown either way. Same reason the local board says
 * "also show 39 jobs that rule you out" rather than quietly dropping them.
 */
export function matches(job: Job, f: Filters): boolean {
  if (f.maxYears !== null) {
    if (job.years_basis === 'stated' && (job.years_required ?? 0) > f.maxYears) {
      return false
    }
    if (job.years_basis === 'unknown' && !f.includeUnknownYears) return false
  }

  if (f.hideEntryExclusions && job.excludes_entry_level) return false
  if (f.hideClearance && job.demands.clearance_held) return false
  if (f.remoteOnly && !job.remote) return false

  // Same three states as years, and the same reason it has to be a choice.
  //
  // 45 of 107 postings resolve to no country, because the text is "*HQ - San
  // Francisco, CA" — clearly US, unparseable. Dropping those under a country
  // filter hides US jobs from someone filtering for the US. Keeping them lets
  // a bare "São Paulo" through the same filter, which is how MongoDB's Brazil
  // role survived a United States filter the first time this was tried.
  //
  // Neither default is right, so it is the reader's call and the count says
  // how many hang on it.
  if (f.country) {
    if (job.country && job.country !== f.country) return false
    if (!job.country && !f.includeUnclearLocation) return false
  }

  if (f.search.trim()) {
    const needle = f.search.trim().toLowerCase()
    const hay = `${job.title} ${job.company} ${job.location}`.toLowerCase()
    if (!hay.includes(needle)) return false
  }

  return true
}

/** Newest first, by when we first saw it. */
export function byFreshness(a: Job, b: Job): number {
  return (b.first_seen || '').localeCompare(a.first_seen || '')
}

export function sinceLabel(stamp: string): string {
  const then = Date.parse(stamp)
  if (Number.isNaN(then)) return ''
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days} days ago`
  const months = Math.floor(days / 30)
  return months === 1 ? 'a month ago' : `${months} months ago`
}

/** What the years facet says, in words, including when it says nothing. */
export function yearsLabel(job: Job): string | null {
  if (job.years_basis === 'stated') {
    const n = job.years_required ?? 0
    return n === 0 ? 'no experience required' : `${n}+ years`
  }
  if (job.years_basis === 'unknown') return 'experience not stated clearly'
  return null
}
