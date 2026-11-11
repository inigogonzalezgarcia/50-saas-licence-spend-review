import csv
import hashlib
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from licencereview import cli
from licencereview.checks import AMBER, GREEN, RED, check_allocation, check_portfolio, check_renewals, check_seats, check_usage, \
    review, shadow, showback, summary, usage
from licencereview.model import (Assignment, Contract, Data, Expense, User, load, load_assignments, load_contracts, load_users, match,
                                 next_renewal, notice_deadline, settings_from_dict)

AS_OF = datetime(2026, 11, 11, 9, 0)
T = AS_OF.date()


def write(path: Path, header: list[str], rows: list[list]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def contract(app="App", sku="", **kw) -> Contract:
    base = dict(vendor="Vendor", category="", model="per user", seats=10, unit_price=100.0, annual_cost=1000.0, currency="EUR",
                renewal=date(2027, 9, 30), notice_days=30, auto_renew=True, uplift_pct=3, owner="Olga Owner", cost_centre="CC-1")
    base.update(kw)
    return Contract(app, sku, **base)


def ago(days: int) -> date:
    return T - timedelta(days=days)


def people(n: int, status="active", dept="Sales", cc="CC-1", prefix="u") -> dict:
    return {f"{prefix}{k}@x.example": User(f"{prefix}{k}@x.example", f"User {k}", dept, cc, "", status) for k in range(n)}


def data(contracts=(), assignments=None, users=None, expenses=None, **raw) -> Data:
    d = Data(settings_from_dict(raw), AS_OF, list(contracts) or [contract()], assignments, users, expenses)
    if assignments is not None:
        d.unmatched = match(assignments, d.contracts)
    d.sources = {"contracts.csv": len(d.contracts)}
    return d


def codes(fs) -> dict:
    return {f.code: f.severity for f in fs}


class TestLoading(unittest.TestCase):
    def test_register_columns_prices_currencies_and_models(self):
        s = settings_from_dict({"currency": "EUR", "fx": {"USD": 0.9}})
        with tempfile.TemporaryDirectory() as t:
            p = write(Path(t) / "c.csv", ["Product", "Supplier", "Capability", "Edition", "Licensing model", "Quantity",
                                          "Unit price per month", "Currency", "Contract end", "Notice period", "Evergreen", "Price increase",
                                          "Business owner", "Cost center", "Single sign-on", "Classification"],
                      [["Zoom Workplace", "Zoom", "Video meetings", "Business", "Named user", "150", "16,67", "USD", "31/01/2027", "30",
                        "Yes", "0.07", "Diego", "CC-210", "No", "Internal"],
                       ["SAP Concur", "SAP", "Expenses", "", "Enterprise subscription", "", "", "EUR", "2027-10-31", "90", "no", "3 %",
                        "", "", "", ""],
                       ["", "No app", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]])
            cs = load_contracts(p, s)
            write(Path(t) / "c2.csv", ["App", "AnnualCost", "Seats"], [["Flat", "€ 38.000,00", "4"]])
            flat = load_contracts(Path(t) / "c2.csv", s)[0]
        self.assertEqual([c.app for c in cs], ["SAP Concur", "Zoom Workplace"])
        concur, zoom = cs
        self.assertEqual((zoom.vendor, zoom.category, zoom.sku, zoom.model, zoom.seats, zoom.renewal, zoom.notice_days, zoom.auto_renew),
                         ("Zoom", "Video meetings", "Business", "per user", 150, date(2027, 1, 31), 30, True))
        self.assertAlmostEqual(zoom.unit_price, 16.67 * 12 * 0.9, places=2)
        self.assertAlmostEqual(zoom.annual_cost, 150 * 16.67 * 12 * 0.9, places=2)
        self.assertAlmostEqual(zoom.uplift_pct, 7.0)
        self.assertIs(zoom.sso, False)
        self.assertEqual((concur.model, concur.auto_renew, concur.uplift_pct, concur.seats), ("flat", False, 3.0, None))
        self.assertEqual((flat.annual_cost, flat.unit_price), (38_000, 9_500))

    def test_assignments_users_status_and_matching(self):
        with tempfile.TemporaryDirectory() as t:
            a = write(Path(t) / "a.csv", ["Application", "SKU part number", "UPN", "Date assigned", "Last sign-in", "Premium used"],
                      [["Microsoft 365", "SPE_E5", "Ana@X.example", "2025-01-02", "2026-11-02T08:15:00Z", "No"],
                       ["", "SPE_E3", "bo@x.example", "", "", ""], ["Miro", "", "cy@x.example", "2026-01-01", "never", "yes"],
                       ["Ghost", "", "dee@x.example", "", "", ""]])
            asg = load_assignments(a)
            u = write(Path(t) / "u.csv", ["UserPrincipalName", "Display name", "Dept", "Cost center", "accountEnabled", "Termination date"],
                      [["ana@x.example", "Ana", "Sales", "CC-1", "true", ""], ["bo@x.example", "Bo", "IT", "CC-9", "false", ""],
                       ["cy@x.example", "Cy", "HR", "CC-2", "Maternity leave", ""], ["dee@x.example", "Dee", "HR", "CC-2", "Terminated",
                                                                                    "2026-10-01"]])
            us = load_users(u)
        self.assertEqual(len(asg), 3)                                     # the row without app is skipped
        self.assertEqual((asg[0].user, asg[0].last_active, asg[0].premium), ("ana@x.example", date(2026, 11, 2), False))
        self.assertEqual((asg[1].last_active, asg[1].premium), (None, True))
        self.assertEqual([us[k].status for k in sorted(us)], ["active", "leaver", "leave", "leaver"])
        self.assertEqual(us["dee@x.example"].leave_date, date(2026, 10, 1))
        cs = [contract("Microsoft 365", "SPE_E5"), contract("Microsoft 365", "SPE_E3"), contract("Miro", "Business")]
        missing = match(asg + [Assignment("", "SPE_E3", "bo@x.example")], cs)
        self.assertEqual([a.contract for a in asg], ["Microsoft 365 SPE_E5", "Miro Business", ""])
        self.assertEqual([a.user for a in missing], ["dee@x.example"])


class TestChecks(unittest.TestCase):
    def test_leavers_inactive_never_used_leave_and_unknown(self):
        us = people(10)
        us["u0@x.example"].status = "leaver"
        us["u0@x.example"].leave_date = date(2026, 9, 1)
        us["u1@x.example"].status = "leave"
        asg = [Assignment("App", "", "u0@x.example", ago(400), ago(75)), Assignment("App", "", "u1@x.example", ago(400), ago(120)),
               Assignment("App", "", "u2@x.example", ago(400), ago(90)), Assignment("App", "", "u3@x.example", ago(400), ago(61)),
               Assignment("App", "", "u4@x.example", ago(90), None), Assignment("App", "", "u5@x.example", ago(10), None),
               Assignment("App", "", "u6@x.example", ago(400), ago(45)), Assignment("App", "", "u7@x.example", ago(400), ago(3)),
               Assignment("App", "", "svc@x.example", ago(400), ago(2))]
        d = data(assignments=asg, users=us)
        by, reclaim = usage(d)
        u = by["App"]
        self.assertEqual((u.assigned, u.active, u.idle, u.inactive, u.never, u.leavers, u.leave, u.unknown), (9, 3, 1, 2, 1, 1, 1, 1))
        fs = check_usage(d, by, reclaim)
        self.assertEqual(codes(fs), {"USE-LEAVER": RED, "USE-INACTIVE": RED, "USE-NEVER": AMBER, "USE-LEAVE": AMBER, "USE-UNKNOWN": AMBER})
        self.assertEqual(sorted((r["user"].split("@")[0], r["reason"].split(" ")[0]) for r in reclaim),
                         [("u0", "leaver"), ("u2", "no"), ("u3", "no"), ("u4", "never")])
        self.assertEqual(next(f for f in fs if f.code == "USE-INACTIVE").saving, 200)      # 2 x 100; 22 % of 9 is over 20 %: RED
        fs = check_usage(*((lambda dd: (dd,) + usage(dd))(data(assignments=asg[2:3] + asg[6:], users=us))))
        self.assertEqual(codes(fs)["USE-INACTIVE"], RED)
        quiet = data(assignments=[Assignment("App", "", f"u{k}@x.example", ago(400), ago(k)) for k in range(2, 10)], users=us)
        self.assertEqual(check_usage(quiet, *usage(quiet)), [])

    def test_downgrade_only_for_active_users_without_premium_use(self):
        cs = [contract("Microsoft 365", "E5", seats=4, unit_price=684, annual_cost=2736, downgrade_to="E3"),
              contract("Microsoft 365", "E3", seats=4, unit_price=432, annual_cost=1728)]
        us = people(4)
        us["u3@x.example"].status = "leaver"
        asg = [Assignment("Microsoft 365", "E5", "u0@x.example", ago(300), ago(2), False),
               Assignment("Microsoft 365", "E5", "u1@x.example", ago(300), ago(2), True),
               Assignment("Microsoft 365", "E5", "u2@x.example", ago(300), ago(90), False),
               Assignment("Microsoft 365", "E5", "u3@x.example", ago(300), ago(70), False)]
        d = data(cs, asg, us)
        by, reclaim = usage(d)
        dg = [r for r in reclaim if r["lever"] == "downgrade"]
        self.assertEqual([(r["user"], r["saving"]) for r in dg], [("u0@x.example", 252)])
        f = next(f for f in check_usage(d, by, reclaim) if f.code == "USE-DOWNGRADE")
        self.assertEqual((f.severity, f.count, f.saving), (AMBER, 1, 252))
        self.assertIn("E3 would cover them", f.detail)

    def test_shelfware_and_over_assignment(self):
        cs = [contract("Shelf", seats=100, unit_price=10, annual_cost=1000), contract("Some", seats=100, unit_price=10, annual_cost=1000),
              contract("Over", seats=10, unit_price=190, annual_cost=1900), contract("Flat", model="flat", seats=None, annual_cost=5000)]
        asg = ([Assignment("Shelf", "", f"s{k}", ago(100), ago(1)) for k in range(80)]
               + [Assignment("Some", "", f"s{k}", ago(100), ago(1)) for k in range(93)]
               + [Assignment("Over", "", f"s{k}", ago(100), ago(1)) for k in range(12)])
        d = data(cs, asg)
        fs = check_seats(d, usage(d)[0])
        got = {f.subject: (f.code, f.severity, f.count, f.saving, f.risk) for f in fs}
        self.assertEqual(got, {"Shelf": ("SEAT-SHELF", RED, 20, 200, 0), "Some": ("SEAT-SHELF", AMBER, 7, 70, 0),
                               "Over": ("SEAT-OVER", RED, 2, 0, 380)})

    def test_notice_deadlines_auto_renew_and_roll_forward(self):
        cs = [contract("Soon", renewal=date(2026, 12, 20), notice_days=30),                      # deadline 20 Nov: 9 days
              contract("Near", renewal=date(2027, 2, 14), notice_days=60),                       # deadline 16 Dec: 35 days
              contract("Passed", renewal=date(2026, 12, 1), notice_days=60),                     # deadline 2 Oct: passed
              contract("Ends", renewal=date(2026, 12, 31), notice_days=30, auto_renew=False),
              contract("Far", renewal=date(2027, 2, 28), notice_days=30),                        # deadline 29 Jan: 79 days
              contract("Old", renewal=date(2025, 12, 15), notice_days=30)]                       # rolled to 15 Dec 2026
        fs = check_renewals(data(cs))
        got = {f.subject: f.severity for f in fs if f.code == "REN-NOTICE"}
        self.assertEqual(got, {"Soon": RED, "Near": AMBER, "Passed": RED, "Ends": AMBER, "Old": RED})
        soon = next(f for f in fs if f.subject == "Soon")
        self.assertIn("in 9 days", soon.detail)
        self.assertEqual(soon.due, date(2026, 11, 18))
        self.assertEqual(next_renewal(cs[-1], T), date(2026, 12, 15))
        self.assertEqual(notice_deadline(cs[-1], T), date(2026, 11, 15))
        self.assertEqual(next_renewal(contract(renewal=date(2025, 1, 1), auto_renew=False), T), date(2025, 1, 1))

    def test_uplift_above_the_threshold_and_contracts_without_owner(self):
        cs = [contract("CRM", annual_cost=168_300, uplift_pct=9, renewal=date(2027, 2, 28)), contract("Ok", uplift_pct=5),
              contract("Later", uplift_pct=12, renewal=date(2028, 6, 30)), contract("Nobody", owner="")]
        fs = check_renewals(data(cs))
        up = [f for f in fs if f.code == "REN-UPLIFT"]
        self.assertEqual([(f.subject, round(f.saving)) for f in up], [("CRM", 6732)])
        self.assertEqual([f.subject for f in fs if f.code == "REN-OWNER"], ["Nobody"])

    def test_overlap_with_the_suite_and_between_apps_counted_once(self):
        cs = [contract("Microsoft 365", "E3", category="Productivity suite", annual_cost=400_000),
              contract("Zoom", category="Video meetings", annual_cost=30_000), contract("Webex", category="Video meetings", annual_cost=13_600),
              contract("Miro", category="Whiteboard", annual_cost=17_000), contract("Mural", category="Whiteboard", annual_cost=5_000),
              contract("Slack", category="Team chat", annual_cost=18_000)]
        d = data(cs, suite_capabilities={"Microsoft 365": ["Video meetings", "File sharing"]})
        ledger = {"Zoom": 1_000.0}
        fs = [f for f in check_portfolio(d, ledger) if f.code == "PRT-OVERLAP"]
        got = {f.subject: (sorted(f.apps), f.saving) for f in fs}
        self.assertEqual(got, {"Video meetings": (["Webex", "Zoom"], 42_600), "Whiteboard": (["Mural"], 5_000)})
        self.assertIn("Microsoft 365 already covers it", next(f for f in fs if f.subject == "Video meetings").detail)
        self.assertEqual(ledger["Zoom"], 30_000)

    def test_sso_and_shadow_it_from_expenses(self):
        cs = [contract("Smartsheet", sso=False, data_class="Confidential"), contract("Box", sso=False, data_class="Internal"),
              contract("Acrobat Pro", vendor="Adobe")]
        us = people(3, dept="Marketing")
        ex = [Expense(date(2026, 6, 3), "CANVA* PRO", "Canva Pro", 11.99, "u0@x.example"),
              Expense(date(2026, 7, 3), "CANVA* PRO", "Canva Pro", 11.99, "u1@x.example"),
              Expense(date(2026, 8, 3), "OPENAI *CHATGPT SUBSCR", "", 18.5, "u2@x.example"),
              Expense(date(2025, 6, 3), "NOTION LABS", "Notion", 9.2, "u2@x.example"),                 # older than 12 months
              Expense(date(2026, 5, 9), "ADOBE SYSTEMS SOFTWARE IRELAND", "Acrobat monthly", 24.99, "u1@x.example"),
              Expense(date(2026, 4, 1), "Adobe Systems", "Annual Acrobat licences (AP invoice)", 52_800, ""),
              Expense(date(2026, 4, 1), "Renfe Viajeros", "Train ticket", 64, "u0@x.example")]
        d = data(cs, users=us, expenses=ex, saas_vendors={"canva": "Canva", "openai": "ChatGPT Plus", "notion": "Notion"})
        self.assertEqual([f.subject for f in check_portfolio(d, {}) if f.code == "PRT-SSO"], ["Smartsheet"])
        fs, table = shadow(d)
        got = {f.subject: (f.code, f.count, round(f.risk, 2), round(f.saving, 2)) for f in fs}
        self.assertEqual(got, {"Canva": ("SHD-UNMANAGED", 2, 23.98, 0), "ChatGPT Plus": ("SHD-UNMANAGED", 1, 18.5, 0),
                               "Acrobat Pro": ("SHD-DUPLICATE", 1, 0, 24.99)})
        self.assertIn("Marketing", next(f for f in fs if f.subject == "Canva").detail)
        self.assertEqual([r["status"] for r in table], ["not in the register", "not in the register", "already under a central contract"])

    def test_showback_adds_up_cost_centres_and_budget(self):
        cs = [contract("A", seats=4, unit_price=100, annual_cost=400, category="CRM"),
              contract("B", model="flat", seats=None, annual_cost=1000, cost_centre="", category="HR"),
              contract("C", seats=2, unit_price=50, annual_cost=100, cost_centre="CC-404", category="CRM")]
        us = {**people(2, dept="Sales", cc="CC-1"), **people(1, dept="IT", cc="CC-2", prefix="i")}
        asg = [Assignment("A", "", "u0@x.example"), Assignment("A", "", "i0@x.example"), Assignment("C", "", "u1@x.example"),
               Assignment("C", "", "u0@x.example"), Assignment("C", "", "ghost@x.example")]
        d = data(cs, asg, us, budgets={"CRM": 440, "total": 2000}, cost_centres=["CC-1", "CC-9"])
        sb = showback(d)
        self.assertAlmostEqual(sum(r["cost"] for r in sb), 1500)
        got = {(r["department"], r["cost_centre"]): round(r["cost"], 2) for r in sb}
        self.assertEqual(got, {("Sales", "CC-1"): 166.67, ("IT", "CC-2"): 100, ("(not in the HR list)", ""): 33.33,
                               ("Unassigned seats", "CC-1"): 200, ("Central contracts", "(none)"): 1000})
        fs = check_allocation(d)
        self.assertEqual(sorted((f.code, f.subject, f.severity) for f in fs),
                         [("ALC-BUDGET", "CRM", RED), ("ALC-CC", "C", AMBER), ("ALC-NOCC", "B", AMBER)])
        self.assertEqual(round(next(f for f in fs if f.code == "ALC-BUDGET").risk), 60)

    def test_review_caps_savings_per_app_and_builds_decisions(self):
        cs = [contract("Sign", seats=10, unit_price=100, annual_cost=1000, renewal=date(2026, 12, 20), category="E-signature"),
              contract("Sign2", seats=4, unit_price=100, annual_cost=400, category="E-signature")]
        asg = ([Assignment("Sign", "", f"u{k}@x.example", ago(400), ago(100)) for k in range(5)]
               + [Assignment("Sign", "", f"u{k}@x.example", ago(400), ago(1)) for k in range(5, 7)]
               + [Assignment("Sign2", "", f"u{k}@x.example", ago(400), ago(80)) for k in range(4)])
        d = data(cs, asg, people(8))
        rv = review(d)
        sm = summary(d, rv)
        by = {f.code + " " + f.subject: f.saving for f in rv["findings"] if f.saving}
        self.assertEqual(by, {"USE-INACTIVE Sign": 500, "SEAT-SHELF Sign": 300, "USE-INACTIVE Sign2": 400})   # Sign2 fully reclaimed:
        self.assertEqual((rv["total"], rv["saving"], round(rv["saving_pct"])), (1400, 1200, 86))                # nothing left to consolidate
        self.assertEqual((sm["status"], sm["by_lever"]["reclaim"], sm["by_lever"]["right-size"]), (RED, 900, 300))
        kinds = [x.decision.split(" ")[0] for x in rv["decisions"]]
        self.assertIn("Renew,", kinds)
        self.assertIn("Standardise", kinds)
        dd = next(x for x in rv["decisions"] if x.decision.startswith("Renew"))
        self.assertIn("about 2", dd.options)
        self.assertEqual(review(data([contract()], [], {}))["status"], GREEN)


class TestEndToEnd(unittest.TestCase):
    def test_demo_end_to_end_is_deterministic(self):
        with tempfile.TemporaryDirectory() as t:
            hashes = []
            for k in range(2):
                out = Path(t) / f"out{k}"
                self.assertEqual(cli.main(["demo", "--data", str(Path(t) / f"data{k}"), "--out", str(out)]), 0)
                self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(cli.OUTPUTS))
                h = {n: hashlib.sha1((out / n).read_bytes()).hexdigest() for n in cli.OUTPUTS}
                h.update({n.name: hashlib.sha1(n.read_bytes()).hexdigest() for n in (Path(t) / f"data{k}").iterdir()})
                hashes.append(h)
            self.assertEqual(hashes[0], hashes[1])
            self.assertEqual(json.loads((Path(t) / "data0" / "settings.json").read_text(encoding="utf-8"))["as_of"], "2026-11-11 09:00")
            self.assertLess(sum(p.stat().st_size for p in (Path(t) / "data0").iterdir()), 600_000)
            d = load(Path(t) / "data0")
        rv = review(d)
        sm = summary(d, rv)
        self.assertEqual((sm["apps"], sm["contracts"], sm["status"]), (24, 25, RED))
        self.assertTrue(12 <= sm["saving_pct"] <= 18, sm["saving_pct"])
        fs = rv["findings"]

        def one(code, subject):
            return next(f for f in fs if f.code == code and f.subject == subject)

        self.assertEqual(one("USE-DOWNGRADE", "Microsoft 365 E5").count, 180)
        self.assertEqual(sm["leaver_licences"], 46)
        cc = one("USE-INACTIVE", "Adobe Creative Cloud All Apps")
        self.assertEqual((cc.severity, cc.count), (RED, 18))
        self.assertIn("30 %", cc.detail)
        ov = {f.subject: sorted(f.apps) for f in fs if f.code == "PRT-OVERLAP"}
        self.assertEqual(ov, {"Video meetings": ["Webex Meetings Business", "Zoom Workplace Business"],
                              "File sharing": ["Box Business", "Dropbox Business Advanced"]})
        ds = one("REN-NOTICE", "DocuSign eSignature Business Pro")
        self.assertEqual(ds.severity, RED)
        self.assertIn("in 9 days", ds.detail)
        self.assertIn("9.0 % uplift", one("REN-UPLIFT", "Salesforce Sales Cloud Enterprise").detail)
        self.assertEqual(one("SEAT-OVER", "Miro Business").severity, RED)
        self.assertEqual([f.subject for f in fs if f.code == "REN-OWNER"], ["Smartsheet Business"])
        self.assertEqual(sorted(f.subject for f in fs if f.code == "SHD-UNMANAGED"),
                         ["Calendly", "Canva", "ChatGPT Plus", "Grammarly", "Notion"])
        self.assertEqual([f.subject for f in fs if f.code == "SHD-DUPLICATE"], ["Adobe Acrobat Pro"])
        self.assertEqual([f.subject for f in fs if f.code == "ALC-NOCC"], ["KnowBe4 Security Awareness Gold"])
        self.assertEqual(sm["shadow"], 6)
        self.assertAlmostEqual(sum(r["cost"] for r in rv["showback"]), rv["total"], places=2)

    def test_pack_and_csv_outputs(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.main(["demo", "--data", str(Path(t) / "d"), "--out", str(Path(t) / "o")]), 0)
            o = Path(t) / "o"
            pack = (o / "review-pack.md").read_text(encoding="utf-8")
            html = (o / "report.html").read_text(encoding="utf-8")
            ut, rc, cal, sb, fd, ac = (rows(o / n) for n in ("app-utilisation.csv", "reclaim-list.csv", "renewal-calendar.csv",
                                                             "showback.csv", "findings.csv", "actions.csv"))
        for h in ("## Headlines", "## Decisions needed", "## Renewals to negotiate", "## Savings by action", "## Actions",
                  "## Scope and evidence", "## Notes"):
            self.assertIn(h, pack)
        self.assertIn("notice deadline **20 Nov 2026**", pack)
        self.assertNotIn("\r", pack)
        self.assertEqual(len(ut), 25)
        self.assertEqual(sum(1 for r in rc if r["action"] == "downgrade"), 180)
        self.assertEqual(sum(1 for r in rc if r["reason"].startswith("leaver")), 46)
        self.assertEqual(cal[0]["renewal_date"], "2026-12-01")
        self.assertTrue(any(r["app"] == "DocuSign eSignature" and r["days_to_deadline"] == "9" and r["state"] == "act now" for r in cal))
        self.assertAlmostEqual(sum(float(r["annual_cost"]) for r in sb), sum(float(r["annual_cost"]) for r in ut), places=0)
        self.assertEqual(fd[0]["severity"], RED)
        self.assertTrue(all(a["done"] == "" and a["owner"] and a["due"] for a in ac))
        self.assertEqual(len({a["ref"] for a in ac}), len(ac))
        for part in ("Savings by action", "Renewal calendar", "Showback", "Shadow IT", "class='bar'"):
            self.assertIn(part, html)

    def test_review_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o")]), 2)                      # no contracts.csv
            self.assertEqual(cli.main(["review", "--out", str(Path(t) / "o")]), 2)
            self.assertEqual(cli.main(["review", str(Path(t) / "nope"), "--out", str(Path(t) / "o")]), 2)
            write(Path(t) / "contracts.csv", ["App", "SeatsPurchased", "UnitPriceAnnual", "RenewalDate", "Owner", "CostCentre"],
                  [["Only one", "2", "100", "2027-09-30", "Olga", "CC-1"]])
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o"), "--as-of", "2026-11-11"]), 0)
            ut = rows(Path(t) / "o" / "app-utilisation.csv")
            fd = rows(Path(t) / "o" / "findings.csv")
        self.assertEqual((ut[0]["app"], ut[0]["annual_cost"], ut[0]["assigned"]), ("Only one", "200.00", "0"))
        self.assertEqual(fd, [])


