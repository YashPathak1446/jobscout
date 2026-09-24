import { ExternalLink, KeyRound } from 'lucide-react'

import { BackendPanel } from '@/components/BackendPanel'
import { Button } from '@/components/ui/button'
import type { Session } from '@/lib/api'

/**
 * The key page (Q58, R117). First, because the resume step's import is the
 * first thing a key is used for: a PDF or Word upload is read by Gemini only
 * when the request carries a key (R113).
 *
 * The wording is the product's claim about what a key does, so it has to be
 * exactly true. A key rewrites bullets and reads imports; it does not change
 * matching. The request's key never reaches embeddings, and a hosted instance
 * scores on the local model whatever the key (R113). Saying "add a key for
 * better matches" would be false on both modes.
 */
export function KeyStep({
  mode,
  apiKey,
  persisted,
  onKey,
  onForget,
  onContinue,
}: {
  mode: Session['mode']
  apiKey: string
  /** Whether this browser let the key be saved. False: memory only. */
  persisted: boolean
  onKey: (key: string) => void
  onForget: () => void
  onContinue: () => void
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">
          Your Gemini key (optional)
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          A key lets Google Gemini rewrite your bullets for each job.
        </p>
      </div>

      <section className="space-y-1.5 text-sm">
        <p className="font-medium">Getting a free key</p>
        <p className="text-muted-foreground">
          Open{' '}
          <a
            href="https://aistudio.google.com/app/apikey"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-4"
          >
            Google AI Studio
            <ExternalLink className="size-3" />
          </a>
          , sign in with a Google account, choose <strong>Create API key</strong>
          , and paste the key below.
        </p>
      </section>

      <section className="space-y-1.5 text-sm">
        <p className="font-medium">Without a key</p>
        <p className="text-muted-foreground">
          Everything works except rewriting your bullets. Discovery, scoring,
          component selection and PDFs all run, and your bullets are used
          exactly as you wrote them. A key does not change which jobs you see
          or how they are scored.
        </p>
        {/* Q58: without a model, two postings' resumes can look identical,
            and a person who is not told why concludes the tool does nothing. */}
        <p className="text-muted-foreground">
          So without a key, the resume for one job differs from the next only
          in which of your entries and bullets fit the page and the order of
          your skills. A PDF or Word resume is read by a simpler pattern
          reader, and you correct what it misses before anything is saved.
        </p>
      </section>

      <BackendPanel mode={mode} apiKey={apiKey} onKey={onKey} />

      <section className="space-y-2 text-sm">
        <p className="flex items-center gap-1.5 font-medium">
          <KeyRound className="size-4" />
          Where your key goes
        </p>
        {/* When storage is refused, "saved in this browser" would be false,
            and this page says only what it did. */}
        {persisted ? (
          <p className="text-muted-foreground">
            Your key is saved in this browser only and is sent to Google only
            with your own requests. The server never stores it.
          </p>
        ) : (
          <p className="text-muted-foreground">
            This browser is not letting JobScout save anything, so your key
            lasts only until you reload or close this page. It is sent to
            Google only with your own requests, and the server never stores
            it.
          </p>
        )}
        {/* Worded against Google's Gemini API Additional Terms, "Unpaid
            Services", as read 2026-09-24: content submitted on the free
            tier is used to improve Google's products, and human reviewers
            may read it. Re-read the terms before changing this. */}
        <p className="text-muted-foreground">
          On the free tier, Google may use what you send it (here, your
          resume and the job descriptions) to improve its products, and
          people at Google may read it. See{' '}
          <a
            href="https://ai.google.dev/gemini-api/terms"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-4"
          >
            Google's Gemini API terms
            <ExternalLink className="size-3" />
          </a>
          .
        </p>
        {apiKey && (
          <Button variant="outline" size="sm" onClick={onForget}>
            Forget key
          </Button>
        )}
      </section>

      <div className="flex gap-2 border-t pt-4">
        <Button onClick={onContinue}>
          {apiKey ? 'Continue' : 'Continue without a key'}
        </Button>
      </div>
    </div>
  )
}
