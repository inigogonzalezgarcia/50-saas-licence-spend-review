#!/usr/bin/env python3
"""Read-only export of the Microsoft 365 licences from Microsoft Graph: who holds which SKU and when they last signed in, plus a
contracts stub with the seats bought and assigned per SKU.

Only GET requests to Microsoft Graph (and the token request to Microsoft Entra ID). The client secret is read from an environment
variable or typed in when asked; it is kept in memory and never written to disk or printed.

Microsoft Graph v1.0
  - GET /subscribedSkus                                   the SKUs the tenant has bought: skuPartNumber, prepaidUnits.enabled
                                                          (seats bought and active) and consumedUnits (seats assigned)
  - GET /users?$select=userPrincipalName,displayName,accountEnabled,department,usageLocation,employeeOrgData,
        assignedLicenses,signInActivity&$top=500          every user with the SKUs assigned and the last sign-in; paged with
                                                          @odata.nextLink (with signInActivity a page holds up to 500 users)

Sign-in: an app registration with application permissions, admin consent granted, and a client secret (client credentials):
  - LicenseAssignment.Read.All (or Organization.Read.All) for subscribedSkus
  - User.Read.All for the users, and AuditLog.Read.All for signInActivity
signInActivity needs a Microsoft Entra ID P1 or P2 licence in the tenant. LastActive is its last successful sign-in to Entra ID,
not the use of a particular app: treat it as "the account is in use", and check the list with the app owner before reclaiming.

Writes (to --out):
  assignments.csv      App, Sku, User, AssignedDate (empty: Graph does not give it here), LastActive, UsesPremium (empty)
  contracts-m365.csv   one row per SKU: seats bought; add the unit price, renewal date, notice period and owner by hand,
                       then copy the rows into contracts.csv
  users.csv            with --users: UPN, name, department, cost centre (employeeOrgData), country (usageLocation) and status
                       (accountEnabled false = Disabled); prefer the HR export when you have one, it knows who has left

Example
  export GRAPH_CLIENT_SECRET=...        # or leave it unset and type it when asked
  python scripts/export_m365_licences.py --tenant contoso.onmicrosoft.com --client-id 00000000-0000-0000-0000-000000000000 \\
      --out data --users
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
USER_FIELDS = "userPrincipalName,displayName,accountEnabled,department,usageLocation,employeeOrgData,assignedLicenses,signInActivity"


def _token(tenant: str, client_id: str, secret: str) -> str:
    body = urllib.parse.urlencode({"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
                                   "scope": "https://graph.microsoft.com/.default"}).encode()
    req = urllib.request.Request(f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token", data=body,
                                 method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))["access_token"]
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"error: token request failed with HTTP {exc.code}; check the tenant, the client id and the secret")


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503, 504) and attempt < 5:
                time.sleep(int(exc.headers.get("Retry-After") or 2 ** attempt))
                continue
            if exc.code == 403:
                raise SystemExit(f"error: HTTP 403 from {url.split('?')[0]}: the app needs LicenseAssignment.Read.All, User.Read.All "
                                 "and AuditLog.Read.All with admin consent, and signInActivity needs Entra ID P1 or P2")
            raise SystemExit(f"error: HTTP {exc.code} from {url.split('?')[0]}: {exc.reason}")
    raise SystemExit("error: too many retries")


def _all(url: str, token: str) -> list[dict]:
    """Every page of a collection, following @odata.nextLink."""
    out = []
    while url:
        page = _get(url, token)
        out += page.get("value", [])
        url = page.get("@odata.nextLink")
    return out


def _day(v) -> str:
    return str(v or "")[:10]


def last_active(sign_in: dict | None) -> str:
    """The last successful sign-in (interactive or not) as YYYY-MM-DD; when Graph has none, the later of the last interactive and
    non-interactive sign-in attempts (these include failed attempts). Empty when there is none."""
    s = sign_in or {}
    ok = _day(s.get("lastSuccessfulSignInDateTime"))
    if ok and not ok.startswith("0001"):
        return ok
    ds = [_day(s.get(k)) for k in ("lastSignInDateTime", "lastNonInteractiveSignInDateTime")]
    ds = [d for d in ds if d and not d.startswith("0001")]
    return max(ds) if ds else ""


def export(token: str, app: str) -> dict:
    skus = [s for s in _all(f"{GRAPH}/subscribedSkus", token) if s.get("appliesTo", "User") == "User"]
    names = {s["skuId"]: s.get("skuPartNumber") or s["skuId"] for s in skus}
    query = urllib.parse.urlencode({"$select": USER_FIELDS, "$top": "500"}, safe="$,")
    users = _all(f"{GRAPH}/users?{query}", token)
    assignments, people = [], []
    for u in sorted(users, key=lambda u: (u.get("userPrincipalName") or "").lower()):
        upn = (u.get("userPrincipalName") or "").lower()
        seen = last_active(u.get("signInActivity"))
        for lic in u.get("assignedLicenses") or []:
            sku = names.get(lic.get("skuId"))
            if sku:
                assignments.append([app, sku, upn, "", seen, ""])
        org = u.get("employeeOrgData") or {}
        people.append([upn, u.get("displayName") or "", u.get("department") or "", org.get("costCenter") or "",
                       u.get("usageLocation") or "", "Active" if u.get("accountEnabled", True) else "Disabled", ""])
    contracts = []
    for s in sorted(skus, key=lambda s: s.get("skuPartNumber") or ""):
        pre = s.get("prepaidUnits") or {}
        contracts.append([app, "Microsoft", "Productivity suite", names[s["skuId"]], "Per user", pre.get("enabled", 0), "", "", "", "",
                          "", "", "", "", "", "", "Yes", "", "", s.get("consumedUnits", 0), s.get("capabilityStatus", "")])
    return {"assignments": assignments, "users": people, "contracts": contracts}


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tenant", required=True, help="tenant id or primary domain (contoso.onmicrosoft.com)")
    p.add_argument("--client-id", required=True, help="application (client) id of the app registration")
    p.add_argument("--app", default="Microsoft 365", help="the App name to use in the CSVs (default Microsoft 365)")
    p.add_argument("--out", type=Path, default=Path("data"))
    p.add_argument("--users", action="store_true", help="also write users.csv from Entra ID")
    a = p.parse_args(argv)
    secret = os.environ.get("GRAPH_CLIENT_SECRET") or getpass.getpass("Client secret (not echoed): ")
    token = _token(a.tenant, a.client_id, secret)
    del secret
    x = export(token, a.app)
    a.out.mkdir(parents=True, exist_ok=True)
    _write(a.out / "assignments.csv", ["App", "Sku", "User", "AssignedDate", "LastActive", "UsesPremium"], x["assignments"])
    _write(a.out / "contracts-m365.csv", ["App", "Vendor", "Category", "Sku", "LicenceModel", "SeatsPurchased", "UnitPriceAnnual",
                                          "AnnualCost", "Currency", "ContractStart", "RenewalDate", "NoticeDays", "AutoRenew", "UpliftPct",
                                          "Owner", "CostCentre", "Sso", "DataClassification", "DowngradeTo", "ConsumedUnits",
                                          "CapabilityStatus"], x["contracts"])
    if a.users:
        _write(a.out / "users.csv", ["User", "DisplayName", "Department", "CostCentre", "Country", "Status", "LeaveDate"], x["users"])
    print(f"{len(x['contracts'])} SKUs, {len(x['users'])} users, {len(x['assignments'])} licence assignments written to {a.out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
