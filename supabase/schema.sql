-- ===========================================================================
-- Automated Liquidation Shield -- Supabase (PostgreSQL) schema
-- ===========================================================================
-- Run this once in the Supabase SQL editor (Dashboard -> SQL Editor -> New
-- query -> paste -> Run). It is idempotent: safe to re-run.
--
-- The backend runs perfectly well WITHOUT this. With no Supabase credentials
-- configured it falls back to an in-process store, so the demo never depends
-- on a network round trip. Apply this when you want history to survive a
-- restart.
--
-- Row Level Security is enabled on every table. The backend talks to Supabase
-- with the SERVICE ROLE key, which bypasses RLS -- so the policies below exist
-- to protect the tables from anon/authenticated clients (a browser must never
-- hold the service key).
-- ===========================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
create table if not exists public.users (
  id            uuid primary key default gen_random_uuid(),
  email         text unique,
  display_name  text,
  -- Risk preferences, mirroring backend RiskPreferences.
  mode                  text    not null default 'AUTONOMOUS'
                                check (mode in ('AUTONOMOUS', 'ADVISORY')),
  target_health_factor  numeric not null default 1.50 check (target_health_factor > 1),
  trigger_health_factor numeric not null default 1.20 check (trigger_health_factor > 1),
  max_slippage_pct      numeric not null default 1.50 check (max_slippage_pct > 0),
  available_capital     numeric not null default 4000 check (available_capital >= 0),
  created_at    timestamptz not null default now()
);

-- The seed user the backend writes as when DEMO_USER_ID is left at its default.
insert into public.users (id, email, display_name)
values ('00000000-0000-0000-0000-000000000001', 'demo@liquidation-shield.local', 'Demo user')
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- positions -- one row per analysis, so the Health Factor history is queryable
-- ---------------------------------------------------------------------------
create table if not exists public.positions (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid references public.users(id) on delete cascade,
  collateral_asset      text    not null default 'ETH',
  collateral_amount     numeric not null check (collateral_amount >= 0),
  debt_asset            text    not null default 'USDC',
  debt_amount           numeric not null check (debt_amount >= 0),
  collateral_price      numeric not null check (collateral_price > 0),
  liquidation_threshold numeric not null check (liquidation_threshold > 0 and liquidation_threshold <= 1),
  health_factor         numeric not null,
  risk_level            text    not null
                                check (risk_level in ('SAFE','WARNING','DANGER','LIQUIDATABLE')),
  created_at            timestamptz not null default now()
);

create index if not exists positions_user_created_idx
  on public.positions (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- scenarios -- one row per ladder run; the rungs live in the jsonb payload
-- ---------------------------------------------------------------------------
create table if not exists public.scenarios (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid references public.users(id) on delete cascade,
  base_price           numeric not null check (base_price > 0),
  target_health_factor numeric not null,
  results              jsonb   not null,
  created_at           timestamptz not null default now()
);

create index if not exists scenarios_user_created_idx
  on public.scenarios (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- protection_strategies -- the full candidate set plus which one was selected
-- ---------------------------------------------------------------------------
create table if not exists public.protection_strategies (
  id                      uuid primary key default gen_random_uuid(),
  user_id                 uuid references public.users(id) on delete cascade,
  health_factor           numeric not null,
  risk_level              text    not null,
  candidates              jsonb   not null,
  selected_strategy_type  text,
  explanation             text,
  created_at              timestamptz not null default now()
);

create index if not exists protection_strategies_user_created_idx
  on public.protection_strategies (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- rescue_transactions -- executed rescues. SIMULATED ONLY in this build.
-- ---------------------------------------------------------------------------
create table if not exists public.rescue_transactions (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid references public.users(id) on delete cascade,
  tx_hash               text    not null,
  simulated             boolean not null default true,
  strategy_type         text    not null,
  strategy_name         text,
  action_amount         numeric not null default 0,
  total_cost            numeric not null default 0,
  health_factor_before  numeric,
  health_factor_after   numeric,
  collateral_price      numeric,
  execution_status      text    not null,
  mode                  text    check (mode in ('AUTONOMOUS','ADVISORY')),
  explanation           text,
  executed_at           timestamptz not null default now(),
  created_at            timestamptz not null default now()
);

create index if not exists rescue_transactions_user_created_idx
  on public.rescue_transactions (user_id, created_at desc);

-- A guard rail, not a formality: if this project ever gains a real execution
-- path, simulated and real receipts must never be confused for one another.
alter table public.rescue_transactions
  drop constraint if exists rescue_transactions_simulated_hash_check;
alter table public.rescue_transactions
  add constraint rescue_transactions_simulated_hash_check
  check (simulated = false or tx_hash like '0xSIM%');

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.users                 enable row level security;
alter table public.positions             enable row level security;
alter table public.scenarios             enable row level security;
alter table public.protection_strategies enable row level security;
alter table public.rescue_transactions   enable row level security;

-- No permissive policies are defined for anon/authenticated: with RLS on and
-- no policy, those roles can read and write nothing. The backend's service
-- role bypasses RLS entirely. Add per-user policies here when you introduce
-- Supabase Auth and let the browser talk to the database directly.
