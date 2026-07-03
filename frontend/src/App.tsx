import { Home } from "@/components/Home"
import { Toaster } from "@/components/ui/toast"
import { AuthProvider, useAuth } from "@/context/AuthContext"
import { Auth } from "@/pages/Auth"

function AppContent() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="flex min-h-svh items-center justify-center">Loading...</div>
  }

  return user ? <Home /> : <Auth />
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
      <Toaster />
    </AuthProvider>
  )
}

export default App
