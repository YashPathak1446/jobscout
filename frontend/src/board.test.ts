import { describe, expect, it } from 'vitest'
import {
  countriesIn,
  filtersFromPreset,
  matches,
  yearsLabel,
  type Filters,
  type Job,
  type Preset,
} from './board'

/**
 * The three-state rules, which are the part of this board that can be wrong
 * without looking wrong.
 *
 * A facet reads `unknown` when the export could not determine it — not when
 * the posting has no requirement. Under the old gates that collapse was
 * harmless; under a filter it silently drops postings on a parser failure, or
 * silently keeps ones that should have gone. Both happened during development
 * and both are pinned here.
 */

const PRESET: Preset = {
  name: 'Early career',
  description: '',
  max_years_required: 3,
  include_unknown_years: true,
  exclude_entry_level_exclusions: true,
  exclude_clearance_required: true,
}

function job(over: Partial<Job> = {}): Job {
  return {
    url: 'https://example.com/1',
    title: 'Software Engineer',
    company: 'Example',
    location: 'San Francisco, CA',
    source: 'ats_greenhouse',
    first_seen: '2026-08-26T00:00:00Z',
    years_required: null,
    years_basis: 'none_stated',
    excludes_entry_level: false,
    demands: { clearance_held: false, us_person: false, no_sponsorship: false },
    demands_basis: 'read',
    country: 'United States',
    state: 'California',
    remote: false,
    level: 'unspecified',
    ...over,
  }
}

const base: Filters = filtersFromPreset(PRESET)

describe('the preset is the data, not the code', () => {
  it('takes its values from the export', () => {
    expect(base.maxYears).toBe(3)
    expect(base.includeUnknownYears).toBe(true)
  })

  it('starts with no country chosen', () => {
    expect(base.country).toBeNull()
  })
})

describe('years', () => {
  it('keeps a floor within the limit', () => {
    expect(matches(job({ years_required: 2, years_basis: 'stated' }), base)).toBe(true)
  })

  it('drops a floor above it', () => {
    expect(matches(job({ years_required: 8, years_basis: 'stated' }), base)).toBe(false)
  })

  it('keeps a posting that states none', () => {
    expect(matches(job({ years_basis: 'none_stated' }), base)).toBe(true)
  })

  it('keeps an unreadable one by default, because hiding it would be a guess', () => {
    expect(matches(job({ years_basis: 'unknown' }), base)).toBe(true)
  })

  it('drops the unreadable one only when asked to', () => {
    const strict = { ...base, includeUnknownYears: false }
    expect(matches(job({ years_basis: 'unknown' }), strict)).toBe(false)
    expect(matches(job({ years_basis: 'none_stated' }), strict)).toBe(true)
  })

  it('applies no years rule at all when the limit is off', () => {
    const any = { ...base, maxYears: null, includeUnknownYears: false }
    expect(matches(job({ years_required: 12, years_basis: 'stated' }), any)).toBe(true)
    expect(matches(job({ years_basis: 'unknown' }), any)).toBe(true)
  })
})

describe('country, and the location that never parsed', () => {
  it('drops another country', () => {
    const usa = { ...base, country: 'United States' }
    expect(matches(job({ country: 'Brazil' }), usa)).toBe(false)
  })

  it('keeps an unresolved location by default', () => {
    // "*HQ - San Francisco, CA" resolves to no country and is plainly US.
    const usa = { ...base, country: 'United States' }
    expect(matches(job({ country: null }), usa)).toBe(true)
  })

  it('drops it when the reader tightens', () => {
    // The cost of the default: a bare "São Paulo" also resolves to no country,
    // which is how a Brazil role survived a United States filter once.
    const strict = { ...base, country: 'United States', includeUnclearLocation: false }
    expect(matches(job({ country: null }), strict)).toBe(false)
  })

  it('ignores an unresolved location when no country is chosen', () => {
    expect(matches(job({ country: null }), { ...base, includeUnclearLocation: false }))
      .toBe(true)
  })
})

describe('the hard exclusions', () => {
  it('hides postings that exclude new grads', () => {
    expect(matches(job({ excludes_entry_level: true }), base)).toBe(false)
  })

  it('hides clearance-required postings', () => {
    expect(matches(job({ demands: { clearance_held: true, us_person: false, no_sponsorship: false } }), base))
      .toBe(false)
  })

  it('does not hide a role that merely wants a US person', () => {
    // R56's held-versus-obtainable distinction: "or eligibility to obtain one"
    // rules out far fewer people than "must already hold".
    expect(matches(job({ demands: { clearance_held: false, us_person: true, no_sponsorship: false } }), base))
      .toBe(true)
  })
})

describe('search', () => {
  it('matches title, company and location', () => {
    for (const term of ['engineer', 'example', 'francisco']) {
      expect(matches(job(), { ...base, search: term })).toBe(true)
    }
  })

  it('is case and whitespace insensitive', () => {
    expect(matches(job(), { ...base, search: '  ENGINEER ' })).toBe(true)
  })

  it('drops a miss', () => {
    expect(matches(job(), { ...base, search: 'plumber' })).toBe(false)
  })
})

describe('labels', () => {
  it('says what it knows', () => {
    expect(yearsLabel(job({ years_required: 5, years_basis: 'stated' }))).toBe('5+ years')
  })

  it('says when it does not know, rather than nothing', () => {
    expect(yearsLabel(job({ years_basis: 'unknown' }))).toMatch(/not stated/)
  })

  it('says nothing when the posting genuinely asks for none', () => {
    expect(yearsLabel(job({ years_basis: 'none_stated' }))).toBeNull()
  })
})

describe('countriesIn', () => {
  it('counts and orders by frequency', () => {
    const list = countriesIn([
      job({ country: 'Canada' }),
      job({ country: 'United States' }),
      job({ country: 'United States' }),
      job({ country: null }),
    ])
    expect(list).toEqual([
      { name: 'United States', count: 2 },
      { name: 'Canada', count: 1 },
    ])
  })

  it('omits the unresolved ones rather than inventing a bucket', () => {
    expect(countriesIn([job({ country: null })])).toEqual([])
  })
})
