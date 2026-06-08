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

### Iteration 6 — Math Captcha + Admin Users + Inline @StaffName Join (May 15, 2026)
- **Math captcha** replaces hCaptcha everywhere. Stateless (HMAC-signed in base64 token, 5-min TTL). Endpoint `GET /api/auth/captcha` issues a fresh `What is 11 - 7?` style question. Required on both register and login.
- **Tawk.to removed earlier (iter 5); no captcha library scripts loaded anymore** — site loads faster.
- **Admin Users tab** in `/admin`: list every registered user with role, join date, mute status. Edit email/role/password, mute 24h, unmute, delete. Owner protected from deletion. Endpoints: `GET /api/admin/users`, `PUT /api/admin/users/{id}`, `DELETE /api/admin/users/{id}`, `POST /api/admin/users/{id}/mute|unmute`. All require `x-admin-token`.
- **Inline staff join message**: when admin clicks "Take Over" on an AI chat, the user instantly sees `👋 @Balkin joined the chat — you're now talking with a real person.` in their widget (polled every 3s).
- **AI Widget embedded in Client Dashboard**: floating chat circle now also appears inside `/client/dashboard` with the "Live Chat?" label — logged-in users can reach the AI/staff without going back to homepage.

## Backlog
### Iteration 5 — Smart AI Handover (May 4, 2026)
- **AI Knowledge Base**: AI now knows enabled services + prices and the **24-hour money-back guarantee** (only IPTV / Followers / Likes — explicitly NOT Views/Comments). System prompt is built dynamically from the curated services collection so price changes auto-propagate.
- **Multilingual Handover Detection**: when user asks for "staff/agent/support/admin/operator" or any equivalent in **any language** (verified: English, German, Spanish, French, Russian, Chinese, Japanese), AI replies with a transfer message in the user's language ("Please wait, I'm transferring you to our team…") and emits `HANDOVER_REQUEST` token. Backend strips the token, flags `session.needs_handover=true`, returns `admin_online` based on heartbeat.
- **Staff Display Name** (`POST /api/ai/admin/settings`): admin sets the public-facing name (default "Support"). Stored in `ai_settings` singleton. Shown in user's widget header and bubble label.
- **Admin Heartbeat** (`POST /api/ai/admin/heartbeat`): admin panel pings every ~8s while open. `is_admin_online()` returns true if heartbeat within 90s.
- **Offline Fallback Form**: when handover requested but no admin online, the user widget renders an inline form (email + message + Send/Cancel). Public endpoint `POST /api/ai/offline-message` persists to `ai_offline_messages`. Admin sees them in the Inbox toggle with unread counter.
- **"Live Chat?" Label** next to the floating chat circle FAB on the homepage.
- **"Leave Chat" button** (renamed from "Return to AI"): when admin presses it, AI rejoins and inserts a system note `"({StaffName} has left the chat — I'm back to help.)"` so the user is never confused.
- **"Wants Staff" badge** in admin Inbox highlights sessions awaiting handover (pink, pulsing). Header counter `🔴 X waiting for staff`.
- Backend tests: 25/25 pass (iter 5). Total test coverage: ~70 tests.

### Iteration 7 — Dashboard Buy + Coupon Redeem + Chat Mute/Ban (May 22, 2026)
- **Buy Services from Dashboard** (`POST /api/client/order-with-balance`): logged-in users browse the curated catalog, pick a service, enter link+quantity, and pay with their account balance. Atomic balance precheck, validates min/max, debits as a negative transaction, records order with `source='dashboard'`, payment_method='balance'. Sidebar entry **Buy Services** (testid=nav-buy).
- **Coupon to Balance** (`POST /api/client/redeem-coupon`): users paste a BS-XXXX coupon code → full coupon balance is credited as an auto-approved deposit transaction → coupon is deleted. Sidebar entry **Redeem Coupon** (testid=nav-redeem). Success card + toast.
- **AI Chat Mute / Ban** (admin only):
  - `POST /api/ai/admin/sessions/{id}/mute` (body: `{minutes:int}`) — sets `ai_sessions.muted_until`, inserts a system message in the user's chat. `/api/ai/chat` returns 429 `{code:'muted',muted_until}` while active.
  - `POST /api/ai/admin/sessions/{id}/unmute` — clears mute.
  - `POST /api/ai/admin/sessions/{id}/ban` — upserts entry in `chat_bans` keyed by identifier, flags `ai_sessions.banned=true`. Future `/api/ai/identify` calls with same identifier return 403.
  - `GET /api/ai/admin/chat-bans` + `POST /api/ai/admin/chat-bans/unban`.
  - Admin Inbox toolbar: **MUTE / UNMUTE / BAN** buttons next to Take Over (testid=inbox-mute, inbox-unmute, inbox-ban).
- Backend tests: 9/9 pass (iter 6 test_iteration_6_redeem_buy_mute_ban.py). Frontend smoke verified live: nav-buy + nav-redeem + redeem-success + Not-enough-balance disabling buy-confirm + admin inbox-mute/ban buttons all visible.

### Iteration 8 — Try Chance casino game + Custom service-name override (Jun 8, 2026)
- **Custom service-name override** (Admin → Services): each row has a "Custom display name (optional)" input. Setting it overlays the provider's name on the public catalog (`/api/services`). Sync All never overwrites it.
- **Try Chance** mini-casino in the Client Dashboard:
  - Header button `TRY CHANCE` (testid=header-try-chance) + sidebar entry (testid=nav-casino).
  - `POST /api/client/casino/spin` body `{stake: 1..100}` deducts stake from balance, rolls a multiplier from a weighted table (server-side, `secrets.randbelow`), credits any winnings, returns `{multiplier, win, net, balance}`. Logs each roll in `casino_rolls` collection.
  - Prize table: 0x (92%), 0.5x (4%), 2x (2.5%), 5x (0.9%), 10x (0.4%), 50x (0.15%), 100x (0.03%), 1000x (0.015%), **10000x (0.005% — 1 in 20,000)**. RTP ≈ 91% (house edge ~9%).
  - UI: animated reel (1.5s spin), prize table card with all 9 tiers, last-30-spins history (`GET /api/client/casino/history`). Validates stake range and balance before allowing spin.

