"""Outputs: report.html (tiles, savings by action, the decisions, utilisation per app with bars, the renewal calendar, showback per
department, shadow IT and every finding), review-pack.md (one page for the IT manager and finance before the renewals), and the CSVs:
app-utilisation, reclaim-list, renewal-calendar, showback, findings and actions."""
from __future__ import annotations

import csv
import html
from pathlib import Path

from .checks import ACTIONS, AMBER, AREA_LABEL, GREEN, RED, Finding, money, summary
from .model import FILES, Data

e = html.escape
TODO = "**[TO COMPLETE]**"
LEVER_LABEL = {"reclaim": "Reclaim", "downgrade": "Downgrade", "right-size": "Right-size seats", "negotiate": "Negotiate",
               "consolidate": "Consolidate", "cancel": "Cancel duplicates"}


def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _d(x) -> str:
    return "" if x is None else x.isoformat()


def _day(x) -> str:
    return "–" if x is None else f"{x:%d %b %Y}"


def _f(x, nd: int = 2) -> str:
    return "" if x is None else f"{x:.{nd}f}"


# ---------------------------------------------------------------- csv

def write_utilisation(rv: dict, path: Path) -> None:
    _w(path, ["app", "sku", "vendor", "category", "licence_model", "seats_purchased", "assigned", "active", "idle_warning", "inactive",
              "never_used", "leavers", "on_leave", "not_in_hr", "downgrade_candidates", "unassigned", "utilisation_pct", "unit_price_annual",
              "annual_cost", "saving_identified", "renewal", "owner", "findings"],
       [[u.contract.app, u.contract.sku, u.contract.vendor, u.contract.category, u.contract.model, _f(u.seats, 0), u.assigned, u.active,
         u.idle, u.inactive, u.never, u.leavers, u.leave, u.unknown, u.downgrade, u.unassigned if u.contract.per_user else "",
         _f(u.utilisation, 1) if u.contract.per_user else "", _f(u.contract.unit_price), _f(u.contract.annual_cost), _f(u.saving),
         _d(u.contract.renewal), u.contract.owner, "; ".join(dict.fromkeys(f.code for f in u.findings))] for u in rv["usage"]])


def write_reclaim(rv: dict, path: Path) -> None:
    _w(path, ["user", "display_name", "department", "app", "sku", "action", "reason", "last_active", "saving_annual"],
       [[r["user"], r["name"], r["department"], r["app"], r["sku"], r["lever"], r["reason"], _d(r["last_active"]), _f(r["saving"])]
        for r in rv["reclaim"]])


def write_calendar(rv: dict, path: Path) -> None:
    use = {u.contract.key: u for u in rv["usage"]}
    _w(path, ["renewal_date", "app", "sku", "vendor", "annual_cost", "uplift_pct", "cost_after_uplift", "notice_days", "notice_deadline",
              "days_to_deadline", "auto_renew", "state", "utilisation_pct", "saving_identified", "owner"],
       [[_d(x["renewal"]), x["contract"].app, x["contract"].sku, x["contract"].vendor, _f(x["annual"]), _f(x["contract"].uplift_pct, 1),
         _f(x["after_uplift"]), x["contract"].notice_days, _d(x["deadline"]), "" if x["days_to_deadline"] is None else x["days_to_deadline"],
         "yes" if x["contract"].auto_renew else "no", x["state"],
         _f(use[x["contract"].key].utilisation, 1) if x["contract"].per_user else "", _f(x["saving"]), x["contract"].owner]
        for x in rv["calendar"]])


def write_showback(rv: dict, path: Path) -> None:
    _w(path, ["department", "cost_centre", "users", "licences", "annual_cost", "share_pct", "cost_per_user", "top_apps"],
       [[r["department"], r["cost_centre"], r["users"], r["licences"], _f(r["cost"]), _f(r["share"], 1), _f(r["per_user"]),
         "; ".join(r["top_apps"])] for r in rv["showback"]])


