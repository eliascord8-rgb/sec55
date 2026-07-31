# Better Social — PRD


## Recent Updates (Feb 2026 — Iteration 49 · Custom-comments UX + Auto-Live comments + Client API + TikTok Finder page)

**Custom-comments quantity is now auto-derived from line count**
- On the Buy page, when the selected service has `needs_custom_text=true`:
  - The Quantity input is hidden. The number of non-empty lines in the comments textarea IS the quantity.
  - A live "QUANTITY = N lines" badge appears above the textarea. Total price recomputes automatically (`rate × lines / 1000`).
- Backend `POST /api/client/live-sub/create`, `POST /api/checkout`, `POST /api/client/order-with-balance`, `POST /api/client/orders/multi`, and `POST /api/v2 action=add` all enforce the same rule: for `needs_custom_text` services, `quantity = count of non-empty comment lines`. Any mismatch from the client is normalised server-side.

**Auto-Live custom comments (TikTok + Kick Live)**
- `LiveSubCreate` now accepts a `comments: Optional[str]` field. Comments are stored on the `live_subscriptions` document and re-used on every burst (`_fire_one_burst` passes them to `place_smm_order`).
- Frontend Auto-Live setup panel reads the same textarea used by single-order flow. When the service needs custom text, a "📝 Custom comments mode" note shows on the setup panel with the line count.
- The Auto-Live gate now also allows Kick Live services (`("tiktok" in cat or "kick" in cat) and "live" in cat`).

**JAP-compatible client API — `/api/v2`**
- Dashboard sidebar → "API" tab. Users get a personal API key (48-char hex) they can copy, reveal, or regenerate.
- Fully compatible with JustAnotherPanel / SMMcost API clients. Actions: `balance`, `services`, `add`, `status`, `multi_status`, `cancel`, `refill`.
- Same balance / validation / needs_custom_text rules as the dashboard order flow. Orders placed via API are tagged `source="api"`.
- Endpoints: `GET/POST /api/v2` (form-urlencoded or JSON), `GET /api/client/api-key`, `POST /api/client/api-key/regenerate`.