### Iteration 9 — Crypto Withdrawals + Winnings-only Cashout (Jun 8, 2026)
- **Sidebar entry "Withdraw"** with badge showing withdrawable amount.
- **Winnings-only rule**: separate `withdrawable_balance` field on users — incremented ONLY by casino wins. Deposits (PayPal/coupon/crypto in) cannot be withdrawn. Pending withdrawals reserve both balance + withdrawable.
- **Withdrawal form**: amount (min $10, max-button auto-fills withdrawable), currency picker (USDT TRC-20, USDT ERC-20, BTC), wallet address. Submit → status=pending → reserved.
- **Endpoints**:
  - `GET /api/client/balance` now returns `{balance, withdrawable}`.
  - `POST /api/client/withdraw {amount, currency, address}` — validates, reserves, creates pending tx.
  - `GET /api/client/withdrawals` — user history.
  - `GET /api/admin/withdrawals?status=pending|approved|rejected|all`.
  - `POST /api/admin/withdrawals/{id}/approve {tx_hash?, note?}` — finalises debit.
  - `POST /api/admin/withdrawals/{id}/reject {note?}` — releases reservation, refunds withdrawable.
- **Admin Withdrawals tab** with filter pills (Pending/Approved/Rejected/All) + per-row Approve / Reject buttons. Approve prompts for TX hash (optional); Reject prompts for reason.
- Verified live: $80 win → submit withdrawal → admin sees row → reject refunds correctly; approve permanently debits.

### Iteration 10 — Multi-provider APIs + Custom-comments dialog (Jun 8, 2026)
- **Multiple SMM Providers**: new collection `smm_providers` (name/api_url/api_key/enabled). Admin UI: "Providers" tab with Add, Sync, Toggle (On/Off), Delete. API key masked in listing (only last 4 chars shown). Each provider has its own Sync button (`POST /api/admin/smm-providers/{pid}/sync`) — pulls catalog from THAT provider's API and tags every service with `provider_id` + `provider_name`. `smm_request()` and `place_smm_order()` now accept a `provider_id` arg and route to the correct API key.
- **Custom comments support**: new field `needs_custom_text` on each curated service. Auto-detected on sync (heuristic: name contains "custom" AND NOT "random"/"emoji"). Admin can override in Services tab via the new "Custom?" toggle column.
  - Backend: `/api/checkout`, `/api/client/order-with-balance`, and AI `/api/ai/confirm-order` all enforce that the user provides `comments` text when `needs_custom_text=true`, and pass them to the SMM API as the standard `comments` field.
  - Dashboard Buy view: amber "Custom comments required" box with textarea (one per line, live line counter, 5000 char cap) — Place Order disabled until filled.
  - Landing checkout dialog: same amber box appears for custom services before payment selection.
  - AI Widget: system prompt updated to ask "Which comments?" before READY_TO_ORDER; READY_TO_ORDER JSON now includes optional `comments` field; widget passes it through to `/confirm-order`.
- Public `/api/services` payload now includes `needs_custom_text`, `provider_id`, `provider_name`.

### Iteration 11 — Selly.io payments (Add Funds + Landing checkout) (Jun 8, 2026)
- **Selly.io integration** replaces Cryptomus on the public landing page and adds a new "Pay via Selly" button in the Client Dashboard Add Funds view. Supports BTC/ETH/USDT/LTC crypto + Visa/Mastercard via Selly's hosted checkout.
- **Backend**:
  - New env vars: `SELLY_API_KEY`, `SELLY_WEBHOOK_SECRET` (placeholders in `.env`; admin must set real values on VPS).
  - `_create_selly_invoice()` helper calls `POST https://selly.io/api/v2/payment-requests` with USD value + metadata + return_url. Returns `{id, url}`.
  - `POST /api/client/funds/selly-create` (auth required, min $5) — pre-creates a pending deposit tx then redirects user to Selly checkout. On payment webhook, tx flips to `approved` → balance updated automatically.
  - `POST /api/checkout/selly-create` (public) — landing-page service order. Pre-creates order in `PENDING_PAYMENT` state then redirects to Selly. On payment webhook, auto-routes to `place_smm_order()` with the correct provider_id.
  - `POST /api/selly/webhook` — verifies `X-Selly-Signature` (HMAC-SHA512 over raw body) using `hmac.compare_digest`. Ignores non-paid events; on completion event, dispatches by `metadata.kind` (`funds` → approve tx; `order` → place SMM order).
- **Frontend**:
  - Dashboard FundsView: emerald "Pay $X via Selly (Crypto · Card)" button above existing PayPal flow.
  - CheckoutDialog: Cryptomus tab replaced with "Crypto / Card" tab (emerald). Submit redirects to Selly hosted page.
  - Dashboard auto-detects `?selly_funds=1&tx=...` return URL → toast + jump to Funds view + force-refresh balance.
  - Landing auto-detects `?selly_order=1&order=...` → toast confirming payment received.
  - Landing marketing copy updated (Two ways to pay, How it works, FAQ) — replaces CoinPayments references with Selly.
- **Backend verified via curl**:
  - Webhook signature verification: rejects bad sig (401), accepts correctly-signed HMAC-SHA512 payload (200).
  - Funds-create with no API key → 503 "Selly is not configured".

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
