# Change Log — TEAF PoC

## v1.41 — 2026-06-19
- Kept conversation starters on one compact row with shorter professional labels
- Reduced the remaining gap between chat history and the pinned input

## v1.40 — 2026-06-19
- Made empty-conversation starter prompts neutral gray in both themes and added the architecture-review starter
- Tightened the chat layout so the history panel reaches closer to the pinned input

## v1.39 — 2026-06-19
- Fixed light-mode label contrast for Settings action buttons such as Agent Save and Model Test

## v1.38 — 2026-06-19
- Updated the framework expansion to Tacit Externalisation Framework while keeping the TEAF abbreviation

## v1.37 — 2026-06-19
- Extended the chat history viewport further downward to close the remaining gap above the pinned input

## v1.36 — 2026-06-19
- Extended the chat history viewport closer to the pinned input to remove the remaining dead gap

## v1.35 — 2026-06-19
- Fixed chat history sizing so the viewport grows without stretching individual chat messages
- Restored normal compact chat-message bubbles inside the larger conversation area
- Made empty-conversation starter buttons softer than the app's primary action buttons

## v1.34 — 2026-06-19
- Restored safe top padding so Settings and Tacit Externalisation titles are not clipped
- Made the chat history scroll area target the real Streamlit scroll wrapper and fill more space above the input
- Increased the chat history fallback height for browsers that ignore the CSS override
- Unified action-button styling across the app while keeping Settings tabs styled as tabs

## v1.33 — 2026-06-18
- Domain agent now CONSOLIDATES all three sources (portfolio SQL + anomaly payload + governance RAG) on every app/anomaly question
- RAG is always injected for both agents every call (coach: frameworks; domain: governance)
- Domain SQL prompt grounded with the portfolio header + first rows (real id format, value spellings)
- Loose id matching: "app 180" resolves to APP-0180 via LIKE instead of failing
- Flagged apps' real portfolio rows are pulled in (the data the anomaly ran on) and cross-referenced by app_id
- Interim/thinking/status indicators now render inside the chat history container, in conversation context
- Compacted the conversation header + Data Sources panel; chat history fills the viewport down to the input
- Unified every Settings/options-panel button to the Delete style via one scoped CSS rule

## v1.32 — 2026-06-18
- Message history scrolls in its own viewport-adaptive container; header + Data Sources stay fixed
- Chat history autoscrolls to the newest turn; chat input stays pinned at the bottom
- Consolidation running indicator shows a single hourglass (was two)
- Unified all options-menu buttons to one primary style (Test/Reset/model-Delete were odd ones out)

## v1.31 — 2026-06-18
- Deleting a data source (portfolio CSV or RAG file) now asks for confirm/cancel first
- End-session working indicator now shows at the End Session button, not under Data Sources
- File uploaders auto-clear after a successful ingest; a failed/skipped upload keeps the file + shows why
- Removed the redundant "Also reflect at session end" checkbox; end-of-session reflection is always on
- Added token-driven hover states to buttons (readable in light + dark)
- Conversation starters render in flow, aligned to the chat input's bounds (no overflow)

## v1.30 — 2026-06-18
- Uploaded RAG docs are now retrievable immediately, no restart (refresh the cached vector store on write)
- refresh_store clears Chroma's cached client/system on successful ingest/remove so the next query re-reads disk
- Embedding model stays cached — nothing is re-embedded, no per-rerun rebuild
- Fixed the model Test button rendering black in light mode (help= wraps it; switched to descendant button selectors)

## v1.29 — 2026-06-18
- Domain agent routes policy/principle/standard/document questions to governance-document RAG, not portfolio SQL
- Added a policy-question detector; fixed word-boundary intents so "governance"/"summarise" no longer trigger SQL
- Added a combined SQL+RAG path for questions needing both portfolio data and policy
- Domain prompt now states its three sources (documents / portfolio SQL / anomalies) and the routing rule
- Internal analysis shows the retrieved governance documents (routing is visible)
- Enriched the governance policy seed doc with intake/onboarding and AI/public-facing sections
- Reinforced button-label theming for light mode (model Test button)
- Conversation starter chips now float just above the chat input instead of under the title

