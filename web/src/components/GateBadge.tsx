import { CircleHelp, Ban } from 'lucide-react'

/**
 * What the gate made of a job, when it is anything but a plain pass (A4).
 *
 * Takes any row and reads the two fields by name, because `lib/api.ts` is
 * not yet in the repository (Q41) and so cannot be relied on to declare
 * them; once it is, `Job` should carry them and this should take a `Job`.
 * A row the gate has never judged has no verdict, and that renders as
 * nothing — not as a pass or a fail.
 *
 * Branches on `gate_verdict`, never on whether `gate_reason` is set: an
 * undecidable job carries a reason too, and reading "has a reason" as "rules
 * you out" would mark every job the gate could not decide as ineligible.
 */
export function GateBadge({ job }: { job: object }) {
  const verdict = 'gate_verdict' in job ? job.gate_verdict : null
  const reason =
    'gate_reason' in job && typeof job.gate_reason === 'string'
      ? job.gate_reason
      : ''

  if (verdict === 'undecidable') {
    return (
      <div className="mt-1 flex items-start gap-1.5 text-sm text-amber-700 dark:text-amber-400">
        <CircleHelp className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <strong className="font-medium">Unconfirmed</strong> —{' '}
          {reason}
        </span>
      </div>
    )
  }
  // Only on screen when the reader asked to see hidden jobs, so it explains
  // rather than nags. Before A4 the React board showed these with no reason.
  if (verdict === 'hidden') {
    return (
      <div className="mt-1 flex items-start gap-1.5 text-sm text-destructive">
        <Ban className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <strong className="font-medium">Rules you out</strong> —{' '}
          {reason}
        </span>
      </div>
    )
  }
  return null
}
