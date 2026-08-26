import { useEffect, useState } from 'react'
import { AlertTriangle, ChevronDown } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

const TIERS = ['high', 'medium', 'low'] as const

type Component = {
  id: string
  label: string
  tier: string
  triggers: string[]
  always: boolean
  never: boolean
}

type Rules = { experiences: Component[]; projects: Component[] }

/**
 * Step four: which of your work counts, and when.
 *
 * Trigger words are derived from each component's tech stack, so they cover
 * what you *built with* and not what a posting *calls it* — a mobile project
 * derives `ionic` and `capacitor` while the ad says `android`. Adding those is
 * the one thing nobody but the owner can do.
 *
 * Optional by design: Skip is a first-class button, not a way out of a form
 * someone failed to complete.
 */
export function TuningStep({
  profile,
  onBack,
  onContinue,
}: {
  profile: string
  onBack: () => void
  onContinue: () => void
}) {
  const [rules, setRules] = useState<Rules | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .profile(profile)
      .then((p) => setRules(p.components as Rules))
      .catch((e: Error) => setError(e.message))
  }, [profile])

  if (!rules) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }

  function edit(section: keyof Rules, id: string, patch: Partial<Component>) {
    setRules((r) =>
      r
        ? {
            ...r,
            [section]: r[section].map((c) => (c.id === id ? { ...c, ...patch } : c)),
          }
        : r,
    )
  }

  async function save() {
    setSaving(true)
    setError(null)
    const all = [...rules!.experiences, ...rules!.projects]
    try {
      await api.writeComponents(profile, {
        importance: Object.fromEntries(all.map((c) => [c.id, c.tier])),
        triggers: Object.fromEntries(all.map((c) => [c.id, c.triggers])),
        // never wins over always, which is what the pipeline does with the
        // same conflict. Resolved here so the two screens agree.
        always: Object.fromEntries(all.map((c) => [c.id, c.always && !c.never])),
        never: Object.fromEntries(all.map((c) => [c.id, c.never])),
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
        <h2 className="text-xl font-semibold tracking-tight">
          Tune what gets shown
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Optional. Trigger words are read from each component's tech stack,
          which means they cover what you <em>built with</em> but not what a
          posting <em>calls it</em>. A mobile project derives{' '}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">ionic</code>;
          the job ad says{' '}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">android</code>.
          Adding those is the one thing nobody but you can do.
        </p>
      </div>

      {(['experiences', 'projects'] as const).map((section) => (
        <section key={section} className="space-y-2">
          <h3 className="font-medium capitalize">{section}</h3>
          {rules[section].length === 0 && (
            <p className="text-sm text-muted-foreground">
              Your resume has none of these.
            </p>
          )}
          {rules[section].map((component) => {
            const isOpen = open === component.id
            const conflict = component.always && component.never
            return (
              <div key={component.id} className="rounded-lg border">
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : component.id)}
                  className="flex w-full items-center gap-2 p-3 text-left text-sm"
                >
                  <ChevronDown
                    className={cn(
                      'size-4 shrink-0 transition-transform',
                      isOpen && 'rotate-180',
                    )}
                  />
                  <span className="flex-1 font-medium">{component.label}</span>
                  <Badges component={component} />
                </button>

                {isOpen && (
                  <div className="space-y-4 border-t p-4">
                    <div className="space-y-2">
                      <Label>How central is this to your story?</Label>
                      <div className="flex gap-1.5">
                        {TIERS.map((tier) => (
                          <button
                            key={tier}
                            type="button"
                            aria-pressed={component.tier === tier}
                            onClick={() => edit(section, component.id, { tier })}
                            className={cn(
                              'rounded-full border px-3 py-1 text-sm capitalize',
                              component.tier === tier
                                ? 'border-transparent bg-primary text-primary-foreground'
                                : 'hover:bg-accent',
                            )}
                          >
                            {tier}
                          </button>
                        ))}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        High gets the most bullets. Low is shown only when a job
                        specifically calls for it.
                      </p>
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor={`trig-${component.id}`}>
                        Show this when a job description mentions
                      </Label>
                      <Input
                        id={`trig-${component.id}`}
                        value={component.triggers.join(', ')}
                        placeholder="android, mobile app, mobile development"
                        onChange={(e) =>
                          edit(section, component.id, {
                            // Split only. Trimming, lowercasing and dropping
                            // empties happen in write_component_rules, so both
                            // UIs get the same normalisation rather than each
                            // inventing one.
                            triggers: e.target.value.split(','),
                          })
                        }
                      />
                      <p className="text-sm text-muted-foreground">
                        Comma separated. Leave empty for no rule.
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-6">
                      <label className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={component.always}
                          onCheckedChange={(v) =>
                            edit(section, component.id, { always: v === true })
                          }
                        />
                        Always show this
                      </label>
                      <label className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={component.never}
                          onCheckedChange={(v) =>
                            edit(section, component.id, { never: v === true })
                          }
                        />
                        Never show this
                      </label>
                    </div>

                    {conflict && (
                      <p className="flex items-start gap-2 text-sm">
                        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                        Always and never cannot both be true —{' '}
                        <strong>never</strong> wins, which is what the pipeline
                        does with the same conflict.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </section>
      ))}

      {error && <p className="text-sm text-destructive">Could not save: {error}</p>}

      <div className="flex flex-wrap gap-2 border-t pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save and continue'}
        </Button>
        {/* Skipping is a real answer on this screen: the derived rules work,
            and nothing here is required. It is a button rather than fine
            print so nobody sits stuck on an optional form. */}
        <Button variant="ghost" onClick={onContinue} disabled={saving}>
          Skip this
        </Button>
      </div>
    </div>
  )
}

function Badges({ component }: { component: Component }) {
  const marks: string[] = []
  if (component.never) marks.push('never')
  else if (component.always) marks.push('always')
  if (component.triggers.length) marks.push(`${component.triggers.length} triggers`)
  marks.push(component.tier)
  return (
    <span className="flex shrink-0 gap-1.5 text-xs text-muted-foreground">
      {marks.map((m) => (
        <span key={m} className="rounded-full bg-muted px-2 py-0.5">
          {m}
        </span>
      ))}
    </span>
  )
}
