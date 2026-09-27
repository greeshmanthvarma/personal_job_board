import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'
import App from './Board.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
