/**
 * The pipeline, as seen from the browser.
 *
 * Every call here maps to one endpoint in `api/main.py`, which maps to one
 * function on `agents/orchestrator.py`. Nothing in this file filters, ranks or
 * scores — the same rule `app.py` and the API layer are held to, for the same
 * reason: two views of one pipeline stay interchangeable only while neither of
 * them knows anything the other does not.
 */

export type Job = {
  url: string
  job_id: string
  title: string
  company: string
  location: string
  source: string
  score: number | null
  status: string
  first_seen: string | null
  last_seen: string | null
  scored_at: string | null
  resume_tex: string | null
  resume_pdf: string | null
  run_date: string | null
  /** What the gate made of this job for your profile (A4). `null` is a row
   *  no gate has judged yet — not a pass: the store shows it, and the badge
   *  says nothing about it. Mirrors `job_filter.VERDICTS`. */
  gate_verdict: 'shown' | 'hidden' | 'undecidable' | null
  /** Why, for `hidden` and `undecidable`. An undecidable job carries one
   *  too, so a set reason is not "rules you out" — branch on the verdict. */
  gate_reason: string | null
  has_jd: boolean
  full_jd?: string
}

/** Quartiles of *your* scored jobs. `n` is how many the bands rest on. */
export type Bands = {
  low: number
  typical: number
  strong: number
  high: number
  n: number
}

export type Facet = { value: string; count: number }
export type Filters = { companies: Facet[]; sources: Facet[] }

export type Stats = {
  total: number
  scored: number
  with_resume: number
  by_status: Record<string, number>
}

export type SelectionEntry = {
  id?: string
  sentence?: string
  [key: string]: unknown
}

export type JobDetail = {
  job: Job
  selection: { picked?: SelectionEntry[] } | null
  history: { status: string; changed_at: string }[]
}

export type ResumeSchema = {
  contact?: Record<string, string>
  education?: Record<string, string>[]
  experiences?: Record<string, unknown>[]
  projects?: Record<string, unknown>[]
  skills?: Record<string, string>
  /** Section text the pattern reader could not split into entries. Present
   *  only when no model was available; showing it is the difference between
   *  "we found one job" and "we found one job and could not read this part". */
  _unparsed?: Record<string, string[]>
}

export type Extraction =
  | { kind: 'latex'; filename: string }
  | { kind: 'extracted'; filename: string; schema: ResumeSchema }

export type ProfileSummary = {
  profile_path: string
  derived: Record<string, string>
  needs_you: string[]
  counts: Record<string, number>
  backup_path?: string | null
  // Which saved rules name no component, or more than one. Optional because a
  // profile written before the check existed has no answer, and `undefined`
  // has to stay distinguishable from `[]` all the way to the screen — see
  // `IdProblems`.
  id_problems?: string[]
}

/** The tuning screen's data: the components, and what is wrong with them. */
export type ComponentRules = {
  experiences: unknown[]
  projects: unknown[]
  id_problems?: string[]
}

export type Backend = {
  backend: string
  forced: boolean
  description: string
  available: Record<string, boolean>
}

export type RunStatus = {
  id: string
  profile: string
  state: 'running' | 'finished' | 'failed'
  stage: string
  done: number
  total: number
  message: string | null
  error: string | null
  output_dir: string | null
  result: {
    discovered: number
    enriched: number
    analysed: number
    generated: number
    valid: number
    threshold: number | null
    degraded: string[]
  } | null
}

export type BoardQuery = {
  status?: string
  min_score?: number
  has_resume?: boolean
  company?: string
  source?: string
  search?: string
  sort?: string
  limit?: number
  offset?: number
  include_ineligible?: boolean
}

