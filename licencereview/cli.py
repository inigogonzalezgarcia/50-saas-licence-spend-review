"""Command line: `demo` writes the fictional Proseware Group exports to sample_data/ and builds the outputs; `review` runs on your own
exports."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import report, simulate
from .checks import money, review, summary
from .model import load, parse_dt

OUTPUTS = ("report.html", "review-pack.md", "app-utilisation.csv", "reclaim-list.csv", "renewal-calendar.csv", "showback.csv",
           "findings.csv", "actions.csv")


def run(data: Path, out: Path, title: str | None = None, as_of: datetime | None = None) -> dict:
    d = load(data, as_of)
    rv = review(d)
    title = title or f"{d.settings.organisation} · SaaS and licence spend review, {d.as_of:%d %B %Y}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, rv, title), encoding="utf-8")
    (out / "review-pack.md").write_text(report.pack_md(d, rv, title), encoding="utf-8")
    report.write_utilisation(rv, out / "app-utilisation.csv")
    report.write_reclaim(rv, out / "reclaim-list.csv")
    report.write_calendar(rv, out / "renewal-calendar.csv")
    report.write_showback(rv, out / "showback.csv")
    report.write_findings(rv, out / "findings.csv")
    report.write_actions(rv, out / "actions.csv")
    sm = summary(d, rv)
    sm["currency"] = d.settings.currency
    return sm


def _when(value: str) -> datetime:
    d = parse_dt(value)
    if not d:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM'): {value}")
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="licencereview", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="write the fictional exports to sample_data/ and build the outputs")
    dm.add_argument("--data", type=Path, default=Path("sample_data"))
    dm.add_argument("--out", type=Path, default=Path("output"))
    rv = sub.add_parser("review", help="build the outputs from your own exports")
    rv.add_argument("data", type=Path, nargs="?", help="folder with contracts.csv and the other exports")
    rv.add_argument("--data", dest="data_opt", type=Path, help="same as the positional folder")
    rv.add_argument("--out", type=Path, default=Path("output"))
    rv.add_argument("--title", help="title of the report and the pack")
    rv.add_argument("--as-of", type=_when, help="reference date (default: settings.json, or now)")
    a = p.parse_args(argv)
    if a.cmd == "demo":
        simulate.write(a.data)
        sm = run(a.data, a.out, f"{simulate.ORG} · SaaS and licence spend review, 11 November 2026")
    else:
        folder = a.data or a.data_opt
        if not folder:
            print("error: give the folder with contracts.csv", file=sys.stderr)
            return 2
        try:
            sm = run(folder, a.out, a.title, a.as_of)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    cur = sm["currency"]
    print(f"{sm['status']} · {sm['apps']} apps, {money(sm['total'], cur)} a year · savings identified {money(sm['saving'], cur)} "
          f"({sm['saving_pct']:.1f} %) · {sm['reclaim']} licences to reclaim, {sm['downgrade']} to downgrade · "
          f"{sm['leaver_licences']} leaver licences · {sm['renewals_90']} renewals in 90 days, {sm['deadlines_30']} notice "
          f"deadline{'' if sm['deadlines_30'] == 1 else 's'} in 30 days · {sm['shadow']} shadow-IT apps · {sm['red']} red and "
          f"{sm['amber']} amber findings")
    print(f"outputs in {a.out}/: {', '.join(OUTPUTS)}")
    return 0
