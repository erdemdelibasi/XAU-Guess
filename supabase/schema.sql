-- XAU-Guess database schema. This file is the single source of truth.
--
-- Supabase does NOT apply this automatically. After changing it, run the
-- changed statements yourself in the Supabase SQL Editor, and add an entry to
-- the MIGRATIONS section at the bottom so an existing database can be brought
-- forward without being rebuilt.
--
-- Security model: the frontend uses the public anon key and is restricted to
-- SELECT by RLS. Everything that writes (predict.py, retrain.py,
-- kanal_finans.py) runs with the service_role key, which bypasses RLS and is
-- never exposed to a browser.
--
-- MULTI-ASSET: every table that holds market state is keyed by `asset`
-- ('gold' | 'silver', matching assets.ASSETS). There is deliberately no
-- separate table per metal and no singleton table for the ensemble portfolio:
-- XRP-Guess carried a split like that for historical reasons and paid for it
-- with a special case in every query, and a second asset would have doubled
-- the special case rather than the table.

-- ---------------------------------------------------------------------------
-- predictions
-- ---------------------------------------------------------------------------
-- One row per (asset, target_date). The metals trade weekdays only, so the
-- target is a TRADING SESSION rather than a clock time -- there is no Saturday
-- close to score against.
create table if not exists predictions (
    id                      bigserial primary key,
    created_at              timestamptz not null default now(),
    asset                   text        not null,          -- 'gold' | 'silver'
    symbol                  text        not null,          -- 'GC=F' | 'SI=F'

    target_date             date        not null,
    horizon_days            int         not null default 5,

    price_at_prediction     numeric     not null,
    price_source            text,       -- 'GC=F', 'PAXG->GC=F', 'SI=F(stale)' ...

    -- Blended call.
    predicted_direction     text        not null check (predicted_direction in ('UP', 'DOWN')),
    confidence              numeric     not null,
    -- P(up) from the ensemble, and how far that sits from THIS ASSET's
    -- unconditional base rate (gold 0.557, silver 0.539 -- see assets.py).
    -- `edge_over_base` is the number that answers "did the model add anything
    -- today"; confidence alone is high whenever the prior is.
    p_up                    numeric,
    edge_over_base          numeric,
    base_rate_used          numeric,    -- stored per row so a later change to
                                        -- the constant can't silently rewrite
                                        -- how past rows should be read
    predicted_pct_change    numeric,
    predicted_price         numeric,

    -- Per-component calls. Same five columns per component; adding a
    -- component means adding this block and appending to ensemble.COMPONENTS.
    tech_direction          text, tech_confidence   numeric, tech_pct_change   numeric, tech_price   numeric, tech_correct   boolean,
    ml_direction            text, ml_confidence     numeric, ml_pct_change     numeric, ml_price     numeric, ml_correct     boolean,
    macro_direction         text, macro_confidence  numeric, macro_pct_change  numeric, macro_price  numeric, macro_correct  boolean,

    news_direction          text, news_confidence   numeric, news_pct_change   numeric, news_price   numeric, news_correct   boolean,
    claude_direction        text, claude_confidence numeric, claude_pct_change numeric, claude_price numeric, claude_correct boolean,
    claude_reasoning        text,

    -- The confidence BEFORE calibration, for the three calibrated components.
    -- retrain.py fits each night's isotonic curve on THESE, never on the
    -- calibrated column beside them: a curve maps raw -> P(correct), so
    -- fitting the next curve on the previous curve's output and then applying
    -- it to raw input compounds a scale error every night with nothing
    -- raising. The calibrated columns stay -- they are what sized the position
    -- and what the UI shows.
    tech_confidence_raw     numeric,
    ml_confidence_raw       numeric,
    macro_confidence_raw    numeric,

    -- Display weights at prediction time (ensemble.influence_weights).
    weight_technical        numeric, weight_ml    numeric, weight_macro numeric,
    weight_news             numeric, weight_claude numeric,

    -- Market state the decision was made in, so a row reads back without
    -- re-fetching history.
    trend_average           numeric,    -- 200-session average of close
    realised_volatility     numeric,    -- annualised, 60-session
    target_exposure         numeric,    -- what the ensemble portfolio aimed at

    -- Gold/silver ratio and its trailing 250-session z-score. DISPLAY ONLY.
    -- research/ratio.py tested the ratio in five forms x three targets x four
    -- horizons and none of the 60 cells cleared the Bonferroni bar, so no
    -- strategy and no ensemble component reads these. They exist so the UI can
    -- print the ratio WITH its historical position instead of a bare number a
    -- reader would reasonably mistake for a signal.
    gs_ratio                numeric,
    gs_ratio_z              numeric,

    model_version           text,
    -- True when the blend had NO component track record yet and fell back to
    -- ensemble._cold_start's direction vote. The UI needs it: on such a row
    -- the weight_* columns are DEFAULT_WEIGHTS, which is what the vote
    -- actually used but is NOT measured influence, and showing "25%" beside
    -- a caption about measured skill overstates the system.
    cold_start              boolean,

    -- Resolution.
    resolved_at             timestamptz,
    price_at_resolution     numeric,
    actual_direction        text,
    correct                 boolean,

    -- Idempotency. A manual re-run overlapping the scheduled cron would
    -- otherwise write a second row for the same session, double-counting it
    -- in retrain.py's component records AND firing every portfolio's
    -- maybe_trade() twice for what looks like two independent signals.
    -- predict.py checks before doing any expensive work; this is the backstop.
    unique (asset, target_date)
);

