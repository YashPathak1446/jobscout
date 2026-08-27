import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { AboutYouStep } from '@/components/steps/AboutYouStep'
import { PreferencesStep } from '@/components/steps/PreferencesStep'
import { ResumeStep } from '@/components/steps/ResumeStep'
import { RunStep } from '@/components/steps/RunStep'
import { TuningStep } from '@/components/steps/TuningStep'
import { api, type ProfileSummary } from '@/lib/api'
import { cn } from '@/lib/utils'

export const STEPS = ['Resume', 'About you', 'Preferences', 'Tuning', 'Run'] as const

export function Wizard({
  profile,
  onProfile,
  onOpenBoard,
}: {
  profile: string | null
  onProfile: (name: string) => void
  onOpenBoard: () => void
}) {
  const [step, setStep] = useState(0)
  // The furthest screen reached, so stepping back does not strand someone
  // behind screens they have already completed.
  const [furthest, setFurthest] = useState(0)
  const [profiles, setProfiles] = useState<string[] | null>(null)
  const [summary, setSummary] = useState<ProfileSummary | null>(null)
  // Never persisted, here or on the server: it is passed to the pipeline
  // for the run and forgotten.
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    api
      .health()
      .then((h) => setProfiles(h.profiles))
      .catch(() => setProfiles([]))
  }, [])

  function go(next: number) {
    setStep(next)
    setFurthest((f) => Math.max(f, next))
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      <header className="mb-6 flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">JobScout</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Find roles at your level and tailor your resume to each one,
            locally.
          </p>
        </div>
        {profile && (
          <Button variant="outline" size="sm" onClick={onOpenBoard}>
            Your jobs
          </Button>
        )}
      </header>

      <nav className="mb-8 flex flex-wrap items-center gap-1" aria-label="Steps">
        {STEPS.map((label, index) => {
          const reachable = index <= furthest
          const done = index < furthest
          return (
            <button
              key={label}
              type="button"
              disabled={!reachable}
              onClick={() => reachable && setStep(index)}
              className={cn(
                'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors',
                index === step && 'bg-primary text-primary-foreground',
                index !== step && reachable && 'hover:bg-accent',
                !reachable && 'cursor-not-allowed text-muted-foreground/50',
              )}
            >
              <span
                className={cn(
                  'flex size-5 items-center justify-center rounded-full text-xs tabular-nums',
                  index === step
                    ? 'bg-primary-foreground/20'
                    : 'bg-muted text-muted-foreground',
                )}
              >
                {done ? <Check className="size-3" /> : index + 1}
              </span>
              {label}
            </button>
          )
        })}
      </nav>

      {step === 0 && (
        <>
          {/* profiles === null is "still asking", not "you have none". The
              two look identical on screen and mean opposite things, which is
              the invariant in CLAUDE.md: unknown is never rendered as a
              value. */}
          {profiles === null ? (
            <div className="space-y-3">
              <div className="h-6 w-48 animate-pulse rounded bg-muted" />
              <div className="h-24 w-full animate-pulse rounded-lg bg-muted" />
            </div>
          ) : (
            <ResumeStep
              profiles={profiles}
              onSkipAhead={(name) => {
                onProfile(name)
                setSummary(null)
                go(4)
              }}
              onProfileReady={(name, built) => {
                onProfile(name)
                setSummary(built)
                setProfiles((p) => (p?.includes(name) ? p : [...(p ?? []), name]))
                go(1)
              }}
            />
          )}
          {summary && <BuiltSummary summary={summary} />}
        </>
      )}

      {step === 1 && profile && (
        <AboutYouStep
          profile={profile}
          apiKey={apiKey}
          onKey={setApiKey}
          onBack={() => setStep(0)}
          onContinue={() => go(2)}
        />
      )}

      {step === 1 && !profile && (
        <Alert>
          <AlertTitle>No profile yet</AlertTitle>
          <AlertDescription>
            Go back to step one and pick or build one.
          </AlertDescription>
        </Alert>
      )}

      {step === 2 && profile && (
        <PreferencesStep
          profile={profile}
          onBack={() => setStep(1)}
          onContinue={() => go(3)}
        />
      )}

      {step === 3 && profile && (
        <TuningStep
          profile={profile}
          onBack={() => setStep(2)}
          onContinue={() => go(4)}
        />
      )}

      {step === 4 && profile && (
        <RunStep
          profile={profile}
          apiKey={apiKey}
          onBack={() => setStep(3)}
          onOpenBoard={onOpenBoard}
        />
      )}

      {step > 2 && !profile && (
        <div className="space-y-4">
          <Alert>
            <AlertTitle>{STEPS[step]} is not built yet</AlertTitle>
            <AlertDescription>
              This screen still lives in the Streamlit app. It is next.
            </AlertDescription>
          </Alert>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setStep(step - 1)}>
              Back
            </Button>
            {step < STEPS.length - 1 && (
              <Button onClick={() => go(step + 1)}>Skip for now</Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function BuiltSummary({ summary }: { summary: ProfileSummary }) {
  return (
    <div className="mt-6 space-y-3 rounded-lg border p-4">
      <p className="font-medium">Profile built</p>
      <div className="flex flex-wrap gap-6 text-sm">
        {Object.entries(summary.counts ?? {}).map(([label, value]) => (
          <div key={label}>
            <div className="text-2xl font-semibold tabular-nums">{value}</div>
            <div className="capitalize text-muted-foreground">
              {label.replace(/_/g, ' ')}
            </div>
          </div>
        ))}
      </div>
      {summary.backup_path && (
        <p className="text-sm text-muted-foreground">
          Previous profile saved as{' '}
          <code className="rounded bg-muted px-1.5 py-0.5">
            {summary.backup_path.split(/[\\/]/).pop()}
          </code>
        </p>
      )}
      {Object.keys(summary.derived ?? {}).length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">
            What was read from your resume
          </summary>
          <dl className="mt-2 space-y-1">
            {Object.entries(summary.derived).map(([field, value]) => (
              <div key={field} className="flex gap-2">
                <dt className="font-medium">{field}</dt>
                <dd className="text-muted-foreground">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  )
}
