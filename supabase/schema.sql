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
    -- The CLOSE of the session the features were built from, which is not the
    -- same number as the live quote above: predict.py runs at 23:00 UTC, i.e.
    -- 19:00 New York, two hours into the session AFTER the one it read. The
    -- record is scored close-to-close from this column because that is the
    -- question every component answers and the question assets.py's base
    -- rates were measured on. Scoring from the quote moved the realised base
    -- rate by 1.8 points in gold and 3.8 in silver -- see
    -- predict.resolve_due_predictions.
    close_at_prediction     numeric,

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
    ('technical'), ('ml'), ('macro'), ('claude'), ('kanalfinans'), ('miners'),
    -- `breakout` is NOT in trading.STRATEGIES and must not be added there:
    -- it is all-in/all-out on a discrete state, like `kanalfinans`, not a
    -- scaled target exposure. It is seeded here because it is a real book
    -- with real (fake) money -- see backend/breakout_trading.py for why a
    -- rule that failed its pre-registered bar gets one anyway.
    ('breakout')
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
-- breakout_state  -- the breakout panel's history, one row per session
-- ---------------------------------------------------------------------------
-- Written by track_breakout.py, read by the frontend's "Kırılım Takibi" card
-- and the chart under it. NOT a prediction: nothing here votes in an ensemble
-- and no row sizes a position. Since 2026-09-16 it DOES drive a $1,000 paper
-- book per metal (backend/breakout_trading.py), but that book is all-in /
-- all-out on `state` below rather than on a target exposure, so `breakout` is
-- still deliberately absent from trading.STRATEGIES -- the same third kind as
-- `kanalfinans`. research/flow.py measured the rule against a pre-registered
-- bar and it did not clear it (section 18 of research/README.md); the book
-- exists to show that failure costing money in public, not to be copied.
--
-- The book keeps NO copy of the rule's stop: `portfolios.stop_loss_price`
-- stays null for this strategy and the live stop is the `stop` column here,
-- recomputed from price history every run. A stored second copy could only
-- ever disagree with its own source.
--
-- WHY THE WHOLE WINDOW IS REWRITTEN EVERY RUN, not appended to
-- ------------------------------------------------------------
-- Every column below is a deterministic function of the COMEX contract's own
-- price and volume history, so recomputing a past session yields the same
-- numbers --
-- an append-only log would carry exactly the same values with the added
-- property that the chart starts empty and fills in over six months. The
-- upsert makes the panel complete on its first run.
--
-- The one case where a rewrite changes a past row is a vendor revision, and
-- that is the correct outcome: the levels a person sees should be the levels
-- the current price history implies, not the ones a stale fetch implied.
--
-- `close` is the COMEX contract's close, PER TROY OUNCE. There is no second
-- price column: phase 1 built this panel on GLD/SLV (because Yahoo cannot
-- serve futures volume) and had to carry the metal's price beside the ETF's
-- so the reader could translate. Phase 2 moved the signal onto
-- COMEX:GC1!/SI1! via TradingView, which serves real volume AND quotes in
-- ounces, so the two columns collapsed into one. See tv_history.py.
create table if not exists breakout_state (
    asset           text    not null,          -- 'gold' | 'silver'
    session_date    date    not null,
    -- The series the signal was built on, e.g. 'COMEX:GC1!'. NOT named
    -- `etf_symbol` any more: a column name that outlives the thing it names
    -- is how the next reader learns a wrong fact with no error anywhere.
    source_symbol   text    not null,
    close           numeric not null,          -- $ per troy ounce

    -- Position state.
    state           int     not null,          -- 1 in position, 0 flat
    stop            numeric,                   -- null while flat
    entry_price     numeric,
    entry_date      date,
    exit_reason     text,                      -- 'stop' | 'trend' | null

    -- The three primary instruments.
    avwap           numeric,
    avwap_anchor    numeric,
    poc             numeric,
    vah             numeric,
    val             numeric,
    flow            numeric,                   -- Chaikin money flow, -1..1

    -- The six confirmations, stored raw so the UI prints readings rather
    -- than a re-derived verdict it could get wrong.
    rsi14           numeric,
    macd_hist       numeric,
    cci20           numeric,
    mom10           numeric,
    stoch_k         numeric,
    fib_pos         numeric,
    fib_high        numeric,
    fib_low         numeric,
    votes           int,                       -- sum of the six, -6..+6
    -- The six votes individually, as {"rsi14": 1, "macd_hist": -1, ...}.
    -- Stored rather than re-derived in the browser for the reason the
    -- component-record table states: a threshold comparison IS the decision,
    -- and a decision rule kept in two languages drifts the first time one
    -- side is edited. The UI prints the thresholds as LABELS beside these,
    -- which is description rather than a second implementation.
    votes_detail    jsonb,

    updated_at      timestamptz not null default now(),
    primary key (asset, session_date)
);