## v1.28 — 2026-06-18
- Removed the legacy keyword/head(3) portfolio path that returned the first three rows for every query
- Portfolio questions now go through exactly one path: the agent-written read-only SELECT
- SQL prompt built entirely from the live table schema (no hardcoded column names); survives a portfolio swap
- App-id queries route to SQL; failed queries surface the error instead of returning opening rows
- Themed the model Test output, the clear-stored-key checkbox, and help tooltips for light mode
- Added conversation starter chips on an empty session (anomaly chip only after detection); chips 2 and 3 force coaching mode
- Removed the standalone "Start chatting about these anomalies" button (replaced by the starter chip)
- Added PDF upload to RAG (pypdf text extraction; text-based only, scanned/image PDFs skipped with a warning)
- RAG upload/remove status is now a transient toast, so it does not linger in the panel

## v1.27 — 2026-06-18
- Replaced the portfolio keyword matcher with a real read-only SQL query tool
- Portfolio loaded into a typed in-memory SQLite table; agent writes one SELECT, runs read-only
- SELECT-only enforced (single statement, starts with SELECT/WITH, PRAGMA query_only)
- Enables numeric thresholds, ORDER BY sorts, LIKE search, and GROUP BY counts over all rows
- Renamed synthetic cost column to annual_cost_chf; agent told costs are CHF (no currency caveats)
- Broadened coaching delegation to cover numeric/sort/count portfolio queries
- Run detection and Start chatting now sit adjacent with a standard gap
- End Session button aligned to the right of the panel header
- Added space between Conversation heading and the session number

## v1.26 — 2026-06-18
- Domain Agent now queries the portfolio as structured data (pandas) over ALL rows, not RAG
- Added search_portfolio: case-insensitive filter/search/count on any column, full table
- Routed vendor/name/keyword/list/count questions to the structured tool; policy questions stay on RAG
- Portfolio search cross-references anomaly flags by app_id
- Coaching Agent now delegates portfolio search/list/count queries to the domain agent
- Enriched synthetic portfolio with vendor + category columns; default size 1000 rows
- Consolidation now runs in the background with a per-agent running line; both agents can run at once
- Compacted primary buttons; End Session and Run detection no longer full-width bars
- Start chatting button appears immediately after detection and matches the primary style
- Removed the workspace-ready loading indicator on app start
- Session number shown as plain text (no box) beside Conversation

## v1.25 — 2026-06-18
- Added a loading spinner while a per-agent patch consolidation runs
- Showed both agents' consolidate buttons side by side when both are eligible
- Made the chat session number a small version-style tag beside "Conversation"
- Removed the RAG scopes and anomaly explainer captions from Data Sources
- Moved "Start chatting about these anomalies" next to "Run detection"
- Removed the stray box behind the chat input in dark mode
- Renamed End Session to "End Session & Externalise Tacit Knowledge"

## v1.24 — 2026-06-18
- Hard-isolated RAG retrieval per agent via rag.retrieve_for_agent (agent↔collection links)
- Coaching questions (coaching practice/ICF/EMCC/AC/own documents) answer directly, never delegate
- Narrowed domain auto-delegation heuristic and added a coaching-question guard
- Added coaching knowledge-ownership routing rule to seed prompt + existing-DB migration
- Added per-file Remove (with confirm) to RAG management; rag.remove_document deletes chunks + tombstones seed docs
- Fixed light-mode uploaded-file chip contrast (token-driven)
- Added per-agent Consolidate pending patches in Tacit Externalisation (sources retained as consolidated)
- Added configurable consolidation prompt under Interaction triggers
- Spaced out the Interaction Triggers diagram so arrow labels no longer collide

