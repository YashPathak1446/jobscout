import { cn } from '@/lib/utils'
import { band, type Bands } from '@/lib/api'

const LABEL = {
  strong: 'Strong match',
  typical: 'Typical',
  weak: 'Weak',
} as const

const STYLE = {
  strong: 'bg-strong-bg text-strong',
  typical: 'bg-typical-bg text-typical',
  weak: 'bg-weak-bg text-weak',
} as const

/**
 * Where one job sits among your own, not an absolute verdict.
 *
 * The raw score is normalised against a window far wider than real data uses
 * — 95 scored jobs spanned 44 to 59 on a 0-100 scale — so "53" reads the same
 * whatever it is (R67). The band is the honest signal; the number is shown
 * beside it for anyone who wants it, not instead of it.
 *
 * An unscored job says so. It is not a weak match: analysis never looked at
 * it.
 */
export function MatchBadge({
  score,
  bar = null,
  bands,
  pending,
  className,
}: {
  score: number | null
  bar?: number | null
  bands: Bands | null
  pending?: boolean
  className?: string
}) {
  // The bands arrive on their own request, and the rows can beat them. Until
  // they land, nothing is known about where this score sits — and "Not
  // scored" is a claim, not a placeholder. Rendering it here would tell every
  // reader, for a second on every load, that analysis had skipped their whole
  // board. Absence and not-yet-known are different states; this is the third
  // place in this project that has had to learn it.
  if (pending) {
    return (
      <span
        className={cn(
          'inline-flex h-[22px] w-24 animate-pulse rounded-full bg-muted',
          className,
        )}
      />
    )
  }

  // Scored and set aside (R106). This used to fall through to "Not scored",
  // because the score was never stored: a claim that analysis had not looked
  // at a job it had scored 39.9 and dropped. It gets its own label, with the
  // number, and is never banded: its bar, not its quartile, is what decided it.
  if (score !== null && score !== undefined && bar !== null && score < bar) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5',
          'text-xs font-medium tabular-nums text-muted-foreground',
          className,
        )}
        title={`Scored ${score.toFixed(1)}, under your bar of ${bar}, so no resume was written for it. It stays on your board.`}
      >
        {/* The bar's number on the badge, as Streamlit's row shows it. */}
        Below your bar of {bar}
        <span className="opacity-60">{score.toFixed(0)}</span>
      </span>
    )
  }

  const tier = band(score, bands)

  // Scored, but not yet comparable (R121). Bands need enough scored jobs to
  // divide (`JobStore.MIN_FOR_BANDS`), so a new account's first run has
  // scores and no bands. This fell through to "Not scored" below: a claim
  // that analysis never looked at a job it had scored and written a resume
  // for. Streamlit's label already showed the number alone here.
  if (!tier && score !== null && score !== undefined) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5',
          'text-xs font-medium tabular-nums',
          className,
        )}
        title={`Scored ${score.toFixed(1)}. Strong, typical and weak appear once more of your jobs are scored.`}
      >
        Scored
        <span className="opacity-60">{score.toFixed(0)}</span>
      </span>
    )
  }

  if (!tier) {
    return (
      <span
        className={cn(
          'inline-flex items-center rounded-full border border-dashed px-2.5 py-0.5',
          'text-xs font-medium text-muted-foreground',
          className,
        )}
        title="Discovery found this job; analysis has not scored it yet"
      >
        Not scored
      </span>
    )
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5',
        'text-xs font-medium tabular-nums',
        STYLE[tier],
        className,
      )}
      title={`Score ${score?.toFixed(1)} — your typical is ${bands?.typical.toFixed(
        1,
      )}, strong is ${bands?.strong.toFixed(1)}, across ${bands?.n} scored jobs`}
    >
      {LABEL[tier]}
      <span className="opacity-60">{score?.toFixed(0)}</span>
    </span>
  )
}