create index if not exists predictions_asset_date_idx on predictions (asset, target_date desc);
create index if not exists predictions_unresolved_idx on predictions (resolved_at) where resolved_at is null;

-- ---------------------------------------------------------------------------
-- portfolios / trades
-- ---------------------------------------------------------------------------
-- One row per (asset, strategy). `buyhold` is a real portfolio here, not a
-- line in a report: on both metals it is a genuinely strong strategy (~11.8%
-- a year over 25 years) and it has to be able to beat the clever ones in
-- public where that is what happens.
create table if not exists portfolios (
    asset           text        not null,
    strategy        text        not null,
    cash_usd        numeric     not null default 1000,
    ounces          numeric     not null default 0,
    position        text        not null default 'CASH',
    target_exposure numeric     not null default 0,
    -- Only the `kanalfinans` strategy uses these: it follows a person's
    -- stated levels rather than a computed exposure. NULL everywhere else.
    stop_loss_price numeric,
    resistance_price numeric,
    updated_at      timestamptz not null default now(),
    primary key (asset, strategy)
);

-- Seeds every (asset, strategy) pair. Adding a strategy to
-- trading.STRATEGIES means adding it here for BOTH assets.
insert into portfolios (asset, strategy)
select a.asset, s.strategy
from (values ('gold'), ('silver')) as a(asset)
cross join (values
    ('buyhold'), ('voltarget'), ('trend'), ('defensive'), ('ensemble'),
    ('technical'), ('ml'), ('macro'), ('claude'), ('kanalfinans'), ('miners')
) as s(strategy)
on conflict (asset, strategy) do nothing;

-- Tracked ETFs (assets.TRACKED). A SEPARATE seed because these books run a
-- different and much smaller pipeline: backend/track_etf.py, mechanical
-- strategies only, no prediction row and no model. See that module and
-- research/README.md section 17 -- on GLD and SLV alike the futures
-- scoreboard's ranking changes fundamentally, and only the mechanical
-- strategies survive. BOTH metals get a book: the project is a two-metal one
-- everywhere else, and stopping at gold precisely where the metal becomes
-- buyable would have been a silent narrowing.
--
-- No `model_state` rows for these: model_state tracks ENSEMBLE COMPONENTS'
-- live skill, and no component runs here.
insert into portfolios (asset, strategy)
select a.asset, s.strategy
from (values ('gld'), ('slv')) as a(asset)
cross join (values
    ('buyhold'), ('voltarget'), ('trend'), ('defensive')
) as s(strategy)
on conflict (asset, strategy) do nothing;