## v1.23 — 2026-06-18
- Split Data Sources into separate Domain Agent RAG and Coaching Agent RAG upload scopes
- Injected Coaching Agent RAG only into the Coaching Agent context
- Renamed the top chat control panel to Data Sources and moved the session number to Conversation
- Repositioned and renamed the session action to End Session
- Made the chat composer feel like one integrated input instead of a framed nested box
- Added a first-load workspace status and avoided Chroma loading during document-list rendering
- Added deterministic specific-app anomaly explanations with raw record data and Isolation Forest reasoning

## v1.22 — 2026-06-18
- Enforced Coaching Agent delegation decisions with provider-native structured output
- Added the hard delegation contract to Coaching Agent prompts and existing DB prompts
- Auto-delegated retrieval-intent replies instead of rendering promise-only turns
- Surfaced live chat phases such as Consulting domain agent in the status indicator
- Added deterministic outlier-list responses from the active anomaly payload
- Increased default LLM output budget to reduce truncated coaching replies
- Improved light-mode toast contrast and resized the Interaction Triggers diagram

## v1.21 — 2026-06-18
- Rendered the Interaction Triggers SVG through a Streamlit HTML component
- Made form submit buttons readable in light mode
- Moved both externalisation reflection passes under the Coaching Agent reflection model
- Improved anomaly field inference for arbitrary uploaded portfolio CSVs
- Added raw portfolio-record lookup for Domain Agent data requests
- Made domain-analysis failures explicit instead of pretending retrieval succeeded

## v1.20 — 2026-06-18
- Replaced the Interaction Triggers graph with a fixed theme-aware SVG diagram
- Added editable Coaching, Domain, and shared reflection prompts
- Persisted light/dark mode in app settings with light mode as the default
- Auto-added anomaly and RAG uploads directly into their active scopes
- Added RAG document listings and downloads
- Hardened anomaly detection for uploaded CSVs with missing portfolio columns
- Changed the app icon from compass to agent robot

## v1.19 — 2026-06-18
- Fixed light-mode file upload button contrast
- Added anomaly detection run status inside the Anomaly Detection panel
- Clarified uploaded CSV add button wording

## v1.18 — 2026-06-18
- Clarified Trigger A send and return arrow labels in the Interaction Triggers diagram
- Forced Interaction Triggers diagram into a left-to-right layout

## v1.17 — 2026-06-18
- Reworked Interaction Triggers diagram to match the Trigger A and Trigger B sketch
- Added open-ended start guidance for governance documents, APM anomalies, facilitation, and coaching
- Reinforced human decision ownership and coaching-first posture

## v1.16 — 2026-06-18
- Added visible cards for both user and agent chat messages
- Improved light-mode chat tables and markdown contrast
- Reduced chat markdown heading size
- Replaced busy text with response-progress status
- Styled disabled chat input as muted instead of blocked
- Tightened coaching response style toward concise replies
- Updated Trigger B diagram return path to Coaching Agent

## v1.15 — 2026-06-18
- Fixed light-mode expander header contrast in Agents
- Replaced persistent saved banners with transient toasts
- Fixed Appearance toast emoji crash
- Added per-agent externalisation reflection model selection
- Kept chat turns running in the background when navigating away
- Rendered chat messages with Markdown support
- Removed forced sidebar arrow controls while keeping sidebar visible

## v1.14 — 2026-06-18
- Forced persisted collapsed sidebar state back into visible layout
- Restored visible sidebar collapse and expand controls

## v1.13 — 2026-06-18
- Prevented duplicate chat-submit warnings while a response is running
- Added separate self-reflection patches for Coaching Agent and Domain Agent
- Made Tacit Externalisation target agent easier to see
- Added JSON decision fallback for non-JSON coaching model replies

## v1.12 — 2026-06-18
- Restored sidebar recovery control while keeping expanded default
- Reordered Knowledge Interface panels to RAG, Anomaly Detection, Prompt Engineering
- Removed manual next-message mode selector
- Removed Stop waiting button and kept chat input disabled during responses

