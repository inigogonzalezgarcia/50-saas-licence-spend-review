"""The SaaS and licence checks. Usage: licences unused for N days, never used since they were assigned, still assigned to leavers,
assigned to people on long leave or to accounts HR does not know, and premium tiers for people who do not use the premium features
(downgrade). Seats: shelfware (purchased seats nobody holds) and over-assignment (true-up risk). Renewals: notice deadlines close
or passed on auto-renewing contracts, uplifts above the threshold, contracts with no owner, and the renewal calendar. Portfolio:
overlapping apps for the same capability (consolidation) and apps without SSO that hold confidential data. Shadow IT: SaaS bought on
expenses that is not in the register, and expenses for a vendor already under a central contract. Cost allocation: showback per
department and cost centre, contracts with no or an unknown cost centre, and spend against budget per category. Every saving is
counted once per app, capped at what the app costs."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .model import Contract, Data, _norm, next_renewal, notice_deadline

GREEN, AMBER, RED = "GREEN", "AMBER", "RED"
SEV_ORDER = {RED: 0, AMBER: 1, GREEN: 2}
AREAS = ["usage", "seats", "renewals", "portfolio", "shadow", "allocation"]
AREA_LABEL = {"usage": "Usage", "seats": "Seats", "renewals": "Renewals", "portfolio": "Portfolio", "shadow": "Shadow IT",
              "allocation": "Cost allocation"}
ACTIONS = ["reclaim", "downgrade", "right-size", "negotiate", "consolidate", "cancel"]
# code: area, title, action type (the saving lever or the owner key)
CHECKS = {
    "USE-LEAVER": ("usage", "Licences still assigned to leavers", "reclaim"),
    "USE-INACTIVE": ("usage", "Licences unused for a long time", "reclaim"),
    "USE-NEVER": ("usage", "Licences never used since assigned", "reclaim"),
    "USE-DOWNGRADE": ("usage", "Premium tier without premium use", "downgrade"),
    "USE-LEAVE": ("usage", "Licences of people on long leave", "reclaim"),
    "USE-UNKNOWN": ("usage", "Licences held by accounts HR does not know", "security"),
    "SEAT-OVER": ("seats", "More assigned than purchased (true-up risk)", "sam"),
    "SEAT-SHELF": ("seats", "Shelfware: purchased seats not assigned", "right-size"),
    "REN-NOTICE": ("renewals", "Renewal notice deadline close or passed", "negotiate"),
    "REN-UPLIFT": ("renewals", "Renewal uplift above the threshold", "negotiate"),
    "REN-OWNER": ("renewals", "Contract with no owner", "sam"),
    "PRT-OVERLAP": ("portfolio", "Overlapping apps for the same capability", "consolidate"),
    "PRT-SSO": ("portfolio", "Confidential data in an app without SSO", "security"),
    "SHD-UNMANAGED": ("shadow", "SaaS bought on expenses, not in the register", "security"),
    "SHD-DUPLICATE": ("shadow", "Expenses for a vendor under a central contract", "cancel"),
    "ALC-NOCC": ("allocation", "Contract with no cost centre", "finance"),
    "ALC-CC": ("allocation", "Contract with an unknown cost centre", "finance"),
    "ALC-BUDGET": ("allocation", "Spend over budget", "finance"),
}
SAVING_ORDER = {"reclaim": 0, "downgrade": 1, "right-size": 2, "negotiate": 3, "cancel": 4, "consolidate": 5}


@dataclass
class Finding:
    code: str
    severity: str                  # RED or AMBER
    apps: list                     # contract keys (or product names for shadow IT)
    subject: str
    detail: str
    action: str
    saving: float = 0.0            # annual, in the settings currency, after the per-app cap
    risk: float = 0.0              # cost exposure that is not a saving (true-up, unmanaged spend)
    count: int = 0                 # users, seats or lines behind it
    owner: str = ""
    due: date | None = None

    @property
    def area(self) -> str:
        return CHECKS[self.code][0]

    @property
    def title(self) -> str:
        return CHECKS[self.code][1]

    @property
    def lever(self) -> str:
        return CHECKS[self.code][2]


@dataclass
class Usage:
    contract: Contract
    assigned: int = 0
    active: int = 0                # last activity within the reclaim window
    idle: int = 0                  # between the warning and the reclaim window
    inactive: int = 0              # older than the reclaim window
    never: int = 0                 # no activity, assigned before the grace period
    leavers: int = 0
    leave: int = 0
    unknown: int = 0
    downgrade: int = 0
    saving: float = 0.0
    findings: list = field(default_factory=list)

    @property
    def seats(self) -> float | None:
        return self.contract.seats

    @property
    def unassigned(self) -> int:
        return max(0, int(round(self.seats or 0)) - self.assigned)

    @property
    def utilisation(self) -> float | None:
        """Active holders over purchased seats (or over assigned when the seats are not known)."""
        base = self.seats or self.assigned
        return 100 * self.active / base if base else None


def money(x: float | None, cur: str = "EUR") -> str:
    if x is None:
        return "–"
    a = abs(x)
    s = f"{a / 1e6:.2f}M" if a >= 1e6 else f"{a / 1e3:.1f}k" if a >= 1e4 else f"{a:,.0f}"
    return f"{'-' if x < 0 else ''}{cur} {s}"


def _n(k: int, word: str, plural: str | None = None) -> str:
    return f"{k:,} {word if k == 1 else (plural or word + 's')}"


def _sev(value: float, th: dict) -> str | None:
    return RED if value > th["red"] else AMBER if value > th["amber"] else None


def worst(xs) -> str:
    xs = list(xs)
    return min(xs, key=lambda x: SEV_ORDER[x]) if xs else GREEN


# ---------------------------------------------------------------- usage and seats

def usage(d: Data) -> tuple[dict, list[dict]]:
    """Per contract: who holds it and how they use it. Returns the usage per contract key and the reclaim list (one row per user and
    licence with the reason and the saving)."""
    s = d.settings
    t = d.today
    warn, recl = int(s.inactive_days.get("warning", 30)), int(s.inactive_days.get("reclaim", 60))
    by = {c.key: Usage(c) for c in d.contracts}
    cons = {c.key: c for c in d.contracts}
    lower = {}
    for c in d.contracts:
        if c.downgrade_to:
            lower[c.key] = next((x for x in d.contracts if _norm(x.app) == _norm(c.app) and _norm(x.sku) == _norm(c.downgrade_to)), None)
    reclaim = []
    users = d.users or {}
    for a in sorted(d.assignments or [], key=lambda a: (a.contract, a.user)):
        if not a.contract:
            continue
        u = by[a.contract]
        c = cons[a.contract]
        u.assigned += 1
        who = users.get(a.user)
        age = (t - a.last_active).days if a.last_active else None
        reason = ""
        if d.users is not None and who and who.status == "leaver":
            u.leavers += 1
            reason = "leaver" + (f" since {who.leave_date:%d %b %Y}" if who.leave_date else "")
        elif d.users is not None and who and who.status == "leave":
            u.leave += 1
        elif d.users is not None and not who:
            u.unknown += 1
        if age is not None and age <= recl:
            u.active += 1
            if age > warn:
                u.idle += 1
        elif not reason and who and who.status == "leave":
            pass
        elif not reason:
            if age is None:
                if a.assigned and (t - a.assigned).days > s.never_used_grace_days:
                    u.never += 1
                    reason = f"never used since {a.assigned:%d %b %Y}"
            else:
                u.inactive += 1
                reason = f"no activity for {age} days"
        if reason and c.per_user and c.unit_price:
            reclaim.append({"user": a.user, "name": who.name if who else "", "department": who.department if who else "",
                            "app": c.app, "sku": c.sku, "contract": c.key, "reason": reason, "lever": "reclaim",
                            "last_active": a.last_active, "saving": c.unit_price})
        elif (not reason and a.premium is False and lower.get(c.key) and c.unit_price and lower[c.key].unit_price
              and (age is not None and age <= recl) and not (who and who.status != "active")):
            u.downgrade += 1
            reclaim.append({"user": a.user, "name": who.name if who else "", "department": who.department if who else "",
                            "app": c.app, "sku": c.sku, "contract": c.key, "reason": f"downgrade to {lower[c.key].sku}: no premium use",
                            "lever": "downgrade", "last_active": a.last_active,
                            "saving": max(0.0, c.unit_price - lower[c.key].unit_price)})
    return by, reclaim


def check_usage(d: Data, by: dict, reclaim: list[dict]) -> list[Finding]:
    s = d.settings
    cur = s.currency
    out = []
    recl = int(s.inactive_days.get("reclaim", 60))
    groups = defaultdict(list)
    for r in reclaim:
        kind = "leaver" if r["reason"].startswith("leaver") else "never" if r["reason"].startswith("never") else \
            "downgrade" if r["lever"] == "downgrade" else "inactive"
        groups[(r["contract"], kind)].append(r)
    for key in sorted(by):
        u = by[key]
        c = u.contract
        if not u.assigned:
            continue
        lv = groups.get((key, "leaver"), [])
        if u.leavers:
            out.append(Finding("USE-LEAVER", RED, [key], c.key, f"{_n(u.leavers, 'licence')} still assigned to people who have left"
                               + (f" ({', '.join(r['user'] for r in lv[:3])}{'…' if len(lv) > 3 else ''})" if lv else ""),
                               "Remove the licences today and check the leaver process: the account should lose its licences when HR "
                               "closes the contract.", sum(r["saving"] for r in lv), count=u.leavers))
        ia = groups.get((key, "inactive"), [])
        if u.inactive:
            share = 100 * u.inactive / u.assigned
            out.append(Finding("USE-INACTIVE", RED if share > s.inactive_share_red_pct else AMBER, [key], c.key,
                               f"{_n(u.inactive, 'licence')} ({share:.0f} % of {u.assigned:,} assigned) with no activity for more than "
                               f"{recl} days", "Tell the holders and their managers, then reclaim the licences that nobody claims "
                               "back in two weeks.", sum(r["saving"] for r in ia), count=u.inactive))
        nv = groups.get((key, "never"), [])
        if u.never:
            out.append(Finding("USE-NEVER", AMBER, [key], c.key, f"{_n(u.never, 'licence')} assigned more than "
                               f"{s.never_used_grace_days} days ago and never used", "Reclaim them, and assign this app on request "
                               "instead of by default.", sum(r["saving"] for r in nv), count=u.never))
        dg = groups.get((key, "downgrade"), [])
        if u.downgrade:
            low = dg[0]["reason"].split(":")[0].replace("downgrade to ", "")
            out.append(Finding("USE-DOWNGRADE", AMBER, [key], c.key, f"{_n(u.downgrade, 'active user')} on {c.sku or c.app} "
                               f"who do not use the premium features; {low} would cover them ({money(dg[0]['saving'], cur)} less per user "
                               "a year)", f"Move them to {low} at the next renewal or true-down, after the app owner checks the list.",
                               sum(r["saving"] for r in dg), count=u.downgrade))
        if u.leave:
            out.append(Finding("USE-LEAVE", AMBER, [key], c.key, f"{_n(u.leave, 'licence')} held by people on long leave",
                               "Keep the account, but suspend or reassign the licence where the vendor allows it, and give it back "
                               "on return.", count=u.leave))
        if u.unknown:
            out.append(Finding("USE-UNKNOWN", AMBER, [key], c.key, f"{_n(u.unknown, 'licence')} held by accounts that are not in "
                               "the HR list (service accounts, external users or old accounts)",
                               "Name an owner for each account or remove the licence.", count=u.unknown))
    return out


def check_seats(d: Data, by: dict) -> list[Finding]:
    s = d.settings
    cur = s.currency
    out = []
    if d.assignments is None:
        return out
    for key in sorted(by):
        u = by[key]
        c = u.contract
        if not c.per_user or not c.seats:
            continue
        if u.assigned > c.seats:
            extra = u.assigned - int(c.seats)
            out.append(Finding("SEAT-OVER", RED, [key], c.key, f"{u.assigned:,} assigned against {c.seats:,.0f} purchased: {extra} over, "
                               f"about {money(extra * (c.unit_price or 0), cur)} a year at the current price if the vendor trues it up",
                               "Reclaim inactive licences first, then buy the missing seats before the vendor's audit or the renewal "
                               "true-up.", risk=extra * (c.unit_price or 0), count=extra))
        elif u.unassigned and u.assigned:
            pct = 100 * u.unassigned / c.seats
            sev = _sev(pct, s.shelfware_pct)
            if sev:
                out.append(Finding("SEAT-SHELF", sev, [key], c.key, f"{u.unassigned:,} of {c.seats:,.0f} seats ({pct:.0f} %) not assigned",
                                   "Reduce the seats at the renewal (true-down), or use them before buying more.",
                                   u.unassigned * (c.unit_price or 0), count=u.unassigned))
    return out


# ---------------------------------------------------------------- renewals

def calendar(d: Data, ledger: dict) -> list[dict]:
    s = d.settings
    t = d.today
    end = t + timedelta(days=int(30.44 * s.calendar_months))
    out = []
    for c in d.contracts:
        r = next_renewal(c, t)
        if not r or r < t or r > end:
            continue
        dl = notice_deadline(c, t)
        up = c.uplift_pct or 0
        days_dl = (dl - t).days if dl else None
        if days_dl is not None and days_dl < 0:
            state = "notice passed" if c.auto_renew else "ends: renew or let lapse"
        elif days_dl is not None and days_dl <= s.notice_warning_days.get("red", 14):
            state = "act now"
        elif (r - t).days <= s.renewal_horizon_days:
            state = "prepare"
        else:
            state = "plan"
        out.append({"contract": c, "renewal": r, "deadline": dl, "days_to_deadline": days_dl, "days_to_renewal": (r - t).days,
                    "annual": c.annual_cost, "after_uplift": c.annual_cost * (1 + up / 100), "saving": ledger.get(c.key, 0.0),
                    "state": state})
    return sorted(out, key=lambda x: (x["renewal"], x["contract"].key))


def check_renewals(d: Data) -> list[Finding]:
    s = d.settings
    t = d.today
    cur = s.currency
    out = []
    horizon_end = t + timedelta(days=s.renewal_horizon_days)
    year_end = t + timedelta(days=int(30.44 * s.calendar_months))
    for c in d.contracts:
        r = next_renewal(c, t)
        dl = notice_deadline(c, t)
        if r and t <= r <= horizon_end and dl:
            left = (dl - t).days
            if c.auto_renew and left < 0:
                out.append(Finding("REN-NOTICE", RED, [c.key], c.key, f"renews automatically on {r:%d %b %Y}; the {c.notice_days}-day "
                                   f"notice deadline passed on {dl:%d %b %Y}", "Ask the vendor in writing for a reduction anyway; "
                                   "set the deadline for the next term in the calendar now.", count=c.notice_days))
            elif c.auto_renew and left <= s.notice_warning_days.get("amber", 45):
                out.append(Finding("REN-NOTICE", RED if left <= s.notice_warning_days.get("red", 14) else AMBER, [c.key], c.key,
                                   f"renews automatically on {r:%d %b %Y} for {money(c.annual_cost, cur)}; notice deadline "
                                   f"{dl:%a %d %b %Y}, in {_n(left, 'day')}", "Decide renew, reduce or cancel and send the notice "
                                   "before the deadline; without it the contract renews as it is.", due=max(t, dl - timedelta(days=2)),
                                   count=left))
            elif not c.auto_renew and left <= s.notice_warning_days.get("amber", 45):
                out.append(Finding("REN-NOTICE", AMBER, [c.key], c.key, f"ends on {r:%d %b %Y} without automatic renewal; decision "
                                   f"needed by {dl:%d %b %Y}", "Renew with the right number of seats, or plan the exit and the data "
                                   "export.", due=max(t, dl - timedelta(days=2)), count=max(left, 0)))
        if r and t <= r <= year_end and c.uplift_pct is not None and c.uplift_pct > s.uplift_threshold_pct:
            extra = c.annual_cost * (c.uplift_pct - s.uplift_threshold_pct) / 100
            out.append(Finding("REN-UPLIFT", AMBER, [c.key], c.key, f"{c.uplift_pct:.1f} % uplift at the renewal on {r:%d %b %Y} against "
                               f"a {s.uplift_threshold_pct:.0f} % cap: {money(c.annual_cost * c.uplift_pct / 100, cur)} more a year, "
                               f"{money(extra, cur)} of it above the cap", "Negotiate with the usage data: cap the uplift, trade it "
                               "for a longer term or fewer seats, and write the cap into the next term.", extra))
        if not c.owner.strip():
            out.append(Finding("REN-OWNER", AMBER, [c.key], c.key, f"{money(c.annual_cost, cur)} a year"
                               + (f", renews on {r:%d %b %Y}" if r else "") + " and nobody owns the contract",
                               "Name a business owner who answers for the usage, the renewal decision and the budget."))
    return out


# ---------------------------------------------------------------- portfolio

def check_portfolio(d: Data, ledger: dict) -> list[Finding]:
    s = d.settings
    cur = s.currency
    out = []
    apps = defaultdict(list)              # capability -> app -> contracts
    for c in d.contracts:
        if c.category:
            apps[_norm(c.category)].append(c)
    suites = {_norm(k): k for k in s.suite_capabilities}
    present = {_norm(c.app): c.app for c in d.contracts}
    for cap in sorted(apps):
        byapp = defaultdict(list)
        label = apps[cap][0].category
        for c in apps[cap]:
            byapp[c.app].append(c)
        suite = next((present[k] for k, v in suites.items() if k in present
                      and cap in {_norm(x) for x in s.suite_capabilities[v]} and present[k] not in byapp), None)
        names = sorted(byapp, key=lambda a: (-sum(c.annual_cost for c in byapp[a]), a))
        if suite and names:
            keep, exit_ = suite, names
        elif len(names) >= 2:
            keep, exit_ = names[0], names[1:]
        else:
            continue
        cs = [c for a in exit_ for c in byapp[a]]
        saving = sum(max(0.0, c.annual_cost - ledger.get(c.key, 0.0)) for c in cs)
        for c in cs:
            ledger[c.key] = max(ledger.get(c.key, 0.0), c.annual_cost)
        listed = ", ".join(f"{a} ({money(sum(c.annual_cost for c in byapp[a]), cur)})" for a in exit_)
        out.append(Finding("PRT-OVERLAP", AMBER, [c.key for c in cs], label,
                           f"{keep} " + ("already covers it in the suite" if keep == suite else "is the largest") + f", and the "
                           f"company also pays for {listed}", f"Standardise on {keep} and exit the others at their renewal, with a "
                           "migration plan for the people who use them.", saving, count=len(exit_)))
    for c in d.contracts:
        if c.sso is False and _norm(c.data_class) in {_norm(x) for x in s.confidential_classes}:
            out.append(Finding("PRT-SSO", AMBER, [c.key], c.key, f"{c.data_class} data and no single sign-on: leavers keep access until "
                               "someone removes them by hand, and MFA depends on the app", "Integrate it with Entra ID (SAML or OIDC, "
                               "with provisioning if the plan includes it), or move the data."))
    return out


# ---------------------------------------------------------------- shadow IT

def _has(text: str, word: str) -> bool:
    w = _norm(word)
    return bool(w) and f" {w} " in f" {text} "


def shadow(d: Data) -> tuple[list[Finding], list[dict]]:
    s = d.settings
    t = d.today
    cur = s.currency
    if d.expenses is None:
        return [], []
    since = t - timedelta(days=int(30.44 * s.expense_months))
    names = []
    for c in d.contracts:
        for n in {c.vendor, c.app}:
            if _norm(n):
                names.append((n, c))
    unmanaged, dup = defaultdict(list), defaultdict(list)
    for e in d.expenses:
        if e.date and (e.date < since or e.date > t):
            continue
        text = _norm(f"{e.supplier} {e.description}")
        hit = next(((n, c) for n, c in names if _has(_norm(e.supplier), n)), None)
        if hit:
            if e.employee:                     # bought by a person, not invoiced to the central contract
                dup[hit[1].app].append((e, hit[1]))
            continue
        prod = next((p for k, p in sorted(s.saas_vendors.items(), key=lambda x: -len(x[0])) if _has(text, k)), None)
        if prod:
            unmanaged[prod].append(e)
    out, rows = [], []
    users = d.users or {}
    for prod in sorted(unmanaged):
        es = unmanaged[prod]
        total = sum(e.amount for e in es)
        people = sorted({e.employee for e in es if e.employee})
        depts = sorted({users[p].department for p in people if p in users and users[p].department})
        out.append(Finding("SHD-UNMANAGED", AMBER, [prod], prod, f"{_n(len(es), 'expense line')}, {money(total, cur)} in the last "
                           f"{s.expense_months} months, {_n(len(people), 'person', 'people')}" + (f" in {', '.join(depts)}" if depts else "")
                           + "; no contract, no security review, no SSO", "Talk to the people who buy it: adopt it centrally with "
                           "SSO and a contract, move them to an approved app that does the same, or accept it in writing.",
                           risk=total, count=len(people)))
        rows.append({"product": prod, "status": "not in the register", "lines": len(es), "spend": total, "people": len(people),
                     "departments": depts})
    for app in sorted(dup):
        es = dup[app]
        total = sum(e.amount for e, _ in es)
        people = sorted({e.employee for e, _ in es})
        out.append(Finding("SHD-DUPLICATE", AMBER, [es[0][1].key], app, f"{_n(len(es), 'expense line')}, {money(total, cur)} on cards "
                           f"by {_n(len(people), 'person', 'people')} for {app}, which is already under a central contract",
                           "Give these people a seat from the central contract and stop the card subscriptions.", total,
                           count=len(people)))
        rows.append({"product": app, "status": "already under a central contract", "lines": len(es), "spend": total,
                     "people": len(people), "departments": sorted({users[p].department for p in people if p in users})})
    return out, rows


# ---------------------------------------------------------------- cost allocation

def showback(d: Data) -> list[dict]:
    """Licence cost per department and cost centre. Per-user licences are charged to the department of the holder; unassigned seats,
    and flat or per-device contracts, stay on the contract's cost centre. The rows add up to the annual spend."""
    users = d.users or {}
    rows = defaultdict(lambda: {"cost": 0.0, "licences": 0, "users": set(), "apps": Counter()})
    held = defaultdict(list)
    for a in d.assignments or []:
        if a.contract:
            held[a.contract].append(a)
    for c in d.contracts:
        hs = held.get(c.key, []) if c.per_user else []
        if hs:
            rate = c.annual_cost / max(c.seats or 0, len(hs))
            for a in hs:
                u = users.get(a.user)
                k = (u.department or "(no department)", u.cost_centre or "") if u else ("(not in the HR list)", "")
                r = rows[k]
                r["cost"] += rate
                r["licences"] += 1
                r["users"].add(a.user)
                r["apps"][c.app] += rate
            rest = c.annual_cost - rate * len(hs)
            label = "Unassigned seats"
        else:
            rest = c.annual_cost
            label = "Central contracts"
        if rest > 0.005:
            r = rows[(label, c.cost_centre or "(none)")]
            r["cost"] += rest
            r["apps"][c.app] += rest
    total = sum(r["cost"] for r in rows.values()) or 1
    out = []
    for (dept, cc), r in rows.items():
        out.append({"department": dept, "cost_centre": cc, "users": len(r["users"]), "licences": r["licences"], "cost": r["cost"],
                    "share": 100 * r["cost"] / total, "per_user": r["cost"] / len(r["users"]) if r["users"] else None,
                    "top_apps": [a for a, _ in sorted(r["apps"].items(), key=lambda x: (-x[1], x[0]))[:3]]})
    special = ("Unassigned seats", "Central contracts", "(not in the HR list)", "(no department)")
    return sorted(out, key=lambda x: (x["department"] in special, -x["cost"], x["department"], x["cost_centre"]))


