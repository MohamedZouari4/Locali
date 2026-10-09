// Root React component: the chat screen, with the startup intro over it while the app starts.
// The chat screen mounts once the local services answer, and stays inert until the intro is gone.

import { useCallback, useState } from 'react'
import { ChatScreen } from './components/Chat/ChatScreen'
import { StartupIntro } from './components/Intro/StartupIntro'
import { useServicesReady } from './hooks/useServicesReady'

function App() {
  const servicesReady = useServicesReady()
  const [introDone, setIntroDone] = useState(false)
  const finishIntro = useCallback(() => setIntroDone(true), [])

  return (
    <>
      <div className="app-root" inert={!introDone}>
        {servicesReady && <ChatScreen />}
      </div>
      {!introDone && <StartupIntro ready={servicesReady} onDone={finishIntro} />}
    </>
  )
}

export default App
