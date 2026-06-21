---
name: Post-merge env breakage (Sonder)
description: After a task merge, the app can be broken because deps aren't installed and old workflow processes linger.
---

# Symptom
After a task agent's work is merged into main, the running app can be broken even though the code is correct.

# Root causes seen
- **No post-merge setup hook configured** (`.replit` HOOK_NOT_FOUND). So the platform does NOT auto-install the merged task's new dependencies in the main environment.
  - Backend: `fastapi`/`uvicorn` present in `requirements.txt` but not installed → `ModuleNotFoundError: No module named 'fastapi'`.
  - Frontend: `frontend/node_modules` missing → Vite workflow fails to start.
- **Stale workflow process from the pre-merge stack lingers.** After migrating Streamlit→React, an old `streamlit run app.py --server.port 5000` process kept holding port 5000, so the new Vite workflow could not bind / the wrong app was served (title "Streamlit" instead of "Sonder"). Fix: `ps aux | grep streamlit`, `kill -9 <pid>`, then restart "Start application".

# How to apply
After any merge that changes the stack or deps: install backend deps (`installLanguagePackages` python) AND frontend deps, kill leftover processes on port 5000, then restart both "Backend API" and "Start application".

**Why:** the post-merge setup script isn't configured, so none of this happens automatically.

# Install gotcha
`npm install` in `frontend/` exceeds the 2-min bash limit and detached bg procs get reaped. Run it as a one-shot console workflow (`configureWorkflow` autoStart, no waitForPort) and poll for `frontend/node_modules/.bin/vite`. Interrupted/concurrent installs corrupt `node_modules` (ENOTEMPTY on caniuse-lite) → `rm -rf node_modules package-lock.json` and reinstall clean.
