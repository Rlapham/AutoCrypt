"""AutoCrypt command-line entry point (Phase 1 — read-only data layer).

Commands:
  doctor          report config + which provider credentials are present
  backfill        historical backfill into the local store (survivorship-safe)
  poll            periodic polling of newly-created pools (forward collection)
  stream          live tail of newest swaps for a watchlist of pools
  qc              run data-quality checks over the store
  stats           summarize what's in the store
  dune-validate   ONE free Dune execution: validate field paths + cost before a backfill
  dune-backfill   backfill a Dune dex_solana.trades window into the store (survivorship-safe)
  export-parquet  export the store to Parquet (one file per event type)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Table

from autocrypt import __version__
from autocrypt.config import get_settings
from autocrypt.logging import configure_logging
from autocrypt.storage.store import EventStore

app = typer.Typer(
    name="autocrypt",
    help="Read-only Solana on-chain data layer (Phase 1).",
    no_args_is_help=True,
)
console = Console()


def _run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def _store(read_only: bool = False) -> EventStore:
    s = get_settings()
    configure_logging(s.log_level)
    return EventStore(s.duckdb_path, read_only=read_only)


@app.command()
def version() -> None:
    """Print the AutoCrypt version."""
    console.print(f"AutoCrypt v{__version__}")


@app.command()
def doctor() -> None:
    """Report config + which provider credentials are present (never prints values)."""
    s = get_settings()
    table = Table(title="AutoCrypt environment")
    table.add_column("Setting", style="cyan")
    table.add_column("Value / Status", style="green")
    table.add_row("version", __version__)
    table.add_row("app_env", s.app_env.value)
    table.add_row("log_level", s.log_level)
    table.add_row("data_dir", str(s.data_dir))
    table.add_row("duckdb_path", str(s.duckdb_path))
    for c in (
        "dune_api_key",
        "flipside_api_key",
        "bitquery_api_key",
        "birdeye_api_key",
        "dexpaprika_api_key",
        "geckoterminal_api_key",
        "coingecko_api_key",
        "solana_rpc_url",
    ):
        table.add_row(c, "[green]set[/green]" if s.has(c) else "[dim]not set[/dim]")
    console.print(table)


@app.command()
def backfill(
    window_days: int = typer.Option(14, help="Target historical window (days)."),
    max_pools: int = typer.Option(300, help="Cap on pools backfilled (reported if hit)."),
    max_enum_pages: int = typer.Option(60, help="Cap on universe-enumeration pages."),
    per_day_cap: int = typer.Option(80, help="Max pools sampled per calendar day."),
    min_transactions: int = typer.Option(5, help="Skip pools with fewer txns (dust)."),
    with_ohlcv: bool = typer.Option(False, help="Also pull GeckoTerminal OHLCV (slow)."),
    ohlcv_interval: str = typer.Option("1h", help="OHLCV interval if --with-ohlcv."),
) -> None:
    """Backfill historical Solana pool/swap data into the local store."""
    from autocrypt.ingestion.backfill import run_backfill

    store = _store()
    run_id = _run_id("backfill")
    report = asyncio.run(
        run_backfill(
            store,
            run_id=run_id,
            now=datetime.now(UTC),
            window_days=window_days,
            max_pools=max_pools,
            max_enum_pages=max_enum_pages,
            per_day_cap=per_day_cap,
            min_transactions=min_transactions,
            with_ohlcv=with_ohlcv,
            ohlcv_interval=ohlcv_interval,
        )
    )
    store.close()

    t = Table(title=f"Backfill report — {run_id}")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row(
        "requested window",
        f"{report.requested_window_start:%Y-%m-%d} → {report.requested_window_end:%Y-%m-%d}",
    )
    eff = (
        f"{report.effective_window_start:%Y-%m-%d %H:%M} → {report.effective_window_end:%Y-%m-%d %H:%M}"
        if report.effective_window_start
        else "(none)"
    )
    t.add_row("effective window", eff)
    t.add_row(
        "coverage complete?",
        "[green]yes[/green]" if report.coverage_complete() else "[yellow]NO (partial)[/yellow]",
    )
    t.add_row("pools seen", str(report.pools_seen))
    t.add_row("pools dropped (dust)", str(report.pools_dropped_dust))
    t.add_row("pools backfilled", str(report.pools_backfilled))
    t.add_row("pool tx errors", str(report.pools_tx_errors))
    t.add_row("pool ohlcv errors", str(report.pools_ohlcv_errors))
    t.add_row("events written", str(report.events_written))
    t.add_row("events by type", ", ".join(f"{k}={v}" for k, v in report.events_by_type.items()))
    t.add_row("pools/day", ", ".join(f"{k}:{v}" for k, v in report.pools_per_day.items()))
    console.print(t)
    for note in report.notes:
        console.print(f"  • {note}", style="yellow")


@app.command()
def poll(
    interval: float = typer.Option(60.0, help="Seconds between polls."),
    iterations: int = typer.Option(3, help="Number of polls (0 = run until Ctrl-C)."),
    pages: int = typer.Option(2, help="Pages of newest pools per tick."),
) -> None:
    """Periodically poll newly-created pools (forward collection)."""
    from autocrypt.ingestion.poll import run_poll

    store = _store()
    run_id = _run_id("poll")
    total = asyncio.run(
        run_poll(
            store,
            run_id=run_id,
            interval_s=interval,
            max_iterations=None if iterations == 0 else iterations,
            pages=pages,
        )
    )
    store.close()
    console.print(f"poll wrote {total} records ({run_id})")


@app.command()
def collect(
    interval: float = typer.Option(60.0, help="Seconds between collection cycles."),
    iterations: int = typer.Option(0, help="Number of cycles (0 = run until Ctrl-C)."),
    enum_pages: int = typer.Option(2, help="Pages of newest pools enumerated per cycle."),
    watch_max: int = typer.Option(40, help="Max pools tailed for swaps at once (newest kept)."),
    max_pool_age_h: float = typer.Option(24.0, help="Stop tailing a pool this many hours after creation."),
    tx_pages: int = typer.Option(2, help="Pages of recent swaps tailed per pool per cycle."),
) -> None:
    """Forward-collect a survivorship-complete SWAP dataset (the free multi-day path).

    Unlike `poll` (PoolCreated only) or `stream` (fixed watchlist), `collect` both
    enumerates new pools AND tails their swaps over a rolling, age-bounded watchlist.
    Run unattended for days/weeks to accumulate the dataset the kill-gate profiler needs.
    """
    from autocrypt.ingestion.collect import run_collect

    store = _store()
    run_id = _run_id("collect")
    total = asyncio.run(
        run_collect(
            store,
            run_id=run_id,
            interval_s=interval,
            max_iterations=None if iterations == 0 else iterations,
            enum_pages=enum_pages,
            watch_max=watch_max,
            max_pool_age_s=max_pool_age_h * 3600.0,
            tx_pages=tx_pages,
        )
    )
    store.close()
    console.print(f"collect wrote {total} swap/wallet records ({run_id})")


@app.command()
def stream(
    duration: float = typer.Option(30.0, help="Seconds to tail (0 = until Ctrl-C)."),
    interval: float = typer.Option(3.0, help="Seconds between tail ticks."),
    watch: int = typer.Option(5, help="How many newest pools to watch."),
) -> None:
    """Live-tail newest swaps for the N most recently created pools."""
    from autocrypt.ingestion.stream import run_stream
    from autocrypt.providers.dexpaprika import DexPaprika

    store = _store()
    run_id = _run_id("stream")

    async def _go() -> int:
        dp = DexPaprika()
        contexts: list[dict] = []
        try:
            async for pool in dp.iter_pools_by_creation(max_pools=watch, page_limit=watch):
                pc = dp.to_pool_created(pool, run_id=run_id)
                if pc is None:
                    continue
                store.write_events([pc])
                contexts.append(
                    {
                        "pool_address": pc.pool_address,
                        "base_mint": pc.base_mint,
                        "quote_mint": pc.quote_mint,
                        "base_decimals": pc.base_decimals,
                        "quote_decimals": pc.quote_decimals,
                        "dex": pc.dex,
                    }
                )
        finally:
            await dp.aclose()
        return await run_stream(
            store,
            contexts,
            run_id=run_id,
            interval_s=interval,
            duration_s=None if duration == 0 else duration,
        )

    total = asyncio.run(_go())
    store.close()
    console.print(f"stream wrote {total} records ({run_id})")


@app.command()
def qc() -> None:
    """Run data-quality checks over the store (exits non-zero on any failure)."""
    from autocrypt.quality.checks import run_quality_checks

    store = _store()
    report = run_quality_checks(store)
    store.close()

    t = Table(title="Data-quality checks")
    t.add_column("Check", style="cyan")
    t.add_column("Status")
    t.add_column("Detail", style="dim")
    style = {"ok": "green", "warn": "yellow", "fail": "red"}
    for c in report.checks:
        t.add_row(c.name, f"[{style[c.status]}]{c.status.upper()}[/{style[c.status]}]", c.detail)
    console.print(t)
    if report.failed:
        console.print(f"[red]{len(report.failed)} check(s) FAILED[/red]")
        raise typer.Exit(code=1)
    console.print(
        "[green]all checks passed[/green]"
        + (f" ({len(report.warned)} warnings)" if report.warned else "")
    )


@app.command()
def stats() -> None:
    """Summarize the contents of the store."""
    store = _store()
    counts = store.counts_by_type()
    bounds = store.time_bounds()
    pools = store.distinct_pools()
    store.close()

    t = Table(title="Store stats")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row("total events", str(sum(counts.values())))
    for k, v in counts.items():
        t.add_row(f"  {k}", str(v))
    t.add_row("distinct pools", str(pools))
    t.add_row("event_time range", f"{bounds['event_time_min']} → {bounds['event_time_max']}")
    t.add_row("knowable_at range", f"{bounds['knowable_at_min']} → {bounds['knowable_at_max']}")
    console.print(t)


@app.command()
def profile(
    horizon: float = typer.Option(60.0, help="Hold horizon in seconds (entry → exit)."),
    size_usd: float = typer.Option(250.0, help="Position size per trade (USD)."),
    min_swaps: int = typer.Option(10, help="Skip pools with fewer swaps (too thin to judge)."),
    mode: str = typer.Option(
        "derivative",
        help="Signal to profile: 'derivative' (Phase-2 composite) | 'attribution' "
        "(Phase-3 lead-weighted wallet model).",
    ),
    runup_pct: float = typer.Option(
        1.0, help="Attribution only: a 'run-up' = price reaches entry*(1+this)."
    ),
    runup_window: float = typer.Option(
        300.0, help="Attribution only: run-up must occur within this many seconds of entry."
    ),
    out: str = typer.Option(
        "", help="Markdown report output path (default depends on --mode)."
    ),
) -> None:
    """Phase 2/3: build the frequency-vs-expectancy curve over the store.

    Point-in-time, survivorship-complete, with realistic fees + own price impact.
    `--mode attribution` scores the wallet-attribution edge (Project_spec §2) on the same
    harness; results are directly comparable to the derivative kill-gate curve.
    """
    from pathlib import Path

    from autocrypt.attribution.wallet_book import AttributionConfig
    from autocrypt.profiler.report import build_report, render_markdown

    if mode not in ("derivative", "attribution"):
        console.print(f"[red]Unknown --mode {mode!r} (use 'derivative' or 'attribution').[/red]")
        raise typer.Exit(2)
    signal_field = "attr_score" if mode == "attribution" else "score"
    attr_cfg = AttributionConfig(runup_pct=runup_pct, runup_window_s=runup_window)
    if not out:
        out = (
            "docs/phase-3-attribution-profile.md"
            if mode == "attribution"
            else "docs/phase-2-profile.md"
        )

    store = _store(read_only=True)  # analytics-only; allows concurrent profile sweeps
    rep = build_report(
        store,
        horizon_s=horizon,
        position_size_usd=size_usd,
        min_swaps=min_swaps,
        signal_field=signal_field,
        attr_cfg=attr_cfg,
    )
    store.close()

    md = render_markdown(rep, horizon_s=horizon, position_size_usd=size_usd)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(md)

    t = Table(title=f"Profiler [{mode}] — horizon {horizon:.0f}s, ${size_usd:.0f}/trade")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row("universe pools (survivorship)", str(rep.universe_pools))
    t.add_row("pools used", str(rep.pools_used))
    t.add_row(
        "blind expectancy / hit / fires",
        f"{rep.blind.expectancy*100:+.2f}% / {rep.blind.hit_rate*100:.1f}% / {rep.blind.n_fires}",
    )
    best = max(rep.curve, key=lambda r: r.expectancy) if rep.curve else rep.blind
    bthr = "blind" if best.threshold == float("-inf") else f"{best.threshold:.3f}"
    t.add_row(
        "best-threshold expectancy",
        f"{best.expectancy*100:+.2f}% @ thr={bthr} (n={best.n_fires}, hit={best.hit_rate*100:.1f}%)",
    )
    t.add_row("report written", out)
    console.print(t)
    console.print(
        "[yellow]Verdict is YELLOW gate #2 — needs human sign-off; read the report's "
        "caveats before treating any number as the kill-gate answer.[/yellow]"
    )


@app.command(name="export-parquet")
def export_parquet(out: str = typer.Option("data/parquet", help="Output directory.")) -> None:
    """Export the store to Parquet (one file per event type)."""
    store = _store()
    paths = store.export_parquet(out)
    store.close()
    for p in paths:
        console.print(f"wrote {p}")


def _dune_or_exit() -> object:
    """Build a key-gated Dune adapter, or exit with operator instructions if no key."""
    from autocrypt.providers.dune import Dune

    s = get_settings()
    configure_logging(s.log_level)
    if not s.has("dune_api_key"):
        console.print(
            "[red]DUNE_API_KEY not set.[/red] Dune is FREE (Community tier): create a key at "
            "dune.com → Settings → API and add it to .env as DUNE_API_KEY (never commit).\n"
            "Also save the DEX_TRADES_SQL from src/autocrypt/providers/dune.py as a Dune query "
            "with `since`/`till` TIMESTAMP parameters, and pass its numeric --query-id."
        )
        raise typer.Exit(code=1)
    return Dune(api_key=s.dune_api_key.get_secret_value())  # type: ignore[union-attr]


@app.command(name="dune-validate")
def dune_validate(
    query_id: int = typer.Option(..., help="Numeric query_id of the saved DEX_TRADES_SQL query."),
    since: str = typer.Option(..., help="Window start UTC, e.g. '2026-05-20 12:00:00' or ISO-8601."),
    till: str = typer.Option(..., help="Window end UTC (exclusive). Keep this window SMALL."),
    sample_size: int = typer.Option(5000, help="Rows sampled for field-path validation."),
) -> None:
    """ONE free Dune execution to validate field paths + cost + survivorship BEFORE a backfill.

    Confirms `dex_solana.trades` column names against a real pull, maps the sample through the
    canonical mappers, reads Dune's row-count/cost metadata, and checks survivorship breadth.
    Run this first — the bulk backfill is gated on it (docs/provider-evaluation.md, Phase 2c/2d).
    """
    from autocrypt.ingestion.dune_backfill import parse_window, validate_dune

    dune = _dune_or_exit()
    rep = asyncio.run(
        _with_aclose(
            dune,
            validate_dune(
                dune,  # type: ignore[arg-type]
                query_id=query_id,
                since=parse_window(since),
                till=parse_window(till),
                sample_size=sample_size,
            ),
        )
    )

    t = Table(title=f"Dune validation — query {query_id}")
    t.add_column("Check", style="cyan")
    t.add_column("Result", style="green")
    t.add_row("window", f"{rep.since:%Y-%m-%d %H:%M} → {rep.till:%Y-%m-%d %H:%M} UTC")
    t.add_row("total rows in window (Dune)", str(rep.total_row_count))
    t.add_row("rows sampled / mapped / skipped", f"{rep.sampled_rows} / {rep.mapped_swaps} / {rep.skipped_non_quote}")
    t.add_row(
        "field paths OK?",
        "[green]yes[/green]" if rep.field_paths_ok else "[red]NO[/red]",
    )
    if rep.missing_expected:
        t.add_row("MISSING columns", ", ".join(rep.missing_expected))
    if rep.extra_columns:
        t.add_row("extra columns", ", ".join(rep.extra_columns))
    t.add_row("native pool address?", "yes" if rep.pool_field_present else "no (surrogate key)")
    t.add_row("rows with amount_usd", f"{rep.rows_with_usd}/{rep.sampled_rows}")
    t.add_row("distinct base mints (survivorship)", str(rep.distinct_base_mints))
    t.add_row("distinct surrogate markets", str(rep.distinct_markets))
    console.print(t)
    for note in rep.notes:
        console.print(f"  • {note}", style="yellow")
    if rep.field_paths_ok:
        console.print(
            "[green]Field paths validated.[/green] Next: `autocrypt dune-backfill --query-id "
            f"{query_id} --since ... --till ...` for the ~14d window, then `autocrypt qc` + "
            "`autocrypt profile`.",
        )
    else:
        console.print(
            "[red]Do NOT backfill yet[/red] — fix the field paths / quote filter above first.",
        )


@app.command(name="dune-backfill")
def dune_backfill(
    query_id: int = typer.Option(..., help="Numeric query_id of the saved DEX_TRADES_SQL query."),
    since: str = typer.Option(..., help="Window start UTC, e.g. '2026-05-19 00:00:00'."),
    till: str = typer.Option(..., help="Window end UTC (exclusive), e.g. '2026-06-02 00:00:00'."),
    max_rows: int = typer.Option(10**7, help="Client-side safety ceiling (reported if hit)."),
    page_size: int = typer.Option(5000, help="Results page size."),
) -> None:
    """Backfill a Dune `dex_solana.trades` window into the store (Swap/WalletEvent/PoolCreated).

    Survivorship-complete by construction (every market that traded, rugs included). NOTE: the
    store has a single DuckDB writer — stop `autocrypt collect` first, or point at a separate DB.
    """
    from autocrypt.ingestion.dune_backfill import parse_window, run_dune_backfill

    dune = _dune_or_exit()
    store = _store()
    run_id = _run_id("dune-backfill")
    rep = asyncio.run(
        _with_aclose(
            dune,
            run_dune_backfill(
                store,
                dune,  # type: ignore[arg-type]
                run_id=run_id,
                query_id=query_id,
                since=parse_window(since),
                till=parse_window(till),
                max_rows=max_rows,
                page_size=page_size,
            ),
        )
    )
    store.close()

    t = Table(title=f"Dune backfill — {run_id}")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row("window", f"{rep.since:%Y-%m-%d %H:%M} → {rep.till:%Y-%m-%d %H:%M} UTC")
    t.add_row("raw trade rows", str(rep.raw_rows))
    t.add_row("swaps mapped", str(rep.swaps_mapped))
    t.add_row("pools created (proxy)", str(rep.pools_created))
    t.add_row("skipped (no quote leg)", str(rep.skipped_non_quote))
    t.add_row("net-new store rows", str(rep.net_new_rows))
    t.add_row("hit max_rows cap?", "[yellow]YES[/yellow]" if rep.hit_max_rows else "no")
    console.print(t)
    for note in rep.notes:
        console.print(f"  • {note}", style="yellow")


async def _with_aclose(provider: object, coro: object) -> object:
    """Await `coro`, then aclose the provider's HTTP client (best-effort)."""
    try:
        return await coro  # type: ignore[misc]
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()


