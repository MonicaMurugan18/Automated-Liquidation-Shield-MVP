# Security

## Scope and status

This is a hackathon prototype. It **simulates** DeFi liquidation protection:
there is no wallet connection, no smart contract, no signed transaction and no
mainnet interaction of any kind. Every simulated receipt is flagged
`simulated: true` and its hash is prefixed `0xSIM`.

Do not deploy this against real funds. It has not been audited.

## Handling credentials

- No secret is ever hard-coded. Everything is read from the environment.
- `backend/.env.example` and `frontend/.env.example` document the variables;
  the real `.env` files are gitignored and must never be committed.
- The Supabase **service-role key** is server-side only. It bypasses Row Level
  Security, so it must never reach the browser or any `VITE_*` variable —
  anything prefixed `VITE_` is inlined into the public bundle.
- The frontend holds no credentials at all. It talks only to the FastAPI
  backend, which is the sole holder of the database key.

## Database posture

`supabase/schema.sql` enables Row Level Security on every table and defines no
permissive policies, so the `anon` and `authenticated` roles can read and write
nothing. The backend's service role bypasses RLS by design. Add per-user
policies before letting a browser talk to the database directly.

A database constraint enforces that any row marked `simulated` carries a
`0xSIM` transaction hash, so simulated and real receipts can never be confused.

## Automated checks

`.github/workflows/ci.yml` runs on every push and pull request:

| Check | Blocking | What it covers |
| --- | --- | --- |
| Secret scan | yes | Committed `.env`, populated service keys, private keys, Supabase JWTs |
| `pytest` | yes | 238 tests across the engines and the API |
| Lint + build | yes | Frontend correctness gates |
| `pip-audit` | no | Python dependency advisories |
| `npm audit` | no | JavaScript dependency advisories |

The dependency audits are reported but non-blocking: advisories appear outside
this repo's control and should not turn a demo red. The secret scan is
blocking, because a committed credential is our own mistake.

## Reporting an issue

Open a GitHub issue. Since nothing here touches real funds, there is no
embargo process — but please do not paste real credentials into an issue.
