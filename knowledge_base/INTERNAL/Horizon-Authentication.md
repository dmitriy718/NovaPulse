# Authentication

This document covers the complete authentication architecture in HorizonAlerts, including Firebase setup, token verification, account lockout, and the auth context.

---

## Firebase Configuration

### Client-Side (Next.js)

Firebase client SDK is initialized in `apps/web/app/lib/firebase.ts`. Configuration is loaded from `NEXT_PUBLIC_FIREBASE_*` environment variables:

```
NEXT_PUBLIC_FIREBASE_API_KEY
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
NEXT_PUBLIC_FIREBASE_PROJECT_ID
NEXT_PUBLIC_FIREBASE_APP_ID
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET
```

The client SDK handles:
- Sign up with email/password
- Sign in with email/password
- Google SSO sign-in
- Email verification (sending verification emails)
- Password reset
- Token refresh (automatic via `onIdTokenChanged`)

### Server-Side (Fastify API)

Firebase Admin SDK is initialized in `services/api/src/auth/firebase.ts`.

**Service Account Resolution Priority**:
1. `FIREBASE_SERVICE_ACCOUNT_BASE64` environment variable (Base64-encoded JSON) -- best for Docker/VPS
2. `FIREBASE_SERVICE_ACCOUNT_PATH` environment variable (file path)
3. `./horizonsvcfirebase.json` (default file path)
4. `./horizontalv2.json` (fallback file path)

The service account is resolved once at module load and cached. The Firebase app is initialized lazily on first use.

```typescript
export function firebaseConfigured(): boolean {
  return Boolean(_cachedServiceAccount);
}

export async function verifyFirebaseToken(idToken: string) {
  const firebaseApp = getFirebaseApp();
  if (!firebaseApp) return null;
  const decoded = await admin.auth(firebaseApp).verifyIdToken(idToken);
  return {
    uid: decoded.uid,
    email: decoded.email || "",
    email_verified: Boolean(decoded.email_verified),
  };
}
```

### Production Validation

In `env.ts`, production builds validate:
1. `DATABASE_URL` is present
2. `JWT_SIGNING_KEY` is at least 12 characters
3. Firebase service account file exists at the configured or default path

---

## Token Verification Flow

The `requireAuth` decorator on the Fastify server handles all authentication:

```
Request -> Extract Bearer token from Authorization header
         |
         v
     Token present?
    /         \
   No          Yes
   |            |
   v            v
  401      Firebase configured?
           /         \
         Yes          No
          |            |
          v            v
  verifyFirebaseToken   jwtVerify
    |        |            |
  Success  Failure     Success/Failure
    |        |            |
    v        v            v
  Set user  401         Set user / 401
```

**Critical behavior**: When Firebase IS configured, there is NO fallback to JWT. If Firebase verification fails, the request is rejected with 401. This prevents token confusion attacks.

### Request User Object

After successful authentication, `request.user` contains:

```typescript
{
  uid: string;          // Firebase UID
  email: string;        // User's email address
  email_verified: boolean;  // Whether email has been verified
}
```

---

## Auth Context (Frontend)

The `AuthProvider` in `apps/web/app/context/auth-context.tsx` wraps the entire application and provides auth state via React Context.

```typescript
const AuthContext = createContext<{
  user: User | null;       // Firebase User object
  loading: boolean;        // True until initial auth state resolves
  logOut: () => Promise<void>;
}>({...});
```

### How It Works

1. On mount, subscribes to `onIdTokenChanged` which fires:
   - Immediately with the current auth state
   - Whenever the ID token refreshes (automatic)
   - When the user signs in/out
2. Sets `loading = false` after first callback
3. Components use `useAuth()` hook to access auth state

### Dashboard Protection

`apps/web/app/dashboard/layout.tsx` implements auth guards:

1. **Loading state**: Shows "Loading Dashboard..." while auth resolves
2. **No user**: Redirects to `/auth`
3. **Email not verified**: Shows a full-screen verification modal that:
   - Blurs the dashboard content behind it
   - Polls `currentUser.reload()` every 3 seconds
   - Offers a "Resend Verification Email" button
   - Automatically dismisses when email is verified
