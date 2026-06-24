# PIN Ticket Analysis Web UI

A lightweight local web app for browsing, analysing, and commenting on PIN
(Product Incoming Need) Jira tickets. Data is fetched live from Jira — no
local caches or intermediate scripts.

## What you get

- **Dashboard** with totals + distribution charts (Status, Urgency).
- **PIN List** with Status / Urgency filters and a free-text search.
- **PIN Detail** with three tabs:
  - `LLM Analysis` — click **Analyze with LLM** to run a per-PIN analysis;
    results are session-only (not saved to disk).
  - `Intake Form` — click **Load Intake Form** to pull the ProForma form live
    from Jira; fields render inline.
  - `Raw` — clean form text (after loading the form).
- **Comments** panel — live from Jira; supports AI-assisted draft via DeepSeek.

No Jira tokens ever touch the browser. All API calls originate from the
FastAPI backend using your local `.env` credentials.

## Stack

- **Backend:** FastAPI + uvicorn (`web/server.py`, single process, direct Jira REST)
- **Frontend:** Vite + React + TypeScript + Tailwind CSS + shadcn/ui + recharts

### Frontend tech spec

| Layer | Choice | Notes |
|-------|--------|-------|
| Build | Vite | Fast HMR dev server; production bundle to `dist/` |
| UI framework | React 18 + TypeScript | Strict mode enabled |
| Styling | Tailwind CSS v3 | Utility-first; theme tokens in `tailwind.config.js` |
| Component library | **shadcn/ui** (New York style) | Copy-paste components under `src/components/ui/` — do not hand-edit generated files; use `npx shadcn add <component>` to add new ones |
| Primitives | Radix UI | Underlying headless primitives used by shadcn/ui |
| Date picker | **shadcn/ui Calendar** (`react-day-picker` v10) | Wrapped in a Popover for inline use; import from `@/components/ui/calendar` |
| Date utilities | `date-fns` v4 | `format`, `parse`, etc. — already a transitive dep of react-day-picker |
| Charts | recharts | Used on the Dashboard for status/urgency distributions |
| Icons | lucide-react | Single icon set across the whole frontend |
| Forms / state | React hooks (`useState`, `useRef`, `useMemo`) | No form library; keep local state in components |
| HTTP client | Fetch API (wrapped in `src/api/client.ts`) | No Axios; all calls go through the FastAPI backend |

**Rule of thumb:** reach for a shadcn/ui component first. Only use a raw HTML element or a custom primitive when no shadcn/ui equivalent exists.

## Prerequisites

- Python 3.10+ with `.env` configured (`ATLASSIAN_API_TOKEN`, `DEEPSEEK_KEY`).
- Node 18+ and npm.

## First-time setup

```powershell
pip install -r web/requirements.txt
cd web/frontend
npm install
npm run build
```

`npm run build` writes the production bundle to `web/frontend/dist/`, which the
backend serves at the root path.

## Run

### Single-port mode (recommended for daily use)

```powershell
python web\server.py
# open http://127.0.0.1:8765
```

The backend serves both `/api/...` and the built frontend.

### Dev mode (hot reload)

Open two PowerShell windows.

```powershell
# window 1 - backend
python web\server.py

# window 2 - frontend with HMR (Vite proxies /api to 127.0.0.1:8765)
cd web\frontend
npm run dev
# open http://127.0.0.1:5173
```

## API surface

| Method | Path                                      | What it does                                                              |
| ------ | ----------------------------------------- | ------------------------------------------------------------------------- |
| GET    | `/api/pins`                               | List PINs via JQL (assignee = me, Backlog/Ready for Tech Review)          |
| GET    | `/api/pins/{key}`                         | Fetch one issue from Jira                                                 |
| GET    | `/api/pins/{key}/form`                    | Fetch intake form live; returns `{available:false}` when none exists      |
| POST   | `/api/pins/{key}/analyze`                 | Run LLM analysis for one PIN; result returned, not persisted              |
| GET    | `/api/pins/{key}/forms`                   | List all ProForma forms attached to the issue (metadata only)             |
| GET    | `/api/pins/{key}/forms/submitted`         | List submitted ProForma forms with cleaned text                           |
| GET    | `/api/pins/{key}/comments`                | List Jira comments                                                        |
| POST   | `/api/pins/{key}/comments`                | Post a new comment                                                        |
| POST   | `/api/pins/{key}/comments/ai-draft`       | Non-streaming AI comment draft                                            |
| POST   | `/api/pins/{key}/comments/ai-draft/stream`| Streaming AI comment draft (NDJSON)                                       |
| GET    | `/api/users/search`                       | Search Jira users (for @mention auto-complete)                            |
| GET    | `/api/profile`                            | base_url / account_id / email from `config/assets/global/profile.yaml`   |

Every request is real-time — there is no local file cache. Entering a PIN detail
page fetches the issue from Jira; loading the intake form or running LLM analysis
requires an explicit button click.

## FAQ

**No summary shown in the list**  
The issue has no `summary` field in Jira. This is unusual; check the ticket directly.

**Load Intake Form returns "No intake form found"**  
The PIN does not have a *Feature Request Intake Form* ProForma form attached.

**Analyze with LLM takes 5–15 s**  
The analysis is synchronous. The button is disabled while in progress and a toast
shows the status.

**Why no auth?**  
The server binds to `127.0.0.1` only and reuses the user's local `.env`. It is
intended as a single-user local tool, not a deployable service.

## Project layout

```
web/
  server.py                 # FastAPI backend (direct Jira REST, no subprocess)
  requirements.txt
  README.md
  frontend/
    package.json
    vite.config.ts
    tailwind.config.js
    tsconfig.json
    components.json         # shadcn/ui config
    index.html
    src/
      main.tsx
      App.tsx
      api/{client,types}.ts
      hooks/{usePins,usePinDetail}.ts
      pages/{Dashboard,PinList,PinDetail}.tsx
      components/
        Layout.tsx
        StatusBadge.tsx
        StatCard.tsx
        DistributionChart.tsx
        MultiFilter.tsx
        IntakeFormPanel.tsx
        AnalysisEditor.tsx
        AttachedFormsPanel.tsx
        CommentsPanel.tsx
        RawPanel.tsx
        MarkdownLite.tsx
        ui/                  # shadcn-managed primitives (do not hand-edit)
      lib/utils.ts
      styles/globals.css
    dist/                    # build output (git-ignored)
```