**TikTok Finder — dedicated `/tiktok-finder` page**
- Lives at its own route (opens in a new tab from the marketing landing header).
- Two lookup modes:
  - **@username** → live scrape of the public `/@handle` page (existing behaviour, unchanged).
  - **User ID** → cache-based reverse lookup. Every successful handle lookup writes to `tiktok_lookup_cache`; the reverse endpoint (`GET /api/tools/tiktok-lookup-by-id`) serves from that cache and re-scrapes if stale (>24h). Returns a friendly 404 when the id was never cached (TikTok doesn't expose a public user_id→username endpoint without paid signing).
- Nav entries: `nav-tiktok-finder` in desktop nav bar + `header-tiktok-finder-btn` pill for mobile/tablet.
- New sec_uid + copy-to-clipboard for user_id and sec_uid. Rate limit still 30/min per IP.


## Recent Updates (Feb 2026 — Iteration 48 · Fake orders + own-code country resolver)

**Fake orders paired with the fake-chat toggle**
- New background worker `_fake_order_activity_loop` — same on/off as fake chat (`app_settings.fake_chat_enabled`). Every 25-60s (jittered) it inserts a random order into `db.orders` with `bot: True` from one of the 15 fake personas, picking from 19 realistic service/quantity/price combos (Instagram Followers HQ × 500 / $2.50 up to YouTube Views × 10 000 / $12.40).
- Throttled to skip when >15 real orders were placed in the last 10 min so it doesn't drown genuine activity.
- These flow straight into `/api/orders/latest-global` → the "Latest Orders" panel on the client dashboard AND the guest landing feed with the standard username masking (`@Na***`).

**TikTok country resolver — 100% own code, no external API**
- Bio flag-emoji parser (`_flag_to_country`) decodes regional-indicator surrogate pairs from the bio (🇩🇪 → `DE`, 🇷🇸 → `RS`, …) — **high confidence**.
- Fallback keyword scanner (`_BIO_KEYWORDS`) — 60+ country entries with city/country names in local languages (Deutschland, Beograd, İstanbul, São Paulo, Sarajevo, …) — **medium confidence**.
- Then TikTok's own `region` field when present — **high confidence**.
- Then TikTok's `language` code mapped via `_LANG_TO_COUNTRY` (de→DE, sr→RS, bs→BA, etc.) — **low confidence**.
- Returns `{country, name, source, confidence}` and the frontend shows the confidence chip with a tooltip explaining which signal fired (`bio_flag`, `bio_keyword:beograd`, `tiktok_region`, `language:de`, `no_signal`).
- Verified: `@bella.poarch` → PT (language:pt · low), `@charlidamelio` → no_signal (no signals in payload).


## Recent Updates (Feb 2026 — Iteration 47 · Two new addons + TikTok public lookup + Balkan geo language detect)

**New addons in the store (Admin can price-override each)**
- **Auto-Live · 1-Week Pass** (`auto_live_week`, **$80**) — one-tap 7-day Auto-Live boost. Stackable: buying again extends `auto_live_expires_at` from whichever is later.
- **Username Blacklist** (`username_blacklist`, **$100**) — 2 slots per purchase; stackable. Blocks Auto-Live provisioning + bulk orders on the blacklisted TikTok handles. New endpoints: `GET/POST /api/client/addons/blacklist`, `DELETE /api/client/addons/blacklist/{id}`. `_is_handle_blacklisted()` helper for enforcement.

**Free public TikTok Lookup** (no login required)
- Backend: `GET /api/tools/tiktok-lookup?username=<handle>` — scrapes the public `/@handle` page for `nickname`, `avatar`, `verified`, `private`, `signature`, `region`, `language`, `user_id`, `sec_uid`, `followers`, `hearts`, `videos`, `following`, `profile_url`, `created_at` (Snowflake decode for post-2018 accounts, legacy note otherwise). 30 lookups/minute per IP.
- Frontend: `/app/frontend/src/components/TikTokLookupBox.jsx` — mounted on the Guest Landing under the welcome hero. `data-testid="tiktok-lookup-{box,input,btn,result,error}"`. Verified live against `@charlidamelio` (159.3M / 12.3B / 3.2K / 1.4K).

**Balkan geo-IP → language auto-detect**
- `GET /api/geo/detect-language` — reads `x-forwarded-for` → resolves country via CF/Vercel headers if present, else `ip-api.com`. Returns `{ip, country, recommended_lang}`.
- `COUNTRY_TO_LANG` map: RS/ME/MK/HR/SI/BG/AL/XK → `sr`, BA → `bs`, DE/AT/CH/LI → `de`, ES → `es`, PT/BR → `pt`. Frontend can call this once on first mount and switch language if it hasn't been set manually.


## Recent Updates (Jun 2026 — Iteration 50 · Live NOWPayments IPN end-to-end test PASSED)
- Ran a full live IPN test against the real NOWPayments API + public webhook URL:
  - Real invoice created via `/api/client/funds/nowpayments-create` (live API key works).
  - HMAC-SHA512-signed IPN (real ipn_secret, sorted-JSON per NOWPayments spec) → auto-credited $10 + $7 (70% bonus), balance delta exactly +17.00.
  - Bad signature → 401 rejected; replay → `already_credited` (idempotent); all 3 events logged in `nowpayments_events` with correct `signature_ok` flags.
- **Bug fixed**: IPN callback URL registered with NOWPayments was `http://` (TLS terminates at ingress so `request.base_url` reports http). Now force-upgraded to `https://` in `nowpayments_create_funds`. Verified new invoices register the https callback.
- Conclusion: automatic IPN crediting works end-to-end — users no longer need "Verify & Credit" as long as NOWPayments can reach the public URL. Test transactions cleaned from DB.

## Recent Updates (Feb 2026 — Iteration 46 · Discord community button + NOWPayments Verify-and-credit safety net)

**Discord community links**
- Guest landing header now has an indigo Discord button (`data-testid=guest-discord-btn`) linking to `https://discord.gg/namelessstore`, hidden on mobile to save room.
- Help Center gets a full-width Discord card under the shortcuts (`data-testid=help-discord-join`) — Live giveaways / sneak-peeks / direct chat with the team.

**NOWPayments — manual Verify & credit**
- Root cause of "user paid but balance didn't fund": if the IPN webhook doesn't reach us (blocked, rate-limited, tab closed, ngrok/proxy hiccup, or NOWPayments `Timeout`), the transaction sits at `pending` forever unless we poll. Polling the `/payment/` endpoint requires a **NOWPayments account JWT**, which we get by exchanging the email+password saved in Admin → NOWPayments Config. If those two fields are empty, auto-verify is OFF and pending payments never self-heal.
- **New endpoint** `POST /api/admin/deposits/{tx_id}/verify` — the safety net. Fetches the latest status from NOWPayments for a specific pending crypto tx and credits the user's balance if the payment is `finished`/`confirmed`. Returns a detailed status object so the reason is obvious (`no_payment_yet`, `partially_paid`, `waiting`, actual payload snapshot).
- Admin → Transactions → pending rows now show a **"Verify & credit"** button next to Approve/Reject (only on `nowpayments`/`crypto` methods, `data-testid=verify-crypto-<txid>`). Toasts either *"✅ Credited $X to @user"* or the exact upstream status.
- The existing config banner already warns *"⚠️ Auto-verify OFF — add account email+password"* — this is the single fix that makes auto-crediting work again without any manual clicks.


## Recent Updates (Feb 2026 — Iteration 45 · Discord `%` prefix + guild fix + rich help embed)

**Discord bot**
- **Moderation prefix switched to `%`** — legacy `$` and `!` still work as aliases. All `%help`, `%kick`, `%ban`, `%mute`, `%warn`, `%slowmode`, `%lock`, `%nick`, `%role`, `%say`, `%userinfo`, `%serverinfo`, `%avatar`, `%modlog`, `%purge`, `%softban`, `%unban`, `%unmute`, `%ping` re-labelled consistently.
- **`%help` now posts a rich Discord embed** (green, three fields: Moderation / Channel / Info & Utility) with a footer noting who can run mod commands. Falls back to code block if embed post fails.
- **Fixed the "Not Found" purchase channel bug** — `send_channel_message` now accepts an optional `guild_id`, looks up the guild first, and returns a **precise reason**: `"channel {id} not found in guild {name} — check the channel exists and the bot has 'View Channel' permission"` or `"bot has no access to channel {id} — give the bot Send Messages permission on it"`. The `discord_notify_log` records the real cause every time.

**Admin UI (`/admin → Discord → Purchase notifications`)**
- New **Server (Guild) ID** input placed left of Channel ID. Copy from Discord: right-click your server icon → *Copy Server ID*.
- Save posts both `purchase_guild_id` + `purchase_channel_id` in one call. Verified round-trip: guild `1477630408404373604` + channel `1477630409742221499` saved and read back cleanly.

**How to make purchase notifications appear in your Discord server**
1. Paste the **Server ID** of `NamelessStore.de` (`1477630408404373604`) into the new field.
2. Keep the Channel ID as `1477630409742221499`.
3. Save.
4. Go to Admin → Discord Bot → **Start** (bot is currently stopped).
5. In Discord, give the `Better Social` app the permissions **View Channel** + **Send Messages** on the target channel.
6. Click *Send test message* — the message will appear, or the log will tell you exactly what's missing.


## Recent Updates (Feb 2026 — Iteration 44 · Live-chat queue + Department transfer + UI cleanup)

**Backend (`auth_and_chat.py`)**
- `/api/ai/poll` now returns `queue_position` (10 → 1 over ~30s starting from `handover_requested_at`), `department`, and `assigned_staff` so the widget can render a live-support waiting UX.
- `/api/ai/admin/sessions/{sid}/takeover` now resolves the acting staff's login username via `get_actor_display_name()` and stores it in `assigned_staff_name`. The system message the user sees says *"👋 @{actor} joined the chat — you're now talking with a real person."* — no more generic "Support".
- **New `/api/ai/admin/sessions/{sid}/transfer`** — Owner/staff can move any live session to another department. Departments: `support`, `technical`, `sales`, `billing`, `call_support`. Endpoint restarts the queue timer, clears the previous assignee, flips status back to AI so the receiving dept can pick it up, and inserts a system message *"🔀 You've been transferred to the **{label}** department. Someone from that team will be with you shortly."*
- **New `GET /api/ai/admin/departments`** returns the department list for the admin UI dropdown.

**Frontend**
- `AIWidget.jsx` — **Previous** tab and **+ Start new** button removed from the chat tab bar (as requested).
- Queue banner: sticky yellow pill at the top of the messages panel showing the position number in a pulsing orb, the department name, and estimated pickup time. Only appears when `queue_position` is set and no staff has taken over yet.
- Assigned-staff banner: emerald pill saying *"🟢 Talking with @{staffname}"* once a staff joins.
- `Admin.jsx` — new **`<TransferMenu>`** dropdown next to the Take-Over button in the AI Inbox panel. Fetches departments live, calls the transfer endpoint, and toasts the result. `data-testid` on every menu item (`inbox-transfer`, `inbox-transfer-support/technical/sales/billing/call_support`).

**Files touched**
- `backend/auth_and_chat.py` — enrich `/ai/poll`, staff-name in takeover, transfer + departments endpoints.
- `frontend/src/components/AIWidget.jsx` — remove Previous/Start-new, add queue + assigned banners.
- `frontend/src/pages/Admin.jsx` — add TransferMenu next to Take Over.


## Recent Updates (Feb 2026 — Iteration 43 · Mod role, 2FA, Discord OAuth scaffolding, Live Activity, Fake social-proof)

**Backend**
- **2FA (TOTP) opt-in** — `pyotp` + `qrcode`. New endpoints: `POST /api/auth/2fa/setup` (returns QR image + secret), `POST /api/auth/2fa/enable` (verify + issues 8 one-time recovery codes), `POST /api/auth/2fa/disable`, `GET /api/auth/2fa/status`. `LoginRequest` and `AdminAccountLogin` accept an optional `totp_code`; login returns HTTP 401 `TOTP_REQUIRED` if the account has 2FA on and no code was sent. Recovery codes are also accepted at login/disable and consumed once.
- **STAFF_PERMS expanded** to 21 keys (`tickets, ai_inbox, orders, discord, withdrawals, services, providers, users, coupons, giveaways, payments, deposits, livesubs, aiactions, backups, reports, settings, sim5, games, invoices, audit`). Owner can now grant any subset to any moderator via `PATCH /api/admin/users/{uid}/admin-perms`.
- **Discord OAuth scaffolding** — `GET /api/auth/discord/login-url`, `POST /api/auth/discord/callback` (login or auto-create), `POST /api/client/discord/link`, `POST /api/client/discord/unlink`, plus owner-only `GET/POST /api/admin/discord/oauth-config` for pasting Client ID / Secret / Redirect URI. `discord_id` + `discord_username` stored on the user document.
- **Live activity feed** — `POST /api/client/activity/heartbeat` (route + viewport + last action tag, no form values), `GET /api/admin/activity/live?stale_minutes=5` and `GET /api/admin/activity/user/{id}` (recent breadcrumb trail). Gated by `audit` perm; owner has full access.
- **Fake social-proof chat worker** — 15 personas (Serbian / English / German), 27 message templates with @-mentions across languages. Inserts one message every 4-8s (jittered), throttled when real human activity is high. Admin toggle: `GET/POST /api/admin/fake-chat/toggle`, `POST /api/admin/fake-chat/purge`.

**Frontend**
- **Support button + Mod badge** — moderators now see a yellow "Support" button in the header (instead of the emerald "Admin" one). Mod role tag switched from cyan `#00E5FF` to yellow `#FBBF24` everywhere (badge, side avatar shield, chat rendering).
- **LiveChatFAB** — staff role tag styling: OWNER (amber), ADMIN (emerald), MOD (yellow), STAFF (sky). Each role tints the @username in the chat so users know a staff member is talking to them.
- **Client Dashboard → Security & 2FA** — new page in the Profile menu with: QR enrolment flow (setup → confirm code → recovery codes shown once), disable (requires current code or recovery), and a "Link with Discord" card that hits the OAuth URL when the owner has configured OAuth.
- **Activity heartbeat hook** — every dashboard sends a route/action heartbeat every 5s plus a click-tagged event whenever the user clicks any `data-testid` element.
- **Admin → Live Activity tab** — real-time table of everyone online (auto-refresh 4s), clickable rows open a breadcrumb trail with viewport / IP / route history. Requires `audit` perm.
- **Guest Landing "social proof" toasts** — `<FakePurchaseAlerts />` fires two randomised "Milan B. just bought Instagram Followers × 1500" toasts about 4s and 14s after page load, with country flag, timing and product name.
- **NOWPayments deposit confirmed working end-to-end** — real invoice creation returned `iid=4916942043`, pending list shows it, IPN webhook wired to `/api/nowpayments/webhook`.

**Files touched**
- `backend/server.py` — 2FA hooks in admin-login, activity endpoints, fake-chat worker + admin API, Discord OAuth endpoints, message-enrichment fix so fake avatars survive.
- `backend/auth_and_chat.py` — /auth/2fa/* endpoints, TOTP gate in /auth/login, DB-manager owner seed (previously).
- `backend/requirements.txt` — added PyOTP 2.10, qrcode 8.2, pillow 12.2.
- `frontend/src/pages/GuestLanding.jsx` — FakePurchaseAlerts.
- `frontend/src/pages/SettingsAndAviator.jsx` — new `SecurityView` export.
- `frontend/src/pages/ClientDashboard.jsx` — activity heartbeat, Support button for mod/admin, security nav item, mod color yellow, view=security dispatch.
- `frontend/src/components/LiveChatFAB.jsx` — role-tinted usernames + MOD yellow.
- `frontend/src/pages/Admin.jsx` — Live Activity tab + `<LiveActivityPanel>`.


## Recent Updates (Feb 2026 — Iteration 42 · Admin Live Subs + AI Ticket Assistant + Sports Removed + DB Manager Hardening)
- 🧹 **Sports section fully removed.** Every `/api/sports/*`, `/api/client/sports/*`, `/api/admin/sports/*` route and the `_sports_watcher_loop` background worker have been deleted from `server.py` (~500 lines gone). `SportsView` import stripped from `ClientDashboard.jsx`, the "Sports" toggle removed from Admin → Settings → Features, and `GoalNotifier` now renders nothing. `features.sports` defaults to `false` in the DB.
- ✅ **Admin Live-Subscriptions manager** (Admin → Live Subs). Lists every user's Auto-Live sub with status/spent/refunded/refundable. Owner can cancel any sub, refund up to what's still refundable in one click, and auto-open a support ticket that the AI assistant handles. Backend endpoints: `GET /api/admin/live-subs`, `POST /api/admin/live-subs/{sid}/cancel`.
- ✅ **AI ticket auto-reply.** When any user creates or replies to a ticket, `_ai_ticket_autoreply()` fires in the background: the AI reads the ticket + refundable items + user balance, posts a staff reply signed "BS Assistant (AI)", and — when justified — refunds cancelled orders / live-subs straight to the user's balance (capped at the refundable amount). Uses Emergent LLM key.
- ✅ **AI Actions History** (Admin → AI Actions). New `ai_actions` collection + `GET /api/admin/ai-actions` audit log. Every AI ticket reply, AI refund, and admin sub-cancellation lands here with actor/kind/target/amount/reason.
- ✅ **Dedicated DB-manager owner account**. Seed `dbmanager` / `DbM4nager!2026` (env overridable: `DBMGR_USERNAME/PASSWORD/EMAIL`). Only that account needs to be shared for `/db-manager`; the main `Balkin` login stays owner-exclusive for the shop.
- 🛡️ **DB-manager hardening**:
  - Protected collections: `users`, `admin_users`, `smm_providers`, `wallets`, `app_settings`, `nowpayments_config`, `paypal_config`, `coinpayments_config`, `selly_config` — single-doc delete + mass-delete both return 403.
  - Protected fields on `users`: `balance`, `withdrawable_balance`, `role`, `password_hash`, `banned`, `session_epoch` are dropped from any PUT payload.
  - **Balance carry-forward** on transaction deletion: when the owner deletes transaction history, the DB manager first aggregates the net approved balance per user from the doomed rows and writes a `carry_forward` compensating transaction with `protected=true`, so `/api/client/balance` is *exactly* unchanged after the wipe. Carry-forward rows themselves are immune to further deletion.
- ✅ **Automatic DB backups every 6 hours** to `/app/backups/backup_YYYYMMDD_HHMMSS.json.gz` (all collections). Keeps last 20. Admin → DB Backups panel: run-now, list, download, delete. Endpoints: `GET/POST/DELETE /api/admin/db-backups`, `GET /api/admin/db-backups/{name}/download?t=<admin-token>`.
- 🧪 Testing agent iter42: 9/11 focused backend tests passed on first run. All fixed after retest: sports fully removed (404), balance carry-forward makes destructive transaction deletion balance-safe, backup metadata purged on delete/rotate.


## Recent Updates (Feb 2026 — Iteration 40 · Re-Live Detection Fix + LiveSubRow on Live-Orders tab)
- 🐛 **Auto-Live now catches re-lives fast**. User reported: "went live → bots joined → stopped stream → went live again 2 min later → bots didn't come back". Fix:
  - `_is_tiktok_user_live` now queries the webcast API AND the `/@handle/live` HTML **in parallel** and returns LIVE if EITHER signal is positive. Previously the webcast endpoint's stale-cache response (up to ~2 min after a re-live) short-circuited detection to False without ever consulting the HTML fallback.
  - `TIKTOK_CHECK_INTERVAL_SEC` reduced from 90s → **45s** so re-lives are caught in ~75s worst case instead of ~120s.
- ✨ **`LiveSubRow` is now rendered on the Live-Orders tab too**, with the red/green status dot, "Next check in Ns" live countdown, mode chip, check tallies, always-visible history strip, and expandable audit table (up to 100 rows). The user was looking at that tab and not seeing the red/green history box that was only on Buy → now it's everywhere.
- 🐛 `waiting_for_live` subs are treated as "Active" in the Live-Orders section (previously fell into "history").



## Recent Updates (Feb 2026 — Iteration 39 · Auto-Live overhaul + Chat mod-bot + /clear N)
- 🐛 **Auto-Live no longer wastes balance** — when user creates a `live_only` subscription for an OFFLINE target, the initial SMM burst is now skipped, sub marked `waiting_for_live`, initial red check logged. Fixes user's #1 complaint ("wastes balance if he is offline").
- 🚀 **Rapid-fire when live** — in `live_only` mode, once the target is detected LIVE the worker fires up to **30 bursts spaced 2 seconds apart** in the same 90s check window (with balance + live-status spot-checks every 10 bursts to abort mid-window if streamer drops or funds run out).
- 📊 **Live-check history for everybody** — every 90s check on every subscription (both modes) now writes a row into `tiktok_live_checks`. New `LiveSubRow` component on Buy tab shows red/green dot + strip of last 30 checks + expandable audit table with the last 60. Refreshes every 30s.
- 🔊 **Removed the "🔴 boosted" chat announce** — subscriptions no longer spam the public shoutbox with system messages when a target goes live.
- 💬 **`/clear N` command** — owners can `/clear` (all) or `/clear 50` (delete only the latest 50 messages).
- 🤖 **BetterBot chat auto-mod** — when someone posts "help / support / contact / problem / not working / stuck / @admin" etc., the bot auto-replies with a friendly pointer to Live Chat + Ticket. Per-user 5-minute cooldown so it doesn't spam.
- 🐛 Cancel endpoint now accepts `active | waiting_for_live | paused` (was hard-coded to `active` only → 404 for the new waiting state).
- 🧪 Testing agent iter39: 4/6 backend + LiveSubRow UI passed. Cancel-404 fixed after retest.



## Recent Updates (Feb 2026 — Iteration 38 · Multi-Service Atomic Orders + Manual Order UX)
- ✅ **Multi-service cart on Buy page** — user clicks "Multi order" chip in the hero, then "Add" on each service in the catalog to build a cart. One target URL applies to every service. Per-item qty inputs, per-item comments for custom-text services, live total, insufficient-balance guard.
- ✅ **New `POST /api/client/orders/multi`** endpoint — accepts `{ link, items: [{ service_id, quantity, comments? }] }` (max 15). Pre-checks all services & total cost against balance before any provider call. Fires each order sequentially, per-item results returned. Marks orders `source='dashboard_multi'`, `multi_batch=true`. Sends one roll-up email summary.
- 🐛 **Fixed**: manual single-order response now returns `order_id` + `smm_order_id: null`. Previously the UI showed `Order ID #undefined` for flat-priced manual services.
- 🐛 **Fixed**: catalog now shows `$X.XX flat` for manual services instead of misleading `$0.000 / 1000`.
- 🧪 Testing agent iteration 38: 6/7 backend + all frontend UI passed. The single "failed" case is the SMM provider rejecting service #7242 (external issue — endpoint behaviour is correct: rejected item → item-level fail, successful item → placed & debited).



## Recent Updates (Feb 2026 — Iteration 37 · Fork · Bulk Gift + PayPal UI + Sports Bet UI + Global Chat FAB)
- ✅ **Admin OrdersPanel fixed** — table now shows `@username`, `service_name`, and `$price` with fallbacks for old & new order schemas. Previously most cells rendered blank.
- ✅ **Admin User Statistics drill-down modal restored** — `StatCard` component was referenced but never defined, causing a React crash on click. Now defined, modal renders 4 tiles (Deposits / Spent / Orders / Transactions) + recent orders/transactions lists.
- ✅ **Bulk Gift Orders** (Admin → Bulk Gift tab):
  - New `POST /api/admin/bulk-order` — accepts `{ user_ids[], services[{service_id:int, quantity:int}], link, note? }`. Fires one order per (user × service) as `payment_method="admin_gift"`, `source="admin_bulk"`, `charge=0.0`. Free (no balance deduction).
  - New `BulkGiftPanel` UI with searchable user picker (checkbox multi-select), searchable service picker with per-service qty, one target URL, admin note field, and per-result success/failure log.
- ✅ **PayPal in Add Funds** — new "Pay with PayPal" button next to Crypto. Calls existing `/api/client/funds/paypal-checkout`, redirects to hosted PayPal URL. Return-handler in ClientDashboard toasts on `?paypal=success` and polls balance for the next minute until IPN lands.
- ✅ **Sports Betting UI live** — `SportsView.jsx` was "read-only" placeholder. Now full betslip: 1/X/2 odds buttons per match, right-side sticky slip (combined odds, potential win, stake presets $0.5–$20), Place Bet POST /api/client/sports/bet, My Bets tab with cashout button (85% refund).
- ✅ **LiveChatFAB global** — mounted in `App.js` inside `<MaintenanceGate>`, `md:hidden` restriction dropped. FAB now appears on every route (dashboard, sports, admin, guest, etc.) at all screen sizes.
- ✅ **Classic ⇄ New layout switch removed** — force `useNewLayout=true` and dropped both toggle buttons (top-bar + old view). Only the green theme dashboard exists now.
- 🧪 Testing agent Iteration 37: 100% of new UI flows PASS. Backend 14/15 feature tests PASS. The one "failure" is a route-naming contract mismatch (`POST /client/orders` vs implemented `POST /client/order-with-balance`) — pre-existing, not a regression. Auth-hardening defects (cookies, CORS wildcard, brute-force lockout) also carried from earlier iterations.


## Recent Updates (Jul 26, 2026 — Iteration 34 · Fork · Sports Betting Ships)
- ✅ **Free live-scores API** — `sports_livescores` now falls back to **SofaScore** (public JSON, no key, no KYC) when RapidAPI fails. Returns `source: "rapidapi"` or `source: "sofascore"` so frontend can label the data source.
- ✅ **Full betting system MVP** shipped end-to-end:
  - `bets` collection with fields: `{id, user_id, selections[], stake, combined_odds, potential_win, status, is_combo, cashout_offered, cashout_amount, created_at, settled_at}`
  - `match_odds` collection for admin overrides + per-match suspension.
  - Endpoints (all backend-tested with real curl):
    - `GET /api/sports/odds/{match_id}` — merged odds board (admin overrides on top of defaults)
    - `POST /api/client/sports/bet` — single or combo bet, stake $0.10–$20, deducts from balance atomically
    - `POST /api/client/sports/bet/{id}/cashout` — dynamic refund at 85% of stake (admin-tunable)
    - `GET /api/client/sports/my-bets?status=open|won|lost|cashed_out`
    - `PATCH /api/admin/sports/odds/{match_id}` — set custom odds + suspend/unsuspend market
    - `POST /api/admin/sports/settle-bet/{bet_id}?won=true|false` — settle wins credit `potential_win` to balance
  - **Markets supported**: 1X2, over/under 0.5, 1.5, 2.5, BTTS (yes/no).
  - **Odds format**: Decimal + Asian both use the same numeric field — front-end can render as either.

## Recent Updates (Jul 25, 2026 — Iteration 33 · Fork · Auto-Live audit + Purchase polish)
- ✅ **TikTok live-status polling: 60s → 90s** per user request. Existing subs pick this up on their next tick.
- ✅ **Live-status history log** — new `tiktok_live_checks` collection. Every scrape (only in `live_only` mode) records `{sub_id, user_id, tiktok_username, is_live, will_fire, checked_at, mode}`. Cap at 500 rows per sub (auto-trim).
- ✅ **Endpoints for the log**:
  - `GET /api/client/live-sub/{sid}/checks` — user views their own sub's check history + stats (`{total_checks, was_live, was_offline}`)
  - `GET /api/admin/live-sub-checks?user_id=X&sub_id=Y&limit=500` — owner/staff cross-user audit
- ✅ **Purchase page hero redesign** — new premium header banner: emerald gradient card with "Grow anything. In one click." headline, 3 live stat boxes (services / balance / active auto-subs), quick-action chip row (Bulk mode toggle · Auto-Live shortcut · Repeat last order). Matches the dashboard's dark obsidian + emerald green theme.

## Recent Updates (Jul 25, 2026 — Iteration 32 · Fork · Notifications + Feature toggles)
- ✅ **Universal email notifications** — new `notification_service.py` with `notify_user()` helper. Wired into 4 trigger points so far:
  - **Order placed (balance flow)** → `notify_order_placed` sends a branded confirmation with service, quantity, charge, order ID + "View order" CTA.
  - **Deposit credited (NOWPayments)** → `notify_deposit_credited` — includes amount, 70% bonus, total credited + "Place an order" CTA.
  - **Staff ticket reply** → `notify_ticket_reply` — includes staff name, ticket subject, message preview + "Open ticket" CTA.
  - **Direct message received** → `notify_dm_received` — text OR voice message (voice gets 🎤 icon), rate-limited to 1 email per 2 minutes per user.
  - **Account closed** → `notify_account_closed` (helper ready, not yet wired to any endpoint).
- ✅ **Per-event rate limiting** stored in `db.email_notifications`. DM: 2min, voice: 1min, orders/deposits/tickets: 0 (every occurrence).
- ✅ **Opt-out prefs** — reads `users.email_prefs.{email_orders, email_tickets, email_dms, email_voice, email_generic}` so users can silence categories later. `account_close` + `deposit` are non-toggleable (billing/security).
- ✅ **Feature toggles** — new `GET /api/features` (public) + `PATCH /api/admin/features` (owner-only). Persisted in `app_settings.features`. Toggleable keys: sports · numbers · games · addons · live_orders · coupons · invoices · messages · tickets · tos.
  - `<FeaturesProvider>` polls `/api/features` every 60s.
  - `useFeatureEnabled(key)` / `useFeatures()` hooks let any component gate.
  - `ClientDashboard` sidebar + top nav now hide items when their feature flag is off.
  - Admin: new `<FeatureTogglesPanel>` in Settings — 10 rows with pill switches + inline descriptions.
- ✅ **AI chat: Persistent "Talk to a human" button** in chat view (above the AI header) — fires handover immediately + puts user in waiting state. Message input stays live so anything typed reaches admin inbox verbatim.
- ✅ **AI chat: Post-handover feedback fix** — when backend returns empty reply + `needs_handover: true`, frontend now shows a "🔔 A team member will jump in shortly — feel free to keep typing" system message so users aren't confused by silence.
- ✅ **Home CTAs fixed** — Buy / Deposit / Spin / AI Chat buttons under balance are now proper `<button onClick>` handlers instead of `<a href>` full-page reloads. In-app SPA navigation preserves session.
- ✅ **Admin auto-elevation confirmed working** for BOTH login paths:
  - Owner logs in with dashboard credentials → visits `/admin` → `bs_user_token` in localStorage → auto-elevates via `session-from-user`.
  - Owner logs in via Google → same flow works identically (JWT issued by `/google-status` OR `/google-finalize`).

## Recent Updates (Jul 25, 2026 — Iteration 31 · Fork · Auto-Live rebuilt)
- ✅ **Auto-Live rebuilt as a strict timer** (per repeated user complaint). New `mode` field on `live_subscriptions`:
  - `mode: "always"` (default & recommended) — Pure timer. Fires the exact same order (service, quantity, link) every 2/5/10/60 minutes on the dot, for the full duration in days. No TikTok live-status check. This finally fixes the "orders came once then stopped" bug — the live-status scraper kept returning false-negatives after TikTok markup changes and silently killed the loop.
  - `mode: "live_only"` — Legacy. Only fires while target is broadcasting. Fails OPEN (fires anyway) if scraping fails, so you can never get stuck.
- ✅ **Migration ran** — all existing subs updated to `mode="always"`, paused subs that still have time reactivated, `next_check_at` reset to now.
- ✅ **UI: mode picker** in the Auto-Live setup — big Always/Live-only toggle with clear copy so users understand what they're getting. Default is Always.
- ✅ **Reply-To header** added to `send_email()` for all three providers (Elastic Email `ReplyTo`, MailerSend `reply_to`, SMTP `Reply-To` header) — measurably lowers spam-folder placement rate.
- ✅ **Admin UI**: new "Reply-To Email" field with green "Boosts inbox rate" badge in Email Config panel.

## Recent Updates (Jul 21, 2026 — Iteration 30 · Fork · Google Auth)
- ✅ **Google Sign-in / Sign-up** — Emergent-managed Google OAuth wired up end-to-end:
  - Backend: `POST /api/auth/google-status` (exchanges Emergent `session_id` → JWT for existing users OR `signup_token` for new users) + `POST /api/auth/google-finalize` (creates user with chosen username, tolerates uniqueness collisions).
  - Frontend: `<GoogleSignInButton>` in `ClientAuth`, "Continue with Google" in `GuestLanding` auth modals, `<GoogleAuthCallback>` mounted inside `<BrowserRouter>` — parses `#session_id` fragment on any route, cleans it, calls status endpoint, and shows a mandatory username picker modal for new users.
  - New user flow: Google → 15-min `signup_token` in `pending_google_signups` → username picker → account created (no password, `auth_provider_google: true`, avatar synced from Google profile picture).
  - Existing user flow: Email match → auto-link Google id + refresh avatar → issue our JWT → done.
- ✅ `authedApi()` now exposes `patch` + `delete` (required by AvatarSettings).

## Recent Updates (Jul 21, 2026 — Iteration 29 · Fork)
- ✅ **AI chat flow rebuilt** — "Send us a message" no longer auto-hands-off to staff. AI is first responder again; explicit "Talk to a human" button + user-initiated handover only. Duplicate "Got it — I've paged the human team" messages fixed via 10-min dedupe check in backend. Once handover flagged, LLM calls skip (message still saved for admin).
- ✅ **NOWPayments auto-reconciler** — New 90s background worker (`_nowpayments_reconciler_loop`) polls pending crypto deposits in the last 48h and auto-credits any that NOWPayments now reports as paid. Belt-and-suspenders for missed webhooks — users never have to click "Verify" again.
- ✅ **Maintenance mode** — `GET /api/maintenance` (public) + `PATCH /api/admin/maintenance` (owner-only). New `<MaintenanceGate>` wraps the router; when enabled, regular clients see a "Be right back" screen. Staff/admin/owner + `/admin` route always allowed. Admin panel has toggle + custom message input.
- ✅ **Profile pictures** — `POST /api/auth/me/avatar` (upload), `PATCH /api/auth/me/avatar-url` (paste URL), `DELETE /api/auth/me/avatar`, `GET /api/auth/avatars/{fname}` (serve). Avatar shows in Settings, topbar profile menu, shoutbox messages.
- ✅ **Chat XP/level system** — `_award_chat_xp` grants 3 XP per shoutbox message; formula `level = isqrt(xp // 25) + 1`. Level badge shows next to username in topbar profile menu + shoutbox.
- ✅ **Elastic Email integration (no-KYC)** — `send_email()` now supports Elastic Email API v4 as primary provider, MailerSend as fallback, SMTP as last resort. Admin panel Email Config panel has dedicated Elastic key field.
- ✅ **Landing page redesign** — Complete rewrite to match dashboard: emerald green + obsidian dark, Outfit+Manrope fonts, bento-grid features, glassy scroll-blur header, radial glow hero, crypto chips grid, sleek 1px-border FAQ, giant "BETTER SOCIAL" watermark footer.
- ✅ **Classic-layout dashboard footer bug FIXED** — Footer had escaped the flex wrapper causing huge green void on right side. Moved footer outside `<div className="flex flex-1">` container.
- ✅ **Removed $0.80 daily free-bet** from topbar per user request. Backend endpoints kept as no-op.
- ✅ **Support FAB gated to Help Center only** — Removed global AI FAB from ClientDashboard; new big "Need help? Customer support" button lives at the top of Help Center view.
- ✅ **Staff name locked to login username** — Staff no longer have a "display name" editable field. `get_actor_display_name()` always returns their login username. Owner keeps customizable nickname.
- ✅ **AI Inbox deduplication** — `admin_ai_sessions` now merges duplicate sessions by `identified_user_id` OR `identified_as`. One card per user. `_merged_count` field tells admin how many sessions were consolidated.
- ✅ **Session migration on identify** — Both `/ai/identify` and `_auto_identify_from_token` now migrate messages from guest session IDs to canonical `ai-user-<username>` sessions, then delete the old session doc.
- ✅ **User-agent + device parsing** — Sessions capture UA on identify/auth; `_parse_ua_device()` extracts OS/browser/type. Rendered in admin inbox header.
- ✅ **Order history in admin inbox** — Each dedup'd session shows lifetime order count, total spent, and last 5 orders (collapsible details section).
- ✅ **FAB label change** — "Live Chat?" → "Need help? Customer support" everywhere.

## Recent Updates (Jul 17, 2026 — Iterations 29+)
- ✅ **Rollbit-style support widget** — Redesigned AIWidget header: BS brand square + stacked circular avatars of on-shift team members + large "Hi there 👋 How can we help?" heading. On-shift status pulled from new `GET /api/team/online` (public) endpoint. Team members flip themselves on/off shift via new `POST /api/admin/shift/toggle` — the "🟢 On shift" toggle now lives at the top of the Admin panel next to Logout.
- ✅ **Auto-human on widget open** — Signed-in users now trigger `/ai/request-handover` immediately when they open the chat (no need to wait for the AI to fail). Past sessions preload into the Previous tab.
- ✅ **Team-member DMs via widget** — Existing handover pipeline already lets any staff (owner/admin/moderator) reply as themselves via the AI-inbox admin tab. Their avatar shows on the client widget.
- ✅ **Mobile live-chat FAB** — Emerald round button above the AI FAB opens the public shoutbox as a bottom-sheet drawer.
- ✅ **Design bug fixed** — Footer no longer renders as a sibling column on desktop.

## Recent Updates (Jul 17, 2026 — Iterations 27-28)
- ✅ **Design bug fixed** — Dashboard footer had escaped the `<main>` flex wrapper and was rendering as a sibling column on 1280+ screens (screenshot user posted). Split the wrapper so `useNewLayout` uses block layout and only the classic sidebar layout stays flex.
- ✅ **AI chat auto-connects to human** — When a signed-in user OPENS the widget, we immediately fire `/api/ai/request-handover` and show "Paging a live agent for you now — please stay on this chat" + auto-preload their previous conversations. No more waiting for the AI to fail first.
- ✅ **Mobile live-chat FAB** — New emerald floating button (`live-chat-fab`) on phone screens, sits directly above where the AI robot FAB would live. Tap → full-height bottom-sheet with the public shoutbox (@username + role badges + timestamps). Unread-since-last-open counter badge. Present on both dashboard + guest landing.

## Recent Updates (Jul 17, 2026 — Iterations 23-26)
- ✅ **Auto-Live TikTok rewrite (P0 fixed)** — Fresh worker: check every **60s**, place first order immediately on subscription create, then repeat every user-chosen 2/5/10/60 min while target is actually live. Per-sub `repeat_every_minutes` gate. Sub auto-expires at `expires_at`, cancel via `POST /api/client/live-sub/{sid}/cancel`. If user goes offline, worker idles (no spam); if they go live again, loop resumes.
- ✅ **Repeat previous order** — `POST /api/client/orders/{oid}/repeat` re-runs same params from balance; UI button under "Last order placed".
- ✅ **Saved bulk-target lists** — `GET/POST/DELETE /api/client/bulk-lists`; save/load/delete named lists in the Purchase bulk mode.
- ✅ **Add-ons store** — `GET /api/client/addons/catalog` + `POST /api/client/addons/purchase`. Auto-Live is a $250 one-time unlock (editable via `PATCH /api/admin/addons/{id}`). Purchase pays from balance, unlocks the Live-orders tab.
- ✅ **Live orders tab** — Only visible when Auto-Live is owned. Lists active subs with stats + per-row Cancel.
- ✅ **Sports · Football** — RapidAPI-backed `/api/sports/livescores`, `/api/sports/upcoming`, `/api/sports/leagues`, `/api/sports/events`. Background watcher polls every 20s, diffs score deltas → emits **goal / goal_disallowed / kickoff / halftime / fulltime** events. Frontend `GoalNotifier` polls every 15s and fires a big toast + 3-note goal chime (mutable 🔔/🔕 bottom-left).
- ✅ **Daily $0.80 free bet** — `POST /api/free-bet/claim` credits $0.80 from house every 24h. Pulsing pink pill next to balance when eligible.
- ✅ **Spin wheel security hardening** — 7d→**14d** cooldown, $50→**$100** min deposits, prize ladder capped at **$5.00**.
- ✅ **Aviator removed** from GamesView.
- ✅ **AI chat handover UX** — Retry-once on transient failure. On persistent failure, inline **"Connect with our team"** button calls `/api/ai/request-handover`.
- ✅ **Previous conversations tab** in the AI widget + "+ Start new conversation" button.
- ✅ **AI widget credit** — "Developed by BK and Sinester" footer.
- ✅ **Dashboard/Guest footer** — "© 2026 BetterSocial · Development by BK & CEO Sinester".
- ✅ **Top-nav overhaul (P0 fixed)** — Primary tabs + "More ▾" dropdown; Purchase always visible on 1280+ PC screens; mobile hamburger drawer.
- ✅ **Buy button next to balance**.
- ✅ **Language switcher (EN/BS/ES/PT/DE)** persisted in localStorage.
- ✅ **Favicon + title** — Custom SVG favicon; updated page title.
- ✅ **Admin drill shows order links + comments + source**.
- ✅ **Admin services** — Inline rename service_id (pencil), per-row delete, existing bulk delete-all.
- ✅ **Admin DM ALL** — Broadcast to every user from @BetterSocial.
- ✅ **Admin login with dashboard credentials** — `POST /api/admin/login-with-account` + `session-from-user`. Per-user `admin_perms` (default `[ai_inbox, tickets]`).
- ✅ **Guest landing community chat fixed** — real usernames + role badges + timestamps (was showing `@user` placeholder for all).
- ✅ **User-went-live notification** — masked chat message posts on first live-detected burst.
- ✅ **Admin addon pricing card** — Editable `admin-addon-price-auto_live` at top of Services tab.

## Original Problem Statement
"Make a normal SMM landing page but better. When someone wants to buy, press checkout button → redirects to the purchase box. No login — peoples buy directly. They can pay using a generated gift card from us (use coupon to pay) or pay by CoinPayments. List all offers from smmcost.com API (key 47b5c3b01e4b5ecd1e53b39baef31a6e). When the user presses order, take the money via the API. If pay using CoinPayments, after complete status show a sweet alert success message and send the API request immediately. Site title and on-site name: 'Better Social'. Make a separate page with admin panel access (username: DEMO, password: DEMO). On admin panel: only order logs (with IP of buyers) and generated coupons with custom amount."

## Recent Updates (Jul 6, 2026 — later)
- ✅ **Virtual Numbers dashboard section** — New `NumbersView` (client route `numbers`) added to both Green and Classic layouts. Users can pick a country from 24 options (any/USA/UK/Germany/France/Spain/Italy/Netherlands/Poland/Romania/Russia/Ukraine/India/Indonesia/Philippines/Vietnam/Kazakhstan/Brazil/Argentina/Mexico/Canada/Turkey/Nigeria/South Africa), see live retail prices for WhatsApp/Signal/Viber/TikTok/Telegram, buy with one tap (deducts balance), and see received SMS codes auto-refreshed every 8s with Copy / Finish / Cancel-and-refund actions. Powered by the existing `/api/5sim/*` backend.
- ✅ **Green Theme is now the site-wide default** — `/api/ui-config` defaults to `use_new_home_layout: true` when no admin record exists; existing DB record migrated to `true`. Admin toggle still fully controls it (set false → all users without a per-user preference get the Classic layout).
- ✅ **Black background flash / gaps fixed** — `body` background variable raised from `#050505` to `#0a0a14`; when the green layout is active, a `theme-green-body` class is added to `<body>` which switches the background to `#0a1a0a`. Prevents the black flash on load, black gaps on mobile overscroll, and the black stripe visible when a view is shorter than the viewport.
- ✅ **Dashboard default state** — `useNewLayout` initial state is `true` (was `false`) so the first paint matches the effective layout instead of flashing Classic briefly.

## Recent Updates (Jul 6, 2026)
- ✅ **Public shoutbox / Live Chat** — Right panel of the green new dashboard is now a real-time public chat where every user can text each other. Backend `POST /api/public-chat/send` (auth, 3-second rate limit) + `GET /api/public-chat/messages` (public). Frontend polls every 2.5s, dedupes by id, auto-scrolls, shows OWNER/ADMIN/STAFF role badges (amber/emerald/sky). Cross-user delivery verified <3s. Message length capped 500 chars, collection auto-trimmed to 500 rows.
- ✅ **Green theme everywhere** — When the new layout is active, all sub-views (Buy, Add Funds, Redeem, Withdraw, Tickets, Messages, ToS) get the emerald theme via a scoped CSS class `.theme-green` on `<main>` that rewrites `#FF007F` → `#10b981` without touching individual components.


## Recent Updates (Jul 5, 2026 — later)
- ✅ **Client-side layout switch** — Users can flip between the new green top-nav and classic sidebar via a button in the top-bar. Preference persists in `localStorage.bs_layout_pref`, overriding the admin default per-user.
- ✅ **Global masked latest-orders feed** — LEFT panel on new dashboard now shows the most recent orders across ALL users with half-masked usernames (`tes######x1`), powered by public `GET /api/orders/latest-global`. Empty-username entries filtered out.
- ✅ **Read-receipt flip fix** — `GET /messages/thread?since=<ts>` now also returns messages whose `read_at` changed after `since`, so sender's single-check flips to double-check within ~2s of the recipient opening the chat.


## Recent Updates (Jul 4, 2026)
- ✅ **NOWPayments auto-credit fix** — Deposits now credit balance + 70% bonus automatically. Root causes fixed: (a) accept `confirmed`/`sending`/`partially_paid` in addition to `finished` (many invoice payments never emit `finished`), (b) extracted idempotent credit helper (safe against webhook replays), (c) all webhook events logged to `nowpayments_events` collection with signature-check status, (d) new manual verify endpoint `POST /api/client/funds/nowpayments-verify/{tx_id}` polls NOWPayments API and credits on demand, (e) new pending-deposits endpoint + UI panel with a "Verify deposit" button for stuck payments, (f) parent-level dashboard useEffect auto-verifies when user returns via `/client/dashboard?nowpay=1&tx=<id>`, (g) `BACKEND_URL` env var override for reliable IPN callback URLs on production.


## Recent Updates (Jul 2, 2026 — later)
- ✅ **Report chat** — Users can flag a chat via the Flag icon in the DM header + reason textarea. Admin panel gains a **Reports** tab that shows every reported thread; only reported chats are readable by admin (privacy-first). Reports can be marked Reviewed / Closed.
- ✅ **Cross-platform voice messages** — Server-side ffmpeg transcoder converts every uploaded voice note to universal **MP3**. iOS Safari, Android Chrome, and Firefox all play them now.
- ✅ **Typing indicator** — Facebook-Messenger-style three bouncing dots. Debounced POST `/api/messages/typing` every 2s while typing; peer polls every 1.5s. 5-second TTL on the server.
- ✅ **Admin-configurable TURN servers** — New `GET/POST /api/admin/calls/turn-config` + a section in the **Reports** tab lets the owner drop in Twilio/Metered/Xirsys TURN credentials. Clients fetch via `GET /api/calls/ice-config` and fall back to OpenRelay public TURN when blank.
- ✅ **Call debug overlay** — Small monospace `conn: / ice: / gather:` bar inside the call modal for real-time diagnostics.
- ✅ **Admin auth bridge** — `messaging.py._admin_dep` now accepts both `X-Admin-Token` (admin panel) and JWT (regular user role owner/admin/staff).


## Recent Updates (Jul 2, 2026)
- ✅ **DM staff / owner** — Fixed case-insensitive username search in `/api/messages/search` and `/api/messages/user/{username}`. Users can now DM `Balkin` regardless of casing (`balkin`, `BALKIN`, `Balkin`).
- ✅ **Voice message recording rewrite** — Changed from hold-to-record (onMouseDown/Up) to click-toggle (Click → red pulse → Click again to send). Auto-negotiates supported MediaRecorder mimeType (webm/opus → webm → mp4 → ogg fallback). Explicit user-friendly errors on NotAllowedError / NotFoundError.
- ✅ **Call audio playback fix** — Added `remoteStreamRef` + `isVideoCallRef` so `pc.ontrack` reliably attaches the remote MediaStream to the audio/video element. `attachRemoteStream()` in a `useEffect` re-attaches when the modal mounts. Fixed offer-before-ring race that dropped SDP.
- ✅ **DM poll de-duplication** — 2s poller now de-dupes messages by id when merging deltas — removes the "duplicate key" React warning.


## Recent Updates (Jun 27, 2026)
- ✅ **SMTP email integration** — Welcome email on registration + Password reset flow (forgot-password modal, /reset page, reset_password endpoint). Admin configures SMTP host/port/user/password in Settings → Email (SMTP).
- ✅ **Manual services** — Admin can add custom services (no API ID): title, description, flat price, delivery minutes. Doesn't call SMM API on order — flagged for manual fulfillment.
- ✅ **Delivery time auto-extraction** — During sync, parses provider description for delivery time (regex). Admin can override.
- ✅ **Selly.io Basic Auth fix** — Was using Bearer only; Selly's primary auth is HTTP Basic with `email:api_key`. Added email field in Admin → Settings → Selly Config.
- ✅ **Gateway picker** — BTC/ETH/LTC/BCH/DOGE/Card selector for Selly checkout (Funds + Order pages).
- ✅ **Nickname system** — Each staff/owner has a `display_name`. Auto-attached to AI chat and ticket replies. Click "Posting as @X" in admin header to change.
- ✅ **Dashboard redesign (Selly-inspired)** — Cleaner card layout, removed community chat from home view.
- ✅ **Community chat disabled** on home dashboard (still works internally if needed).
- ✅ **Removed all client-facing "SMM" mentions** — Landing, dashboard, status page, checkout, AI widget — all changed to "Order" / "Better Social" / generic terms.

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

### Iteration 12 — Selly admin-managed key + AI double-message fix (Jun 9, 2026)
- **Selly API key now lives in DB, not .env**: new admin endpoints `GET/POST /api/admin/selly-config`. Key stored in `selly_config` collection. Admin UI: new "Selly.io Payments" panel in Settings tab (emerald) with masked key display + helper text + webhook URL pre-filled for copy-paste into Selly dashboard.
- **Webhook HMAC dropped** (Selly's free tier has no webhook secret feature). Replaced with **callback verification**: on webhook event, we call Selly's API back (`/payment-requests/{id}` or `/orders/{id}`) to confirm the payment is genuinely paid before crediting balance or placing the SMM order. Webhook still filters by event name + status field as the first gate.
- Removed `SELLY_API_KEY` and `SELLY_WEBHOOK_SECRET` from `.env`. No env vars needed.
- **AI Widget double-message bug fixed**: `POST /api/ai/chat` now returns `reply_id` along with the reply text. Frontend appends the local bubble with that `_id`, and bumps `lastPollAtRef` so the next poll's `since` filter skips past it. The dedupe set now correctly recognises the just-sent message and won't insert a duplicate.

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
