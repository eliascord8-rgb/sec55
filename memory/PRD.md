# Better Social — PRD

## Original problem statement
Better Social is an SMM/live-automation platform (TikTok/Kick focus) with wallet, add-ons, client API access, and TikTok lookup utilities. Frontend: React. Backend: FastAPI. DB: MongoDB. User deploys to a live VPS (better-social.pro) — preview DB is separate from prod DB.

## Users
- Guests browsing landing & TikTok Finder
- Signed-in clients placing orders, subscribing to Auto-Live, using wallet, add-ons and JAP-style API
- Owner/admin/moderator operating panel, moderating chat, running Discord bot

## Core features (implemented)
- Client dashboard, wallet, order flow, multi-order, bulk orders
- Auto-Live subscriptions (always / live_only modes) incl. custom comments
- JAP/SMMCost-style `/api/v2` client API with key regenerate
- TikTok Finder page `/tiktok-finder` with username + user-ID reverse lookup (cache-backed)
- Live community chat with role badges (OWNER/ADMIN/MOD)
- Discord bot (moderation, purchase notifications, welcomer) — token in `db.discord_config`
- Discord OAuth login config UI in Admin
- NOWPayments crypto deposits (webhook + reconciler + manual verify)

## Shipped 2026-06 (this session — 10-point batch)
1. **Add-ons store**: `blacklist_package` "BlackList Username Package" €180 (platform select tiktok/kick/instagram/snapchat/telegram, 1 slot per buy, repeatable); `id_finder` renamed "Find User By ID — Unlimited" €200 with multi-line features; `auto_live_week` $80 already existed. EUR addons convert to USD at live rate (`_eur_usd_rate`, open.er-api.com, cached 6h) — catalog returns `price_usd`.
2. **Blacklist enforcement**: `_enforce_username_blacklist` blocks orders on usernames blacklisted by another user (403) and rejects vm.tiktok/vt.tiktok short links (400) in order-with-balance, orders/multi, live-sub create. BlacklistManager UI in Add-ons store with platform select.
3. **Auto-Live upgrades**: order by numeric TikTok user-ID (resolved from `tiktok_lookup_cache`); username-change auto-follow (sub stores `tiktok_user_id`, worker re-checks cache each cycle, logs rename); `paused` → `on_hold` with auto-resume when balance topped up (worker processes on_hold/paused subs); Cancel works on on_hold; frontend shows "ON HOLD — top up balance to auto-resume"; multi-username input (comma/newline separated → one sub each).
4. **Discount keys**: Admin → Discounts tab (owner-only, `check_owner`): generate key (percent 1–100, optional code/max_uses), list, delete. Client Settings → Discount tab: redeem key. `_apply_user_discount` reduces charges on order-with-balance, orders/multi, live-sub — NEVER addons. Atomic max_uses increment.
5. **Client Discord bot management**: "Manage Discord" in dashboard More menu → invite bot (GET /api/discord/invite-url from oauth_client_id), per-guild config (guild_id unique per account, welcome channel/text, welcomer toggle, custom bot nickname, feature toggles anti_raid/moderation/blacklist/anti_nuke) stored in `db.client_discord_guilds`; bot `on_member_join` uses per-guild config first, falls back to global welcomer; applies nickname lazily.
6. **Moderator role**: PUT /admin/users/{id} accepts role=moderator; Users panel role cell is now a dropdown (user/moderator/admin/owner); "Support Panel" button (amber) shows for moderator/admin in dashboard top bar + mobile; staff sessions gate admin tabs by admin_perms (pre-existing).
7. **Fixed critical bug**: `SecurityView` (2FA page) was rendered but never imported in ClientDashboard → runtime crash ("blue frozen page"). Imported from SettingsAndAviator — fixed.
8. **Fixed CurrencyContext** exchange-rate fetch (frankfurter.dev 404 → open.er-api.com).
9. Verified working in preview (user's VPS "Not found" errors are stale-build issues): NOWPayments create, manual verify, API key regenerate, Discord OAuth save, notify config save, TikTok lookups.

## Shipped 2026-06 (follow-up)
- **Referral Rewards**: users get share link `/?ref=CODE` (code auto-generated, stored `users.referral_code`); signup attributes `referred_by`; on friend's FIRST approved deposit referrer earns fixed reward (default $5 — balance transaction `referral_reward` + `$inc withdrawable_balance`), friend gets +5% bonus (`referral_friend_bonus`). Idempotent via atomic `referral_rewarded` flag. Hooks in: coupon redeem, NOWPayments credit, PayPal IPN, selly webhook, admin tx approve. Endpoints: GET /api/client/referrals (masked invitees, earned total), GET/POST /api/admin/referral-config (owner-only, reward_usd/friend_bonus_pct/enabled). UI: Referrals view in dashboard (nav-referrals), ReferralConfigCard at top of Admin → Discounts tab. ?ref captured in App.js → localStorage bs_ref → sent at register.
- **Auto-Live extras**: "Live check" button per sub (GET /api/debug/tiktok-live/{handle}, toasts live/offline); "Edit @" button changes target username on a running sub (POST /api/client/live-sub/{sid}/username — accepts handle or numeric user ID, blacklist-checked, logs the change).

## Key endpoints (new this session)
- GET/POST/DELETE `/api/admin/discount-keys[/{code}]` (owner-only)
- POST `/api/client/discount/redeem`, GET `/api/client/discount`
- GET `/api/discord/invite-url`
- GET/POST/DELETE `/api/client/discord/guilds[/{gid}]`
- POST `/api/client/addons/blacklist` now takes `platform`

## DB collections (new)
- `discount_keys`: {code, percent, max_uses, uses, active, created_at}
- `client_discord_guilds`: {guild_id (unique), user_id, welcome_channel_id, welcome_text, welcomer_enabled, bot_nickname, features{}}
- `users` new fields: discount_code, discount_pct; `username_blacklist` new field: platform; `live_subscriptions` new: tiktok_user_id, previous_username, hold_reason

## Shipped 2026-08-01 (this session)
- **In-dashboard Finder page** (view=`finder`, nav-finder, shown when user owns `id_finder`): 2-tab UI (User ID / @username) using authed `/api/tools/tiktok-lookup*`. Stat boxes, avatar, verified badge, country, creation date, copy-user-id.
- **In-dashboard Blacklist page** (view=`blacklist`, nav-blacklist, shown when user owns `blacklist_package`/`username_blacklist`): BlacklistManager extracted from AddonsView into its own page.
- **AddonsView "Open" button fixed**: `id_finder` → finder; `blacklist_*` → blacklist; `auto_live` → live; else → buy. Previously every non-auto-live add-on wrongly went to Buy.
- **`/tools/tiktok-lookup-by-id` made public** (was authed+premium → 401 "Not authenticated" on guest `/tiktok-finder`). New `optional_current_user_dep` in auth_and_chat. Rate limit 10/min anonymous, 60/min if authed with `id_finder` or staff.
- **Live TikTok reverse-lookup fallback**: `_tiktok_reverse_by_id_live` tries `/api/search/user/full/?keyword={uid}` + HTML search page. Cache-first, then live search, then 404. Populates cache on success.
- **New public tool endpoints** (all under `/api/tools`, no auth, rate-limited):
  - GET `/tools/tiktok-post?url=` — TikTok video/photo/reel metadata + no-watermark playAddr, cover, music, images carousel, stats
  - GET `/tools/instagram-lookup?username=` — IG profile (avatar HD, followers, following, posts, verified, private, bio, category, external_url, best-effort country from bio)
  - GET `/tools/instagram-post?url=` — IG post/reel image+video URLs from og:meta tags (works logged-out for public posts)
  - GET `/tools/discord-user?user_id=` — Discord snowflake → username, global_name, avatar/banner URLs, badges, account creation date (uses admin's bot_token from discord_config)
- **`/tiktok-finder` page cleanup**: Replaced "Live chat" (community) button with "Support" button that opens GlobalSupportWidget via `bs-open-support-chat`. Hid community-chat FAB on this route.

## Key endpoints (new this session)
- GET `/api/tools/tiktok-post`
- GET `/api/tools/instagram-lookup`
- GET `/api/tools/instagram-post`
- GET `/api/tools/discord-user`
- GET `/api/tools/tiktok-lookup-by-id` (now public + live-search fallback)

## Backlog / Next tasks
- P0 (user env): user must redeploy VPS (git pull + rebuild) to expose the new endpoints — nginx `/api/` block already patched into `better-social` config (all SSL server blocks). Requires: `cd /opt/better-social && git pull && cd frontend && yarn build && systemctl reload nginx`. Then Cloudflare cache purge if public still 404s.
- P0: Frontend `/tiktok-finder` still shows only TikTok tabs — needs UI tabs for TikTok Post, Instagram User, Instagram Post, Discord User (backend endpoints ready). Not yet built in this session.
- P0: Configure NOWPayments IPN URL in merchant dashboard so real deposits auto-credit
- P1: Discord bot token invalid on VPS ("Improper token has been passed") — admin must re-save bot token in Admin → Discord
- P1 (security, flagged by test agent): login brute-force lockout, HttpOnly cookie auth, CORS origin allowlist
- P2: Discord health widget, API usage history
- P3: Refactor server.py, Admin.jsx, ClientDashboard.jsx into modules

## Backlog / Next tasks (older, unchanged)

## Constraints
- All URLs from env; `/api` prefix; wallet settles in USD; no secrets in code/logs
