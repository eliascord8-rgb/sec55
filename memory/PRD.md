# Better Social — PRD

## Original problem statement
Better Social is an SMM/live-automation platform (TikTok/Kick focus) with wallet, add-ons, client API access, and TikTok lookup utilities. Frontend: React. Backend: FastAPI. DB: MongoDB.

## Users
- Guests browsing landing & TikTok Finder
- Signed-in clients placing orders, subscribing to Auto-Live, using wallet, add-ons and JAP-style API
- Owner/admin operating panel, moderating chat, running Discord bot

## Core features (implemented)
- Client dashboard, wallet, order flow
- Custom-comment quantity auto-derived from comment lines (hides quantity input)
- Auto-Live subscriptions incl. custom comments
- JAP/SMMCost-style `/api/v2` client API
- Dedicated TikTok Finder page `/tiktok-finder` with username + user-ID reverse lookup (cache-backed)
- Live community chat (public shoutbox) with global FAB + header button on TikTok Finder
- Discord bot (moderation, notifications) — token stored in `db.discord_config`

## Recently shipped
- 2026-02: Discord bot restart flow — token rotated by owner and saved via admin; bot came online as `Better Social#0191`
- 2026-02: Added a prominent "Live chat" header button on `/tiktok-finder` that opens the community shoutbox

## Backlog / Next tasks
- P0 verified pending: end-to-end signed NOWPayments IPN test (auto-crediting w/o Verify & Credit)
- P0 verified pending: TikTok user-ID reverse-lookup Add-on — unlimited checks for €170 (implementation started, needs full wire-up + test)
- P1: Bonus Modal blocking UI/automation — fix pointer-event interception
- P1: Automatic currency conversion, Balkan translations
- P1: Discord OAuth login + `$deposit` / `$buy` commands (needs bot healthy — done)
- P2: Discord health widget (green/red, latency, guild count)
- P2: API usage history + 1-tap API key rotation on client dashboard
- Refactor: split monolithic `backend/server.py` (~9.5k lines) into routes/models/utils

## Constraints
- All URLs from env; `/api` prefix; MongoDB `PyObjectId` pattern; no secrets in code/logs
