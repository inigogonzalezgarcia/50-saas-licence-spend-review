"""Fictional demo: Proseware Group, a made-up distribution company with about 1,400 employees in Spain, Portugal, France and Italy,
paying in EUR for 24 software and SaaS apps (25 contracts). The review runs on Wednesday 11 November 2026. Every person, contract,
price, date and expense is made up; product names are real, their prices and terms here are not. The problems are placed on purpose
among apps that are used as they should be."""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ORG = "Proseware Group"
SEED = 50
AS_OF = date(2026, 11, 11)
DOMAIN = "proseware.example"

DEPTS = [  # department, cost centre, headcount (active and on leave)
    ("Sales", "CC-210", 225), ("Marketing", "CC-220", 90), ("Customer Service", "CC-230", 210), ("Operations", "CC-310", 380),
    ("Engineering", "CC-410", 200), ("Design", "CC-420", 40), ("Finance", "CC-510", 80), ("HR", "CC-520", 45),
    ("Legal", "CC-530", 25), ("Executive", "CC-100", 15), ("IT", "CC-900", 60),
]
COUNTRIES = [("Spain", 50), ("Portugal", 18), ("France", 17), ("Italy", 15)]
FIRST = ["Ana", "Luis", "Marta", "Pablo", "Lucía", "Javier", "Carmen", "Diego", "Elena", "Sergio", "Laura", "Raúl", "Sara", "Iván",
         "Paula", "Hugo", "Inês", "João", "Rita", "Tiago", "Camille", "Louis", "Chloé", "Hugo", "Giulia", "Marco", "Chiara", "Luca",
         "Sofia", "Matteo", "Nuria", "Óscar", "Irene", "Adrián", "Beatriz", "Mateo", "Clara", "Andrés", "Noelia", "Rubén"]
LAST = ["García", "Martín", "López", "Sánchez", "Romero", "Navarro", "Torres", "Ruiz", "Molina", "Delgado", "Silva", "Costa",
        "Ferreira", "Pereira", "Martins", "Dubois", "Moreau", "Laurent", "Lefèvre", "Rossi", "Bianchi", "Ricci", "Greco", "Gallo",
        "Ortega", "Castro", "Vidal", "Prieto", "Iglesias", "Herrero", "Campos", "Fuentes", "Cabrera", "Méndez", "Soler"]

SETTINGS = {
    "organisation": ORG,
    "as_of": "2026-11-11 09:00",
    "currency": "EUR",
    "fx": {"USD": 0.92, "GBP": 1.17},
    "inactive_days": {"warning": 30, "reclaim": 60},
    "inactive_share_red_pct": 20,
    "never_used_grace_days": 30,
    "shelfware_pct": {"amber": 5, "red": 15},
    "renewal_horizon_days": 120,
    "notice_warning_days": {"amber": 45, "red": 14},
    "uplift_threshold_pct": 5,
    "calendar_months": 12,
    "budget_red_pct": 10,
    "budgets": {"total": 1_500_000, "CRM": 160_000, "Video meetings": 45_000, "Creative suite": 65_000},
    "cost_centres": ["CC-100", "CC-210", "CC-220", "CC-230", "CC-310", "CC-410", "CC-420", "CC-510", "CC-520", "CC-530", "CC-900"],
    "suite_capabilities": {"Microsoft 365": ["Video meetings", "File sharing"]},
    "saas_vendors": {"canva": "Canva", "notion": "Notion", "openai": "ChatGPT Plus", "chatgpt": "ChatGPT Plus", "calendly": "Calendly",
                     "grammarly": "Grammarly", "surveymonkey": "SurveyMonkey", "typeform": "Typeform", "trello": "Trello",
                     "asana": "Asana", "monday com": "monday.com", "airtable": "Airtable", "loom": "Loom", "mailchimp": "Mailchimp",
                     "wetransfer": "WeTransfer", "lucid": "Lucid"},
    "expense_months": 12,
    "confidential_classes": ["Confidential", "Restricted"],
    "action_days": {"red": 5, "amber": 15},
    "owners": {"reclaim": "Service desk lead (Nuria Campos)", "downgrade": "Microsoft 365 administrator (Adrián Prieto)",
               "right-size": "Software asset manager (Clara Fuentes)", "negotiate": "IT procurement (Óscar Méndez)",
               "consolidate": "Head of IT (Irene Vidal)", "cancel": "IT finance (Beatriz Soler)", "security": "IT security (Rubén Ortega)",
               "finance": "IT finance (Beatriz Soler)", "sam": "Software asset manager (Clara Fuentes)"},
}

