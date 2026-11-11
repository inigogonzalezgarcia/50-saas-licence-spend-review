# SaaS and licence review cycle

How to run the monthly licence review and prepare each renewal with `licencereview`. The tool only reads exports; licences are removed, contracts renegotiated and notices sent by their owners, in their own tools.

## Who is involved

| Role | Part |
|---|---|
| Software asset manager (SAM) | Keeps the register, runs the review, prepares the pack, tracks the actions and the notice deadlines |
| IT manager | Chairs the monthly review, decides on consolidation and on the renewals, approves the exceptions |
| Finance (IT finance) | Confirms the costs and the budget, owns the showback, approves spend above the agreed limits |
| App owners (business) | Answer for the usage of their app, confirm who keeps a licence, decide renew, reduce or cancel with SAM |
| Service desk | Reclaims licences after the notice to the holder, and removes them as part of the leaver process |
| IT procurement | Talks to the vendors: notices, true-downs, uplift caps, co-terming |
| IT security | Reviews shadow-IT apps, SSO and data classification |

## Every month

| When | What | Output |
|---|---|---|
| First working day | Export the assignments with the last activity from each tool (Microsoft 365 with `scripts/export_m365_licences.py`), the HR leavers, and the previous month's card expenses and AP lines | `data/` |
| Same day | Run the review; send each app owner their utilisation, inactive users and the reclaim list for their app | `output/` |
| Day 1 to 10 | Leaver licences: remove at once, then fix the leaver process where it failed | |
| Day 1 to 10 | Inactive and never-used licences: e-mail the holders and their managers ("we will remove your licence on <date> unless you tell us you need it"); the service desk reclaims what nobody claims back | `reclaim-list.csv` |
| Day 10 | Review with the IT manager and finance: the pack, the decisions, the renewals in the next 120 days | `review-pack.md` |
| Day 15 | Showback to the department heads with the licences their people hold | `showback.csv` |

```bash
python scripts/export_m365_licences.py --tenant contoso.onmicrosoft.com --client-id <app id> --out data
python -m licencereview review data/
```

Reclaimed licences go back to the pool and are assigned before buying any new one. Never-used licences usually mean an app assigned by default in a joiner profile: move it to "on request".

## Before each renewal

| Renewal − | Step |
|---|---|
| 120 days | The contract appears in "Renewals to negotiate". SAM and the app owner look at the utilisation over the last months, the overlap with other apps and the uplift in the contract. Decide the direction: renew, reduce, change tier, consolidate or cancel |
| 90 days | Clean up first: reclaim inactive licences and leavers, so the seat count you negotiate on is the real one. Ask the vendor for the renewal quote |
| Notice deadline − 14 days | Decision taken by the IT manager (and finance above the agreed amount). Procurement prepares the notice |
| Notice deadline | Notice sent in the form the contract requires (often written, to a named address), and the vendor's receipt kept. Without it an auto-renewing contract renews as it is |
| 60 days | Negotiate the terms with the usage data |
| 0 | New term in the register: seats, price, renewal date, notice period, uplift cap, owner, cost centre |

Many notice periods are 30, 60 or 90 days, and some contracts ask for more; the deadline is the date that matters, not the renewal date. A deadline already passed on an auto-renewing contract still deserves a written request: vendors sometimes agree to reduce seats, but it is a request, not a right.

## Negotiating with usage data

- **True-up and true-down.** A true-up is paying for seats used above what was bought, often at list price and backdated; a true-down is reducing seats at the renewal. Reclaim before the true-up count, and make sure the contract allows the true-down: some terms only allow increases during the term.
- **Utilisation as the argument.** "We use 58 % of what we buy" is a stronger opening than "we want a discount". Bring the active users, not the assigned ones.
- **Uplift caps.** Ask for the uplift to be capped (the settings use 5 %) and written into the contract for the next terms. Trade a longer term or a larger commitment for the cap, never for nothing.
- **Tiers.** Users who do not use the premium features of a tier (E5 against E3, an enterprise plan against a business plan) can move down at the renewal or at the true-down window of the agreement. The app owner checks the list first: a few people may need a feature that the usage data does not show.
- **Co-terming.** Bring the end dates of contracts with the same vendor together, so there is one negotiation a year with the whole volume on the table, and no small renewal slips through.
- **Consolidation.** When the suite already covers a capability (video meetings and file sharing in Microsoft 365), exiting a standalone app saves its whole cost, but only after the people who use it have moved. Plan the migration before the notice, not after.

## Shadow IT without blocking people

Expense lines for SaaS that is not in the register usually mean that people needed something IT did not give them. Talk to them before acting:

1. Ask what they use it for and what data they put in it.
2. If several departments use it, adopt it centrally: a contract, SSO with Entra ID, an owner and a security review.
3. If an approved app does the same, move them to it and help with the move.
4. If it stays individual, accept it in writing with the security review, and keep it on the list.

Card purchases of an app the company already has under a central contract (`SHD-DUPLICATE`) are simpler: give the person a seat from the pool and stop the card subscription. Blocking the vendor on cards works only after people have an alternative.

## Showback

Licence cost is shown per department and cost centre from the people who hold the licences. Unassigned seats stay with IT: they are IT's to fix. Showback is information, not a recharge; moving to chargeback is a finance decision. Send it monthly with the reclaim list: department heads reclaim faster when they see the cost.

## Who approves what

| Decision | Approves |
|---|---|
| Reclaim an inactive or never-used licence after notice to the holder | Service desk, under this process |
| Remove a leaver's licence | Service desk, at once |
| Downgrade a tier | App owner, with SAM |
| Reduce seats or cancel at renewal | IT manager; finance above the agreed amount |
| Consolidate (exit an app) | IT manager, with the app owners and the business heads affected |
| Accept an uplift above the cap, or a multi-year term | IT manager and finance |
| Adopt a shadow-IT app centrally | IT manager and IT security |

Keep the decisions and the notices sent in the pack's notes section, and the actions in `actions.csv` until they are done.