def write_findings(rv: dict, path: Path) -> None:
    _w(path, ["severity", "area", "code", "check", "apps", "subject", "detail", "action", "lever", "saving_annual", "cost_exposure", "owner",
              "due"],
       [[f.severity, f.area, f.code, f.title, "; ".join(f.apps), f.subject, f.detail, f.action, f.lever, _f(f.saving), _f(f.risk),
         f.owner, _d(f.due)] for f in rv["findings"]])


def actions(rv: dict) -> list[tuple[str, Finding]]:
    out = []
    count = {}
    for f in sorted(rv["findings"], key=lambda f: (f.due, f.severity != RED, -f.saving, f.code, f.subject)):
        count[f.code] = count.get(f.code, 0) + 1
        out.append((f"{f.code}-{count[f.code]:02d}", f))
    return out


def write_actions(rv: dict, path: Path) -> None:
    _w(path, ["ref", "severity", "code", "lever", "apps", "action", "detail", "saving_annual", "owner", "due", "done"],
       [[ref, f.severity, f.code, f.lever, "; ".join(f.apps), f.action, f.detail, _f(f.saving), f.owner, _d(f.due), ""]
        for ref, f in actions(rv)])


# ---------------------------------------------------------------- the review pack

def _md(x) -> str:
    return str(x).replace("|", "/").replace("\n", " ")


