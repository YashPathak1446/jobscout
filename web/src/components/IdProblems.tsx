import { AlertTriangle } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

/**
 * Which of a profile's match rules do not name exactly one component.
 *
 * The failure this exists for is silence. A rule keyed to a component the
 * resume no longer has is skipped at scoring time and looks identical to a
 * rule that simply never matched; a rule keyed to an ID that two components
 * share fires on whichever the parser reached first (Q34). Neither produces an
 * error anywhere, so without this the only symptom is a resume that quietly
 * left something out.
 *
 * One component for both call sites — the wizard's build summary and the
 * tuning screen — rather than a block of JSX in each. A warning written twice
 * is a warning improved once, which is this codebase's most repeated bug
 * (R69, R70) wearing a frontend.
 *
 * **`undefined` is not "no problems".** It is a profile written before the
 * check existed, or one whose check could not run, and it gets a muted line
 * rather than silence — because silence here is indistinguishable from a clean
 * result, which is the thing being fixed.
 */
export function IdProblems({ problems }: { problems?: string[] }) {
  if (problems === undefined) {
    return (
      <p className="text-sm text-muted-foreground">
        Match rules were not checked for this profile.
      </p>
    )
  }

  if (problems.length === 0) return null

  return (
    <Alert>
      <AlertTriangle />
      <AlertTitle>
        {problems.length} match {problems.length === 1 ? 'rule does' : 'rules do'}{' '}
        not do what {problems.length === 1 ? 'it says' : 'they say'}
      </AlertTitle>
      <AlertDescription>
        <p>
          These are kept, not deleted. Fix or remove them below — until then
          they are skipped, or applied to the wrong piece of your resume.
        </p>
        <ul className="mt-1 list-disc space-y-1 pl-4">
          {problems.map((problem) => (
            <li key={problem} className="font-mono text-xs">
              {problem}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}