create table if not exists trades (
    id                          bigserial primary key,
    created_at                  timestamptz not null default now(),
    asset                       text    not null,
    strategy                    text    not null,
    side                        text    not null check (side in ('BUY', 'SELL')),
    price                       numeric not null,
    ounce_amount                numeric not null,
    usd_amount                  numeric not null,
    fee_usd                     numeric not null,
    cash_after                  numeric not null,
    ounces_after                numeric not null,
    target_exposure             numeric,
    triggered_by_prediction_id  bigint references predictions (id),
    triggered_by_mention_id     bigint,   -- kanal_finans_mentions.id, FK added below
    reason                      text,
    foreign key (asset, strategy) references portfolios (asset, strategy)
);

create index if not exists trades_asset_strategy_idx on trades (asset, strategy, created_at desc);

-- ---------------------------------------------------------------------------
-- model_state  -- each component's live track record, per asset
-- ---------------------------------------------------------------------------
-- Four counters, not one accuracy figure, and that is the whole point. Gold
-- rises 55.7% of the time over this horizon and silver 53.9%, so a component
-- that says UP every day posts a respectable-looking "accuracy" while knowing
-- nothing. ensemble.component_evidence() needs the UP and DOWN records
-- SEPARATELY to measure a component against the base rate rather than against
-- a coin flip -- and per ASSET, because the two base rates differ.
-- Read by the FRONTEND as well as by predict.py: the "Bileşen sicili" table
-- on the page renders these four counters directly, because an influence
-- percentage cannot show that a component has said UP on 121 of 127
-- opportunities. Public SELECT is already granted below.
create table if not exists model_state (
    asset           text    not null,
    component       text    not null,
    up_calls        int     not null default 0,
    up_correct      int     not null default 0,
    down_calls      int     not null default 0,
    down_correct    int     not null default 0,
    -- Display only (ensemble.influence_weights); combine() pools the four
    -- counters directly and never reads this.
    weight          numeric not null default 0,
    updated_at      timestamptz not null default now(),
    primary key (asset, component)
);

insert into model_state (asset, component, weight)
select a.asset, c.component, c.weight
from (values ('gold'), ('silver')) as a(asset)
cross join (values
    ('technical', 0.25), ('ml', 0.25), ('macro', 0.25), ('news', 0.10), ('claude', 0.15)
) as c(component, weight)
on conflict (asset, component) do nothing;

-- ---------------------------------------------------------------------------
-- Kanal Finans TŞ  (YouTube @KanalFinans, Tunç Şatıroğlu)
-- ---------------------------------------------------------------------------
-- An independent opinion feed, NOT an ensemble component. We are not forming
-- a view here, we are reporting one person's -- see kanal_finans.py.

create table if not exists kanal_finans_videos (
    video_id            text primary key,
    video_title         text,
    published_at        timestamptz,
    transcript_found    boolean not null default false,
    created_at          timestamptz not null default now()
);

-- Retry backoff for videos that failed to process. A video appears here only
-- while it is failing; the row is deleted the moment it succeeds. Without
-- this, a transcript that YouTube is IP-blocking would be retried on every
-- run against the very endpoint already refusing us -- the surest way to turn
-- a temporary block into a lasting one.
--
-- NOTHING IN THIS REPO HAS WRITTEN TO IT SINCE 2026-09-08. The transcript
-- fetch moved to Kanal-Finans-Fetcher, and the backoff moved with it -- into
-- a LOCAL file (state/backoff.json) rather than a table, because the whole
-- point of the split was that XAU-Guess and XRP-Guess share one counter, and
-- two Supabase projects cannot. The table is kept rather than dropped: it is
-- harmless, it holds whatever history it accumulated, and dropping a table
-- that a sibling repo might still reference is not a change to make blind.
-- If you are looking for why a video keeps failing, look in the fetcher.
create table if not exists kanal_finans_fetch_attempts (
    video_id        text primary key,
    attempts        int not null default 0,
    last_attempt_at timestamptz,
    last_error      text
);