async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value))
    }
  }
  const suffix = query.toString() ? `?${query}` : ''
  const response = await fetch(`/api${path}${suffix}`)
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`)
  }
  return response.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return send<T>('POST', path, body)
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  return send<T>('PATCH', path, body)
}

async function put<T>(path: string, body: unknown): Promise<T> {
  return send<T>('PUT', path, body)
}

async function send<T>(method: string, path: string, body: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () =>
    get<{
      profiles: string[]
      backend: { backend: string; forced: boolean; description: string }
      pdflatex: boolean
      statuses: string[]
      sorts: string[]
    }>('/health'),

  board: (query: BoardQuery) =>
    get<{
      jobs: Job[]
      total: number
      /** Jobs the gates hide under the current filters (R62). */
      hidden: number
      /** Shown jobs the gate could not decide, same filters (A4). */
      unconfirmed: number
      offset: number
      limit: number
    }>(
      '/board',
      query as Record<string, unknown>,
    ),

  stats: () => get<Stats>('/board/stats'),
  filters: () => get<Filters>('/board/filters'),
  bands: () => get<Bands>('/board/bands'),
  job: (url: string) => get<JobDetail>('/job', { url }),
  setStatus: (url: string, status: string) =>
    post<{ url: string; status: string }>('/job/status', { url, status }),
  fileUrl: (path: string) => `/api/file?path=${encodeURIComponent(path)}`,

  extractResume: async (file: File): Promise<Extraction> => {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch('/api/resume/extract', { method: 'POST', body: form })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail ?? `Upload failed (${response.status})`)
    }
    return response.json()
  },

  createProfile: async (body: {
    name: string
    filename: string
    force?: boolean
    schema_?: ResumeSchema | null
  }): Promise<ProfileSummary> => {
    const response = await fetch('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      // 409 is "that name is taken", which the screen turns into a question
      // rather than an error: rebuilding discards rules tuned by hand (R30).
      const error = new Error(payload.detail ?? `Failed (${response.status})`)
      ;(error as Error & { status?: number }).status = response.status
      throw error
    }
    return response.json()
  },

  levels: (years: number | null) =>
    // years omitted, not zeroed: an unanswered profile derives nothing, and
    // zero years is the claim "new graduate".
    get<{ all: string[]; derived: string[] }>(
      '/levels',
      years === null ? {} : { years },
    ),

  backend: (key: string) =>
    // POST, not GET: a key in a query string is logged, cached and kept in
    // browser history.
    post<Backend>('/backend', { key }),

  updateProfile: (name: string, updates: Record<string, unknown>) =>
    // PATCH, because the server merges nested sections rather than replacing
    // them. The preferences screen saves two of `locations`' seven fields,
    // and a wholesale replace once left a profile that would not load (R30).
    patch<{ saved: string }>(`/profile/${encodeURIComponent(name)}`, { updates }),

  startRun: (body: {
    profile: string
    api_key: string
    /** Which rung rewrites bullets. `''` means "no opinion" — the profile or
     *  detection decides — which is not the same as 'auto', an opinion that
     *  detection should decide. */
    backend: string
    max_jobs: number
    max_resumes: number
    generate_pdf: boolean
  }) => post<{ run_id: string }>('/run', body),

  runStatus: (id: string) =>
    get<RunStatus>(`/run/${encodeURIComponent(id)}`),

  activeRuns: () => get<{ active: RunStatus[] }>('/run'),

  writeComponents: (
    name: string,
    body: {
      importance: Record<string, string>
      triggers: Record<string, string[]>
      always: Record<string, boolean>
      never: Record<string, boolean>
    },
  ) =>
    put<{ saved: string; id_problems?: string[] }>(
      `/profile/${encodeURIComponent(name)}/components`,
      body,
    ),

  profile: (name: string) =>
    get<{
      personal: Record<string, unknown>
      preferences: Record<string, unknown>
      components: ComponentRules
    }>(`/profile/${encodeURIComponent(name)}`),
}

/**
 * Where a score sits among your own, or null when nothing is known.
 *
 * Null is not zero and not "weak". An unscored job is one analysis never
 * reached — discovery finds thousands and analysis looks at the top slice —
 * and rendering that as a bad match would be the mistake this codebase keeps
 * making in other places: treating absence as a low value rather than as
 * absence.
 */
export function band(score: number | null, bands: Bands | null) {
  if (score === null || score === undefined) return null
  if (!bands || !bands.n) return null
  if (score >= bands.strong) return 'strong' as const
  if (score >= bands.typical) return 'typical' as const
  return 'weak' as const
}
