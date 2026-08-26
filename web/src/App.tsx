import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'

import { Board } from '@/components/Board'
import { Wizard } from '@/components/Wizard'
import { Button } from '@/components/ui/button'

export default function App() {
  const [view, setView] = useState<'setup' | 'board'>('setup')
  const [profile, setProfile] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-background">
      {view === 'board' ? (
        <>
          <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-6 pt-6">
            <Button variant="ghost" size="sm" onClick={() => setView('setup')}>
              <ArrowLeft className="size-4" />
              Back to setup
            </Button>
            {profile && (
              <span className="text-sm text-muted-foreground">
                Profile: <strong className="font-medium">{profile}</strong>
              </span>
            )}
          </div>
          <Board />
        </>
      ) : (
        <Wizard
          profile={profile}
          onProfile={setProfile}
          onOpenBoard={() => setView('board')}
        />
      )}
    </div>
  )
}
