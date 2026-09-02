import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { AppProvider } from './store.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* Outside AppProvider: the store reads useNavigate/useLocation to make
        the URL the source of truth for which view is open. */}
    <BrowserRouter>
      <AppProvider>
        <App />
      </AppProvider>
    </BrowserRouter>
  </StrictMode>,
)