def _exporter():
    import importlib.util
    spec = importlib.util.spec_from_file_location("export_m365_licences",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "export_m365_licences.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestExporter(unittest.TestCase):
    def test_graph_export_is_read_only_with_paging(self):
        m = _exporter()
        calls = []
        e5, e3 = "06ebc4ee-1bb5-47dd-8120-11324bc54e06", "05e9a617-0261-4cee-bb44-138d3ef5d965"

        def fake(url, token):
            calls.append(url)
            self.assertEqual(token, "tok")
            if url.endswith("/subscribedSkus"):
                return {"value": [{"skuId": e5, "skuPartNumber": "SPE_E5", "appliesTo": "User", "capabilityStatus": "Enabled",
                                   "consumedUnits": 2, "prepaidUnits": {"enabled": 5, "suspended": 0, "warning": 0}},
                                  {"skuId": e3, "skuPartNumber": "SPE_E3", "appliesTo": "User", "capabilityStatus": "Enabled",
                                   "consumedUnits": 1, "prepaidUnits": {"enabled": 3}},
                                  {"skuId": "x", "skuPartNumber": "TENANT_ADDON", "appliesTo": "Company", "prepaidUnits": {"enabled": 1}}]}
            if "/users?" in url and "skiptoken" not in url:
                self.assertIn("signInActivity", url)
                self.assertIn("%24top=500", url.replace("$top", "%24top"))
                return {"value": [{"userPrincipalName": "Ana@Contoso.example", "displayName": "Ana", "accountEnabled": True,
                                   "department": "Sales", "usageLocation": "ES", "employeeOrgData": {"costCenter": "CC-210"},
                                   "assignedLicenses": [{"skuId": e5, "disabledPlans": []}],
                                   "signInActivity": {"lastSignInDateTime": "2026-11-09T08:00:00Z",
                                                      "lastSuccessfulSignInDateTime": "2026-11-02T08:00:00Z"}}],
                        "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=abc"}
            if "skiptoken" in url:
                return {"value": [{"userPrincipalName": "bo@contoso.example", "displayName": "Bo", "accountEnabled": False,
                                   "assignedLicenses": [{"skuId": e5}, {"skuId": e3}],
                                   "signInActivity": {"lastSignInDateTime": "2026-06-01T10:00:00Z",
                                                      "lastNonInteractiveSignInDateTime": "2026-07-15T10:00:00Z"}},
                                  {"userPrincipalName": "new@contoso.example", "accountEnabled": True, "assignedLicenses": [{"skuId": e3}]}]}
            raise AssertionError(url)

        m._get = fake
        m._token = lambda tenant, cid, secret: "tok" if secret == "s3cret" else "bad"
        with mock.patch.dict(os.environ, {"GRAPH_CLIENT_SECRET": "s3cret"}), tempfile.TemporaryDirectory() as t:
            self.assertEqual(m.main(["--tenant", "contoso.onmicrosoft.com", "--client-id", "abc", "--out", t, "--users"]), 0)
            asg, con, us = rows(Path(t) / "assignments.csv"), rows(Path(t) / "contracts-m365.csv"), rows(Path(t) / "users.csv")
            self.assertNotIn("s3cret", "".join(p.read_text(encoding="utf-8") for p in Path(t).iterdir()))
            d = Data(settings_from_dict({}), AS_OF, load_contracts(Path(t) / "contracts-m365.csv"), load_assignments(Path(t) / "assignments.csv"))
        self.assertEqual([(r["Sku"], r["User"], r["LastActive"]) for r in asg],
                         [("SPE_E5", "ana@contoso.example", "2026-11-02"), ("SPE_E5", "bo@contoso.example", "2026-07-15"),
                          ("SPE_E3", "bo@contoso.example", "2026-07-15"), ("SPE_E3", "new@contoso.example", "")])
        self.assertEqual([(r["Sku"], r["SeatsPurchased"], r["ConsumedUnits"]) for r in con], [("SPE_E3", "3", "1"), ("SPE_E5", "5", "2")])
        self.assertEqual([(r["User"], r["CostCentre"], r["Status"]) for r in us],
                         [("ana@contoso.example", "CC-210", "Active"), ("bo@contoso.example", "", "Disabled"),
                          ("new@contoso.example", "", "Active")])
        self.assertEqual(match(d.assignments, d.contracts), [])
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
