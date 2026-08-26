import { useRef, useState } from 'react'
import { FileUp, Loader2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ImportConfirm } from '@/components/ImportConfirm'
import { api, type Extraction, type ProfileSummary, type ResumeSchema } from '@/lib/api'

/**
 * Step one: the resume, and the profile built out of it.
 *
 * A returning user does not upload anything — making them re-upload to reach
 * the run screen is the friction that stops people using a tool they
 * otherwise like. So the existing-profile path is offered first and skips
 * ahead.
 *
 * A `.tex` upload goes straight through: it is already the pipeline's own
 * format, so there is nothing a model guessed at. A PDF or Word file stops at
 * the confirmation screen, always.
 */
export function ResumeStep({
  profiles,
  onProfileReady,
  onSkipAhead,
}: {
  profiles: string[]
  onProfileReady: (name: string, summary: ProfileSummary | null) => void
  onSkipAhead: (name: string) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [existing, setExisting] = useState<string>('')
  const [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState<'reading' | 'building' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<Extraction | null>(null)
  const input = useRef<HTMLInputElement>(null)

  // Derived, not stored: an effect that copies props into state renders
  // twice and leaves a stale value if the list arrives later.
  const selected = existing || profiles[0] || ''

  const clash = Boolean(name) && profiles.includes(name)

  async function read() {
    if (!file || !name) return
    setBusy('reading')
    setError(null)
    try {
      const extracted = await api.extractResume(file)
      if (extracted.kind === 'latex') {
        await build(extracted.filename, null)
        return
      }
      setPending(extracted)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function build(filename: string, schema: ResumeSchema | null) {
    setBusy('building')
    setError(null)
    try {
      const summary = await api.createProfile({
        name,
        filename,
        force: replace,
        schema_: schema,
      })
      onProfileReady(name, summary)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  // An extraction awaiting confirmation takes over the screen: agreeing with
  // it, or fixing it, is the only sensible next action.
  if (pending && pending.kind === 'extracted') {
    return (
      <>
        {error && <ErrorNote message={error} />}
        <ImportConfirm
          schema={pending.schema}
          filename={pending.filename}
          busy={busy === 'building'}
          onConfirm={(corrected) => build(pending.filename, corrected)}
          onCancel={() => {
            setPending(null)
            setFile(null)
            if (input.current) input.current.value = ''
          }}
        />
      </>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Your resume</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload it as PDF, Word or LaTeX. Everything it already states is read
          from it — name, contact links, education, and which of your projects
          suit which jobs.
        </p>
      </div>

      {profiles.length > 0 && (
        <div className="space-y-3 rounded-lg border p-4">
          <p className="font-medium">Already set up?</p>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={selected} onValueChange={setExisting}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Pick a profile" />
              </SelectTrigger>
              <SelectContent>
                {profiles.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button onClick={() => onSkipAhead(selected)} disabled={!selected}>
              Continue with this profile
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            Or upload a resume below to start fresh.
          </p>
        </div>
      )}

      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="resume-file">Your resume</Label>
          <Input
            id="resume-file"
            ref={input}
            type="file"
            accept=".tex,.pdf,.docx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <p className="text-sm text-muted-foreground">
            PDF and Word files are read into a LaTeX resume you can keep and
            edit. Text-based PDFs work; a scanned image will not.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="profile-name">Profile name</Label>
          <Input
            id="profile-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. jane_doe"
            className="max-w-sm"
          />
          <p className="text-sm text-muted-foreground">
            Used for the profile file and generated resume filenames.
          </p>
        </div>

        {/* Overwriting is never implicit. Rebuilding discards every rule the
            owner tuned by hand, and one profile was already lost that way
            (R30). A backup is kept, but the live profile is replaced. */}
        {clash && (
          <Alert>
            <AlertTitle>“{name}” already exists</AlertTitle>
            <AlertDescription className="space-y-3">
              <p>
                Rebuilding replaces it completely, including any rules you
                tuned by hand. A timestamped backup is kept, but the live
                profile is replaced.
              </p>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="replace"
                  checked={replace}
                  onCheckedChange={(v) => setReplace(v === true)}
                />
                <Label htmlFor="replace">Yes, replace “{name}”</Label>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {error && <ErrorNote message={error} />}

        <Button
          onClick={read}
          disabled={!file || !name || (clash && !replace) || busy !== null}
        >
          {busy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <FileUp className="size-4" />
          )}
          {busy === 'reading'
            ? 'Reading your resume…'
            : busy === 'building'
              ? 'Building your profile…'
              : 'Read my resume'}
        </Button>
      </div>
    </div>
  )
}

function ErrorNote({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>That did not work</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