# app, sku, vendor, category, licence model, seats, unit price a year (EUR), start, renewal, notice days, auto-renew, uplift %, owner,
# cost centre, SSO, data classification, downgrade to, holder departments, holders, leavers, inactive (>60 days), never used
APPS = [
    ("Microsoft 365", "E5", "Microsoft", "Productivity suite", "Per user", 420, 684, "2024-07-01", "2027-06-30", 30, "Yes", 3, "Irene Vidal",
     "CC-900", "Yes", "Confidential", "E3", None, 0, 0, 0, 0),
    ("Microsoft 365", "E3", "Microsoft", "Productivity suite", "Per user", 1030, 432, "2024-07-01", "2027-06-30", 30, "Yes", 3, "Irene Vidal",
     "CC-900", "Yes", "Confidential", "", None, 0, 0, 0, 0),
    ("Adobe Acrobat Pro", "Teams", "Adobe", "PDF and documents", "Per user", 220, 240, "2023-05-01", "2027-04-30", 30, "Yes", 4,
     "Clara Fuentes", "CC-900", "Yes", "Internal", "", ["Finance", "Legal", "Sales", "HR", "Operations"], 205, 3, 8, 3),
    ("Adobe Creative Cloud", "All Apps", "Adobe", "Creative suite", "Per user", 60, 1020, "2023-05-01", "2027-04-30", 30, "Yes", 4,
     "Marta Ruiz", "CC-220", "Yes", "Internal", "", ["Design", "Marketing"], 60, 0, 18, 0),
    ("Zoom Workplace", "Business", "Zoom", "Video meetings", "Per user", 150, 200, "2024-02-01", "2027-01-31", 30, "Yes", 0,
     "Diego Navarro", "CC-210", "Yes", "Internal", "", ["Sales", "Customer Service"], 128, 3, 15, 2),
    ("Webex Meetings", "Business", "Cisco", "Video meetings", "Per user", 80, 170, "2023-03-16", "2027-03-15", 60, "Yes", 3,
     "Javier Torres", "CC-230", "Yes", "Internal", "", ["Customer Service", "Operations"], 61, 0, 12, 1),
    ("Slack", "Business+", "Salesforce", "Team chat", "Per user", 120, 150, "2024-06-01", "2027-05-31", 30, "Yes", 5, "Hugo Molina",
     "CC-410", "Yes", "Internal", "", ["Engineering"], 110, 3, 4, 0),
    ("Miro", "Business", "Miro", "Whiteboard", "Per user", 90, 190, "2025-01-16", "2027-01-15", 30, "Yes", 4, "Sara López", "CC-420",
     "Yes", "Internal", "", ["Design", "Engineering", "Marketing"], 102, 2, 6, 0),
    ("Figma", "Organization", "Figma", "UI design", "Per user", 40, 540, "2025-04-01", "2027-03-31", 30, "Yes", 4, "Sara López", "CC-420",
     "Yes", "Internal", "", ["Design", "Engineering"], 36, 1, 2, 0),
    ("DocuSign eSignature", "Business Pro", "DocuSign", "E-signature", "Per user", 60, 480, "2023-12-21", "2026-12-20", 30, "Yes", 4,
     "Lucía Delgado", "CC-530", "Yes", "Confidential", "", ["Legal", "Sales", "HR", "Finance"], 41, 0, 5, 1),
    ("Salesforce Sales Cloud", "Enterprise", "Salesforce", "CRM", "Per user", 85, 1980, "2024-03-01", "2027-02-28", 30, "Yes", 9,
     "Diego Navarro", "CC-210", "Yes", "Confidential", "", ["Sales"], 78, 4, 6, 0),
    ("Jira Software", "Cloud Standard", "Atlassian", "Work tracking", "Per user", 260, 95, "2024-10-01", "2027-09-30", 30, "Yes", 5,
     "Hugo Molina", "CC-410", "Yes", "Internal", "", ["Engineering", "IT", "Operations"], 248, 2, 10, 0),
    ("Confluence", "Cloud Standard", "Atlassian", "Wiki", "Per user", 300, 70, "2024-10-01", "2027-09-30", 30, "Yes", 5, "Hugo Molina",
     "CC-410", "Yes", "Internal", "", ["Engineering", "IT", "Operations", "HR"], 285, 0, 12, 0),
    ("1Password", "Business", "1Password", "Password manager", "Per user", 300, 96, "2025-09-01", "2027-08-31", 30, "Yes", 3,
     "Rubén Ortega", "CC-900", "Yes", "Restricted", "", ["IT", "Engineering", "Finance"], 292, 0, 4, 0),
    ("Dropbox", "Business Advanced", "Dropbox", "File sharing", "Per user", 70, 216, "2025-02-15", "2027-02-14", 60, "Yes", 4,
     "Marta Ruiz", "CC-220", "Yes", "Internal", "", ["Marketing", "Design"], 58, 0, 9, 0),
    ("Box", "Business", "Box", "File sharing", "Per user", 50, 240, "2024-07-01", "2027-06-30", 30, "Yes", 3, "Paula Gallo", "CC-310",
     "Yes", "Confidential", "", ["Operations"], 44, 0, 6, 0),
    ("Smartsheet", "Business", "Smartsheet", "Work management", "Per user", 45, 300, "2025-01-21", "2027-01-20", 30, "Yes", 5, "",
     "CC-310", "No", "Confidential", "", ["Operations"], 42, 0, 5, 0),
    ("Power BI", "Pro", "Microsoft", "BI and reporting", "Per user", 150, 168, "2024-07-01", "2027-06-30", 30, "Yes", 3, "Laura Martín",
     "CC-510", "Yes", "Confidential", "", ["Finance", "Sales", "Operations"], 141, 0, 9, 4),
    ("Visio", "Plan 2", "Microsoft", "Diagramming", "Per user", 40, 180, "2024-07-01", "2027-06-30", 30, "Yes", 3, "Adrián Prieto",
     "CC-900", "Yes", "Internal", "", ["IT", "Engineering"], 33, 0, 5, 0),
    ("Project", "Plan 3", "Microsoft", "Project management", "Per user", 30, 360, "2024-07-01", "2027-06-30", 30, "Yes", 3, "Irene Vidal",
     "CC-900", "Yes", "Internal", "", ["IT", "Operations"], 29, 0, 3, 0),
    ("AutoCAD", "Subscription", "Autodesk", "CAD", "Per user", 25, 2100, "2025-05-10", "2027-05-09", 30, "Yes", 4, "Paula Gallo",
     "CC-310", "Yes", "Internal", "", ["Operations", "Engineering"], 24, 0, 2, 0),
    ("LinkedIn Learning", "Business", "LinkedIn", "E-learning", "Per user", 100, 300, "2024-12-02", "2026-12-01", 60, "Yes", 3,
     "Elena Iglesias", "CC-520", "Yes", "Internal", "", ["HR", "Sales", "Marketing", "IT"], 96, 0, 22, 2),
    ("SAP Concur", "Expense", "SAP", "Expense management", "Flat", None, None, "2024-11-01", "2027-10-31", 90, "Yes", 3, "Laura Martín",
     "CC-510", "Yes", "Confidential", "", None, 0, 0, 0, 0),
    ("KnowBe4", "Security Awareness Gold", "KnowBe4", "Security awareness", "Flat", None, None, "2025-04-01", "2027-03-31", 30, "Yes", 4,
     "Rubén Ortega", "", "Yes", "Internal", "", None, 0, 0, 0, 0),
    ("TeamViewer", "Tensor", "TeamViewer", "Remote support", "Per device", 40, 350, "2025-03-01", "2027-02-28", 60, "No", 5,
     "Adrián Prieto", "CC-950", "Yes", "Internal", "", None, 0, 0, 0, 0),
]
FLAT_COST = {"SAP Concur": 38_000, "KnowBe4": 18_000}
E5_DEPTS = {"IT": 60, "Finance": 80, "Legal": 25, "Executive": 15, "Engineering": 120, "Sales": 100}
E5_NO_PREMIUM = 180
LEAVERS = 28                  # people who left with their Microsoft 365 licence still assigned (8 E5, 20 E3)
ON_LEAVE = 6
SERVICE_ACCOUNTS = ["svc-scanner", "svc-reporting"]

