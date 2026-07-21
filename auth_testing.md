# Auth Testing Playbook (Emergent-managed Google Auth)

See the full playbook at the bottom of the Emergent Auth integration returned by the integration agent.
Key steps for the testing agent:

## Test User & Session (mongosh)
```
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  id: userId, username: 'gtest' + Date.now(), email: 'test.user.' + Date.now() + '@example.com',
  role: 'user', avatar_url: 'https://via.placeholder.com/150', created_at: new Date().toISOString(),
  auth_provider: 'google',
});
db.google_sessions.insertOne({
  user_id: userId, session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000), created_at: new Date(),
});
print('token=' + sessionToken); print('uid=' + userId);
"
```

## Curl checks
- `GET /api/auth/me` with `Authorization: Bearer <jwt>` OR cookie `session_token=<google_session>` returns the user
- `GET /api/auth/google-status?session_id=<sid>` (custom endpoint) exchanges Emergent session_id for either JWT or `{ needs_username: true, signup_token }`
- `POST /api/auth/google-finalize` with `{ signup_token, username }` returns JWT + user

## Frontend flow
- Landing/Login page has "Continue with Google" button → redirects to `https://auth.emergentagent.com/?redirect=<origin>/client/login`
- After Google, user returns with `#session_id=xxx` in URL fragment
- ClientAuth reads the fragment, calls `/api/auth/google-status` with the session_id
- If `needs_username=true` → show a mandatory username modal → `/api/auth/google-finalize`
- If token returned → log user in and go to `/client/dashboard`
