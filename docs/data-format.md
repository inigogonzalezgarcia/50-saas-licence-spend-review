# Data format

Put the files in one folder and run `python -m licencereview review <folder>`. Only `contracts.csv` is required; every other file adds its checks (a check without its file is skipped, not passed). Comma, semicolon or tab separated, UTF-8. Column names are matched loosely (case, accents and punctuation are ignored), and the alternatives below are accepted. Dates as ISO 8601 (`2026-11-11`, `2026-11-02T08:15:00Z`), `dd/mm/yyyy`, `MM/dd/yyyy` or `11 Nov 2026`; the time zone suffix is ignored. Amounts may carry a currency sign and thousands separators (`€ 38,000`, `38.000,00`).

`contracts.csv` usually comes from the SAM tool (Flexera, Apptio) or the contract sheet; `assignments.csv` from each tool's admin console or user export, and for Microsoft 365 from `scripts/export_m365_licences.py`; `users.csv` from HR (or from Entra ID with the exporter's `--users`); `expenses.csv` from the expense tool and the AP invoice lines.

## How the review works

| Step | Rule |
|---|---|
| Matching | Each assignment is linked to a contract by `App` and `Sku`; when the app has one contract and the assignment has no SKU, by `App`; when only the SKU matches one contract, by `Sku` (Microsoft 365 SKU part numbers such as `SPE_E5`) |
| Active | Last activity within `inactive_days.reclaim` (60) days. Between `inactive_days.warning` (30) and 60 days the licence is counted as idle in `app-utilisation.csv`, not reclaimed |
| Utilisation | Active holders / seats purchased (or / assigned when the seats are unknown) |
| Reclaim | Leavers (`USE-LEAVER`), no activity for more than 60 days (`USE-INACTIVE`), never used and assigned more than `never_used_grace_days` (30) ago (`USE-NEVER`). Saving = the unit price per licence. People on long leave are reported (`USE-LEAVE`), not counted as savings |
| Downgrade | Active holder of a SKU with `DowngradeTo` and `UsesPremium` = No: saving = unit price − the lower tier's unit price |
| Right-size | Seats purchased and not assigned (`SEAT-SHELF`): saving = the unassigned seats × unit price, taken at the renewal (true-down) |
| Negotiate | An uplift above `uplift_threshold_pct` (5) on a renewal in the next `calendar_months` (12): saving = annual cost × (uplift − threshold) |
| Cancel duplicates | Card expenses for a vendor already under a central contract (`SHD-DUPLICATE`): saving = that spend |
| Consolidate | Apps with the same `Category` (`PRT-OVERLAP`): when a suite in `suite_capabilities` covers the capability, every standalone app is an exit candidate; otherwise all but the largest. Saving = what is left of each exit candidate's cost after the other savings |
| Counting once | Savings are applied per app in the order above and capped at the app's annual cost, so one euro is never counted twice |
| Severity | RED: licences on leavers, inactive share above `inactive_share_red_pct` (20 %), shelfware above `shelfware_pct.red` (15 %), over-assignment, a notice deadline within `notice_warning_days.red` (14) days or passed on an auto-renewing contract, spend more than `budget_red_pct` (10 %) over budget. Everything else AMBER. The review is RED with any RED finding |
| Due dates | RED actions `action_days.red` (5) days from the review date, AMBER `action_days.amber` (15); a notice deadline two days before it |
| Showback | Per-user licences are charged to the holder's department at annual cost / max(seats, assigned); unassigned seats, flat and per-device contracts stay on the contract's cost centre. The rows add up to the annual spend |

## contracts.csv

One row per app and SKU (Microsoft 365 E3 and E5 are two rows).

| Column | Alternatives | Notes |
|---|---|---|
| App | Application, Product, Software, Service | Required |
| Vendor | Supplier, Publisher | Also used to match expenses |
| Category | Capability, Function | The capability (`Video meetings`, `File sharing`, `E-signature`, `CRM`…); apps with the same one are overlap candidates |
| Sku | Tier, Edition, Plan, sku part number | |
| LicenceModel | Licence model, metric | `Per user` (default), `Per device`, `Flat` (site, enterprise, tenant); usage and seat checks run for per-user contracts only |
| SeatsPurchased | Seats, Quantity, Licences purchased, prepaid units | |
| UnitPriceAnnual | Unit price per year, unit price | Or `UnitPriceMonthly` (× 12); worked out from `AnnualCost / Seats` when missing |
| AnnualCost | Annual value, acv | Worked out as seats × unit price when missing |
| Currency | | Converted with `fx` in the settings |
| ContractStart | Start | Informational |
| RenewalDate | Renewal, End date, Expiry, term end | A past date on an auto-renewing contract rolls forward a year at a time |
| NoticeDays | Notice period days, notice period | Notice deadline = renewal − notice days |
| AutoRenew | Auto-renew, Evergreen | `Yes` / `No` |
| UpliftPct | Uplift %, Renewal uplift, price increase | `9`, `9 %` or `0.09` |
| Owner | Contract owner, Business owner | Empty: `REN-OWNER` |
| CostCentre | Cost center, cc | Empty: `ALC-NOCC`; not in `cost_centres` or users.csv: `ALC-CC` |
| Sso | Single sign-on, SSO enabled | `No` with confidential data: `PRT-SSO` |
| DataClassification | Classification, sensitivity | Compared with `confidential_classes` |
| DowngradeTo | Lower tier | The SKU (same app) that covers users who do not use the premium features |