def pack_md(d: Data, rv: dict, title: str) -> str:
    s = d.settings
    sm = summary(d, rv)
    cur = s.currency
    out = [f"# {title}", "",
           f"> Prepared on {d.as_of:%a %d %b %Y} from the exports listed at the end, for the IT manager and finance before the next "
           f"renewals. Read-only: no licence or contract was changed. Thresholds are in settings.json; savings are annual, in {cur}, "
           f"and each euro is counted once per app. Sections marked {TODO} are for the meeting.", "",
           f"**{sm['status']}. Annual software and SaaS spend {money(sm['total'], cur)} on {sm['apps']} apps; savings identified "
           f"{money(sm['saving'], cur)} ({sm['saving_pct']:.1f} %).**", "", "## Headlines", ""]
    bl = sm["by_lever"]
    out.append("- Savings by action: " + "; ".join(f"{LEVER_LABEL[k].lower()} {money(bl[k], cur)}" for k in ACTIONS if bl[k]) + ".")
    if sm["leaver_licences"]:
        out.append(f"- **{sm['leaver_licences']} licences are still assigned to people who have left**: a cost and a security gap.")
    nxt = [x for x in rv["calendar"] if x["days_to_deadline"] is not None and 0 <= x["days_to_deadline"] <= 30]
    for x in nxt:
        out.append(f"- **{_md(x['contract'].key)}** renews on {_day(x['renewal'])}: notice deadline **{_day(x['deadline'])}**, in "
                   f"{x['days_to_deadline']} days.")
    if sm["true_up"]:
        out.append(f"- True-up risk: {money(sm['true_up'], cur)} a year for seats assigned above what was bought.")
    if sm["shadow"]:
        sh = [f.subject for f in rv["findings"] if f.code in ("SHD-UNMANAGED", "SHD-DUPLICATE")]
        out.append(f"- Shadow IT on expenses: {', '.join(sh)}.")
    out.append(f"- {sm['renewals_90']} renewals in the next 90 days; {sm['red']} red and {sm['amber']} amber findings.")
    out += ["", "## Decisions needed", "", "| # | Decision | Options | Proposed | Saving a year | Owner | Needed by | Outcome |",
            "|---|---|---|---|---|---|---|---|"]
    out += [f"| {x.id} | **{_md(x.decision)}**<br>{_md(x.why)} | {_md(x.options)} | {_md(x.proposed)} | "
            f"{money(x.saving, cur) if x.saving else '–'} | {_md(x.owner)} | {_day(x.needed_by)} | |" for x in rv["decisions"]] or \
        ["| – | No decisions needed | | | | | | |"]
    out += ["", "## Renewals to negotiate", "", f"Renewals in the next {s.renewal_horizon_days} days, with the date by which notice has "
            "to reach the vendor.", "", "| Renewal | App | Annual cost | Uplift | Notice deadline | Auto-renew | Utilisation | Saving identified | "
            "Owner |", "|---|---|---|---|---|---|---|---|---|"]
    use = {u.contract.key: u for u in rv["usage"]}
    for x in rv["calendar"]:
        if x["days_to_renewal"] > s.renewal_horizon_days:
            continue
        c = x["contract"]
        ut = use[c.key].utilisation if c.per_user else None
        dl = _day(x["deadline"]) + (f" ({x['days_to_deadline']} days)" if x["days_to_deadline"] is not None and x["days_to_deadline"] >= 0
                                    else " (passed)")
        out.append(f"| {_day(x['renewal'])} | {_md(c.key)} | {money(c.annual_cost, cur)} | {_f(c.uplift_pct, 1) or '–'} % | {dl} | "
                   f"{'yes' if c.auto_renew else 'no'} | {'–' if ut is None else format(ut, '.0f') + ' %'} | "
                   f"{money(x['saving'], cur) if x['saving'] else '–'} | {_md(c.owner or 'nobody')} |")
    out += ["", "## Savings by action", "", "| Action | Saving a year | Findings |", "|---|---|---|"]
    for k in ACTIONS:
        n = sum(1 for f in rv["findings"] if f.lever == k and f.saving)
        out.append(f"| {LEVER_LABEL[k]} | {money(bl[k], cur)} | {n} |")
    out.append(f"| **Total** | **{money(sm['saving'], cur)}** ({sm['saving_pct']:.1f} % of {money(sm['total'], cur)}) | |")
    out += ["", "## Actions", "", "The red findings and the largest savings; every action with owner and due date is in `actions.csv`, "
            "and every user and licence to reclaim or downgrade in `reclaim-list.csv`.", "",
            "| Ref | Severity | Action | Saving | Owner | Due | Done |", "|---|---|---|---|---|---|---|"]
    acts = actions(rv)
    top = [a for a in acts if a[1].severity == RED] + sorted([a for a in acts if a[1].severity != RED and a[1].saving],
                                                             key=lambda a: -a[1].saving)[:6]
    for ref, f in top:
        out.append(f"| {ref} | {f.severity} | **{_md(f.subject)}**: {_md(f.detail)} → {_md(f.action)} | "
                   f"{money(f.saving, cur) if f.saving else '–'} | {_md(f.owner)} | {_day(f.due)} | |")
    out += ["", f"All {len(rv['findings'])} findings are in `findings.csv`.", "",
            "## Scope and evidence", "", f"- Organisation: {s.organisation}", f"- Reference date: {d.as_of:%a %d %b %Y %H:%M}",
            f"- Active means activity in the last {s.inactive_days.get('reclaim', 60)} days; idle between "
            f"{s.inactive_days.get('warning', 30)} and {s.inactive_days.get('reclaim', 60)} days (reported, not reclaimed). Last activity "
            "is what each tool exports (for Microsoft 365, the last Entra ID sign-in), so check the list with the app owner before "
            "reclaiming.", "- Savings are annual at the current unit price, applied in this order and capped at the cost of each app: "
            "reclaim, downgrade, right-size, negotiate, cancel duplicates, consolidate (the remainder of the app).", "",
            "| Source | File | Records |", "|---|---|---|"]
    out += [f"| {FILES.get(k, k)} | `{k}` | {v:,} |" for k, v in d.sources.items()]
    out += ["", "## Notes", "", f"- Decisions taken: {TODO}", f"- Notices sent (vendor, date, by whom): {TODO}", f"- Next review: {TODO}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--info:#0b6bcb;
--g:#cfeedd;--a:#fbe6bd;--r:#f8d2cd;--n:#eef0f2;--act:#2f8f5b;--idle:#8fb9a3;--off:#d9822b;--lv:#c0392b;--free:#c9ced4}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;
--bad:#f2685c;--info:#5aa9f0;--g:#173527;--a:#3d2f12;--r:#45201d;--n:#232a31;--act:#3fae74;--idle:#5f8b74;--off:#e0913f;--lv:#e05a4c;--free:#46505a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:24px}
.overall{display:inline-block;margin-top:14px;padding:6px 14px;border-radius:99px;font-weight:700;border:2px solid currentColor}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.red{color:var(--bad)}.amber{color:var(--warn)}.green{color:var(--ok)}
.bar{display:flex;height:14px;min-width:160px;border-radius:4px;overflow:hidden;background:var(--n)}.bar span{display:block;height:100%}
.b-act{background:var(--act)}.b-idle{background:var(--idle)}.b-off{background:var(--off)}.b-lv{background:var(--lv)}.b-free{background:var(--free)}
.legend span{display:inline-block;margin-right:14px;font-size:13px}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.hbar{height:12px;background:var(--info);border-radius:3px}.lever td{vertical-align:middle}
td.subj{min-width:150px}td.nw{white-space:nowrap}td.fix{font-size:13px;color:var(--muted);min-width:200px;max-width:340px}td.sm{font-size:13px}
.brk{overflow-wrap:anywhere;word-break:break-word}tr.soon td{background:var(--r)}tr.near td{background:var(--a)}
footer{margin-top:40px;font-size:13px}
"""


def _cls(x: str) -> str:
    return x.lower()


def _pill(x: str) -> str:
    return f"<span class='pill {_cls(x)}'>{e(x)}</span>"


def _table(head: list[str], rows: list[str], cls: str = "") -> str:
    return (f"<div class='wrap'><table class='{cls}'><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" + "".join(rows)
            + "</table></div>")


def _bar(u) -> str:
    """Seats split into active, idle, inactive or never used, leavers and unassigned (over-assignment widens the base)."""
    base = max(u.seats or 0, u.assigned) or 1
    parts = [("b-act", u.active - u.idle, "active"), ("b-idle", u.idle, "idle"), ("b-off", u.inactive + u.never, "inactive or never used"),
             ("b-lv", u.leavers, "leavers"), ("b-free", u.unassigned, "unassigned")]
    other = u.assigned - (u.active + u.inactive + u.never + u.leavers)
    if other > 0:
        parts.insert(2, ("b-idle", other, "on leave or no date"))
    return ("<div class='bar'>" + "".join(f"<span class='{c}' style='width:{100 * n / base:.1f}%' title='{n} {t}'></span>"
                                          for c, n, t in parts if n > 0) + "</div>")


def render_html(d: Data, rv: dict, title: str) -> str:
    s = d.settings
    sm = summary(d, rv)
    cur = s.currency
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>{e(s.organisation)} · {sm['apps']} apps, {sm['contracts']} contracts · {sm['users']:,} people "
         f"in the HR list · {sm['assignments']:,} licence assignments · run on {d.as_of:%a %d %b %Y %H:%M}</p>",
         f"<span class='overall {_cls(sm['status'])}'>{e(sm['status'])} · {sm['red']} red and {sm['amber']} amber findings</span>",
         "<div class='tiles'>"]
    tiles = [("Annual spend", money(sm["total"], cur), f"{sm['apps']} apps"),
             ("Savings identified", money(sm["saving"], cur), f"{sm['saving_pct']:.1f} % of the spend"),
             ("Renewals in 90 days", str(sm["renewals_90"]), f"{len(rv['calendar'])} in 12 months"),
             ("Notice deadlines", str(sm["deadlines_30"]), "in the next 30 days"),
             ("Shadow-IT apps", str(sm["shadow"]), "bought on expenses"),
             ("Leaver licences", str(sm["leaver_licences"]), "still assigned"),
             ("To reclaim", f"{sm['reclaim']:,}", f"and {sm['downgrade']:,} to downgrade"),
             ("True-up risk", money(sm["true_up"], cur), "seats over purchased")]
    h += [f"<div class='tile'><span class='muted'>{e(a)}</span><b>{e(b)}</b><span class='muted'>{e(c)}</span></div>" for a, b, c in tiles]
    h.append("</div><h2>Savings by action</h2>")
    top = max(sm["by_lever"].values()) or 1
    h.append(_table(["Action", "Saving a year", ""], [f"<tr><td>{e(LEVER_LABEL[k])}</td><td class='num'>{money(v, cur)}</td>"
                                                      f"<td style='width:60%'><div class='hbar' style='width:{100 * v / top:.1f}%'></div></td></tr>"
                                                      for k, v in sm["by_lever"].items()], "lever"))
    h.append("<h2>Decisions needed</h2><p class='muted'>For the IT manager and finance before the renewals: each with options, a proposal, "
             "the saving and the date it is needed by.</p>")
    h.append(_table(["#", "Decision", "Options", "Proposed", "Saving", "Owner", "By"],
                    [f"<tr><td class='nw'>{e(x.id)}</td><td class='subj'><b>{e(x.decision)}</b><br><span class='sm muted'>{e(x.why)}</span></td>"
                     f"<td class='sm'>{e(x.options)}</td><td class='fix'>{e(x.proposed)}</td><td class='num'>"
                     f"{e(money(x.saving, cur)) if x.saving else '–'}</td><td class='sm'>{e(x.owner)}</td><td class='nw'>{e(_day(x.needed_by))}</td></tr>"
                     for x in rv["decisions"]] or ["<tr><td colspan='7'>No decisions needed.</td></tr>"]))
    h.append("<h2>Utilisation per app</h2><p class='muted legend'><span><i class='b-act'></i>active</span><span><i class='b-idle'></i>idle "
             f"{s.inactive_days.get('warning', 30)}–{s.inactive_days.get('reclaim', 60)} days or on leave</span><span><i class='b-off'></i>"
             "inactive or never used</span><span><i class='b-lv'></i>leavers</span><span><i class='b-free'></i>unassigned</span></p>")
    rows = []
    for u in rv["usage"]:
        c = u.contract
        sev = min((f.severity for f in u.findings), key=lambda x: {RED: 0, AMBER: 1}[x], default=GREEN)
        if c.per_user:
            cells = (f"<td class='num'>{_f(u.seats, 0) or '–'}</td><td class='num'>{u.assigned:,}</td>"
                     f"<td class='num'>{_f(u.utilisation, 0) or '–'} %</td><td>{_bar(u)}</td>")
        else:
            cells = f"<td class='num'>{_f(u.seats, 0) or '–'}</td><td class='num muted'>–</td><td class='num muted'>–</td><td class='sm muted'>{e(c.model)}</td>"
        rows.append(f"<tr><td class='nw'><b>{e(c.app)}</b> <span class='muted sm'>{e(c.sku)}</span></td><td>{_pill(sev)}</td>{cells}"
                    f"<td class='num'>{money(c.annual_cost, cur)}</td><td class='num'>{money(u.saving, cur) if u.saving else '–'}</td></tr>")
    h.append(_table(["App", "Status", "Seats", "Assigned", "Used", "Seats by use", "Annual cost", "Saving"], rows))
    h.append(f"<h2>Renewal calendar</h2><p class='muted'>The next {s.calendar_months} months. Red rows: notice deadline in "
             f"{s.notice_warning_days.get('red', 14)} days or less, or passed; amber: within {s.notice_warning_days.get('amber', 45)} days.</p>")
    use = {u.contract.key: u for u in rv["usage"]}
    crow = []
    for x in rv["calendar"]:
        c = x["contract"]
        dd = x["days_to_deadline"]
        cls = "soon" if dd is not None and dd <= s.notice_warning_days.get("red", 14) else "near" if dd is not None and dd <= s.notice_warning_days.get("amber", 45) else ""
        ut = use[c.key].utilisation if c.per_user else None
        crow.append(f"<tr class='{cls}'><td class='nw'>{e(_day(x['renewal']))}</td><td class='nw'><b>{e(c.app)}</b> <span class='muted sm'>"
                    f"{e(c.sku)}</span></td><td class='num'>{money(c.annual_cost, cur)}</td><td class='num'>{_f(c.uplift_pct, 1) or '–'} %</td>"
                    f"<td class='nw'>{e(_day(x['deadline']))}</td><td class='num'>{'' if dd is None else dd}</td>"
                    f"<td>{'yes' if c.auto_renew else 'no'}</td><td class='num'>{'–' if ut is None else format(ut, '.0f') + ' %'}</td>"
                    f"<td class='num'>{money(x['saving'], cur) if x['saving'] else '–'}</td><td class='sm'>{e(x['state'])}</td>"
                    f"<td class='sm'>{e(c.owner or 'nobody')}</td></tr>")
    h.append(_table(["Renewal", "App", "Annual", "Uplift", "Notice by", "Days", "Auto", "Used", "Saving", "State", "Owner"], crow))
    h.append("<h2>Showback</h2><p class='muted'>Per-user licences charged to the holder's department; unassigned seats and flat or "
             "per-device contracts stay on the contract's cost centre. The rows add up to the annual spend.</p>")
    mx = max((r["cost"] for r in rv["showback"]), default=1) or 1
    h.append(_table(["Department", "Cost centre", "People", "Licences", "Annual cost", "Share", "Per person", ""],
                    [f"<tr><td class='nw'>{e(r['department'])}</td><td class='nw'>{e(r['cost_centre'])}</td><td class='num'>{r['users']:,}</td>"
                     f"<td class='num'>{r['licences']:,}</td><td class='num'>{money(r['cost'], cur)}</td><td class='num'>{r['share']:.1f} %</td>"
                     f"<td class='num'>{money(r['per_user'], cur) if r['per_user'] else '–'}</td><td style='width:25%'>"
                     f"<div class='hbar' style='width:{100 * r['cost'] / mx:.1f}%'></div></td></tr>" for r in rv["showback"]]))
    if rv["shadow"]:
        h.append("<h2>Shadow IT</h2>")
        h.append(_table(["Product", "Status", "Lines", "Spend (12 months)", "People", "Departments"],
                        [f"<tr><td><b>{e(r['product'])}</b></td><td class='sm'>{e(r['status'])}</td><td class='num'>{r['lines']}</td>"
                         f"<td class='num'>{money(r['spend'], cur)}</td><td class='num'>{r['people']}</td>"
                         f"<td class='sm'>{e(', '.join(r['departments']) or '–')}</td></tr>" for r in rv["shadow"]]))
    h.append("<h2>All findings</h2>")
    h.append(_table(["Severity", "Area", "Subject", "Detail", "Saving", "Owner", "Due"],
                    [f"<tr><td>{_pill(f.severity)}</td><td class='sm'>{e(AREA_LABEL[f.area])}</td><td class='subj'><b>{e(f.subject)}</b><br>"
                     f"<span class='sm muted'>{e(f.title)}</span></td><td class='sm brk'>{e(f.detail)}</td>"
                     f"<td class='num'>{money(f.saving, cur) if f.saving else '–'}</td><td class='sm'>{e(f.owner)}</td>"
                     f"<td class='nw'>{e(_day(f.due))}</td></tr>" for f in rv["findings"]]))
    h.append("<footer class='muted'>Generated by licencereview. Fictional demo data unless you ran it on your own exports. The one-page "
             "pack for the IT manager and finance is review-pack.md; the users to reclaim or downgrade are in reclaim-list.csv.</footer>"
             "</main></body></html>")
    return "".join(h)


__all__ = ["render_html", "pack_md", "write_utilisation", "write_reclaim", "write_calendar", "write_showback", "write_findings",
           "write_actions", "actions"]