# card expenses: product, supplier on the statement, description, department of the buyers, buyers, months, monthly amount (EUR)
SHADOW = [
    ("Canva", "CANVA* PRO", "Canva Pro subscription", "Marketing", 4, [11, 12, 1, 2, 3], 11.99),
    ("Notion", "NOTION LABS INC", "Notion Plus workspace", "Engineering", 3, [1, 2, 3, 4, 5], 9.20),
    ("ChatGPT Plus", "OPENAI *CHATGPT SUBSCR", "ChatGPT Plus", None, 5, [6, 7, 8, 9, 10], 18.50),
    ("Calendly", "CALENDLY", "Calendly Standard", "Sales", 3, [3, 4, 5], 9.20),
    ("Grammarly", "GRAMMARLY INC", "Grammarly Pro annual", None, 2, [9], 132.00),
    ("Adobe", "ADOBE SYSTEMS SOFTWARE IRELAND", "Acrobat Pro monthly plan", "Finance", 3, [5, 6, 7, 8, 9], 24.99),
]
NOISE = [("Renfe Viajeros", "Train ticket", 35, 140), ("Uber BV", "Taxi to client", 12, 45), ("Hotel NH", "Hotel, sales visit", 90, 240),
         ("Amazon EU", "Office supplies", 15, 120), ("Taxi Lisboa", "Taxi", 9, 30), ("SNCF Connect", "Train ticket", 40, 160),
         ("Trenitalia", "Train ticket", 25, 110), ("Restaurante La Plaza", "Client lunch", 40, 180), ("El Corte Ingles", "Gift for event", 30, 90),
         ("Packlink", "Courier", 8, 40), ("Fnac", "Adapter and cables", 15, 60), ("Eventbrite", "Conference ticket", 50, 450)]