## assignments.csv

One row per user and licence.

| Column | Alternatives | Notes |
|---|---|---|
| App | Application, Product | |
| Sku | Tier, Plan, sku part number | |
| User | UserPrincipalName, UPN, Email | Matched to users.csv, case-insensitive |
| AssignedDate | Assigned, Date assigned | Used for the never-used grace period |
| LastActive | Last sign-in, last activity, last used | Empty = never. For Microsoft 365 the exporter writes the last successful Entra ID sign-in |
| UsesPremium | Premium features used | `No` marks a downgrade candidate; empty = unknown |

## users.csv

| Column | Alternatives | Notes |
|---|---|---|
| User | UserPrincipalName, UPN, Email | Required |
| DisplayName | Name | |
| Department | Dept, Business unit | Showback |
| CostCentre | Cost center | Showback, and the list of valid cost centres |
| Country | Location, Office, usage location | Informational |
| Status | Employment status, accountEnabled | `Active`; `Leaver` (or terminated, left, disabled, `false`); `Long leave` (or maternity, parental, sabbatical) |
| LeaveDate | Termination date, last day | Shown in the reclaim list |

Accounts with licences that are not in users.csv are reported as `USE-UNKNOWN` (service accounts, external users, old accounts).

## expenses.csv

| Column | Alternatives | Notes |
|---|---|---|
| Date | Transaction date, Invoice date | Lines older than `expense_months` (12) are ignored |
| Supplier | Vendor, Merchant, Payee | Matched to the contracts' vendors and apps, then to `saas_vendors` |
| Description | Memo, Narrative | Also searched for the `saas_vendors` keywords |
| Amount | Net amount, Total | Converted with `fx` when `Currency` is set |
| Currency | | |
| Employee | Spender, Cardholder | Empty = an AP invoice to the central contract (not a duplicate); set = bought by a person |
| CostCentre | Cost center | |

## settings.json

| Key | Default | Meaning |
|---|---|---|
| `organisation`, `as_of`, `currency` | | Name, review date (`2026-11-11 09:00`), currency of the report |
| `fx` | `{}` | Rates to the report currency (`{"USD": 0.92}`) |
| `inactive_days` | 30 / 60 | Idle warning and reclaim windows |
| `inactive_share_red_pct` | 20 | Share of inactive licences that makes `USE-INACTIVE` red |
| `never_used_grace_days` | 30 | Days after assignment before an unused licence counts |
| `shelfware_pct` | 5 / 15 | Unassigned seats, AMBER / RED |
| `renewal_horizon_days` | 120 | Renewals checked for notice deadlines |
| `notice_warning_days` | 45 / 14 | Notice deadline AMBER / RED |
| `uplift_threshold_pct` | 5 | Uplift cap |
| `calendar_months` | 12 | Length of the renewal calendar |
| `budgets`, `budget_red_pct` | `{}`, 10 | Annual budget per category, and `total`; RED beyond 10 % over |
| `cost_centres` | `[]` | Valid cost centres (users.csv adds its own) |
| `suite_capabilities` | `{}` | Capabilities a suite already covers: `{"Microsoft 365": ["Video meetings", "File sharing"]}` |
| `saas_vendors` | `{}` | Keyword in the expense supplier or description → product (`{"openai": "ChatGPT Plus"}`) |
| `expense_months` | 12 | Expense window |
| `confidential_classes` | confidential, restricted | Classifications that need SSO |
| `action_days` | 5 / 15 | Days to the due date of RED / AMBER actions |
| `owners` | | Owner per action type: `reclaim`, `downgrade`, `right-size`, `negotiate`, `consolidate`, `cancel`, `security`, `finance`, `sam`. Renewal findings go to the contract owner when there is one |
