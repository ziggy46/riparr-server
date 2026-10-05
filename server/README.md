# Riparr service

The service itself: FastAPI + SQLite in a single process, serving a static frontend.
No separate database and no separate web server; the Docker image is this plus MakeMKV.

```sh
./run.sh              # http://localhost:8000
```

Off Linux (or with `RIPARR_MOCK=1`) it runs in **mock mode**: `riparr/platform.py`
reports simulated hardware, a simulated drive with a disc in it, and discoverable network
shares, so the whole interface is exercisable on a laptop. `IS_APPLIANCE` is the only
switch.

## Layout

| File | Purpose |
|---|---|
| `riparr/main.py` | The API and static serving |
| `riparr/platform.py` | **Everything that differs between real hardware and a laptop.** Nothing else shells out. |
| `riparr/db.py` | SQLite. Settings are typed key/value; WAL, because the cable gets yanked (D4) |
| `riparr/shares.py` | SMB discovery, and the write test that proves a share works |
| `riparr/updater.py` | Update check and install against the official repository |
| `static/` | The web UI |
| `static/themes/` | theme.park palettes (MIT), plus `servarr.css` |

## The interface

Follows *arr-family conventions closely enough to be immediately familiar: sub-navigation
in the sidebar expanded under the active section, count badges, a search underline beside
the logo, an icon-over-label toolbar, and flat underlined section headings.

All colour resolves through **theme.park**'s custom-property contract, so a user already
theming their *arr stack themes Riparr for free. Eleven palettes ship, totalling 14 KB.

> **`servarr.css` carries Sonarr's exact palette and dimensions, and Sonarr is GPL-3.0.**
> The licensing consequence is unresolved and deliberately
> confined to that one file plus a handful of constants in `app.css`.

## Two things worth knowing

**A share is not saved until it is proven.** `POST /api/shares` writes a real file, reads
it back, compares it and deletes it before persisting anything. An SMB write returning
success is not proof of a good file (D6), and a wrong share path otherwise surfaces at 3am
on the first rip rather than during setup.

**Capacity is reported as a mode, not a number.** Under D11 a buffer too small for the
next disc means *stream mode*, not a refusal. `/api/status` returns
`{discs_free, mode, phrase}` and the UI renders the phrase, because "no room" would
contradict the design and push people toward larger cards for a benefit that doesn't
exist.

## API

Self-documenting at `/api/docs` (in mock mode, or with `RIPARR_API_DOCS=1`). The UI is only the first client of it — that is what
makes Homepage widgets and multi-unit setups nearly free later.

## Not built

**The rip engine.** Queue, history and disc history read real tables that nothing
populates yet. Disc detection, MakeMKV invocation, the follow-copy uploader and the
fingerprint cache are all still ahead.