create index if not exists breakout_state_idx
    on breakout_state (asset, session_date desc);

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
                             'kanal_finans_mentions', 'kanal_finans_themes',
                             'breakout_state']
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
-- 2026-09-15  Breakout panel (order flow / anchored VWAP / volume profile).
--             RUN THIS ONE before deploying backend/track_breakout.py and the
--             new frontend card -- both read `breakout_state`, and PostgREST
--             rejects a query against an unknown table outright, so the card
--             would render its heading with an empty chart under it. Safe to
--             run twice.
--
--             This is a NEW table, so the `create table if not exists` block
--             above is enough on a fresh database; the copy below is here
--             because an existing database will not re-run that block's
--             companion RLS loop with the new name in it.
--
--             Nothing here trades. research/flow.py scored the rule against a
--             bar declared before the results were looked at and it did not
--             clear it: on gold it beat buy-and-hold on Calmar (0.566 vs
--             0.495) and finished 33.9% behind in money; on silver it lost on
--             both counts. So `breakout` is NOT in trading.STRATEGIES and
--             there are no `portfolios` rows to seed.
--
--   create table if not exists breakout_state (
--       asset           text    not null,
--       session_date    date    not null,
--       etf_symbol      text    not null,
--       close           numeric not null,
--       metal_close     numeric,
--       state           int     not null,
--       stop            numeric,
--       entry_price     numeric,
--       entry_date      date,
--       exit_reason     text,
--       avwap           numeric,
--       avwap_anchor    numeric,
--       poc             numeric,
--       vah             numeric,
--       val             numeric,
--       flow            numeric,
--       rsi14           numeric,
--       macd_hist       numeric,
--       cci20           numeric,
--       mom10           numeric,
--       stoch_k         numeric,
--       fib_pos         numeric,
--       fib_high        numeric,
--       fib_low         numeric,
--       votes           int,
--       votes_detail    jsonb,
--       updated_at      timestamptz not null default now(),
--       primary key (asset, session_date)
--   );
--   create index if not exists breakout_state_idx
--       on breakout_state (asset, session_date desc);
--   alter table breakout_state enable row level security;
--   drop policy if exists breakout_state_public_read on breakout_state;
--   create policy breakout_state_public_read on breakout_state
--       for select using (true);
--
-- 2026-09-15b Breakout panel moved from GLD/SLV to the COMEX contract.
--             RUN THIS ONE if you already ran the 2026-09-15 migration above.
--             It DROPS and recreates the table, which is safe here and would
--             not be for any other table in this file: every row is a pure
--             function of price history that track_breakout.py rewrites on
--             every run, so nothing is lost that the next run does not
--             reproduce. Safe to run twice.
--
--             Why: research/flow.py part 0 measured that TradingView serves
--             real COMEX volume where Yahoo cannot (gold 176,514 against a
--             fresh Yahoo fetch's 176,343; silver 57,776 against 168), and
--             the COMEX contract is quoted PER TROY OUNCE -- so the card's
--             levels stop being GLD dollars the reader has to convert.
--
--             Two columns change shape: `etf_symbol` becomes `source_symbol`
--             (it holds 'COMEX:GC1!' now, so the old name was a lie), and
--             `metal_close` is gone (the signal's own series IS the metal's
--             price now, so there is nothing left to translate between).
--
--             Re-measured on the new source, the rule STILL fails its bar --
--             gold Calmar 0.520 vs 0.463 but 41.8% less money, silver behind
--             on both. So there is still no `breakout` portfolio.
--             (Both of those became untrue later and the note is kept as
--             written: a book was opened 2026-09-16, and the 2026-09-17
--             re-run -- after tv_history stopped stamping bars a session
--             early -- put gold behind on Calmar too, 0.452 vs 0.460.)
--
--   drop table if exists breakout_state;
--   create table if not exists breakout_state (
--       asset           text    not null,
--       session_date    date    not null,
--       source_symbol   text    not null,
--       close           numeric not null,
--       state           int     not null,
--       stop            numeric,
--       entry_price     numeric,
--       entry_date      date,
--       exit_reason     text,
--       avwap           numeric,
--       avwap_anchor    numeric,
--       poc             numeric,
--       vah             numeric,
--       val             numeric,
--       flow            numeric,
--       rsi14           numeric,
--       macd_hist       numeric,
--       cci20           numeric,
--       mom10           numeric,
--       stoch_k         numeric,
--       fib_pos         numeric,
--       fib_high        numeric,
--       fib_low         numeric,
--       votes           int,
--       votes_detail    jsonb,
--       updated_at      timestamptz not null default now(),
--       primary key (asset, session_date)
--   );
--   create index if not exists breakout_state_idx
--       on breakout_state (asset, session_date desc);
--   alter table breakout_state enable row level security;
--   drop policy if exists breakout_state_public_read on breakout_state;
--   create policy breakout_state_public_read on breakout_state
--       for select using (true);
--

-- ---------------------------------------------------------------------------
-- MIGRATION 2026-09-16 -- the `breakout` paper books
-- ---------------------------------------------------------------------------
-- Opens one $1,000 book per metal on the breakout rule. The rule FAILED its
-- pre-registered bar on both data sources it was measured against (see the
-- 2026-09-15b note above and research/README.md section 18), and the book was
-- opened deliberately anyway: the card carries the measurement, and what a
-- live book adds is the cost arriving one fill at a time against the same
-- buy-and-hold benchmark every other book is measured against.
--
-- Safe to re-run: `on conflict do nothing` leaves an existing book untouched,
-- so this cannot reset a book that has already traded.
--
--   insert into portfolios (asset, strategy)
--   select a.asset, 'breakout'
--   from (values ('gold'), ('silver')) as a(asset)
--   on conflict (asset, strategy) do nothing;
--
-- To RESET these two books later (and only these two -- this deletes fills):
--   delete from trades where strategy = 'breakout';
--   update portfolios set cash_usd = 1000, ounces = 0, position = 'CASH',
--          target_exposure = 0, updated_at = now()
--    where strategy = 'breakout';

-- ---------------------------------------------------------------------------
-- MIGRATION 2026-09-17 -- score the record on the close, not the live quote
-- ---------------------------------------------------------------------------
-- predict.py runs at 23:00 UTC = 19:00 New York, so `price_at_prediction` is
-- a quote from two hours INTO the session after the one every feature was
-- built from. The components all answer "close[t+5] > close[t]" and the base
-- rates in assets.py were measured that way, so resolving against the quote
-- scored the record on a different question than the ensemble weighs it
-- against.
--
-- Measured on 392 sessions of hourly history: the quote sits a median 0.27%
-- (gold) / 0.77% (silver) from that session's close, flipping 5.9% / 6.9% of
-- labels, and shifting the realised base rate on the SAME rows from 61.2% to
-- 59.4% (gold) and 58.2% to 54.3% (silver).
--
-- Rows written before this column exists keep resolving from
-- `price_at_prediction` and the console says so. Safe to run twice.
--
--   alter table predictions add column if not exists close_at_prediction numeric;