-- Per-asset opinion extracted from a video. `stance` is the SPEAKER's tone,
-- never this project's view.
create table if not exists kanal_finans_mentions (
    id                  bigserial primary key,
    created_at          timestamptz not null default now(),
    video_id            text        not null references kanal_finans_videos (video_id),
    video_title         text,
    published_at        timestamptz,
    asset               text        not null,   -- 'ALTIN' | 'GUMUS' | 'GENEL'
    summary             text        not null,
    stance              text        not null check (stance in ('UP', 'DOWN', 'NEUTRAL')),
    action              text        not null check (action in ('BUY', 'SELL', 'HOLD')),
    -- Levels in USD per troy ounce, or NULL when he did not give one. The
    -- extraction returns 0 as "not mentioned" and kanal_finans.py converts
    -- that sentinel to NULL, so a stored number is always a real level.
    ounce_target        numeric,
    stop_loss_price     numeric,
    resistance_price    numeric,
    -- NULL = not yet traded on. Written by Kanal-Finans-Fetcher (a sibling
    -- repo shared with XRP-Guess, see CLAUDE.md); read and stamped by this
    -- project's own kanal_finans.py, which no longer talks to YouTube at
    -- all and just applies whatever mentions this column says are pending.
    applied_at          timestamptz
);

create index if not exists kf_mentions_asset_idx on kanal_finans_mentions (asset, published_at desc);
create index if not exists kf_mentions_pending_idx on kanal_finans_mentions (applied_at) where applied_at is null;

alter table trades
    drop constraint if exists trades_triggered_by_mention_id_fkey;
alter table trades
    add constraint trades_triggered_by_mention_id_fkey
    foreign key (triggered_by_mention_id) references kanal_finans_mentions (id);

-- The macro narrative behind the calls: war, US policy, central-bank reserves,
-- the dollar. Separate from `mentions` because these are NOT tradeable
-- instructions -- they are the story, kept so a stance can be read in context
-- rather than as a bare UP/DOWN.
create table if not exists kanal_finans_themes (
    id              bigserial primary key,
    created_at      timestamptz not null default now(),
    video_id        text        not null references kanal_finans_videos (video_id),
    published_at    timestamptz,
    theme           text        not null,   -- see kanal_finans.THEMES
    summary         text        not null,
    -- Which way the speaker thinks this theme pushes the metals.
    impact          text        not null check (impact in ('POSITIVE', 'NEGATIVE', 'NEUTRAL'))
);

create index if not exists kf_themes_idx on kanal_finans_themes (theme, published_at desc);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
-- The frontend reads with the anon key; every write path uses service_role,
-- which bypasses RLS entirely. So: public SELECT, no public INSERT/UPDATE.
do $$
declare t text;
begin
    foreach t in array array['predictions', 'portfolios', 'trades', 'model_state',
                             'kanal_finans_videos', 'kanal_finans_fetch_attempts',
                             'kanal_finans_mentions', 'kanal_finans_themes']
    loop
        execute format('alter table %I enable row level security', t);
        execute format('drop policy if exists %I on %I', t || '_public_read', t);
        execute format('create policy %I on %I for select using (true)', t || '_public_read', t);
    end loop;
end $$;

