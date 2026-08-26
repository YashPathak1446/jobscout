import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'

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

const split = (text: string) =>
  text.split(',').map((s) => s.trim()).filter(Boolean)

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
  const [derived, setDerived] = useState<string[]>([])
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
    api
      .levels(years)
      .then((l) => {
        setLevels(l.all)
        setDerived(l.derived)
      })
      .catch(() => undefined)
  }, [years])

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
  const inForce = override.length ? override : derived

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
          max={40}
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

      <div className="space-y-1.5">
        <Label htmlFor="cities">Cities (comma separated, optional)</Label>
        <Input
          id="cities"
          value={prefs.cities.join(', ')}
          onChange={(e) => setPrefs({ ...prefs, cities: split(e.target.value) })}
          placeholder="San Francisco, New York"
          className="max-w-md"
        />
      </div>

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
              placeholder="United States"
            />
            <Field
              id="states-priority"
              label="States you would most like"
              hint="Discovery searches the first of these by name."
              value={prefs.states_priority}
              onChange={(v) => setPrefs({ ...prefs, states_priority: v })}
              placeholder="California, New York"
            />
            <Field
              id="states-acceptable"
              label="States you would accept"
              value={prefs.states_acceptable}
              onChange={(v) => setPrefs({ ...prefs, states_acceptable: v })}
              placeholder="Texas, Washington"
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
        {/* Gated on the levels in force, never on the override box — that is
            empty for everyone who has not overridden, and gating on it left
            the Streamlit button dead for every new profile. */}
        <Button
          onClick={save}
          disabled={!prefs.target_roles.length || !inForce.length || saving}
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
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value.join(', ')}
        onChange={(e) => onChange(split(e.target.value))}
        placeholder={placeholder}
        className="max-w-md"
      />
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  )
}
