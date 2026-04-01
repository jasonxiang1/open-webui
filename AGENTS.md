# AGENTS.md

## Purpose
This repository is a full-stack Open WebUI checkout. Future coding agents should use this file as the primary local guide for feature work, debugging, and safe edits in this repo.

This codebase is not a small demo app. It is a production-style monorepo with:
- a SvelteKit frontend in `src/`
- a FastAPI backend in `backend/open_webui/`
- shared runtime assumptions around auth, notes, models, tools, retrieval, audio, terminals, and sockets
- both local-dev and Docker workflows

When in doubt, prefer integrating with existing APIs, stores, routers, and UI primitives instead of adding parallel systems.

## Quick Facts
- Frontend stack: SvelteKit 2, Svelte 5, Vite 5, Tailwind 4
- Backend stack: FastAPI, SQLAlchemy, Alembic, Redis-capable session/task support
- Python version: `>=3.11,<3.13`
- Node version: `>=18.13.0 <=22.x.x`
- Local frontend dev port: `5173`
- Local backend dev port: `8080`
- Default local DB: `backend/data/webui.db`

## Repo Layout
- `src/`
  - SvelteKit app routes
  - `src/lib/apis/` mirrors backend API domains
  - `src/lib/components/` contains reusable UI, chat, notes, workspace, admin, and layout components
  - `src/lib/stores/` contains global app state
- `backend/open_webui/`
  - `main.py` assembles the FastAPI app and mounts routers
  - `routers/` contains API routes by domain
  - `models/` contains DB-facing domain logic
  - `retrieval/` contains loaders, vector DB integrations, web retrieval, embeddings/reranking logic
  - `socket/` contains websocket/event behavior
  - `config.py` and `env.py` contain startup-time configuration and many side effects
- `static/`
  - frontend static assets source of truth in local dev
  - also contains `pyodide/` assets generated/fetched by frontend scripts
- `backend/open_webui/static/`
  - backend-served static directory
  - important: startup code mutates this directory
- `cypress/`
  - existing browser E2E coverage

## Architecture Rules Of Thumb

### 1. Frontend and backend are domain-symmetric
For many features there is:
- a backend router in `backend/open_webui/routers/<domain>.py`
- a frontend API client in `src/lib/apis/<domain>/index.ts`
- one or more route/pages/components consuming that API

Before adding a new endpoint, check if the domain already exists on both sides.

Examples:
- notes: `backend/open_webui/routers/notes.py` and `src/lib/apis/notes/index.ts`
- audio: `backend/open_webui/routers/audio.py` and `src/lib/apis/audio/index.ts`
- models: `backend/open_webui/routers/models.py` and `src/lib/apis/models/index.ts`

### 2. Most new user features should be built on existing primitives
Prefer reusing:
- existing notes APIs instead of creating sidecar storage
- existing STT/TTS routes instead of introducing duplicate audio endpoints
- existing modal/drawer components instead of one-off overlays
- existing stores and layout conventions

### 3. App shell matters
The main authenticated app shell lives under:
- `src/routes/(app)/+layout.svelte`
- `src/lib/components/layout/Sidebar.svelte`

Fixed-position UI inside child pages must account for:
- the narrow app sidebar
- the wide collapsible sidebar
- mobile-vs-desktop layout differences

If a page uses `position: absolute` or `fixed`, verify it is not hidden behind the sidebars.

## Local Development

### Frontend
From repo root:

```bash
nvm use v22.17.1
npm install
npm run dev
```

Canonical frontend run command:

```bash
nvm use v22.17.1 && npm run dev
```

Important:
- `npm run dev` runs `scripts/prepare-pyodide.js` first
- that script updates `static/pyodide/*` and can modify generated lock/artifact files
- `package-lock.json` may change after reinstalling dependencies

### Backend
From repo root, after activating a Python 3.11 environment:

```bash
pip install -r backend/requirements.txt
cd backend
sh dev.sh
```

Canonical backend run command:

```bash
cd backend/ && sh dev.sh
```

`backend/dev.sh` starts uvicorn with reload on port `8080` and allows `http://localhost:5173`.

If running backend directly from source, missing Python packages are a common issue. `starsessions[redis]` is required by startup.

## Required Run-And-Debug Loop
For local feature work, agents should treat these as the baseline execution commands:

Frontend:

```bash
nvm use v22.17.1 && npm run dev
```

Backend:

```bash
cd backend/ && sh dev.sh
```

If either command fails:
- do not stop at the first error
- debug the actual failure in the local environment
- apply the minimum necessary fix
- rerun the command
- continue iterating until the command runs cleanly or you hit a real external blocker

Typical examples:
- missing Python package in the active backend environment
- stale or mismatched `node_modules`
- npm cache permission issue
- missing local asset or generated artifact
- environment-variable or path issue in dev mode

Agents should prefer fixing root causes over adding broad workarounds.

## Generated And Dangerous Paths

### `backend/open_webui/static` is not safe to treat as hand-edited source in local dev
Backend startup code in `backend/open_webui/config.py` clears top-level files in `STATIC_DIR` and then tries to copy from frontend build output.

Implications:
- tracked files in `backend/open_webui/static` can appear deleted during backend startup
- do not use this directory as your primary asset source in dev
- prefer top-level `static/` for source assets unless you are intentionally changing backend static serving behavior

If tracked backend static files disappear in git status:

```bash
git restore backend/open_webui/static
```

If you want a safer dev workflow, consider overriding `STATIC_DIR` to a generated directory outside tracked files.

### Other generated or high-churn paths
- `node_modules/`
- `build/`
- `static/pyodide/`
- `backend/data/cache/`
- `backend/data/uploads/`
- `backend/data/vector_db/`

Avoid committing generated noise unless the change is intentional.

## Validation Strategy

### Frontend
Useful commands:

```bash
npm run dev
npm run test:frontend
```

There is a repo-wide `npm run check`, but this checkout has historically produced a very large pre-existing `svelte-check` backlog. Do not assume a failing `npm run check` was caused by your change.

Practical guidance:
- prefer targeted validation in the affected route/component/API path
- manually exercise the changed feature in local dev
- use Cypress files as examples of existing E2E coverage patterns

### Backend
Useful commands:

```bash
cd backend
sh dev.sh
```

Watch backend logs while exercising frontend flows. Many user-visible failures are surfaced only in backend tracebacks.

## Common Local Pitfalls

### Svelte version mismatch in `node_modules`
The repo expects Svelte 5 from `package.json`.
If Vite reports errors like missing `svelte/legacy`, your install is likely stale or mixed with Svelte 4.

Check:

```bash
node -p "require('./node_modules/svelte/package.json').version"
```

If needed, reinstall from scratch:

```bash
rm -rf node_modules
npm install
```

### npm cache permission issues
If `npm install` fails under `~/.npm/_cacache` with `EACCES`, either:
- fix ownership of `~/.npm`, or
- temporarily use a local cache directory:

```bash
npm install --cache ./.npm-cache
```

### Backend static fallback assumptions
Some backend routes expect a favicon fallback. In local dev, missing backend static files can cause unrelated 500s if fallback paths are not robust.

### Notes update compatibility
Some older notes can have `meta = null` or `data = null`. Backend and frontend note updates should defensively treat those as dict-like objects, not assume mappings are always present.

### Record/voice features are often blocked by UX state, not STT itself
If recording appears “not working”, first verify:
- mic permission was granted
- a target note or target entity is selected if the flow requires one
- the record button is not intentionally disabled by local UI state

## Feature-Building Guidance

### Notes features
- Primary routes:
  - `src/routes/(app)/notes/+page.svelte`
  - `src/routes/(app)/notes/[id]/+page.svelte`
- Frontend APIs:
  - `src/lib/apis/notes/index.ts`
- Backend router:
  - `backend/open_webui/routers/notes.py`
- Backend DB logic:
  - `backend/open_webui/models/notes.py`

When appending or updating notes:
- preserve existing `data.content` structure
- keep `md` and `html` in sync
- avoid assuming `meta` is populated

### Audio / STT features
- Frontend APIs:
  - `src/lib/apis/audio/index.ts`
- Existing recorder patterns:
  - chat voice input components under `src/lib/components/chat/MessageInput/`
- Backend STT/TTS:
  - `backend/open_webui/routers/audio.py`

Before adding new recording endpoints, check whether:
- browser recording already exists
- `transcribeAudio(...)` already does the needed upload
- permissions depend on `chat.stt`