def check_allocation(d: Data) -> list[Finding]:
    s = d.settings
    cur = s.currency
    out = []
    valid = {_norm(x) for x in s.cost_centres} | {_norm(u.cost_centre) for u in (d.users or {}).values() if u.cost_centre}
    for c in d.contracts:
        if not c.cost_centre.strip():
            out.append(Finding("ALC-NOCC", AMBER, [c.key], c.key, f"{money(c.annual_cost, cur)} a year with no cost centre: it lands in "
                               "an IT overhead nobody reviews", "Agree the cost centre with finance and the owner, and record it in "
                               "the register."))
        elif valid and _norm(c.cost_centre) not in valid:
            out.append(Finding("ALC-CC", AMBER, [c.key], c.key, f"cost centre {c.cost_centre} is not in the list of valid cost centres "
                               f"({money(c.annual_cost, cur)} a year)", "Correct the cost centre with finance."))
    spend = defaultdict(float)
    for c in d.contracts:
        spend[c.category or "(none)"] += c.annual_cost
    for k, v in sorted(s.budgets.items()):
        b = float(v or 0)
        actual = sum(spend.values()) if _norm(k) == "total" else next((x for n, x in spend.items() if _norm(n) == _norm(k)), 0.0)
        if b and actual > b:
            over = 100 * (actual - b) / b
            out.append(Finding("ALC-BUDGET", RED if over > s.budget_red_pct else AMBER, [], "Total" if _norm(k) == "total" else k,
                               f"{money(actual, cur)} a year against a budget of {money(b, cur)}: +{over:.1f} %",
                               "Fund the gap or bring the savings in this review forward to the renewals in this category.",
                               risk=actual - b))
    return out


