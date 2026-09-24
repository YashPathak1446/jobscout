import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'

import { Board } from '@/components/Board'
import { SignIn } from '@/components/SignIn'
import { STEPS, Wizard } from '@/components/Wizard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { api, SIGNED_OUT, type Session } from '@/lib/api'

export default function App() {
  // `null` until the server has said which mode it is in. Not "signed out"
  // and not "local": rendering either before the answer would flash the
  // wrong screen, and a sign-in form on a laptop is a claim about the app.
  const [session, setSession] = useState<Session | null>(null)
  const [sessionError, setSessionError] = useState<string | null>(null)
  // 'home' is "signed in, not yet known whether this account has a board"
  // (R122). Showing the wizard for that beat would tell a returning user
  // their data is gone; showing the board would tell a new one they have
  // one. It resolves to 'board' or 'setup' as soon as health answers.
  const [view, setView] = useState<'signin' | 'home' | 'setup' | 'board'>('setup')
  const [profile, setProfile] = useState<string | null>(null)
  // The wizard's opening step: undefined is its first, and the board's empty
  // state asks for Run (R123).
  const [wizardStep, setWizardStep] = useState<number | undefined>(undefined)

  // Where a signed-in hosted account starts (R122): its board when it has a
  // profile, the wizard only when it has none. Signing in used to land every
  // account on the wizard's first step, empty, with no way to its board, so
  // a returning friend's jobs, resumes and marks looked gone.
  function openHome() {
    setView('home')
    api
      .health()
      .then((h) => {
        if (h.profiles.length > 0) {
          setProfile(h.profiles[0])
          setView('board')
        } else {
          setView('setup')
        }
      })
      // Could not tell: the wizard, which works either way (its resume step
      // offers an existing profile), rather than a board that may be empty.
      .catch(() => setView('setup'))
  }

  useEffect(() => {
    api
      .session()
      .then((s) => {
        setSession(s)
        if (s.mode === 'hosted' && s.user === null) setView('signin')
        else if (s.mode === 'hosted') openHome()
      })
      .catch((e: Error) => setSessionError(e.message))
  }, [])

  // Any call answered 401 means the session ended mid-use. What was on
  // screen belonged to whoever was signed in, so it goes with them.
  useEffect(() => {
    const signedOut = () => {
      setSession((s) => (s ? { ...s, user: null } : s))
      setProfile(null)
      setView('signin')
    }
    window.addEventListener(SIGNED_OUT, signedOut)
    return () => window.removeEventListener(SIGNED_OUT, signedOut)
  }, [])

  if (session === null) {
    return (
      <div className="mx-auto max-w-md px-6 pt-24">
        {sessionError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not reach JobScout</AlertTitle>
            <AlertDescription>{sessionError}</AlertDescription>
          </Alert>
        ) : (
          <p className="text-sm text-muted-foreground">Connecting…</p>
        )}
      </div>
    )
  }

  if (view === 'home') {
    return (
      <div className="mx-auto max-w-md px-6 pt-24">
        <p className="text-sm text-muted-foreground">Opening your jobs…</p>
      </div>
    )
  }

  if (view === 'signin') {
    return (
      <div className="min-h-screen bg-background">
        <SignIn
          onSignedIn={(email) => {
            setSession({ mode: 'hosted', user: { email } })
            setProfile(null)
            openHome()
          }}
        />
      </div>
    )
  }

  const signOut = () => {
    api
      .signOut()
      .catch(() => undefined)
      .finally(() => window.dispatchEvent(new Event(SIGNED_OUT)))
  }

  return (
    <div className="min-h-screen bg-background">
      {session.user && (
        <div className="mx-auto flex w-full max-w-6xl items-center justify-end gap-3 px-6 pt-4 text-sm text-muted-foreground">
          <span>
            Signed in as <strong className="font-medium">{session.user.email}</strong>
          </span>
          <Button variant="ghost" size="sm" onClick={signOut}>
            Sign out
          </Button>
        </div>
      )}
      {view === 'board' ? (
        <>
          <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-6 pt-6">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setWizardStep(undefined)
                setView('setup')
              }}
            >
              <ArrowLeft className="size-4" />
              Edit setup
            </Button>
            {profile && (
              <span className="text-sm text-muted-foreground">
                Profile: <strong className="font-medium">{profile}</strong>
              </span>
            )}
          </div>
          <Board
            onStartRun={
              profile
                ? () => {
                    setWizardStep(STEPS.indexOf('Run'))
                    setView('setup')
                  }
                : undefined
            }
          />
        </>
      ) : (
        <Wizard
          mode={session.mode}
          profile={profile}
          onProfile={setProfile}
          onOpenBoard={() => setView('board')}
          initialStep={wizardStep}
        />
      )}
    </div>
  )
}
