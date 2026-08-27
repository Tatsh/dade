import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import './site.scss';

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

// A relative script, so it resolves against the page's base and its scope is wherever the site is
// served from. The service worker is what makes the site installable and lets a tune already looked
// at open again offline.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('sw.js');
  });
}
