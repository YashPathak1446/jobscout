import { useState } from 'react'
import { AlertTriangle, Plus, Trash2 } from 'lucide-react'

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

  // Skills are held as rows rather than as the object they will become,
  // because renaming a key while somebody is typing it drops every keystroke
  // that leaves the object momentarily invalid.
  //
  // They were not on this screen at all — a count in the header and nothing
  // else, on a screen headed "Correct anything that is wrong". So the section
  // that reaches the employer verbatim was the one section nobody could see,
  // let alone fix. Priya's PDF extracts `A WS` for AWS, a kerning artifact of
  // her file; the email glued to the line above it is flagged and correctable
  // and this was not, though both come from the same reader and land on the
  // same page. The Streamlit screen has had a skills field the whole time,
  // which is the tell: two screens, one walked.
  const [skillRows, setSkillRows] = useState<{ label: string; value: string }[]>(
    () => Object.entries(schema.skills ?? {}).map(([label, value]) => ({ label, value })),
  )

  /** The rows back into the schema's shape, dropping any left blank. */
  function skillsFromRows(): Record<string, string> {
    const out: Record<string, string> = {}
    for (const { label, value } of skillRows) {
      const name = label.trim()
      const listed = value.trim()
      if (!name || !listed) continue
      out[name] = out[name] ? `${out[name]}, ${listed}` : listed
    }
    return out
  }

  function setSkillRow(index: number, field: 'label' | 'value', next: string) {
    setSkillRows((rows) =>
      rows.map((row, i) => (i === index ? { ...row, [field]: next } : row)),
    )
  }

  const leftovers = Object.entries(draft._unparsed ?? {}).filter(
    ([, lines]) => lines && lines.length,
  )

  function setContact(field: string, value: string) {
    setDraft((d) => ({ ...d, contact: { ...(d.contact ?? {}), [field]: value } }))
  }

  /**
   * A blank entry, in the shape `tex_renderer` reads.
   *
   * This is the whole of the fix for the dead end. The screen used to render
   * entry fields only when extraction had produced entries, so a resume the
   * pattern reader could not split showed the owner three jobs it had read
   * correctly, told them "anything you want kept has to be typed in above",
   * and gave them nowhere to type. Priya Raghunathan walked five screens and
   * a full pipeline from there to a 574-byte file with no work history on it.
   */
  function setEducation(index: number, field: string, value: string) {
    setDraft((d) => ({
      ...d,
      education: (d.education ?? []).map((row, i) =>
        i === index ? { ...row, [field]: value } : row,
      ),
    }))
  }

  function addEducation() {
    setDraft((d) => ({
      ...d,
      education: [...(d.education ?? []),
                  { school: '', location: '', degree: '', dates: '' }],
    }))
  }

  function dropEducation(index: number) {
    setDraft((d) => ({
      ...d,
      education: (d.education ?? []).filter((_, i) => i !== index),
    }))
  }

  function addEntry(section: 'experiences' | 'projects') {
    const blank =
      section === 'experiences'
        ? { title: '', company: '', dates: '', location: '', bullets: [] }
        : { name: '', tech: '', dates: '', url: '', bullets: [] }
    setDraft((d) => ({ ...d, [section]: [...(d[section] ?? []), blank] }))
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
        <Stat label="Skill groups" value={Object.keys(skillsFromRows()).length} />
      </div>

      {leftovers.length > 0 && (
        <Alert>
          <AlertTriangle className="size-4" />
          <AlertTitle>Some of this could not be split into entries</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              Most likely because no model was available to read it. It is
              below exactly as it appeared. Use <strong>Add an experience</strong>
              or <strong>Add a project</strong> further down to enter what you
              want kept — copying from here — and delete anything you do not.
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
        {/* Exactly the fields the header renders. `portfolio` used to be here
            and appeared nowhere else in the repository — nothing extracted it,
            nothing stored it, and `_header` does not print it, so a URL typed
            into a labelled box on a screen headed "correct anything that is
            wrong" was collected and dropped. Same shape as the project link
            (R74) and the education degree before it.

            Removed rather than rendered, because rendering it honestly needs
            a parser counterpart: `latex_parser` recovers GitHub and LinkedIn
            from the href by matching the domain, and an arbitrary portfolio
            URL has no pattern to match, so it would print once and vanish on
            the next round trip. A field that does nothing is better gone than
            left on screen implying otherwise. */}
        <div className="grid gap-3 sm:grid-cols-2">
          {['name', 'email', 'phone', 'github', 'linkedin'].map(
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

      {/* Education was not on this screen at all, which is how a degree went
          missing without anybody being able to put it back. The pattern
          reader hands over one entry with whatever it could place, and the
          four fields here are exactly the four `tex_renderer` writes and the
          parser reads — no more, no less, so nothing can be typed in that the
          renderer will drop. */}
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <h3 className="font-medium">Education</h3>
          <Button variant="outline" size="sm" onClick={addEducation}>
            <Plus className="size-4" />
            Add a school
          </Button>
        </div>
        {(draft.education ?? []).length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing was read as education.
          </p>
        )}
        {(draft.education ?? []).map((row, index) => (
          <div key={index} className="flex items-start gap-3 rounded-lg border p-4">
            <div className="grid flex-1 gap-3 sm:grid-cols-2">
              {['school', 'degree', 'location', 'dates'].map((field) => (
                <div key={field} className="space-y-1.5">
                  <Label htmlFor={`education-${index}-${field}`} className="capitalize">
                    {field}
                  </Label>
                  <Input
                    id={`education-${index}-${field}`}
                    value={String(row[field] ?? '')}
                    onChange={(e) => setEducation(index, field, e.target.value)}
                  />
                </div>
              ))}
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Remove this school"
              onClick={() => dropEducation(index)}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        ))}
      </section>

      {/* Both sections always render, empty or not. An empty section with an
          add button is a form; an absent section is a dead end. */}
      {(['experiences', 'projects'] as const).map((section) => {
        const entries = section === 'experiences' ? experiences : projects
        const noun = section === 'experiences' ? 'experience' : 'project'
        return (
          <section key={section} className="space-y-3">
            <div className="flex items-center gap-3">
              <h3 className="font-medium capitalize">{section}</h3>
              <Button
                variant="outline"
                size="sm"
                onClick={() => addEntry(section)}
              >
                <Plus className="size-4" />
                Add {noun === 'experience' ? 'an' : 'a'} {noun}
              </Button>
            </div>
            {entries.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Nothing was read into separate {section}. A resume with none of
                these produces a resume with none of these — add what you have
                before continuing.
              </p>
            )}
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

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Skills</h3>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setSkillRows((rows) => [...rows, { label: '', value: '' }])
            }
          >
            <Plus className="size-4" /> Add a skill group
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          One group per line — a heading, then the skills in it. This is
          printed on your resume as you leave it here.
        </p>
        {skillRows.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing was read out of a skills section. Add a group if your
            resume has one.
          </p>
        )}
        {skillRows.map((row, index) => (
          <div key={index} className="flex flex-wrap items-end gap-3">
            <div className="w-48 space-y-1.5">
              <Label htmlFor={`skill-label-${index}`}>Group</Label>
              <Input
                id={`skill-label-${index}`}
                value={row.label}
                placeholder="Languages"
                onChange={(e) => setSkillRow(index, 'label', e.target.value)}
              />
            </div>
            <div className="min-w-64 flex-1 space-y-1.5">
              <Label htmlFor={`skill-value-${index}`}>Skills</Label>
              <Input
                id={`skill-value-${index}`}
                value={row.value}
                placeholder="Java, Kotlin, Python"
                onChange={(e) => setSkillRow(index, 'value', e.target.value)}
              />
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Remove this skill group"
              onClick={() =>
                setSkillRows((rows) => rows.filter((_, i) => i !== index))
              }
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        ))}
      </section>

      <div className="flex items-center gap-3 border-t pt-4">
        <Button
          onClick={() => onConfirm({ ...draft, skills: skillsFromRows() })}
          disabled={busy}
        >
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
