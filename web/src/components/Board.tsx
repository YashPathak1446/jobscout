import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Building2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  EyeOff,
  FileDown,
  Loader2,
  MapPin,
  Search,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { MatchBadge } from '@/components/MatchBadge'
import { api, type Bands, type Filters, type Job, type Stats } from '@/lib/api'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 25
const ANY = '__any__'

const SORT_LABEL: Record<string, string> = {
  best: 'Best match',
  newest: 'Newest posting',
  recent: 'Recently seen',
  company: 'Company',
}

function since(stamp: string | null): string {
  if (!stamp) return '—'
  const then = new Date(stamp).getTime()
  if (Number.isNaN(then)) return '—'
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  return `${Math.floor(days / 30)}mo ago`
}

export function Board() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [total, setTotal] = useState(0)
  const [hidden, setHidden] = useState(0)
  const [stats, setStats] = useState<Stats | null>(null)
  const [bands, setBands] = useState<Bands | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)
  const [statuses, setStatuses] = useState<string[]>([])
  const [sorts, setSorts] = useState<string[]>(['best'])

  const [search, setSearch] = useState('')
  const [company, setCompany] = useState<string>(ANY)
  const [source, setSource] = useState<string>(ANY)
  const [status, setStatus] = useState<string>(ANY)
  const [sort, setSort] = useState('best')
  const [withResume, setWithResume] = useState(false)
  const [showIneligible, setShowIneligible] = useState(false)
  const [page, setPage] = useState(0)

  const [loading, setLoading] = useState(true)
  // Bands, statuses and facets arrive on their own request. Rows can beat
  // them, and a row rendered without them makes claims it cannot support.
  const [metaReady, setMetaReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The search box filters server-side, so every keystroke would be a query.
  const debounced = useRef<number | undefined>(undefined)
  const [term, setTerm] = useState('')
  useEffect(() => {
    window.clearTimeout(debounced.current)
    debounced.current = window.setTimeout(() => setTerm(search), 250)
    return () => window.clearTimeout(debounced.current)
  }, [search])

  useEffect(() => {
    Promise.all([api.stats(), api.bands(), api.filters(), api.health()])
      .then(([s, b, f, h]) => {
        setStats(s)
        setBands(b.n ? b : null)
        setFilters(f)
        setStatuses(h.statuses)
        setSorts(h.sorts)
        setMetaReady(true)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const query = useMemo(
    () => ({
      search: term || undefined,
      company: company === ANY ? undefined : company,
      source: source === ANY ? undefined : source,
      status: status === ANY ? undefined : status,
      has_resume: withResume ? true : undefined,
      include_ineligible: showIneligible ? true : undefined,
      sort,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [term, company, source, status, withResume, showIneligible, sort, page],
  )

  const load = useCallback(() => {
    setLoading(true)
    api
      .board(query)
      .then((result) => {
        setJobs(result.jobs)
        setTotal(result.total)
        setHidden(result.hidden)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [query])

  useEffect(load, [load])

  /**
   * Change a filter and go back to page one, in one update.
   *
   * The obvious version resets the page from an effect watching the filters,
   * which works and costs a wasted request: the query changes with the old
   * offset, fetches, then the effect moves the page and fetches again. Page
   * 3 of "all companies" is not a page of "Affirm only", so the reset is
   * part of the change rather than a reaction to it.
   */
  function change<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value)
      setPage(0)
    }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const first = total === 0 ? 0 : page * PAGE_SIZE + 1
  const last = Math.min(total, (page + 1) * PAGE_SIZE)

  async function move(job: Job, next: string) {
    setJobs((rows) =>
      rows.map((row) => (row.url === job.url ? { ...row, status: next } : row)),
    )
    try {
      await api.setStatus(job.url, next)
    } catch (e) {
      setError((e as Error).message)
      load()
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Your jobs</h1>
        {/* A div, not a p: the loading skeleton is a div, and a div inside a
            p is invalid HTML the browser silently reparents. */}
        <div className="mt-1 text-sm text-muted-foreground">
          {stats ? (
            <>
              {stats.total} discovered · {stats.scored} scored ·{' '}
              {stats.with_resume} with a tailored resume
            </>
          ) : (
            <Skeleton className="h-4 w-64" />
          )}
        </div>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => change(setSearch)(e.target.value)}
            placeholder="Search title or company"
            className="pl-9"
          />
        </div>

        <Select value={company} onValueChange={change(setCompany)}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Company" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All companies</SelectItem>
            {filters?.companies.map((c) => (
              <SelectItem key={c.value} value={c.value}>
                {c.value} ({c.count})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={source} onValueChange={change(setSource)}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Source" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All sources</SelectItem>
            {filters?.sources.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.value.replace('ats_', '')} ({s.count})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={status} onValueChange={change(setStatus)}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any status</SelectItem>
            {statuses.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={sort} onValueChange={change(setSort)}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {sorts.map((s) => (
              <SelectItem key={s} value={s}>
                {SORT_LABEL[s] ?? s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          variant={withResume ? 'default' : 'outline'}
          onClick={() => change(setWithResume)(!withResume)}
        >
          <FileDown className="size-4" />
          Has resume
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-dashed p-4 text-sm">
          <p className="font-medium">The board could not be loaded.</p>
          <p className="mt-1 text-muted-foreground">{error}</p>
          <p className="mt-2 text-muted-foreground">
            Is the API running?{' '}
            <code className="rounded bg-muted px-1.5 py-0.5">
              uvicorn api.main:app --port 8000
            </code>
          </p>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border">
        {loading && jobs.length === 0 ? (
          <div className="divide-y">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 p-4">
                <Skeleton className="h-4 w-64" />
                <Skeleton className="ml-auto h-6 w-24" />
              </div>
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="p-12 text-center">
            <p className="font-medium">No jobs match these filters.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {total === 0 && stats?.total
                ? `${stats.total} jobs are stored — try clearing the filters.`
                : 'Run a discovery pass to fill the board.'}
            </p>
          </div>
        ) : (
          <ul className={cn('divide-y', loading && 'opacity-60')}>
            {jobs.map((job) => (
              <li
                key={job.url}
                className="group flex flex-wrap items-center gap-x-4 gap-y-2 p-4 transition-colors hover:bg-accent/40"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                      className="truncate font-medium hover:underline"
                    >
                      {job.title}
                    </a>
                    <ExternalLink className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <Building2 className="size-3.5" />
                      {job.company}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <MapPin className="size-3.5" />
                      {job.location || 'Location not stated'}
                    </span>
                    <span>seen {since(job.last_seen)}</span>
                  </div>
                </div>

                <MatchBadge
                  score={job.score}
                  bands={bands}
                  pending={!metaReady}
                />

                {job.resume_pdf ? (
                  <Button asChild variant="outline" size="sm">
                    <a href={api.fileUrl(job.resume_pdf)}>
                      <FileDown className="size-4" />
                      Resume
                    </a>
                  </Button>
                ) : (
                  <Badge variant="secondary" className="font-normal">
                    No resume
                  </Badge>
                )}

                <Select
                  value={job.status}
                  onValueChange={(v) => move(job, v)}
                  disabled={!metaReady}
                >
                  <SelectTrigger size="sm" className="w-28">
                    <SelectValue placeholder="…" />
                  </SelectTrigger>
                  <SelectContent>
                    {statuses.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* R62 hides jobs the gates would reject, and requires the screen to
          say how many — a filter that removes things without saying so is
          the shape this project keeps regretting. The count follows the
          current filters, so it answers "what am I not seeing *here*". */}
      {(hidden > 0 || showIneligible) && (
        <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
          <EyeOff className="size-4 shrink-0" />
          <span>
            {showIneligible
              ? 'Showing jobs that do not match your profile.'
              : `${hidden} more ${
                  hidden === 1 ? 'job does' : 'jobs do'
                } not match your profile and ${
                  hidden === 1 ? 'is' : 'are'
                } hidden.`}
          </span>
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0"
            onClick={() => change(setShowIneligible)(!showIneligible)}
          >
            {showIneligible ? 'Hide them' : 'Show them'}
          </Button>
        </div>
      )}

      {/* The total travels with the page. A page cap with no total looks
          exactly like running out of jobs (R65). */}
      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span className="tabular-nums">
          {loading && <Loader2 className="mr-2 inline size-3.5 animate-spin" />}
          {total > 0 ? `${first}–${last} of ${total}` : 'Nothing to show'}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft className="size-4" />
            Previous
          </Button>
          <span className="tabular-nums">
            Page {page + 1} of {pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
