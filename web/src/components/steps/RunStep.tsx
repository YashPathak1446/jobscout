import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, FileDown, Loader2, PenLine, Play, XCircle } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api, type Backend, type RunStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

const STAGES = ['discovery', 'enrichment', 'analysis', 'generation'] as const

/**
 * Step five: the run.
 *
 * Two things this screen must say out loud before anyone presses the button.
 *
 * **What will rewrite the bullets.** With no key configured the pipeline still
 * discovers, scores and picks components — it uses the owner's own bullets
 * verbatim instead of rewriting them. That is a supported outcome, not a
 * failure, and someone who is not told will read their unchanged bullets as
 * the tool having done nothing.
 *
 * **Whether a PDF can be produced.** Without a LaTeX engine the run yields
 * `.tex` files. Saying so beforehand is the difference between a limitation
 * and a broken download button (R43).
 *
 * Progress is polled from `data/runs.db`, not held here: the run outlives this
 * page, and a reload has to be able to find it again (R51).
 */
export function RunStep({
  profile,
  apiKey,
  onBack,
  onOpenBoard,
}: {
  profile: string
  apiKey: string
  onBack: () => void
  onOpenBoard: () => void
}) {
  const [health, setHealth] = useState<{ pdflatex: boolean } | null>(null)
  const [backend, setBackend] = useState<Backend | null>(null)
  const [maxJobs, setMaxJobs] = useState(20)
  const [maxResumes, setMaxResumes] = useState(3)
  const [runId, setRunId] = useState<string | null>(null)
  const [status, setStatus] = useState<RunStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const poll = useRef<number | undefined>(undefined)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    api.backend(apiKey).then(setBackend).catch(() => setBackend(null))
  }, [apiKey])

  // A reload has no memory of starting anything, so the answer comes from
  // disk rather than from anything this component held.
  useEffect(() => {
    api
      .activeRuns()
      .then(({ active }) => {
        const mine = active.find((r) => r.profile === profile)
        if (mine) setRunId(mine.id)
      })
      .catch(() => undefined)
  }, [profile])

  const tick = useCallback(() => {
    if (!runId) return
    api
      .runStatus(runId)
      .then(setStatus)
      .catch((e: Error) => setError(e.message))
  }, [runId])

  useEffect(() => {
    if (!runId) return
    tick()
    poll.current = window.setInterval(tick, 2000)
    return () => window.clearInterval(poll.current)
  }, [runId, tick])

  const finished = status?.state === 'finished' || status?.state === 'failed'
  useEffect(() => {
    if (finished) window.clearInterval(poll.current)
  }, [finished])

  async function start() {
    setStarting(true)
    setError(null)
    setStatus(null)
    try {
      const { run_id } = await api.startRun({
        profile,
        api_key: apiKey,
        max_jobs: maxJobs,
        max_resumes: maxResumes,
        generate_pdf: health?.pdflatex ?? true,
      })
      setRunId(run_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  const running = Boolean(runId) && !finished

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Run it</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Discovery, scoring, then a tailored resume for each of the best
          matches. It takes a few minutes and keeps going if you close this
          page.
        </p>
      </div>

      {/* What this machine can do, before the button rather than after the
          disappointment. `null` is "still asking", not "cannot". */}
      {backend === null || health === null ? (
        <Skeleton className="h-20 w-full" />
      ) : (
        <div className="space-y-3">
          <Alert>
            {backend.backend === 'none' ? (
              <PenLine className="size-4" />
            ) : (
              <CheckCircle2 className="size-4" />
            )}
            <AlertTitle>
              {backend.backend === 'none'
                ? 'Your bullets will be used exactly as you wrote them'
                : `Bullets will be rewritten by ${backend.backend}`}
            </AlertTitle>
            <AlertDescription>
              {backend.backend === 'none'
                ? 'Jobs are still discovered and scored, and the right ' +
                  'components are picked for each one. Only the rewriting is ' +
                  'skipped — add a key on the previous screen to change that.'
                : backend.description}
            </AlertDescription>
          </Alert>

          {!health.pdflatex && (
            <Alert>
              <FileDown className="size-4" />
              <AlertTitle>No LaTeX engine on this machine</AlertTitle>
              <AlertDescription>
                You will get <code>.tex</code> files rather than PDFs. Install
                MiKTeX on Windows or TeX Live elsewhere and run again to get
                both.
              </AlertDescription>
            </Alert>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-4">
        <Number
          id="max-jobs"
          label="Jobs to look at"
          value={maxJobs}
          onChange={setMaxJobs}
          disabled={running}
        />
        <Number
          id="max-resumes"
          label="Resumes to write"
          value={maxResumes}
          onChange={setMaxResumes}
          disabled={running}
        />
      </div>

      {error && (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <AlertTitle>That did not work</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {status && <Progress status={status} />}

      <div className="flex flex-wrap gap-2 border-t pt-4">
        <Button variant="outline" onClick={onBack} disabled={running}>
          Back
        </Button>
        <Button onClick={start} disabled={running || starting}>
          {running || starting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Play className="size-4" />
          )}
          {running ? 'Running…' : starting ? 'Starting…' : 'Run JobScout'}
        </Button>
        {status?.state === 'finished' && (
          <Button variant="secondary" onClick={onOpenBoard}>
            See your jobs
          </Button>
        )}
      </div>
    </div>
  )
}

function Progress({ status }: { status: RunStatus }) {
  const failed = status.state === 'failed'
  const done = status.state === 'finished'
  const reached = STAGES.indexOf(status.stage as (typeof STAGES)[number])

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center gap-2 text-sm">
        {failed ? (
          <XCircle className="size-4 shrink-0" />
        ) : done ? (
          <CheckCircle2 className="size-4 shrink-0" />
        ) : (
          <Loader2 className="size-4 shrink-0 animate-spin" />
        )}
        <span className="font-medium">
          {failed ? 'The run failed' : done ? 'Finished' : status.message || 'Working…'}
        </span>
        {/* total 0 means "not counted yet", which is not "0 of 0 done". */}
        {!done && !failed && status.total > 0 && (
          <span className="ml-auto tabular-nums text-muted-foreground">
            {status.done} of {status.total}
          </span>
        )}
      </div>

      <ol className="flex flex-wrap gap-1.5 text-xs">
        {STAGES.map((stage, index) => (
          <li
            key={stage}
            className={cn(
              'rounded-full px-2.5 py-1 capitalize',
              done || index < reached
                ? 'bg-strong-bg text-strong'
                : index === reached && !failed
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground',
            )}
          >
            {stage}
          </li>
        ))}
      </ol>

      {failed && status.error && (
        <p className="text-sm text-destructive">{status.error}</p>
      )}

      {done && status.result && (
        <div className="space-y-2 text-sm">
          <p>
            {status.result.analysed} jobs analysed · {status.result.generated}{' '}
            resumes written · {status.result.valid} passed validation
          </p>
          {/* Named, not hidden. A resume built from the owner's own bullets
              is a real outcome, and someone who is not told reads unchanged
              bullets as the tool having done nothing. */}
          {status.result.degraded?.length > 0 && (
            <p className="text-muted-foreground">
              Some resumes used your own bullets unchanged:{' '}
              {status.result.degraded.join(', ')}.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Number({
  id,
  label,
  value,
  onChange,
  disabled,
}: {
  id: string
  label: string
  value: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={1}
        max={100}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Math.max(1, globalThis.Number(e.target.value) || 1))}
        className="w-28"
      />
    </div>
  )
}