# ---------------------------------------------------------------- everything

def _cap(findings: list[Finding], cons: dict) -> dict:
    """Count each euro once per app: savings are applied in lever order and capped at what the app costs."""
    ledger = defaultdict(float)
    for f in sorted([f for f in findings if f.saving and f.lever in SAVING_ORDER and f.code != "PRT-OVERLAP"],
                    key=lambda f: (SAVING_ORDER[f.lever], f.apps[:1], f.code)):
        c = cons.get(f.apps[0]) if f.apps else None
        if not c:
            continue
        room = max(0.0, c.annual_cost - ledger[c.key])
        f.saving = min(f.saving, room)
        ledger[c.key] += f.saving
    return ledger


def review(d: Data) -> dict:
    s = d.settings
    t = d.today
    cons = {c.key: c for c in d.contracts}
    by, reclaim = usage(d)
    findings = check_usage(d, by, reclaim) + check_seats(d, by) + check_renewals(d)
    sh, shadow_rows = shadow(d)
    findings += sh
    ledger = _cap(findings, cons)
    findings += check_portfolio(d, ledger)
    findings += check_allocation(d)
    for f in findings:
        if f.code == "PRT-OVERLAP":
            continue
        for k in f.apps[:1]:
            if k in by and f.saving:
                by[k].saving += f.saving
    for f in findings:
        if f.code == "PRT-OVERLAP":
            for k in f.apps:
                by[k].saving = cons[k].annual_cost
    for f in findings:
        for k in f.apps:
            if k in by:
                by[k].findings.append(f)
        lever = f.lever
        c = cons.get(f.apps[0]) if f.apps else None
        if f.area == "renewals" and c and c.owner and f.code != "REN-OWNER":
            f.owner = c.owner
        else:
            f.owner = s.owner(lever)
        due = t + timedelta(days=int(s.action_days.get("red" if f.severity == RED else "amber", 15)))
        f.due = min(due, f.due) if f.due else due
    findings.sort(key=lambda f: (SEV_ORDER[f.severity], list(CHECKS).index(f.code), -f.saving, f.subject))
    total = sum(c.annual_cost for c in d.contracts)
    saving = sum(f.saving for f in findings)
    by_lever = {k: sum(f.saving for f in findings if f.lever == k) for k in ACTIONS}
    cal = calendar(d, {k: u.saving for k, u in by.items()})
    status = worst(f.severity for f in findings)
    rv = {"usage": [by[k] for k in sorted(by, key=lambda k: (-cons[k].annual_cost, k))], "reclaim": sorted(reclaim, key=lambda r: (
        r["app"], r["sku"], r["lever"], r["user"])), "findings": findings, "total": total, "saving": saving,
          "saving_pct": 100 * saving / total if total else 0.0, "by_lever": by_lever, "calendar": cal, "shadow": shadow_rows,
          "showback": showback(d), "status": status}
    rv["decisions"] = decisions(d, rv)
    return rv