AP_INVOICES = [("DocuSign Inc", "Annual subscription eSignature", 28_800), ("Atlassian Pty Ltd", "Jira and Confluence cloud annual", 45_700),
               ("Zoom Video Communications", "Zoom Workplace annual", 30_000)]


def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _ago(days: int) -> str:
    return (AS_OF - timedelta(days=days)).isoformat()


def _people(rnd: random.Random) -> list[dict]:
    people, seen = [], set()
    countries = [c for c, w in COUNTRIES for _ in range(w)]
    for dept, cc, n in DEPTS:
        for _ in range(n):
            while True:
                f, l = rnd.choice(FIRST), rnd.choice(LAST)
                base = f"{f}.{l}".lower()
                for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ê", "e"), ("è", "e"), ("ç", "c"), ("ã", "a")):
                    base = base.replace(a, b)
                k = 1
                u = f"{base}@{DOMAIN}"
                while u in seen:
                    k += 1
                    u = f"{base}{k}@{DOMAIN}"
                seen.add(u)
                break
            people.append({"user": u, "name": f"{f} {l}", "department": dept, "cost_centre": cc, "country": rnd.choice(countries),
                           "status": "Active", "leave_date": ""})
    return people


def build(rnd: random.Random) -> dict:
    people = _people(rnd)
    by_dept = {}
    for p in people:
        by_dept.setdefault(p["department"], []).append(p)
    # people on long leave (still employed) and leavers (former employees, kept in the HR export with their leave date)
    for p in rnd.sample(people, ON_LEAVE):
        p["status"] = "Long leave"
    leavers = []
    for k in range(LEAVERS):
        dept, cc, _ = DEPTS[k % len(DEPTS)]
        f, l = FIRST[(k * 7) % len(FIRST)], LAST[(k * 11) % len(LAST)]
        base = f"{f}.{l}".lower().translate(str.maketrans("áéíóúêèçãñ", "aeioueecan"))
        leavers.append({"user": f"{base}.old{k + 1}@{DOMAIN}", "name": f"{f} {l}", "department": dept, "cost_centre": cc,
                        "country": COUNTRIES[k % 4][0], "status": "Leaver", "leave_date": _ago(rnd.randint(20, 160))})
    assignments = []

    def active_date(p: dict, inactive: bool = False, lo: int = 61, hi: int = 200) -> str:
        if p["status"] == "Long leave":
            return _ago(rnd.randint(70, 150))
        if inactive:
            return _ago(rnd.randint(lo, hi))
        return _ago(rnd.randint(0, 20) if rnd.random() < 0.9 else rnd.randint(31, 55))

    # Microsoft 365: E5 for some departments, E3 for everyone else
    e5 = []
    for dept, n in E5_DEPTS.items():
        e5 += by_dept[dept][:n]
    e5_ids = {p["user"] for p in e5}
    no_premium = set(p["user"] for p in rnd.sample([p for p in e5 if p["department"] not in ("IT",) and p["status"] == "Active"],
                                                    E5_NO_PREMIUM))
    for p in people:
        sku = "E5" if p["user"] in e5_ids else "E3"
        prem = "" if sku == "E3" else ("No" if p["user"] in no_premium else "Yes")
        assignments.append(["Microsoft 365", sku, p["user"], _ago(rnd.randint(200, 1200)), active_date(p), prem])
    for k, p in enumerate(leavers):
        left = date.fromisoformat(p["leave_date"])
        assignments.append(["Microsoft 365", "E5" if k < 8 else "E3", p["user"], _ago(rnd.randint(400, 1300)),
                            (left - timedelta(days=rnd.randint(0, 3))).isoformat(), "Yes" if k < 8 else ""])
    for s in SERVICE_ACCOUNTS:
        assignments.append(["Microsoft 365", "E3", f"{s}@{DOMAIN}", _ago(rnd.randint(300, 900)), _ago(rnd.randint(0, 3)), ""])
    # the other per-user apps
    li = 0
    for row in APPS:
        app, sku, depts, n, n_leave, n_inactive, n_never = row[0], row[1], row[17], row[18], row[19], row[20], row[21]
        if not depts:
            continue
        pool = [p for d in depts for p in by_dept[d] if p["status"] == "Active"]
        rest = [p for p in people if p["department"] not in depts and p["status"] == "Active"]
        holders = rnd.sample(pool, min(n, len(pool)))
        if n > len(pool):
            holders += rnd.sample(rest, n - len(pool))
        holders.sort(key=lambda p: p["user"])
        flagged = rnd.sample(range(len(holders)), n_inactive + n_never)
        inactive, never = set(flagged[:n_inactive]), set(flagged[n_inactive:])
        lo, hi = (90, 240) if app == "Adobe Creative Cloud" else (61, 200)
        for i, p in enumerate(holders):
            assigned = _ago(rnd.randint(120, 900))
            if i in never:
                assignments.append([app, sku, p["user"], _ago(rnd.randint(45, 300)), "", ""])
            else:
                assignments.append([app, sku, p["user"], assigned, active_date(p, i in inactive, lo, hi), ""])
        for _ in range(n_leave):
            p = leavers[li % LEAVERS]
            li += 1
            left = date.fromisoformat(p["leave_date"])
            assignments.append([app, sku, p["user"], _ago(rnd.randint(300, 900)), (left - timedelta(days=rnd.randint(1, 10))).isoformat(), ""])
    assignments.sort(key=lambda r: (r[0], r[1], r[2]))
    contracts = []
    for row in APPS:
        (app, sku, vendor, cat, model, seats, unit, start, renewal, notice, auto, uplift, owner, cc, sso, dc, down) = row[:17]
        annual = FLAT_COST.get(app, (seats or 0) * (unit or 0))
        contracts.append([app, vendor, cat, sku, model, "" if seats is None else seats, "" if unit is None else f"{unit:.2f}",
                          f"{annual:.2f}", "EUR", start, renewal, notice, auto, uplift, owner, cc, sso, dc, down])
    users = [[p["user"], p["name"], p["department"], p["cost_centre"], p["country"], p["status"], p["leave_date"]]
             for p in sorted(people + leavers, key=lambda p: p["user"])]
    # expenses: travel and supplies, the SaaS on cards, and central AP invoices (no employee) for contracted vendors
    expenses = []
    staff = [p for p in people if p["status"] == "Active"]
    for _ in range(260):
        sup, desc, lo_, hi_ = rnd.choice(NOISE)
        p = rnd.choice(staff)
        expenses.append([_ago(rnd.randint(1, 360)), sup, desc, f"{rnd.uniform(lo_, hi_):.2f}", "EUR", p["user"], p["cost_centre"]])
    for prod, sup, desc, dept, buyers, months, amount in SHADOW:
        pool = by_dept[dept] if dept else staff
        for p in rnd.sample([x for x in pool if x["status"] == "Active"], buyers):
            for m in months:
                y = 2026 if m <= 10 else 2025
                d = date(y, m, rnd.randint(3, 26))
                expenses.append([d.isoformat(), sup, desc, f"{amount:.2f}", "EUR", p["user"], p["cost_centre"]])
    for k, (sup, desc, amount) in enumerate(AP_INVOICES):
        expenses.append([_ago(40 + 60 * k), sup, desc, f"{amount:.2f}", "EUR", "", "CC-900"])
    expenses.sort(key=lambda r: (r[0], r[1], r[5], r[3]))
    return {"contracts": contracts, "assignments": assignments, "users": users, "expenses": expenses}


def write(folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    b = build(random.Random(SEED))
    _w(folder / "contracts.csv", ["App", "Vendor", "Category", "Sku", "LicenceModel", "SeatsPurchased", "UnitPriceAnnual", "AnnualCost",
                                  "Currency", "ContractStart", "RenewalDate", "NoticeDays", "AutoRenew", "UpliftPct", "Owner", "CostCentre",
                                  "Sso", "DataClassification", "DowngradeTo"], b["contracts"])
    _w(folder / "assignments.csv", ["App", "Sku", "User", "AssignedDate", "LastActive", "UsesPremium"], b["assignments"])
    _w(folder / "users.csv", ["User", "DisplayName", "Department", "CostCentre", "Country", "Status", "LeaveDate"], b["users"])
    _w(folder / "expenses.csv", ["Date", "Supplier", "Description", "Amount", "Currency", "Employee", "CostCentre"], b["expenses"])
    (folder / "settings.json").write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder


__all__ = ["write", "ORG", "SETTINGS", "APPS"]
