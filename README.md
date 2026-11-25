# HourBank: trade skills, not money

A community **time bank**. One hour of any skill equals one hour of any other skill.
Teach an hour of guitar, earn an hour of laptop repair.

## Run it (no installs needed)

Requires only Python 3.8+ (standard library, nothing to pip install).

```bash
python3 server.py
```

Open http://localhost:8000. Use `PORT=9000 python3 server.py` to change the port.
To reset all data, delete `hourbank.db` and restart (it re-seeds from `seed.json`).

## How it works

- Everyone starts with 3 hours. You can go at most 2 hours into credit.
- **Offers** ("I can teach…") and **Requests** ("I need help with…") are posted to the marketplace.
- Someone books an offer or volunteers for a request, creating a *pending* swap.
- When the person who **received** help confirms it, hours move from receiver to provider.
- Pick any member in the top-right selector to act as them (demo mode, no passwords).

## Project layout

```
server.py        Python HTTP server + REST API + SQLite (members, listings, exchanges, ledger)
seed.json        Full starter data: 12 members, 36 listings, 9 completed swaps
static/          Frontend: index.html, style.css, app.js (vanilla JS, no build step)
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stats` | Totals and category list |
| GET | `/api/members` | All members with balances and hours given |
| GET | `/api/members/<id>` | Member with listings, swaps and ledger |
| GET | `/api/listings?q=&type=&category=&status=` | Search the marketplace |
| POST | `/api/listings` | Create a listing |
| POST | `/api/listings/<id>/accept` | Book an offer or volunteer for a request |
| POST | `/api/exchanges/<id>/complete` | Receiver confirms and hours transfer |
| POST | `/api/exchanges/<id>/cancel` | Either party cancels a pending swap |
| GET | `/api/activity` | Recent completed swaps with thank-you notes |

## Ideas to extend

Real logins, ratings, photos, a map view, email notifications, group workshops.