## v1.11 — 2026-06-18
- Moved theme toggle from sidebar to Settings
- Disabled sidebar collapse and tightened sidebar spacing
- Made knowledge-base loading lazy so prompt-engineering panel appears immediately
- Added chat busy state and duplicate-submit guard
- Replaced Streamlit badge markup with styled chat mode badges
- Improved placeholder contrast and chat input styling
- Added saved indicators for settings forms
- Increased rolling model context to the latest 80 visible messages

## v1.10 — 2026-06-18
- Reworked light and dark tokens for stronger contrast
- Replaced outlined chat containers with filled modern message bubbles
- Added LLM request timeouts so provider calls cannot hang indefinitely
- Limited model chat context to the latest 24 visible messages
- Queued turn-driven reflection so normal chat replies do not block

## v1.09 — 2026-06-17
- Theme rebuilt on two token palettes (dark + light) selected by the toggle; no hardcoded per-theme colours
- Anomaly results table is now token-styled HTML (themes in both modes) instead of the canvas dataframe
- Turn runs under one open status that stays active until the answer; internal domain analysis renders inside it
- Chat composer restyled: single integrated bar, inline send, accent focus ring
- Messages render as filled distinct bubbles (blue-ish you / green-ish coach) lifted off the page
- Removed the theme-toggle help tooltip
- Added a Download button per dataset in the data scope
- Relabelled the internal domain-analysis block (no longer self-contradictory)

## v1.08 — 2026-06-17
- Dark theme reworked: native dark base + CSS token palette; readable off-white text, visible card borders, themed inputs/uploader/dataframe (no white boxes)
- Turn now shows one persistent status indicator with phases (coaching / domain / composing)
- System prompt + patch previews wrap (no horizontal scroll)
- Registered models: per-model Test button (real minimal call, latency + verbatim errors)
- Stripped TEAF/knowledge-channel annotations from the agent settings UI

## v1.07 — 2026-06-17
- Fix: OpenAI calls use max_completion_tokens (fallback to max_tokens) for newer models
- Dark mode overhaul: themes the chat input bar, forms, expanders, buttons; readable
- Conversation boxes restyled: subtle professional look, blue/green left accent per speaker
- Tacit Externalisation promoted to its own top-level menu item (Chat / Tacit Externalisation / Settings)
- Settings: Danger zone renamed Data Management; Tacit Externalisation tab removed
- Sidebar: larger TEAF PoC title, version pinned bottom-left, sun/moon theme toggle
- Chat bubble icon moved from the page title to the Conversation header
- Agents: coaching shows its three modes; domain shown as "domain knowledge expert"
- Channels renamed (Anomaly Detection · Dynamic Explicit; RAG · Static Explicit) + new info-only Prompt Engineering · Externalised Tacit channel

## v1.06 — 2026-06-17
- Nav simplified to Chat + Settings; the four admin areas are now tabs inside Settings
- Sidebar: title pinned on top, version pinned to the bottom; added a dark/light toggle
- Renamed "Prompt patches" to "Tacit Externalisation" throughout
- Settings → Danger zone: delete conversations / Tacit Externalisations / all data (type-yes confirm)
- Chat: coach labelled "Coaching Agent"; mode badges without emoji; friendly KB labels (no raw collection name)
- Anomaly: manage the data scope (list/add/remove CSV files) then run detection over the combined set
- Domain Agent must now cite evidence (document name + application/anomaly id) with reasoning

## v1.05 — 2026-06-17
- Chat: separated top control panel from the conversation; mode selector kept on top
- Chat: user turns render as blue boxes, coach turns as green boxes
- Dynamic data: upload CSV + Run detection (no auto-regenerate); "Start chatting about these anomalies"
- Domain KB: upload-only (.txt/.md); removed the paste title/text form
- Interaction triggers: Trigger A shown first + fuller explanation; dynamic graphviz flow diagram
- Prompt patches: Pending / Approved / Rejected tabs; decisions reversible (reject removes appended text)
- Models: registered models are now editable (name/provider/model_string/key)
- Sidebar: title on top, version pinned to the bottom
- Theme: blue accent; removed the top-right toolbar/print menu