# ── Track M (Iteration 2) — mid-cap deep-pool universe ────────────────────────


@app.command(name="midcap-snapshot")
def midcap_snapshot(
    min_reserve_usd: float = typer.Option(500_000.0, help="Min pool reserve (liquidity) USD."),
    fdv_min_usd: float = typer.Option(1_000_000.0, help="Min FDV USD (exclude micro-caps)."),
    fdv_max_usd: float = typer.Option(250_000_000.0, help="Max FDV USD (exclude majors)."),
    max_pages: int = typer.Option(10, help="Top-pool pages to enumerate (caps ~10/200 pools)."),
) -> None:
    """Take ONE forward universe snapshot (survivorship-safe over wall-clock).

    Records ALL enumerated top pools (in_band flagged) into `universe_snapshots`, so a
    point-in-time membership set accrues — a pool captured while alive stays in the
    snapshot after it later dies. Schedule this daily to ripen a clean Track M dataset.
    """
    from autocrypt.midcap.universe import UniverseBand, snapshot_universe

    band = UniverseBand(min_reserve_usd=min_reserve_usd, fdv_min_usd=fdv_min_usd, fdv_max_usd=fdv_max_usd)
    store = _store()
    n_all, n_band = asyncio.run(snapshot_universe(store, band, max_pages=max_pages))
    store.close()
    console.print(
        f"universe snapshot: enumerated {n_all} pools, {n_band} in-band "
        f"(reserve>=${min_reserve_usd:,.0f}, FDV ${fdv_min_usd:,.0f}-${fdv_max_usd:,.0f})"
    )