### Simple Mode recorder and cost-chat handoff
- Primary route:
  - `src/routes/(app)/simple/+page.svelte`
- Related picker:
  - `src/lib/components/simple/SimpleModeNotePicker.svelte`
- Chat bootstrap consumer:
  - `src/lib/components/chat/Chat.svelte`

Simple Mode currently has two linked behaviors:
- record audio, transcribe it with the built-in STT flow, and append into a selected note
- start a new cost-estimation chat from that selected note

Important frontend bootstrap constants used by this flow:

```ts
const COST_CHAT_BOOTSTRAP_KEY = 'simple-mode-cost-chat-bootstrap';
const COST_CHAT_MODEL_ID = 'models/gemini-3.1-flash-lite-preview';
const COST_ESTIMATE_SKILL_KEY = 'calculate-estimate';
```

Behavior notes:
- the lower-left control selects or creates the target note used by Simple Mode
- the lower-right action starts a new chat using `COST_CHAT_MODEL_ID`
- the selected note is passed as a normal chat note attachment, not through a new backend API
- the skill is invoked through the existing skill-mention flow, using the resolved skill id and `COST_ESTIMATE_SKILL_KEY`
- the handoff to chat does not rely on URL params alone; it uses `sessionStorage` bootstrap state keyed by `COST_CHAT_BOOTSTRAP_KEY`
- the actual auto-submit happens inside `Chat.svelte` during `initNewChat()`, so if this flow breaks, inspect that path first

When changing this feature:
- keep the note attachment shape compatible with normal chat note attachments
- do not introduce a parallel backend endpoint for starting the chat unless the existing bootstrap path is proven insufficient
- verify both pieces of state transfer:
  - selected model bootstrap
  - note + prompt + skill bootstrap
- if the UI lands on an empty new chat, debug the bootstrap restore path in `Chat.svelte` before changing the model selector flow

### Sidebar / navigation features
- Primary files:
  - `src/lib/components/layout/Sidebar.svelte`
  - `src/lib/components/app/AppSidebar.svelte`

If adding a top-level app feature:
- update both collapsed and expanded sidebar variants if appropriate
- verify the route works with authenticated app layout
- confirm the control remains visible when the sidebar is open

## Debugging Checklist

### If the frontend action spins forever
1. Check browser console.
2. Check network requests in order.
3. Check backend logs for the corresponding route.
4. Confirm whether the UI is waiting on:
   - transcription
   - note update
   - socket event
   - a hidden disabled state

### If backend logs show unrelated 500s
Separate:
- the user-triggered request path
- background or shell-level requests such as profile-image or favicon fallbacks

Do not anchor on the first scary traceback if the visible feature path is different.

### If git shows many deletes in backend static files
This is probably startup-side static sync behavior, not an editor or git bug.

## Editing Guardrails
- Make minimal coding changes.
- Only make code changes that are necessary to implement the requested feature or instruction.
- Prefer the narrowest safe fix over opportunistic cleanup or refactors.
- Avoid changing unrelated files just because they are nearby or already noisy.
- Prefer small, integrated changes over new subsystems.
- Reuse existing API clients and backend routers whenever possible.
- Avoid editing generated directories unless the task is specifically about generation/build behavior.
- Be careful with startup/config files:
  - `backend/open_webui/config.py`
  - `backend/open_webui/env.py`

They contain side effects at import time and can have broad repo-wide impact.

## Recommended Agent Workflow
1. Identify the domain: notes, audio, models, workspace, auth, etc.
2. Find the corresponding frontend API client in `src/lib/apis/<domain>/`.
3. Find the backend router in `backend/open_webui/routers/<domain>.py`.
4. Inspect the relevant route/page/component under `src/routes/` and `src/lib/components/`.
5. Implement using existing patterns.
6. Validate with local dev servers and targeted manual testing.
7. Treat repo-wide check failures carefully; distinguish pre-existing noise from regressions.

## Files Worth Reading First
- [README.md](README.md)
- [package.json](package.json)
- [pyproject.toml](pyproject.toml)
- [backend/dev.sh](backend/dev.sh)
- [backend/open_webui/main.py](backend/open_webui/main.py)
- [backend/open_webui/env.py](backend/open_webui/env.py)
- [backend/open_webui/config.py](backend/open_webui/config.py)
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
