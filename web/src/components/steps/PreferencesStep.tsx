import { useEffect, useState } from 'react'
import { ChevronDown, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

const ROLE_OPTIONS = [
  'Software Engineer', 'Backend Engineer', 'Frontend Engineer',
  'Full Stack Engineer', 'Mobile Engineer', 'iOS Engineer',
  'Android Engineer', 'ML Engineer', 'AI Engineer', 'Data Engineer',
  'Data Scientist', 'Data Analyst', 'DevOps Engineer',
  'Site Reliability Engineer', 'Platform Engineer', 'Security Engineer',
  'QA Engineer', 'Solutions Engineer', 'Engineering Manager',
]

const EXCLUDE_ALWAYS = ['PhD required', 'security clearance required']

/** `profile_schema.YEARS_EXPERIENCE_MAX`, which the server enforces on save
 *  and on `/api/levels`. A test holds the two equal (Q44). */
const YEARS_MAX = 60

/** What `/api/levels` said for one value of years. `derived: null` is a
 *  lookup that failed — the server refused that number. */
type Lookup = { years: number | null; derived: string[] | null }

type Preferences = {
  target_roles: string[]
  seniority: string[]
  years_experience: number | null
  exclude_keywords: string[]
  cities: string[]
  remote_ok: boolean
  countries: string[]
  states_priority: string[]
  states_acceptable: string[]
  willing_to_relocate: boolean
}

/** Levels above where someone sits, plus year floors beyond their reach. */
function excludeOptions(years: number | null): string[] {
  if (years === null) return EXCLUDE_ALWAYS
  const above =
    years <= 1 ? ['senior', 'staff', 'principal', 'lead']
    : years <= 4 ? ['staff', 'principal', 'lead']
    : years <= 7 ? ['principal', 'lead']
    : []
  const floors = [3, 5, 7, 10].filter((n) => n > years + 3).map((n) => `${n}+ years`)
  return [...above, ...floors, ...EXCLUDE_ALWAYS]
}


/**
 * Step three: what you are looking for, and at which levels.
 *
 * The screen asks for **years**, not for level words — R68's finding was that
 * the second pushes a translation onto the user that the code does in reverse
 * anyway. The override exists for people who disagree, and stays empty
 * otherwise so the levels follow the number.
 *
 * That emptiness is load-bearing and it is what the Streamlit version got
 * wrong: its Save button was gated on the override box, so every profile that
 * had not overridden — every new one — found the button dead with nothing
 * saying why. Gate on what is *in force*.
 */
export function PreferencesStep({
  profile,
  onBack,
  onContinue,
}: {
  profile: string
  onBack: () => void
  onContinue: () => void
}) {
  const [prefs, setPrefs] = useState<Preferences | null>(null)
  const [levels, setLevels] = useState<string[]>([])
  // Keyed by the years it answers for, so a lookup for any other value —
  // the one before, or one still in flight — is never shown as this one's.
  const [lookup, setLookup] = useState<Lookup | null>(null)
  const [showOverride, setShowOverride] = useState(false)
  const [showElsewhere, setShowElsewhere] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .profile(profile)
      .then((p) => setPrefs(p.preferences as Preferences))
      .catch((e: Error) => setError(e.message))
  }, [profile])

  const years = prefs?.years_experience ?? null

  useEffect(() => {
    // Typing 12 asks for 1 and then 12. Without this, the answer for 1 can
    // land second and stand under a box that says 12.
    let current = true
    api
      .levels(years)
      .then((l) => {
        if (!current) return
        setLevels(l.all)
        setLookup({ years, derived: l.derived })
      })
      // A refused number (2.5, -1, 61) clears the levels rather than keeping
      // the last answer's on screen beside a number they were not derived
      // from (Q44). `levels` is not years-dependent and stays.
      .catch(() => {
        if (current) setLookup({ years, derived: null })
      })
    return () => {
      current = false
    }
  }, [years])

  // Three states, not two: known, refused, and not back yet. The last used
  // to render as "any level" for the beat before the first answer arrived.
  const answered = lookup !== null && lookup.years === years
  const derived = answered ? lookup.derived : null
  const refused = answered && lookup.derived === null

  if (!prefs) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-10 w-full max-w-md" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  const override = prefs.seniority.filter((s) => levels.includes(s))
  // What is actually in force, not what would be derived — a caption saying
  // "looking at New Grad" while an override says otherwise is a caption that
  // lies.
  const inForce = override.length ? override : (derived ?? [])

  function toggle(list: string[], value: string): string[] {
    return list.includes(value)
      ? list.filter((v) => v !== value)
      : [...list, value]
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await api.updateProfile(profile, {
        job_preferences: {
          target_roles: prefs!.target_roles,
          years_experience: prefs!.years_experience,
          // Written as given: empty when nobody overrode, so the levels keep
          // deriving. Nothing writes a derived value back here, which is what
          // lets an override outlive edits on any other screen (R68).
          seniority: prefs!.seniority,
          exclude_keywords: prefs!.exclude_keywords,
          locations: {
            cities: prefs!.cities,
            remote_ok: prefs!.remote_ok,
            countries: prefs!.countries,
            states_priority: prefs!.states_priority,
            states_acceptable: prefs!.states_acceptable,
            willing_to_relocate: prefs!.willing_to_relocate,
          },
        },
      })
      onContinue()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const roleOptions = [
    ...ROLE_OPTIONS,
    ...prefs.target_roles.filter((r) => !ROLE_OPTIONS.includes(r)),
  ]
  const excludes = excludeOptions(years)
  const excludeChoices = [
    ...excludes,
    ...prefs.exclude_keywords.filter((e) => !excludes.includes(e)),
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">
          What are you looking for?
        </h2>
      </div>

      <div className="space-y-2">
        <Label>Target roles</Label>
        <div className="flex flex-wrap gap-1.5">
          {roleOptions.map((role) => (
            <Chip
              key={role}
              on={prefs.target_roles.includes(role)}
              onClick={() =>
                setPrefs({ ...prefs, target_roles: toggle(prefs.target_roles, role) })
              }
            >
              {role}
            </Chip>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="years">Years of professional experience</Label>
        {/* Empty, not zero. `years_experience: null` means the question has
            not been answered, and zero is the claim "new graduate" — the
            Streamlit field did `int(current or 0)` and turned one into the
            other. */}
        <Input
          id="years"
          type="number"
          min={0}
          max={YEARS_MAX}
          step={1}
          value={prefs.years_experience ?? ''}
          placeholder="e.g. 6"
          onChange={(e) =>
            setPrefs({
              ...prefs,
              years_experience: e.target.value === '' ? null : Number(e.target.value),
            })
          }
          className="max-w-32"
        />
        <p className="text-sm text-muted-foreground">
          Internships and coursework do not count. This decides which postings
          are worth showing you and which rule you out.
        </p>
      </div>

      <div className="rounded-lg border p-4 text-sm">
        {years === null ? (
          <p className="text-muted-foreground">
            Answer the years above and the levels follow from it.
          </p>
        ) : refused ? (
          <p className="text-destructive">
            {`Years has to be a whole number from 0 to ${YEARS_MAX}, so no levels follow from it yet.`}
          </p>
        ) : !override.length && derived === null ? (
          <p className="text-muted-foreground">Working out levels…</p>
        ) : (
          <p>
            Looking at{' '}
            <strong>
              {inForce.map((l) => l.replace(/\b\w/g, (c) => c.toUpperCase())).join(', ') ||
                'any level'}
            </strong>{' '}
            roles
            {override.length > 0 && (
              <span className="text-muted-foreground">
                {' '}
                · your choice, not derived from the number above
              </span>
            )}
          </p>
        )}

        <button
          type="button"
          onClick={() => setShowOverride((v) => !v)}
          className="mt-2 inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        >
          <ChevronDown
            className={cn('size-4 transition-transform', showOverride && 'rotate-180')}
          />
          Choose the levels yourself
        </button>

        {showOverride && (
          <div className="mt-3 space-y-2">
            <p className="text-muted-foreground">
              Only if you disagree. Leave this empty and the levels follow the
              number above; set it and your choice is kept, whatever else you
              change later.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {levels.map((level) => (
                <Chip
                  key={level}
                  on={prefs.seniority.includes(level)}
                  onClick={() =>
                    setPrefs({ ...prefs, seniority: toggle(prefs.seniority, level) })
                  }
                >
                  {level}
                </Chip>
              ))}
            </div>
          </div>
        )}
      </div>

      <Field
        id="cities"
        label="Cities (optional)"
        value={prefs.cities}
        onChange={(v) => setPrefs({ ...prefs, cities: v })}
        placeholder="Type a city, then press Enter"
      />

      <div className="flex items-center gap-2">
        <Checkbox
          id="remote"
          checked={prefs.remote_ok}
          onCheckedChange={(v) => setPrefs({ ...prefs, remote_ok: v === true })}
        />
        <Label htmlFor="remote">Remote roles are fine</Label>
      </div>

      <div className="rounded-lg border p-4">
        <button
          type="button"
          onClick={() => setShowElsewhere((v) => !v)}
          className="inline-flex items-center gap-1 text-sm font-medium"
        >
          <ChevronDown
            className={cn('size-4 transition-transform', showElsewhere && 'rotate-180')}
          />
          Where else would you work?
        </button>
        {showElsewhere && (
          <div className="mt-3 space-y-3">
            <Field
              id="countries"
              label="Countries"
              hint="Postings outside these score lower rather than being cut."
              value={prefs.countries}
              onChange={(v) => setPrefs({ ...prefs, countries: v })}
              placeholder="Type a country, then press Enter"
            />
            <Field
              id="states-priority"
              label="States you would most like"
              hint="Discovery searches the first of these by name."
              value={prefs.states_priority}
              onChange={(v) => setPrefs({ ...prefs, states_priority: v })}
              placeholder="Type a state, then press Enter"
            />
            <Field
              id="states-acceptable"
              label="States you would accept"
              value={prefs.states_acceptable}
              onChange={(v) => setPrefs({ ...prefs, states_acceptable: v })}
              placeholder="Type a state, then press Enter"
            />
            <div className="flex items-center gap-2">
              <Checkbox
                id="relocate"
                checked={prefs.willing_to_relocate}
                onCheckedChange={(v) =>
                  setPrefs({ ...prefs, willing_to_relocate: v === true })
                }
              />
              <Label htmlFor="relocate">Willing to relocate</Label>
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Label>Skip postings mentioning</Label>
        <p className="text-sm text-muted-foreground">
          A hard filter on wording, separate from the levels above. Excluding
          “senior” while asking for senior roles will find you nothing.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {excludeChoices.map((word) => (
            <Chip
              key={word}
              on={prefs.exclude_keywords.includes(word)}
              onClick={() =>
                setPrefs({
                  ...prefs,
                  exclude_keywords: toggle(prefs.exclude_keywords, word),
                })
              }
            >
              {word}
            </Chip>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-destructive">Could not save: {error}</p>}

      <div className="flex gap-2 border-t pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        {/* Gated on target roles alone. Never on the override box — that is
            empty for everyone who has not overridden, and gating on it left
            the Streamlit button dead for every new profile (R72). And no
            longer on the levels in force either: those are empty whenever the
            years are unanswered and nothing is overridden, which is a
            legitimate state. `/api/levels` returns `derived: []` for an
            unanswered profile on purpose, the caption reads "any level", and
            `_tolerated_years` treats it as the widest tolerance rather than
            as zero. Gating on it rebuilt the same silent wall one field
            over. */}
        <Button
          onClick={save}
          disabled={!prefs.target_roles.length || saving}
        >
          {saving ? 'Saving…' : 'Save and continue'}
        </Button>
      </div>
    </div>
  )
}

function Chip({
  on,
  onClick,
  children,
}: {
  on: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        'rounded-full border px-3 py-1 text-sm transition-colors',
        on
          ? 'border-transparent bg-primary text-primary-foreground'
          : 'hover:bg-accent',
      )}
    >
      {children}
    </button>
  )
}

/**
 * A list of places, one entry per chip (R127).
 *
 * This was one text box showing the list joined with ", ", re-split on
 * commas and trimmed on every keystroke. So a space was trimmed away before
 * the next letter arrived, and a comma was a separator the moment it was
 * typed: "San Francisco", "New York" and "North Carolina" could not be
 * entered. Entries now come from a draft typed freely, spaces and commas
 * included, and **Enter adds it** as one chip; × removes one. The draft is
 * also kept when the box loses focus, so pressing Save straight after typing
 * does not drop what was typed. Saved lists are shown as they are.
 */
function Field({
  id,
  label,
  hint,
  value,
  onChange,
  placeholder,
}: {
  id: string
  label: string
  hint?: string
  value: string[]
  onChange: (value: string[]) => void
  placeholder?: string
}) {
  const [draft, setDraft] = useState('')

  function add() {
    const entry = draft.trim().replace(/\s+/g, ' ')
    setDraft('')
    if (!entry) return
    // One entry per place, whatever its case: matching ignores case.
    if (value.some((v) => v.toLowerCase() === entry.toLowerCase())) return
    onChange([...value, entry])
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {value.length > 0 && (
        <ul className="flex max-w-md flex-wrap gap-1.5" aria-label={label}>
          {value.map((entry) => (
            <li
              key={entry}
              className="inline-flex items-center gap-1 rounded-full border bg-muted px-2.5 py-0.5 text-sm"
            >
              {entry}
              <button
                type="button"
                aria-label={`Remove ${entry}`}
                onClick={() => onChange(value.filter((v) => v !== entry))}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Input
        id={id}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            add()
          }
        }}
        onBlur={add}
        placeholder={placeholder}
        className="max-w-md"
      />
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  )
}
