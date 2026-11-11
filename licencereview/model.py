"""Loading: the SaaS and licence register (exported from Flexera, Apptio or a contract sheet), the licence assignments with the last
activity of each user, the HR or Entra ID user list and the card expenses and AP invoices. Forgiving column names, into plain
dataclasses."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

CONTRACT_ALIASES = {
    "app": ["App", "Application", "Product", "Software", "Service", "title"],
    "vendor": ["Vendor", "Supplier", "Publisher", "Manufacturer", "provider"],
    "category": ["Category", "Capability", "Function", "software category", "service category"],
    "sku": ["Sku", "SKU", "Tier", "Edition", "Plan", "licence type", "license type", "sku part number", "product name"],
    "model": ["LicenceModel", "Licence model", "License model", "licensing model", "metric", "licence metric", "license metric"],
    "seats": ["SeatsPurchased", "Seats purchased", "Seats", "Quantity", "Licences purchased", "Licenses purchased", "entitlements",
              "purchased", "prepaid units", "licences", "licenses"],
    "unit_price": ["UnitPriceAnnual", "Unit price per year", "Unit price annual", "annual unit price", "price per seat per year",
                   "unit price", "price per seat"],
    "unit_price_month": ["UnitPriceMonthly", "Unit price per month", "monthly unit price", "price per seat per month"],
    "annual_cost": ["AnnualCost", "Annual cost", "Annual value", "Contract value per year", "yearly cost", "acv", "annual spend"],
    "currency": ["Currency", "ccy"],
    "start": ["ContractStart", "Contract start", "Start", "Start date"],
    "renewal": ["RenewalDate", "Renewal date", "Renewal", "End date", "Contract end", "Expiry", "expiry date", "term end"],
    "notice_days": ["NoticeDays", "Notice period days", "Notice days", "notice period", "cancellation notice days"],
    "auto_renew": ["AutoRenew", "Auto renew", "Auto-renew", "Evergreen", "automatic renewal"],
    "uplift": ["UpliftPct", "Uplift %", "Uplift", "Renewal uplift", "price increase", "price increase %"],
    "owner": ["Owner", "Contract owner", "Business owner", "App owner", "service owner"],
    "cost_centre": ["CostCentre", "Cost centre", "Cost center", "CostCenter", "cc"],
    "sso": ["Sso", "SSO", "Single sign-on", "SSO enabled", "sso integrated"],
    "data_class": ["DataClassification", "Data classification", "Classification", "data class", "sensitivity"],
    "downgrade_to": ["DowngradeTo", "Downgrade to", "Lower tier", "downgrade sku"],
}
ASSIGNMENT_ALIASES = {
    "app": ["App", "Application", "Product", "Software", "Service"],
    "sku": ["Sku", "SKU", "Tier", "Edition", "Plan", "licence type", "license type", "sku part number"],
    "user": ["User", "UserPrincipalName", "UPN", "Email", "E-mail", "Mail", "login", "user name", "username"],
    "assigned": ["AssignedDate", "Assigned date", "Assigned", "Date assigned", "assignment date", "created"],
    "last_active": ["LastActive", "Last active", "LastSignIn", "Last sign-in", "Last sign in", "last login", "last activity",
                    "last activity date", "last used", "lastsignindatetime"],
    "premium": ["UsesPremium", "Uses premium features", "Premium used", "premium", "premium features used", "uses premium"],
}
USER_ALIASES = {
    "user": ["User", "UserPrincipalName", "UPN", "Email", "E-mail", "Mail", "login", "work email"],
    "name": ["DisplayName", "Display name", "Name", "Full name", "employee name"],
    "department": ["Department", "Dept", "Business unit", "Team", "Function"],
    "cost_centre": ["CostCentre", "Cost centre", "Cost center", "CostCenter", "cc"],
    "country": ["Country", "Location", "Office", "Site", "usage location"],
    "status": ["Status", "Employment status", "Worker status", "state", "account status", "accountenabled"],
    "leave_date": ["LeaveDate", "Leave date", "Termination date", "End date", "Last day", "leaving date"],
}
EXPENSE_ALIASES = {
    "date": ["Date", "Transaction date", "Expense date", "Invoice date", "posting date"],
    "supplier": ["Supplier", "Vendor", "Merchant", "Payee", "Merchant name"],
    "description": ["Description", "Memo", "Narrative", "Details", "line description", "purpose"],
    "amount": ["Amount", "Amount EUR", "Net amount", "Total", "Value", "Gross amount"],
    "currency": ["Currency", "ccy"],
    "employee": ["Employee", "Spender", "Cardholder", "Requester", "Submitted by", "user"],
    "cost_centre": ["CostCentre", "Cost centre", "Cost center", "CostCenter", "cc"],
}
YES = {"yes", "y", "true", "1", "x", "si", "enabled", "on", "auto", "automatic"}
NO = {"no", "n", "false", "0", "disabled", "off", "manual", "none"}
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%d %b %Y", "%d-%b-%Y")
DEFAULT_OWNERS = {"reclaim": "Service desk lead", "downgrade": "Microsoft 365 administrator", "right-size": "Software asset manager",
                  "negotiate": "IT procurement", "consolidate": "Head of IT", "cancel": "IT finance", "security": "IT security",
                  "finance": "IT finance", "sam": "Software asset manager"}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def parse_dt(v) -> datetime | None:
    s = str(v or "").strip()
    if not s or _norm(s) in {"n a", "na", "none", "null", "never", "tbd"}:
        return None
    s = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", "", s)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def parse_d(v) -> date | None:
    x = parse_dt(v)
    return x.date() if x else None


def num(v) -> float | None:
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def yes_no(v) -> bool | None:
    n = _norm(v)
    if n in YES:
        return True
    if n in NO:
        return False
    return None


def licence_model(v) -> str:
    n = _norm(v)
    if any(w in n for w in ("device", "machine", "endpoint", "seat per device")):
        return "per device"
    if any(w in n for w in ("flat", "site", "enterprise", "tenant", "fixed", "unlimited", "subscription fee", "platform")):
        return "flat"
    return "per user"


def user_status(v) -> str:
    """active, leaver or leave (long leave). Entra ID's accountEnabled false counts as a leaver."""
    n = _norm(v)
    if any(w in n for w in ("leave", "loa", "sabbatical", "maternity", "paternity", "parental", "sick")) and "leaver" not in n:
        return "leave"
    if n in {"false", "disabled", "inactive", "terminated", "left", "leaver", "withdrawn", "former", "ex employee", "exited"} or "terminat" in n:
        return "leaver"
    return "active"


