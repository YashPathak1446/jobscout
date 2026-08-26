import { useState } from 'react'
import { AlertTriangle, Trash2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { ResumeSchema } from '@/lib/api'

/**
 * Everything read out of a PDF or Word resume, shown before anything is used.
 *
 * R33's rule: nothing is written until the owner agrees with it. A silent
 * misparse otherwise produces bad resumes until somebody notices, and by then
 * they have been sent. So this screen is deliberately in the way.
 *
 * It is also the only thing standing between the no-model path and a wrong
 * profile. Without a key the pattern reader gets contact details and skills
 * and cannot split roles apart at all — and one thing it reliably gets wrong
 * is an email glued to the text above it ("Boston, MApriya@..."), because PDF
 * extraction runs adjacent text together. That field is flagged rather than
 * silently corrected: every rule that trims the prefix also breaks
 * `JSmith@example.com`.
 */
export function ImportConfirm({
  schema,
  filename,
  onConfirm,
  onCancel,
  busy,
}: {
  schema: ResumeSchema
  filename: string
  onConfirm: (corrected: ResumeSchema) => void
  onCancel: () => void
  busy?: boolean
}) {
  const [draft, setDraft] = useState<ResumeSchema>(() =>
    JSON.parse(JSON.stringify(schema)),
  )

  const leftovers = Object.entries(draft._unparsed ?? {}).filter(
    ([, lines]) => lines && lines.length,
  )

  function setContact(field: string, value: string) {
    setDraft((d) => ({ ...d, contact: { ...(d.contact ?? {}), [field]: value } }))
  }

  function dropEntry(section: 'experiences' | 'projects', index: number) {
    setDraft((d) => ({
      ...d,
      [section]: (d[section] ?? []).filter((_, i) => i !== index),
    }))
  }

  function setEntryField(
    section: 'experiences' | 'projects',
    index: number,
    field: string,
    value: string | string[],
  ) {
    setDraft((d) => ({
      ...d,
      [section]: (d[section] ?? []).map((entry, i) =>
        i === index ? { ...entry, [field]: value } : entry,
      ),
    }))
  }

  const experiences = draft.experiences ?? []
  const projects = draft.projects ?? []
  const contact = draft.contact ?? {}

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">
          Check what we read from {filename}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Nothing is saved until you agree with it. Correct anything that is
          wrong, and delete any entry that should not be there.
        </p>
      </div>

      <div className="flex flex-wrap gap-6 rounded-lg border bg-card p-4 text-sm">
        <Stat label="Experiences" value={experiences.length} />
        <Stat label="Projects" value={projects.length} />
        <Stat label="Skill groups" value={Object.keys(draft.skills ?? {}).length} />
      </div>

      {leftovers.length > 0 && (
        <Alert>
          <AlertTriangle className="size-4" />
          <AlertTitle>Some of this could not be split into entries</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              Most likely because no model was available to read it. It is
              below exactly as it appeared — anything you want kept has to be
              typed in above.
            </p>
            {leftovers.map(([section, lines]) => (
              <div key={section} className="w-full">
                <p className="mb-1 font-medium capitalize">{section}</p>
                <pre className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
                  {lines.join('\n')}
                </pre>
              </div>
            ))}
          </AlertDescription>
        </Alert>
      )}

      <section className="space-y-3">
        <h3 className="font-medium">Contact</h3>
        <p className="text-sm text-muted-foreground">
          A PDF shows link text, not link targets, so a URL field may hold the
          word “GitHub” rather than the address. Check the email especially —
          PDFs often run it together with the line above.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {['name', 'email', 'phone', 'github', 'linkedin', 'portfolio'].map(
            (field) => (
              <div key={field} className="space-y-1.5">
                <Label htmlFor={`contact-${field}`} className="capitalize">
                  {field}
                </Label>
                <Input
                  id={`contact-${field}`}
                  value={contact[field] ?? ''}
                  onChange={(e) => setContact(field, e.target.value)}
                  placeholder="—"
                />
              </div>
            ),
          )}
        </div>
      </section>

      {(['experiences', 'projects'] as const).map((section) => {
        const entries = section === 'experiences' ? experiences : projects
        if (!entries.length) return null
        return (
          <section key={section} className="space-y-3">
            <h3 className="font-medium capitalize">{section}</h3>
            {entries.map((entry, index) => (
              <div key={index} className="space-y-3 rounded-lg border p-4">
                <div className="flex items-start gap-3">
                  <div className="grid flex-1 gap-3 sm:grid-cols-2">
                    {(section === 'experiences'
                      ? ['title', 'company', 'dates', 'location']
                      : ['name', 'tech', 'dates', 'url']
                    ).map((field) => (
                      <div key={field} className="space-y-1.5">
                        <Label
                          htmlFor={`${section}-${index}-${field}`}
                          className="capitalize"
                        >
                          {field}
                        </Label>
                        <Input
                          id={`${section}-${index}-${field}`}
                          value={String(entry[field] ?? '')}
                          onChange={(e) =>
                            setEntryField(section, index, field, e.target.value)
                          }
                        />
                      </div>
                    ))}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove this ${section.slice(0, -1)}`}
                    onClick={() => dropEntry(section, index)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`${section}-${index}-bullets`}>
                    Bullets — one per line
                  </Label>
                  <Textarea
                    id={`${section}-${index}-bullets`}
                    rows={Math.min(6, ((entry.bullets as string[]) ?? []).length + 1)}
                    value={((entry.bullets as string[]) ?? []).join('\n')}
                    onChange={(e) =>
                      setEntryField(
                        section,
                        index,
                        'bullets',
                        e.target.value.split('\n').filter((l) => l.trim()),
                      )
                    }
                  />
                </div>
              </div>
            ))}
          </section>
        )
      })}

      <div className="flex items-center gap-3 border-t pt-4">
        <Button onClick={() => onConfirm(draft)} disabled={busy}>
          {busy ? 'Building your profile…' : 'This is right — build my profile'}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Start over
        </Button>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-muted-foreground">{label}</div>
    </div>
  )
}
