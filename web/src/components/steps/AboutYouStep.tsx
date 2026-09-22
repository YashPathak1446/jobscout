import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { BackendPanel } from '@/components/BackendPanel'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

type Answer = 'yes' | 'no' | 'unknown'
type Field = 'us_person' | 'needs_sponsorship' | 'holds_clearance'
// null is "not answered on this screen yet" — distinct from 'unknown',
// which is the answer "Prefer not to say".
type Answers = Record<Field, Answer | null>

/**
 * The three work-authorization questions (A4).
 *
 * A copy of `WORK_AUTHORIZATION_QUESTIONS` in `scripts/init_profile.py`,
 * which Streamlit renders from. The wording is load-bearing and was reviewed
 * as such; `tests/test_about_you.py` fails if any string there is missing
 * here verbatim, so edit both or neither.
 */
const QUESTIONS: {
  field: Field
  question: string
  options: [Answer, string][]
  help: string
}[] = [
  {
    field: 'us_person',
    question:
      'Are you a US citizen, green-card holder, or admitted as a refugee or asylee?',
    options: [
      ['yes', 'Yes'],
      ['no', 'No'],
      ['unknown', 'Prefer not to say'],
    ],
    help: 'Some postings are open only to US persons: ITAR, export-control and most clearance work.',
  },
  {
    field: 'needs_sponsorship',
    question: 'Will you need visa sponsorship, now or in future?',
    options: [
      ['yes', 'Yes, now or later'],
      ['no', 'No'],
      ['unknown', 'Prefer not to say'],
    ],
    help: "If you're on a work visa today, the answer is yes. F-1 on OPT or CPT: yes, you'll need it later. H-1B: yes, a transfer is sponsorship. Green card or citizen: no.",
  },
  {
    field: 'holds_clearance',
    question: 'Do you hold an active security clearance today?',
    options: [
      ['yes', 'Yes'],
      ['no', 'No'],
      ['unknown', 'Prefer not to say'],
    ],
    help: "Active today. Being eligible to get one doesn't count; postings that only need eligibility are already covered by question 1.",
  },
]

/**
 * A stored "yes" or "no" is shown as answered. A stored "unknown" is shown as
 * **unanswered**, not as "Prefer not to say": it is also what a profile that
 * was never asked holds — the template starts there — and pre-selecting it
 * would record a default as the reader's choice.
 */
function seed(stored: unknown): Answers {
  const auth = (stored ?? {}) as Partial<Record<Field, unknown>>
  const pick = (v: unknown): Answer | null =>
    v === 'yes' || v === 'no' ? v : null
  return {
    us_person: pick(auth.us_person),
    needs_sponsorship: pick(auth.needs_sponsorship),
    holds_clearance: pick(auth.holds_clearance),
  }
}

type Personal = {
  location: string
  answers: Answers
}

/**
 * Step two: the things a resume cannot state.
 *
 * An address line says where you live, not where you are allowed to work, and
 * a resume never says whether a clearance is active today — which is the
 * difference between two postings that read almost identically (R56).
 *
 * The form is seeded from the stored profile, never from its own defaults.
 * Saving a blank form over stored answers is a silent revert, and this wizard
 * has done that before.
 */
export function AboutYouStep({
  profile,
  apiKey,
  onKey,
  onBack,
  onContinue,
}: {
  profile: string
  apiKey: string
  onKey: (key: string) => void
  onBack: () => void
  onContinue: () => void
}) {
  const [stored, setStored] = useState<Personal | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .profile(profile)
      .then((p) => {
        const personal = p.personal as {
          location?: string
          work_authorization?: unknown
        }
        setStored({
          location: personal.location ?? '',
          answers: seed(personal.work_authorization),
        })
      })
      .catch((e: Error) => {
        setError(e.message)
        setStored({ location: '', answers: seed(null) })
      })
  }, [profile])

  // null is "still loading the profile", and rendering it as an empty form
  // would invite someone to save blanks over their own answers.
  if (stored === null) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-10 w-full max-w-md" />
        <Skeleton className="h-10 w-full max-w-md" />
      </div>
    )
  }

  const answered = QUESTIONS.every((q) => stored.answers[q.field] !== null)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await api.updateProfile(profile, {
        personal_info: {
          location: stored!.location,
          work_authorization: stored!.answers,
        },
      })
      onContinue()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">About you</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Things a resume cannot reliably tell us. An address line says where
          you live, not where you are allowed to work.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="location">Where are you based?</Label>
        <Input
          id="location"
          value={stored.location}
          onChange={(e) => setStored({ ...stored, location: e.target.value })}
          placeholder="City, State"
          className="max-w-md"
        />
      </div>

      {QUESTIONS.map((q) => (
        <div key={q.field} className="space-y-1.5">
          <Label id={`work-${q.field}`}>{q.question}</Label>
          <div
            role="radiogroup"
            aria-labelledby={`work-${q.field}`}
            className="flex flex-wrap gap-2"
          >
            {q.options.map(([value, label]) => {
              const chosen = stored.answers[q.field] === value
              return (
                <Button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={chosen}
                  size="sm"
                  variant={chosen ? 'default' : 'outline'}
                  className={cn(!chosen && 'font-normal')}
                  onClick={() =>
                    setStored({
                      ...stored,
                      answers: { ...stored.answers, [q.field]: value },
                    })
                  }
                >
                  {label}
                </Button>
              )
            })}
          </div>
          {/* Visible, not a tooltip: the sponsorship help is what turns
              "not today" into the right answer. */}
          <p className="text-sm text-muted-foreground">{q.help}</p>
        </div>
      ))}

      <BackendPanel apiKey={apiKey} onKey={onKey} />

      {error && (
        <p className="text-sm text-destructive">Could not save: {error}</p>
      )}

      <div className="flex gap-2 border-t pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        {/* Every question answered, "Prefer not to say" included. An
            unanswered question stays unanswered: the Streamlit form once
            defaulted its select to the first option, which silently asserted
            US citizenship for anyone who did not touch it. */}
        <Button
          onClick={save}
          disabled={!stored.location.trim() || !answered || saving}
        >
          {saving ? 'Saving…' : 'Continue'}
        </Button>
      </div>
    </div>
  )
}
