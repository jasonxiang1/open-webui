# Clara Upstream Main Merge Notes

This file records the merge-specific context from the `upstream/main` merge that preserved Clara as a local feature.

The durable guidance has been consolidated into `AGENTS.md`, especially:
- local backend verification through `conda activate open-webui`
- Clara recorder/session endpoint behavior
- Clara result restore/edit/PDF behavior
- Clara note and chat integrations
- pinned-menu sidebar behavior
- future upstream merge conflict defaults

Merge outcome:
- Clara route files and `ClaraNotePicker` were retained.
- Clara transcription session endpoints were restored on top of upstream's async/non-blocking audio router.
- Clara was added to the pinned menu with default order `['notes', 'clara', 'workspace']`.
- Note-page `Clara`, `Last Estimate`, and `Compute Estimate` actions were preserved alongside upstream pinned-note controls.
- Chat composer `Estimate` / `Back to Estimate` behavior was preserved alongside upstream chat task/queue changes.
- Notes update logic kept null-safe `data` and `meta` merges.

Verification performed after the merge:
- Backend: `conda activate open-webui && cd backend/ && sh dev.sh`; `/health` returned `{"status": true}` on port `8080`.
- Frontend: `nvm use v22.17.1 && npm run dev`; Vite started on `localhost:5173` with only the existing Svelte package warning.

Use `AGENTS.md` as the source of truth for future Clara work and future upstream merge conflict resolution.