def upn(v) -> str:
    return str(v or "").strip().lower()


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = fh.readline()
        fh.seek(0)
        delim = max(",;\t", key=header.count)
        reader = csv.DictReader(fh, delimiter=delim)
        return list(reader.fieldnames or []), list(reader)


def _map(fields: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    heads = {_norm(h): h for h in fields}
    cols = {}
    for k, names in aliases.items():
        for n in names + [k.replace("_", " ")]:
            if _norm(n) in heads and heads[_norm(n)] not in cols.values():
                cols[k] = heads[_norm(n)]
                break
    return cols


def _rows(path: Path, aliases: dict[str, list[str]]) -> list[dict]:
    fields, raw = _read(path)
    cols = _map(fields, aliases)
    return [{k: (r.get(c) or "").strip() for k, c in cols.items()} for r in raw]


# ---------------------------------------------------------------- records

@dataclass
class Contract:
    app: str
    sku: str = ""
    vendor: str = ""
    category: str = ""
    model: str = "per user"
    seats: float | None = None
    unit_price: float | None = None          # per seat per year, in the settings currency
    annual_cost: float = 0.0                 # in the settings currency
    currency: str = ""
    start: date | None = None
    renewal: date | None = None
    notice_days: int = 0
    auto_renew: bool = False
    uplift_pct: float | None = None
    owner: str = ""
    cost_centre: str = ""
    sso: bool | None = None
    data_class: str = ""
    downgrade_to: str = ""

    @property
    def key(self) -> str:
        return f"{self.app} {self.sku}".strip()

    @property
    def per_user(self) -> bool:
        return self.model == "per user"


@dataclass
class Assignment:
    app: str
    sku: str
    user: str
    assigned: date | None = None
    last_active: date | None = None
    premium: bool | None = None
    contract: str = ""                       # Contract.key it was matched to


@dataclass
class User:
    user: str
    name: str = ""
    department: str = ""
    cost_centre: str = ""
    country: str = ""
    status: str = "active"                   # active, leaver, leave
    leave_date: date | None = None


@dataclass
class Expense:
    date: date | None
    supplier: str
    description: str = ""
    amount: float = 0.0
    employee: str = ""
    cost_centre: str = ""


@dataclass
class Settings:
    organisation: str = "SaaS and licence portfolio"
    as_of: datetime | None = None
    currency: str = "EUR"
    fx: dict = field(default_factory=dict)                      # {"USD": 0.92}: 1 USD = 0.92 in the settings currency
    inactive_days: dict = field(default_factory=lambda: {"warning": 30, "reclaim": 60})
    inactive_share_red_pct: float = 20.0
    never_used_grace_days: int = 30
    shelfware_pct: dict = field(default_factory=lambda: {"amber": 5, "red": 15})
    renewal_horizon_days: int = 120
    notice_warning_days: dict = field(default_factory=lambda: {"amber": 45, "red": 14})
    uplift_threshold_pct: float = 5.0
    calendar_months: int = 12
    budget_red_pct: float = 10.0
    budgets: dict = field(default_factory=dict)                 # {"category": amount} and optionally {"total": amount}
    cost_centres: list = field(default_factory=list)           # the valid cost centres (users.csv adds its own)
    suite_capabilities: dict = field(default_factory=dict)      # {"Microsoft 365": ["video meetings", "file sharing"]}
    saas_vendors: dict = field(default_factory=dict)            # {"keyword in the expense supplier": "product name"}
    expense_months: int = 12
    confidential_classes: list = field(default_factory=lambda: ["confidential", "restricted", "highly confidential"])
    action_days: dict = field(default_factory=lambda: {"red": 5, "amber": 15})
    owners: dict = field(default_factory=lambda: dict(DEFAULT_OWNERS))

    def owner(self, k: str) -> str:
        return self.owners.get(k) or DEFAULT_OWNERS.get(k, "Software asset manager")

    def to_ccy(self, amount: float, ccy: str) -> float:
        c = (ccy or "").strip().upper()
        if not c or c == self.currency.upper():
            return amount
        rate = num(self.fx.get(c))
        return amount * rate if rate else amount


def settings_from_dict(raw: dict) -> Settings:
    s = Settings()
    for k, v in raw.items():
        if not hasattr(s, k) or v is None:
            continue
        cur = getattr(s, k)
        if k == "as_of":
            s.as_of = parse_dt(v)
        elif isinstance(cur, dict):
            if k in ("budgets", "fx", "suite_capabilities", "saas_vendors"):
                setattr(s, k, dict(v))
            else:
                cur.update({str(a): b for a, b in v.items()})
        elif isinstance(cur, list):
            setattr(s, k, list(v))
        elif isinstance(cur, bool):
            setattr(s, k, bool(v))
        elif isinstance(cur, int):
            setattr(s, k, int(num(v) or 0))
        elif isinstance(cur, float):
            setattr(s, k, float(num(v) or 0))
        else:
            setattr(s, k, str(v))
    return s


@dataclass
class Data:
    settings: Settings
    as_of: datetime
    contracts: list[Contract] = field(default_factory=list)
    assignments: list[Assignment] | None = None
    users: dict | None = None                                  # upn -> User
    expenses: list[Expense] | None = None
    sources: dict = field(default_factory=dict)
    unmatched: list = field(default_factory=list)              # assignments that match no contract

    @property
    def today(self) -> date:
        return self.as_of.date()


# ---------------------------------------------------------------- loaders

def load_contracts(path: Path, s: Settings | None = None) -> list[Contract]:
    s = s or Settings()
    out = []
    for r in _rows(path, CONTRACT_ALIASES):
        if not r.get("app"):
            continue
        ccy = r.get("currency", "") or s.currency
        seats = num(r.get("seats"))
        unit = num(r.get("unit_price"))
        if unit is None and num(r.get("unit_price_month")) is not None:
            unit = num(r.get("unit_price_month")) * 12
        annual = num(r.get("annual_cost"))
        if annual is None:
            annual = (seats or 0) * (unit or 0)
        if unit is None and seats:
            unit = annual / seats
        up = r.get("uplift", "")
        uplift = num(up)
        if uplift is not None and "%" not in up and 0 < uplift < 1:
            uplift *= 100
        nd = num(r.get("notice_days"))
        out.append(Contract(r["app"], r.get("sku", ""), r.get("vendor", ""), r.get("category", ""), licence_model(r.get("model")), seats,
                            None if unit is None else s.to_ccy(unit, ccy), s.to_ccy(annual, ccy), ccy.upper(), parse_d(r.get("start")),
                            parse_d(r.get("renewal")), int(nd or 0), bool(yes_no(r.get("auto_renew"))), uplift, r.get("owner", ""),
                            r.get("cost_centre", ""), yes_no(r.get("sso")), r.get("data_class", ""), r.get("downgrade_to", "")))
    return sorted(out, key=lambda c: (_norm(c.app), _norm(c.sku)))


def load_assignments(path: Path) -> list[Assignment]:
    out = []
    for r in _rows(path, ASSIGNMENT_ALIASES):
        if not r.get("app") or not r.get("user"):
            continue
        out.append(Assignment(r["app"], r.get("sku", ""), upn(r["user"]), parse_d(r.get("assigned")), parse_d(r.get("last_active")),
                              yes_no(r.get("premium"))))
    return out


def load_users(path: Path) -> dict:
    out = {}
    for r in _rows(path, USER_ALIASES):
        if not r.get("user"):
            continue
        u = User(upn(r["user"]), r.get("name", ""), r.get("department", ""), r.get("cost_centre", ""), r.get("country", ""),
                 user_status(r.get("status")), parse_d(r.get("leave_date")))
        out[u.user] = u
    return out


def load_expenses(path: Path, s: Settings | None = None) -> list[Expense]:
    s = s or Settings()
    out = []
    for r in _rows(path, EXPENSE_ALIASES):
        if not r.get("supplier") and not r.get("description"):
            continue
        out.append(Expense(parse_d(r.get("date")), r.get("supplier", ""), r.get("description", ""),
                           s.to_ccy(num(r.get("amount")) or 0.0, r.get("currency", "")), upn(r.get("employee")), r.get("cost_centre", "")))
    return out


def match(assignments: list[Assignment], contracts: list[Contract]) -> list[Assignment]:
    """Link each assignment to a contract by app and SKU (or by app when the app has one contract, or by the SKU alone, which is how
    Microsoft 365 SKU part numbers arrive). Returns the assignments that match none."""
    by_key = {(_norm(c.app), _norm(c.sku)): c for c in contracts}
    by_app: dict = {}
    by_sku: dict = {}
    for c in contracts:
        by_app.setdefault(_norm(c.app), []).append(c)
        if c.sku:
            by_sku.setdefault(_norm(c.sku), []).append(c)
    missing = []
    for a in assignments:
        c = by_key.get((_norm(a.app), _norm(a.sku)))
        if not c and len(by_app.get(_norm(a.app), [])) == 1 and not a.sku:
            c = by_app[_norm(a.app)][0]
        if not c and len(by_sku.get(_norm(a.sku), [])) == 1:
            c = by_sku[_norm(a.sku)][0]
        if c:
            a.contract = c.key
        else:
            missing.append(a)
    return missing


FILES = {
    "contracts.csv": "SaaS and licence register (Flexera, Apptio or the contract sheet)",
    "assignments.csv": "Licence assignments with the last activity per user",
    "users.csv": "Users from HR or Entra ID: department, cost centre, status",
    "expenses.csv": "Card expenses and AP invoice lines (for shadow IT)",
}


def load(folder: Path, as_of: datetime | None = None) -> Data:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"no folder {folder}")
    sp = folder / "settings.json"
    s = settings_from_dict(json.loads(sp.read_text(encoding="utf-8"))) if sp.exists() else Settings()
    when = as_of or s.as_of or datetime.now().replace(second=0, microsecond=0)
    if not (folder / "contracts.csv").exists():
        raise FileNotFoundError(f"{folder}: need contracts.csv ({FILES['contracts.csv']})")
    d = Data(s, when)
    d.contracts = load_contracts(folder / "contracts.csv", s)
    if not d.contracts:
        raise ValueError(f"{folder / 'contracts.csv'}: no contracts (check the App column)")
    d.sources = {"contracts.csv": len(d.contracts)}
    if (folder / "assignments.csv").exists():
        d.assignments = load_assignments(folder / "assignments.csv")
        d.unmatched = match(d.assignments, d.contracts)
        d.sources["assignments.csv"] = len(d.assignments)
    if (folder / "users.csv").exists():
        d.users = load_users(folder / "users.csv")
        d.sources["users.csv"] = len(d.users)
    if (folder / "expenses.csv").exists():
        d.expenses = load_expenses(folder / "expenses.csv", s)
        d.sources["expenses.csv"] = len(d.expenses)
    return d


def next_renewal(c: Contract, today: date) -> date | None:
    """The next renewal on or after today: a past renewal date of an auto-renewing contract rolls forward a year at a time."""
    r = c.renewal
    if not r or r >= today or not c.auto_renew:
        return r
    while r < today:
        try:
            r = r.replace(year=r.year + 1)
        except ValueError:                    # 29 February
            r = r.replace(year=r.year + 1, day=28)
    return r


def notice_deadline(c: Contract, today: date) -> date | None:
    r = next_renewal(c, today)
    return r - timedelta(days=c.notice_days) if r else None


__all__ = ["Data", "Settings", "Contract", "Assignment", "User", "Expense", "load", "load_contracts", "load_assignments", "load_users",
           "load_expenses", "match", "settings_from_dict", "next_renewal", "notice_deadline", "licence_model", "user_status", "yes_no",
           "num", "parse_d", "parse_dt", "FILES"]