## v1.04 — 2026-06-17
- Fix: unique url_path per page (all page callables are named `render`, which collided)
- Verified the app script with Streamlit AppTest (catches render errors a health-check misses)
- Replaced deprecated use_container_width with width="stretch"
- Dockerfile: pre-bake model before copying app code so code changes don't re-download it

## v1.03 — 2026-06-17
- Deploy: back to build-on-runner (like other homelab apps); dropped the registry detour
- docker-compose.yml uses build.network: host so build DNS resolves via the host
- .woodpecker.yml builds again (--build); removed deploy/build-and-push.ps1

## v1.02 — 2026-06-17
- Deploy: switched to pull-based (Gitea registry) — runner has no build-time internet
- docker-compose.yml pulls git.home/eli/msc-thesis:latest; .woodpecker.yml pulls (no --build)
- Added deploy/build-and-push.ps1 (build on dev box + push to git.home)
- Verified image builds (9.57GB) + container boots locally with model pre-baked

## v1.01 — 2026-06-17
- Added homelab deployment files (Dockerfile, docker-compose.yml, .woodpecker.yml, .dockerignore)
- DATA_DIR + PORT now env-configurable; mutable state under one volume, seed docs bundled
- Root README with deploy notes; root .env.example + .gitignore

## v1.00 — 2026-06-17
- Phase 6: user-managed domain KB panel in chat (browse + upload/paste documents)
- Three real tests (orchestration domain branch, anomaly payload, RAG retrieve)
- Pinned requirements.txt to tested versions; feature-complete v1.00

## v0.60 — 2026-06-17
- Phase 5: self-reflection generates a structured prompt patch to disk + pending row (teaf/reflection.py)
- Trigger B wired: reflect every N turns and/or at session end (orchestrator)
- Interaction-trigger config persisted via new app_settings table (admin_interaction.py)
- Patch review: approve appends suggested text to the agent prompt; reject; never auto-merged (admin_patches.py)

## v0.50 — 2026-06-17
- Phase 4: synthetic EA portfolio generator with injected anomalies (explicit_channels/anomaly.py)
- Hybrid detection: rule-based data-quality checks + Isolation Forest, unified payload
- Domain Agent receives the active anomaly payload via the orchestrator (interprets, not computes)
- Anomaly snapshot on the chat page (summary + flagged records + regenerate)

## v0.40 — 2026-06-17
- Phase 3: visible mode badge (Coaching/Facilitation/Consulting) on each coaching turn
- User mode correction control; override fed to the coach as explicit input + recorded
- Orchestrator honours forced mode in both domain and no-domain branches

## v0.30 — 2026-06-17
- Phase 2: RAG explicit channel (Chroma + local embeddings) in explicit_channels/rag.py
- Domain Agent grounds answers in retrieved policy content (teaf/agents/domain_agent.py)
- Two-call orchestration with judgment-driven Trigger A (teaf/orchestration.py)
- Coaching Agent structured decide() + finalize() for domain folding
- Seeded two RAG collections + placeholder framework/policy docs under data/docs/
- Chat routes through orchestrator; background domain exchange shown in an expander

## v0.20 — 2026-06-17
- Phase 1: provider-agnostic LLM wrapper (Anthropic + OpenAI) in teaf/llm.py
- Model registry admin (add/delete, masked keys) in ui/admin_models.py
- Per-agent model assignment + system-prompt editing in ui/admin_agents.py
- Single-agent coaching chat loop (sessions + messages) in ui/chat.py
- Added anthropic + openai to installed deps

## v0.10 — 2026-06-17
- Initial Phase 0 scaffold: project structure under poc/
- SQLite schema + DAO for all seven tables
- Seeded fixed two-agent topology (coaching + domain) with default system prompts
- Streamlit shell with page routing (Chat + 4 admin pages)
- README with TEAF→module mapping table
- requirements.txt, .env.example, .gitignore
