# Better Social — PRD

## Original Problem Statement
"Make a normal SMM landing page but better. When someone wants to buy, press checkout button → redirects to the purchase box. No login — peoples buy directly. They can pay using a generated gift card from us (use coupon to pay) or pay by CoinPayments. List all offers from smmcost.com API (key 47b5c3b01e4b5ecd1e53b39baef31a6e). When the user presses order, take the money via the API. If pay using CoinPayments, after complete status show a sweet alert success message and send the API request immediately. Site title and on-site name: 'Better Social'. Make a separate page with admin panel access (username: DEMO, password: DEMO). On admin panel: only order logs (with IP of buyers) and generated coupons with custom amount."

## User Choices (Feb 29, 2026)
- CoinPayments: keys configured later via Admin → Settings (no env vars)
- Coupons: multi-use, deplete-by-balance
- Admin features confirmed: order logs (with IP) + coupon generator
- Currency: USD
- Theme: pink + purple dark mix

## Architecture
- Backend: FastAPI + MongoDB (motor) + httpx for SMM/CoinPayments calls
- Frontend: React + Tailwind + shadcn/ui + sweetalert2 + react-router-dom
- Theme: pink (#FF007F) + purple (#7000FF) on void black (#050505), Unbounded display + IBM Plex body
- No-login public flow; in-memory admin sessions for DEMO admin

## Personas
- Visitor / Buyer: anonymous user looking to boost their social account
- Operator / Admin: site owner managing orders & coupons (DEMO/DEMO)

## Implemented (Feb 29, 2026)
- Landing page (Hero / Features / How it works / Services teaser / Payments / FAQ / Footer)
- Live checkout dialog: pulls **curated** services from the admin's selection, search + category filter, link/qty/email inputs, total calc, two payment tabs
- Coupon flow: multi-use balance, atomic deduction with refund-on-SMM-failure, **auto-deletes when balance reaches $0**
- CoinPayments flow: HMAC SHA-512 signed create_transaction; pending state with QR + address; "I've paid → check & fulfill" polls get_tx_info
- SweetAlert2 success modal with SMM order ID
- Admin login (DEMO/DEMO) → 4-tab dashboard:
  - **Orders** (IP + status)
  - **Services** — sync 9k+ provider catalog, see provider price + your custom price, enable/disable per service, bulk enable/disable, % markup tool
  - **Coupons** (generate custom amount + table)
  - **Settings** (configurable SMM API URL+Key + CoinPayments keys with masked display)
- Backend tests: 19/20 passed (1 skipped due to test ordering, not a bug)

### Iteration 2 (Feb 29, 2026)
- SMM API URL + Key are now stored in DB and editable from admin (was hardcoded)
- Curated services system: admin syncs from provider, sets custom prices, only enabled services appear on the public checkout (provider price hidden from buyers)
- Coupons auto-delete when balance hits $0

### Iteration 3 — Client Area + AI + Discord (May 2, 2026)
- Migrated CoinPayments → **Cryptomus** (merchant callback + sig verify)
- **Client Area**: JWT auth (bcrypt), hCaptcha, dashboard, Community Chat with half-username privacy, `/mute` moderation command
- **Floating AI Widget** (Claude Sonnet 4.5 via `EMERGENT_LLM_KEY`): natural-language ordering flow (detect language → ask service/link/qty/coupon → `READY_TO_ORDER` JSON → auto-place)
- **Standalone Discord Bot** (`/app/discord_bot/bot.py`) with `/buy` slash command; Developer role bypass for coupon; configured via Admin → Discord tab
- VPS one-shot deploy script `/app/deploy.sh`

### Iteration 4 — Social-Proof Ticker + Admin Live Takeover (May 2, 2026)
- **Public order ticker** on Landing page: `GET /api/orders/recent-feed` returns last 30 orders with masked emails (`ab**`, `gu**` for guests). Marquee at bottom of landing.
- **Coupon balance edit** in Admin → Coupons: pencil icon opens modal → `PUT /api/admin/coupons/{code}/balance`
- **AI chat persistence**: `ai_chat_messages` + `ai_sessions` collections store every exchange with IP + last activity
- **Admin AI Inbox** (`Admin → AI Inbox` tab): list of all live chats, click to view history, **Take Over** button pauses AI and lets admin reply directly — client widget polls `/api/ai/poll` every 3s and renders admin bubbles in cyan with "Support" label + system notice "A human team-member is now handling your chat"
- **Security fix**: added `_admin_check(request)` to `/api/ai/admin/orders`, `/api/ai/admin/service-map` (GET+POST) — these were missing auth in iter 3
- Backend tests: 24/24 new tests pass (total 43+ passing)

## Backlog
### P1
- hCaptcha: swap test keys for production keys in backend `.env` on VPS
- Persist admin sessions in DB (currently in-memory; lost on restart — breaks AI Inbox + Coupons across backend restarts until re-login)
- Rate limit Discord `/buy` command to prevent coupon spam drain
### P2
- Email receipt on success
- Service favorites / quick-pick
- Order status tracking page (smmcost status API)
- Split `auth_and_chat.py` (~700 lines) into separate auth/chat/ai modules
- Stream Claude replies instead of blocking HTTP worker
- Push notifications / sound alert for admin when a new AI chat arrives (currently 8s polling)