@app.command(name="midcap-control")
def midcap_control(
    min_reserve_usd: float = typer.Option(500_000.0, help="Min pool reserve (liquidity) USD."),
    fdv_min_usd: float = typer.Option(1_000_000.0, help="Min FDV USD."),
    fdv_max_usd: float = typer.Option(250_000_000.0, help="Max FDV USD."),
    interval: str = typer.Option("1d", help="OHLCV interval (1d ~6mo depth, 1h ~41d)."),
    max_pages: int = typer.Option(10, help="Top-pool pages to enumerate."),
) -> None:
    """Ingest today's in-band pools' OHLCV — an EXPLICITLY survivorship-BIASED control.

    ⚠️ NOT A GO TEST. The universe is today's survivors, so any positive expectancy could
    be pure survivorship. A NEGATIVE result is the trustworthy one (bias only inflates
    returns). Point DB_URL at a dedicated file, e.g.
    DB_URL=duckdb:///data/autocrypt_midcap.duckdb autocrypt midcap-control
    """
    from autocrypt.midcap.universe import UniverseBand, build_control_dataset

    band = UniverseBand(min_reserve_usd=min_reserve_usd, fdv_min_usd=fdv_min_usd, fdv_max_usd=fdv_max_usd)
    store = _store()
    run_id = _run_id("midcap_control_BIASED")
    n_pools, n_bars = asyncio.run(
        build_control_dataset(store, band, run_id=run_id, interval=interval, max_pages=max_pages)
    )
    store.close()
    console.print(
        f"[yellow]BIASED control[/yellow]: ingested {n_bars} {interval} bars across "
        f"{n_pools} in-band pools ({run_id}). Survivorship-biased upper bound — never a GO."
    )


if __name__ == "__main__":
    app()