# ---------------------------------------------------------------- decisions before the renewals

@dataclass
class Decision:
    id: str
    decision: str
    why: str
    options: str
    proposed: str
    saving: float
    owner: str
    needed_by: date | None


def decisions(d: Data, rv: dict) -> list[Decision]:
    s = d.settings
    cur = s.currency
    cons = {c.key: c for c in d.contracts}
    use = {u.contract.key: u for u in rv["usage"]}
    fs = rv["findings"]
    out = []
    for f in fs:
        c = cons.get(f.apps[0]) if f.apps else None
        if f.code == "REN-NOTICE" and c and f.severity == RED and c.auto_renew and "passed" not in f.detail:
            u = use.get(c.key)
            free = (u.unassigned + u.inactive + u.never + u.leavers) if u else 0
            keep = int(round((c.seats or 0) - free)) if c.seats else None
            sv = u.saving if u else 0.0
            out.append(Decision("", f"Renew, reduce or cancel {c.key} before {notice_deadline(c, d.today):%d %b}", f.detail,
                                "Renew as it is / give notice to reduce the seats" + (f" to about {keep}" if keep else "")
                                + " / give notice to cancel and move the users to an app the company already pays for",
                                (f"Give notice to reduce to {keep} seats, from the usage in this review" if keep and sv else
                                 "Confirm the renewal with the owner"), sv, c.owner or s.owner("negotiate"), f.due))
        elif f.code == "PRT-OVERLAP":
            keep = f.action.split("Standardise on ")[1].split(" and exit")[0]
            exit_ = sorted({cons[k].app for k in f.apps})
            first = min((next_renewal(cons[k], d.today) for k in f.apps if cons[k].renewal), default=None)
            out.append(Decision("", f"Standardise {f.subject.lower()} on {keep}", f.detail,
                                f"Keep everything / exit {', '.join(exit_)} at renewal and move the users to {keep} / keep one "
                                "standalone app for a named group with a business reason",
                                f"Exit {', '.join(exit_)} at renewal" + (f" (first renewal {first:%d %b %Y})" if first else ""),
                                f.saving, s.owner("consolidate"), first))
        elif f.code == "USE-DOWNGRADE":
            out.append(Decision("", f"Downgrade {_n(f.count, 'user')} on {f.subject}", f.detail,
                                "Downgrade all of them / downgrade except a named list the managers keep / keep the premium tier",
                                "Downgrade at the next true-down after the app owner reviews the list", f.saving,
                                s.owner("downgrade"), next_renewal(c, d.today) if c else None))
        elif f.code == "REN-UPLIFT" and c:
            out.append(Decision("", f"Negotiate the {c.uplift_pct:.1f} % uplift on {c.key}", f.detail,
                                f"Accept / cap at {s.uplift_threshold_pct:.0f} % / cap in exchange for a longer term / reduce seats",
                                f"Cap at {s.uplift_threshold_pct:.0f} %, with the utilisation in this review as the argument",
                                f.saving, c.owner or s.owner("negotiate"), notice_deadline(c, d.today)))
        elif f.code == "SEAT-OVER" and c:
            out.append(Decision("", f"Close the true-up gap on {c.key}", f.detail, "Buy the missing seats now / reclaim inactive "
                                "licences first and buy the rest / wait for the vendor's true-up", "Reclaim first, then buy the "
                                "rest before the renewal", 0.0, s.owner("sam"), f.due))
    sh = [f for f in fs if f.code == "SHD-UNMANAGED"]
    if sh:
        out.append(Decision("", f"Decide on {_n(len(sh), 'SaaS product')} bought on expenses", "; ".join(f"{f.subject} "
                            f"{money(f.risk, cur)}" for f in sh), "Adopt centrally with SSO and a contract / replace with an approved "
                            "app / accept in writing with a security review", "Adopt the ones with several departments, replace the "
                            "rest", 0.0, s.owner("security"), d.today + timedelta(days=30)))
    out.sort(key=lambda x: (x.needed_by or date.max, -x.saving, x.decision))
    for i, x in enumerate(out, 1):
        x.id = f"D-{i:02d}"
    return out