-- ---------------------------------------------------------------------------
-- MIGRATIONS
-- ---------------------------------------------------------------------------
-- Applied by hand in the Supabase SQL Editor, newest last. `create table if
-- not exists` above will NOT alter a table that already exists, so any change
-- to an existing table needs an entry here as well.
--
-- 2026-09-07  Initial schema (gold only): predictions, portfolio_state,
--             trades, strategy_portfolios, strategy_trades, model_state.
--
-- 2026-09-07  Silver + Kanal Finans. If the gold-only schema was already
--             applied, run this once. It is written to be safe on a database
--             that only ever held gold rows.
--
--   -- 1. Fold the two portfolio tables into one keyed by (asset, strategy).
--   --    Run the `create table portfolios` + seed above FIRST, then:
--   -- insert into portfolios (asset, strategy, cash_usd, ounces, position, target_exposure, updated_at)
--   -- select 'gold', 'ensemble', cash_usd, ounces, position, target_exposure, updated_at
--   --   from portfolio_state where id = 1
--   -- on conflict (asset, strategy) do update
--   --   set cash_usd = excluded.cash_usd, ounces = excluded.ounces,
--   --       position = excluded.position, target_exposure = excluded.target_exposure;
--   -- insert into portfolios (asset, strategy, cash_usd, ounces, position, target_exposure, updated_at)
--   -- select 'gold', strategy, cash_usd, ounces, position, target_exposure, updated_at
--   --   from strategy_portfolios
--   -- on conflict (asset, strategy) do update
--   --   set cash_usd = excluded.cash_usd, ounces = excluded.ounces,
--   --       position = excluded.position, target_exposure = excluded.target_exposure;
--   --
--   -- 2. predictions gains asset/symbol and a new unique key. The old
--   --    constraint must go first or the new one cannot be created.
--   -- alter table predictions add column if not exists asset text;
--   -- update predictions set asset = 'gold' where asset is null;
--   -- alter table predictions alter column asset set not null;
--   -- alter table predictions add column if not exists base_rate_used numeric;
--   -- alter table predictions drop constraint if exists predictions_symbol_target_time_key;
--   -- alter table predictions drop constraint if exists predictions_symbol_target_date_key;
--   -- alter table predictions add constraint predictions_asset_target_date_key
--   --   unique (asset, target_date);
--   --
--   -- 3. model_state gains asset and a composite primary key.
--   -- alter table model_state add column if not exists asset text;
--   -- update model_state set asset = 'gold' where asset is null;
--   -- alter table model_state drop constraint if exists model_state_pkey;
--   -- alter table model_state add primary key (asset, component);
--   --
--   -- 4. Once the copies above are verified, the old tables can go:
--   -- drop table if exists strategy_trades;
--   -- drop table if exists strategy_portfolios;
--   -- drop table if exists portfolio_state;
--
-- 2026-09-07  Ratio context columns on predictions. Display only -- see
--             research/ratio.py, which measured the ratio to carry no
--             directional information (0 of 60 tests). Safe to run twice.
--
--   -- alter table predictions add column if not exists gs_ratio numeric;
--   -- alter table predictions add column if not exists gs_ratio_z numeric;
--
-- 2026-09-08  Pre-calibration confidences. RUN THIS ONE. Without it
--             predict.py's insert fails on the new keys and no prediction is
--             written at all. Safe to run twice.
--
--             Why it exists: retrain.py used to refit each component's
--             calibration curve on `<c>_confidence`, which predict.py writes
--             AFTER applying the previous curve. Once the first curve was
--             fitted every later fit would have been trained on its own
--             output and then applied to raw input -- a compounding scale
--             error with no error message. Nothing had gone wrong yet only
--             because calibration.MIN_RECORDS_TO_FIT (180 resolved rows) had
--             not been reached.
--
--   alter table predictions add column if not exists tech_confidence_raw numeric;
--   alter table predictions add column if not exists ml_confidence_raw numeric;
--   alter table predictions add column if not exists macro_confidence_raw numeric;
--   alter table predictions add column if not exists cold_start boolean;
--
-- 2026-09-08  Kanal Finans TS split into a shared fetcher (Kanal-Finans-
--             Fetcher, a sibling repo also serving XRP-Guess) plus this
--             project's own trade-application step. RUN THIS ONE before
--             deploying the new backend/kanal_finans.py -- it reads
--             `applied_at`, and PostgREST rejects a query against an unknown
--             column outright. Safe to run twice. This project had zero rows
--             in kanal_finans_mentions at the time of the split (see
--             CLAUDE.md) so the backfill below is a no-op today, but it is
--             included anyway (XRP-Guess's identical migration needed it for
--             its 45 pre-existing rows) so that if any row somehow exists
--             before this runs, it is treated as already-traded rather than
--             replayed against today's price on the new script's first run.
--
--   alter table kanal_finans_mentions add column if not exists applied_at timestamptz;
--   create index if not exists kf_mentions_pending_idx
--     on kanal_finans_mentions (applied_at) where applied_at is null;
--   update kanal_finans_mentions set applied_at = created_at where applied_at is null;
--
