"""AutoCrypt command-line entry point (Phase 1 — read-only data layer).

Commands:
  doctor          report config + which provider credentials are present
  backfill        historical backfill into the local store (survivorship-safe)
  poll            periodic polling of newly-created pools (forward collection)
  stream          live tail of newest swaps for a watchlist of pools
  qc              run data-quality checks over the store
  stats           summarize what's in the store
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


def _store() -> EventStore:
    s = get_settings()
    configure_logging(s.log_level)
    return EventStore(s.duckdb_path)


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
        "bitquery_api_key",
        "birdeye_api_key",
        "dexpaprika_api_key",
        "geckoterminal_api_key",
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
    out: str = typer.Option(
        "docs/phase-2-profile.md", help="Markdown report output path."
    ),
) -> None:
    """Phase 2 KILL-GATE: build the frequency-vs-expectancy curve over the store.

    Point-in-time, survivorship-complete, with realistic fees + own price impact.
    """
    from pathlib import Path

    from autocrypt.profiler.report import build_report, render_markdown

    store = _store()
    rep = build_report(
        store, horizon_s=horizon, position_size_usd=size_usd, min_swaps=min_swaps
    )
    store.close()

    md = render_markdown(rep, horizon_s=horizon, position_size_usd=size_usd)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(md)

    t = Table(title=f"Profiler — horizon {horizon:.0f}s, ${size_usd:.0f}/trade")
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


if __name__ == "__main__":
    app()