def summary(d: Data, rv: dict) -> dict:
    t = d.today
    cal = rv["calendar"]
    fs = rv["findings"]
    return dict(status=rv["status"], apps=len({c.app for c in d.contracts}), contracts=len(d.contracts), total=rv["total"],
                saving=rv["saving"], saving_pct=rv["saving_pct"], by_lever=rv["by_lever"],
                red=sum(f.severity == RED for f in fs), amber=sum(f.severity == AMBER for f in fs), findings=len(fs),
                renewals_90=sum(1 for x in cal if x["days_to_renewal"] <= 90),
                deadlines_30=sum(1 for x in cal if x["days_to_deadline"] is not None and 0 <= x["days_to_deadline"] <= 30),
                shadow=sum(1 for f in fs if f.code in ("SHD-UNMANAGED", "SHD-DUPLICATE")),
                leaver_licences=sum(f.count for f in fs if f.code == "USE-LEAVER"),
                reclaim=sum(1 for r in rv["reclaim"] if r["lever"] == "reclaim"),
                downgrade=sum(1 for r in rv["reclaim"] if r["lever"] == "downgrade"),
                true_up=sum(f.risk for f in fs if f.code == "SEAT-OVER"),
                users=len(d.users or {}), assignments=len(d.assignments or []), decisions=len(rv["decisions"]), today=t)


__all__ = ["GREEN", "AMBER", "RED", "AREAS", "AREA_LABEL", "ACTIONS", "CHECKS", "Finding", "Usage", "Decision", "usage", "check_usage",
           "check_seats", "check_renewals", "calendar", "check_portfolio", "shadow", "showback", "check_allocation", "review",
           "decisions", "summary", "money", "worst"]