4. **Robots meta**: Injects `noindex, nofollow` to prevent search indexing of dashboard

---

## Account Lockout System

### Login Attempt Tracking

The `POST /auth/login-attempt` endpoint tracks all login attempts.

**Rate limit**: 5 requests per 15 minutes (to prevent the tracking endpoint itself from being abused).

### Lockout Flow

```
Login attempt (failure)
  |
  v
Count recent failures in last 30 minutes
  |
  v
failCount == 2 -> Send warning email (failedLogin template)
  |
  v
failCount >= 3 -> Lock account for 30 minutes
                -> Send lock notification email (accountLocked template)
                -> Return { status: "locked", locked_until: ISO8601 }
```

### Lock Status Check

`GET /auth/lock-status?email=xxx` is a public endpoint (no auth required, rate limited to 10/min) that returns:
- `{ locked: false }` if not locked or lock expired
- `{ locked: true, locked_until: ISO8601, minutes_remaining: N }` if locked

**Security note**: This endpoint does NOT reveal whether the email exists. If the email is not found, it returns `{ locked: false }`.

### Lock Expiry

- Locks expire automatically after 30 minutes
- The `locked_until` column value is compared to `new Date()` at check time
- On successful login, `failed_login_count` is reset to 0 and `locked_until` is set to NULL

---

## Registration Flow

### Endpoint: POST /auth/register

1. **Auth required**: User must already have a Firebase account (token verified)
2. **Schema validation**: Zod validates all fields (firstName, lastName, age >= 18, zipCode >= 5 chars, email)
3. **Email security check**: Token email must match body email (case-insensitive) -- returns 403 on mismatch
4. **Database upsert**: INSERT INTO users ... ON CONFLICT (uid) DO UPDATE
5. **Verification email**: Firebase Admin SDK generates a custom verification link
6. **Send email**: Verification email sent via SMTP (support@horizonsvc.com)

### Welcome Email

After the user verifies their email, the frontend calls `POST /auth/welcome` to trigger a welcome email. This is a separate step because email verification happens asynchronously.

---

## Security Emails

Security-related emails are always sent regardless of user notification preferences:

| Template | Trigger | Data Included |
|---|---|---|
| `failedLogin` | 2 failed logins in 30min | firstName, attemptCount, ipAddress, timestamp |
| `accountLocked` | 3+ failed logins in 30min | firstName, ipAddress, timestamp |
| `personalInfoChanged` | Profile name updated | firstName, changedFields, ipAddress, timestamp |
| `passwordChanged` | Password changed | firstName, ipAddress, timestamp |

These emails use `skipPreferenceCheck: true` and the `SECURITY_KEYS` set ensures they cannot be disabled.

---

## JWT Fallback (Development)

When Firebase is not configured (no service account available):
- The server falls back to local JWT verification
- JWTs are signed with `JWT_SIGNING_KEY` (must be at least 12 chars in production)
- This mode is intended only for local development and staging

**Environment variable**: `JWT_SIGNING_KEY` defaults to `"dev-secret-change-local-only"` but throws an error if this value is used in production.

---

## Environment Variables

### Client-Side (NEXT_PUBLIC_*)

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_FIREBASE_API_KEY` | Yes | Firebase web API key |
| `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` | Yes | Firebase auth domain |
| `NEXT_PUBLIC_FIREBASE_PROJECT_ID` | Yes | Firebase project ID |
| `NEXT_PUBLIC_FIREBASE_APP_ID` | Yes | Firebase app ID |
| `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID` | Yes | Firebase messaging sender |
| `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET` | Yes | Firebase storage bucket |

### Server-Side

| Variable | Required | Description |
|---|---|---|
| `FIREBASE_SERVICE_ACCOUNT_BASE64` | Alt | Base64-encoded service account JSON |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Alt | Path to service account JSON file |
| `JWT_SIGNING_KEY` | Yes | JWT signing secret (min 12 chars in prod) |

"Alt" means one of the Firebase service account options must be provided (or default file paths must exist).

---

*Last updated: March 2026*
