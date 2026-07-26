# Better Social — PRD


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
