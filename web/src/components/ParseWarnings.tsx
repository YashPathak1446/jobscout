import { AlertTriangle } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

/**
 * Which lines of the resume the parser could not read (R112).
 *
 * It used to drop them in silence: a skills category holding `C#` vanished
 * from every tailored resume, with nothing anywhere to say so. One component
 * for both call sites (the build summary and the tuning screen), for the
 * same reason as `IdProblems`.
 *
 * Absent or empty renders nothing. Unlike `IdProblems`, there is no "not
 * checked" state to show: the parser always runs to build either screen.
 */
export function ParseWarnings({ warnings }: { warnings?: string[] }) {
  if (!warnings || warnings.length === 0) return null

  return (
    <Alert>
      <AlertTriangle />
      <AlertTitle>
        {warnings.length} {warnings.length === 1 ? 'part' : 'parts'} of your
        resume could not be read
      </AlertTitle>
      <AlertDescription>
        <p>
          They will not appear in tailored resumes until the resume is fixed.
        </p>
        <ul className="mt-1 list-disc space-y-1 pl-4">
          {warnings.map((warning) => (
            <li key={warning} className="text-xs">
              {warning}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}
