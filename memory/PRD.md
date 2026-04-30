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

## Backlog
### P1
- Persist admin sessions in DB (currently in-memory; lost on restart)
- IPN webhook receiver for instant CoinPayments confirmation (currently manual poll)
- Encrypt CoinPayments private key + IPN secret at rest
- Coupon disable/delete from admin
### P2
- Email receipt on success
- Service favorites / quick-pick
- Order status tracking page (smmcost status API)
- Multi-admin support with proper hashed passwords
