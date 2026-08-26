import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, PenLine } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api, type Backend } from '@/lib/api'

const HEADLINE: Record<string, string> = {
  gemini: 'Bullets will be rewritten by Google Gemini.',
  openai: 'Bullets will be rewritten through your OpenAI-compatible key.',
  ollama:
    'Ollama is running locally and nothing leaves this machine — but on ' +
    'llama3.1:8b its rewrites were rejected and your own bullets were used ' +
    'instead. Expect the same output as no model at all.',
  none:
    'Jobs will be scored and the right components picked for each one, but ' +
    'your bullets will be used exactly as you wrote them.',
}

/**
 * What will rewrite bullets, said out loud before anyone runs anything.
 *
 * Detected and explained, not asked (R33): output quality does differ between
 * the rungs, and most people cannot answer "which model backend?" before they
 * have seen the tool work once. The key is optional — discovery, scoring and
 * component selection all work with nothing configured.
 */
export function BackendPanel({
  apiKey,
  onKey,
}: {
  apiKey: string
  onKey: (key: string) => void
}) {
  const [backend, setBackend] = useState<Backend | null>(null)
  const debounce = useRef<number | undefined>(undefined)

  useEffect(() => {
    // Asked when the answer could have changed, not per keystroke: detection
    // asks the network whether Ollama is up.
    window.clearTimeout(debounce.current)
    debounce.current = window.setTimeout(() => {
      api.backend(apiKey).then(setBackend).catch(() => setBackend(null))
    }, 400)
    return () => window.clearTimeout(debounce.current)
  }, [apiKey])

  const chosen = backend?.backend
  const none = chosen === 'none'

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor="api-key">Google Gemini API key (optional)</Label>
        <Input
          id="api-key"
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => onKey(e.target.value)}
          className="max-w-md"
        />
        <p className="text-sm text-muted-foreground">
          Stays on this machine and is passed straight to the pipeline. Free at
          aistudio.google.com/app/apikey. Without one, JobScout still finds and
          scores jobs and builds a resume per posting.
        </p>
      </div>

      {/* backend === null is "still detecting", which is not "no model". The
          two say opposite things and look identical if you render the first
          as the second. */}
      {backend === null ? (
        <div className="space-y-2 rounded-lg border p-4">
          <Skeleton className="h-4 w-72" />
          <Skeleton className="h-3 w-full max-w-md" />
        </div>
      ) : (
        <Alert>
          {none ? (
            <PenLine className="size-4" />
          ) : (
            <CheckCircle2 className="size-4" />
          )}
          <AlertTitle>{HEADLINE[chosen ?? ''] ?? backend.description}</AlertTitle>
          <AlertDescription className="space-y-2">
            {none ? (
              <p>
                To get tailored bullets, add a Gemini key above, or run{' '}
                <strong>Ollama</strong> locally with any model pulled — free,
                and nothing leaves this machine. The Ollama path is not yet
                measured, so expect rougher bullets than this project's notes
                describe.
              </p>
            ) : (
              <p>{backend.description}</p>
            )}
            {backend.forced && (
              <p>
                <code className="rounded bg-muted px-1.5 py-0.5">
                  LLM_BACKEND
                </code>{' '}
                in config.py pins this to <strong>{chosen}</strong>, so
                detection is not choosing it.
              </p>
            )}
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
