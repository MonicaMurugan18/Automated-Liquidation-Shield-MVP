import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { ShieldProvider } from './state/ShieldContext.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <ShieldProvider>
        <App />
      </ShieldProvider>
    </BrowserRouter>
  </StrictMode>,
)
