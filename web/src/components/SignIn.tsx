import { useState, type FormEvent } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'

/**
 * The hosted instance's front door (A5). Invite-only: a friend either signs in
 * or redeems the code they were sent, which creates the account and signs in
 * in one step. There is no reset link because there is no reset flow — the
 * operator's admin script is it, and the screen says so rather than offering
 * a button that goes nowhere.
 */
export function SignIn({ onSignedIn }: { onSignedIn: (email: string) => void }) {
  const [redeeming, setRedeeming] = useState(false)
  const [code, setCode] = useState('')
  const [email, setEmail] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (redeeming) {
        await api.redeemInvite(code.trim(), email, passphrase)
      } else {
        await api.signIn(email, passphrase)
      }
      onSignedIn(email.trim().toLowerCase())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-md items-center px-6">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>{redeeming ? 'Redeem your invite' : 'Sign in to JobScout'}</CardTitle>
          <CardDescription>
            {redeeming
              ? 'Paste the code you were sent, then choose the email and passphrase you will sign in with.'
              : 'JobScout is invite-only while it is a pilot.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            {redeeming && (
              <div className="flex flex-col gap-2">
                <Label htmlFor="invite-code">Invite code</Label>
                <Input
                  id="invite-code"
                  autoComplete="off"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                />
              </div>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="passphrase">Passphrase</Label>
              <Input
                id="passphrase"
                type="password"
                autoComplete={redeeming ? 'new-password' : 'current-password'}
                minLength={redeeming ? 12 : undefined}
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                required
              />
              {redeeming && (
                <p className="text-xs text-muted-foreground">
                  At least 12 characters. There is no reset link — if you lose
                  it, ask whoever invited you.
                </p>
              )}
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Button type="submit" disabled={busy}>
              {busy ? 'Working…' : redeeming ? 'Create account' : 'Sign in'}
            </Button>
            <Button
              type="button"
              variant="link"
              onClick={() => {
                setRedeeming(!redeeming)
                setError(null)
              }}
            >
              {redeeming ? 'I already have an account' : 'I have an invite code'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
