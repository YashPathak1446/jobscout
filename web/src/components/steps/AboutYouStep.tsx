import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { BackendPanel } from '@/components/BackendPanel'
import { api } from '@/lib/api'

// Radix forbids a SelectItem with an empty value, and passing `undefined` as
// the Select's value silently makes it *uncontrolled* — it then manages its
// own selection, flips back to controlled the moment state updates, and the
// displayed value never catches up. So "not answered yet" gets a name.
const UNANSWERED = '__unanswered__'

const VISA_OPTIONS = [
  'US Citizen',
  'Green Card',
  'F1 OPT',
  'F1 CPT',
  'H1B',
  'Other / prefer not to say',
]

type Personal = {
  location: string
  visa_status: string
  holds_security_clearance: boolean
}

/**
 * Step two: the two things a resume cannot state.
 *
 * An address line says where you live, not where you are allowed to work, and
 * a resume never says whether a clearance is active today — which is the
 * difference between two postings that read almost identically (R56).
 *
 * The form is seeded from the stored profile, never from its own defaults.
 * Saving a blank form over stored answers is a silent revert, and this wizard
 * has done that before.
 */
export function AboutYouStep({
  profile,
  apiKey,
  onKey,
  onBack,
  onContinue,
}: {
  profile: string
  apiKey: string
  onKey: (key: string) => void
  onBack: () => void
  onContinue: () => void
}) {
  const [stored, setStored] = useState<Personal | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .profile(profile)
      .then((p) => setStored(p.personal as Personal))
      .catch((e: Error) => {
        setError(e.message)
        setStored({ location: '', visa_status: '', holds_security_clearance: false })
      })
  }, [profile])

  // null is "still loading the profile", and rendering it as an empty form
  // would invite someone to save blanks over their own answers.
  if (stored === null) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-10 w-full max-w-md" />
        <Skeleton className="h-10 w-full max-w-md" />
      </div>
    )
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await api.updateProfile(profile, {
        personal_info: {
          location: stored!.location,
          visa_status: stored!.visa_status,
          us_citizen: stored!.visa_status === 'US Citizen',
          permanent_resident: stored!.visa_status === 'Green Card',
          holds_security_clearance: stored!.holds_security_clearance,
        },
      })
      onContinue()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">About you</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Things a resume cannot reliably tell us. An address line says where
          you live, not where you are allowed to work.
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="location">Where are you based?</Label>
        <Input
          id="location"
          value={stored.location}
          onChange={(e) => setStored({ ...stored, location: e.target.value })}
          placeholder="City, State"
          className="max-w-md"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="visa">Work authorisation</Label>
        <Select
          value={stored.visa_status || UNANSWERED}
          onValueChange={(v) =>
            setStored({ ...stored, visa_status: v === UNANSWERED ? '' : v })
          }
        >
          <SelectTrigger id="visa" className="max-w-md">
            <SelectValue placeholder="Select one" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNANSWERED} disabled>
              Select one
            </SelectItem>
            {VISA_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Asked rather than assumed. A posting that requires an active
          clearance screens out everyone else, so those are filtered out
          rather than shown and wasted on (R56). */}
      <div className="flex items-start gap-2">
        <Checkbox
          id="clearance"
          checked={stored.holds_security_clearance}
          onCheckedChange={(v) =>
            setStored({ ...stored, holds_security_clearance: v === true })
          }
          className="mt-0.5"
        />
        <div className="space-y-1">
          <Label htmlFor="clearance">
            I currently hold an active security clearance
          </Label>
          <p className="text-sm text-muted-foreground">
            Leave this unchecked unless a clearance is active today.
          </p>
        </div>
      </div>

      <BackendPanel apiKey={apiKey} onKey={onKey} />

      {error && (
        <p className="text-sm text-destructive">Could not save: {error}</p>
      )}

      <div className="flex gap-2 border-t pt-4">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        {/* Both, not just location. Work authorisation decides whether
            ITAR-restricted and clearance postings are shown at all, and the
            Streamlit form defaulted the select to its first option — which
            silently asserted US citizenship for anyone who did not touch it.
            An unanswered question stays unanswered. */}
        <Button
          onClick={save}
          disabled={!stored.location.trim() || !stored.visa_status || saving}
        >
          {saving ? 'Saving…' : 'Continue'}
        </Button>
      </div>
    </div>
  )
}
