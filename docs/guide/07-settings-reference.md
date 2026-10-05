# 7. Settings Reference

[← Ripping discs](06-ripping-discs.md) · [Guide index](README.md) · [Next: Troubleshooting →](08-troubleshooting.md)

Every setting, and whether you should care. **Most people never open this page.** The one
exception is [the MakeMKV key](#makemkv-key).

---

## MakeMKV key

**The only setting that needs periodic attention, and Riparr tries hard to make it not
your problem.**

MakeMKV does the actual disc reading. Its free beta key **expires on a month boundary** —
not a fixed number of days after you enter one, so a key issued mid-month may last a day
or five weeks. Riparr says which month yours is good for rather than counting down to a
date it cannot know, and **puts in the new key itself** when GuinpinSoft publishes it.
It checks makemkv.com every six hours, and only ever swaps a beta key for a beta key: a
bought key is never touched, and if makemkv.com, its forum and the backup key service
disagree about the new key, nothing changes. The next time you open the web page, Riparr
tells you it renewed the key.

| Setting | Notes |
|---|---|
| **Key** | Paste a free beta key or a purchased permanent key |
| **Renew the beta key automatically** | Default: on. Turn it off to replace the key yourself |
| **Expires** | The month this key is good for, and the date it stops. Never a countdown to a date GuinpinSoft has not published |
| **Warn me before expiry** | Default: 7 days |
| **Notify via** | Web banner, plus any [notification channel](#notifications) you've set up |

**Riparr warns you before it breaks, never after.** It will not let a key silently expire
mid-rip while nobody is looking at the web page.

The key is stored in the `/data` volume (the container's `HOME` is `/data`), so it
survives rebuilding and recreating the container.

**Buy the permanent key** if you rip regularly. It's a one-time purchase, it never
expires, and it pays the people who make MakeMKV. When makemkv.com isn't selling licences,
as happens, its own site asks everyone to use the free beta key, and Riparr says so
rather than showing a Buy button that leads nowhere.

> MakeMKV is made by GuinpinSoft, not by Riparr, and its licence agreement is between
> you and them. You accept it by setting `MAKEMKV_ACCEPT_EULA: "yes"` in
> `docker-compose.yml`; the container then compiles MakeMKV on its first start. Nothing
> is installed from the web UI.

Every MakeMKV download is checked against a checksum pinned in
`packaging/makemkv-manifest.json`, and mirrors are tried in order if makemkv.com is
down, so the build gets the right file or fails.

**Settings → General** also tracks makemkv.com and its forum separately, because they are
different machines and fail independently. Both publish the free key, and one is usually
up when the other is not.

**A new version of MakeMKV** arrives with a Riparr release, once the pin in
`packaging/makemkv-manifest.json` is updated. To get it, update Riparr
(`docker compose pull && docker compose up -d`); the first start after that compiles the
new version. The version you have keeps working until you do.

## Library

### Where things go

One block per kind of disc, each naming a **share** and a **folder inside it**. Because
both halves are choosable, "two folders on one server" and "two completely different
machines" are the same control.

| Setting | Notes |
|---|---|
| **Films → Share** | Which share. Defaults to the one you set up first |
| **Films → Folder** | The folder inside it, e.g. `Movies` or `Films/Bluray`. Several levels deep is fine |
| **Television → Share** | Can be the same share, or a different one entirely |
| **Television → Folder** | e.g. `TV` or `Shows` |

Under each block Riparr shows the full path it adds up to, and whether that share is
**mounted** — which is what lets a rip be written straight into your library instead of
being staged first. Riparr does not mount shares itself: mount the library on the host
and bind-mount it into the container at `/srv/library` for the default share, or
`/srv/library-<id>` for any other, then recreate the container. See
[Run it in Docker](02-docker.md#optional-rip-straight-into-your-library).

### Shares

| Setting | Notes |
|---|---|
| **Server** | A hostname or an IP address |
| **Share** | The top-level name your server publishes. One word, no slashes |
| **Folder** | Everything below it. Riparr creates it if it does not exist |
| **Username** | Optional. A domain account goes in as `DOMAIN\name`, `DOMAIN/name` or `name@domain` |
| **Test and save** | Writes a real file into the folder, reads it back, compares it, deletes it. A share is not saved until that passes |

Files are copied to shares with `smbclient`, so a share works with nothing mounted.

The first share you add becomes the default, and adding more does not change that — so
adding a share for box sets cannot quietly redirect your films.

> **`NT_STATUS_LOGON_FAILURE` usually is not the password.** Many NAS boxes answer a
> share name they do not recognise with the same error they use for a bad password,
> rather than confirm which shares exist. Check the **Share** box first. Riparr's error
> message says so, and prints the exact path it was trying to write to.

## Naming

| Setting | Default |
|---|---|
| **Film template** | `{Title} ({Year})/{Title} ({Year}).mkv` |
| **TV template** | `{Title} ({Year})/Season {Season:00}/{Title} - S{Season:00}E{Episode:00} - {EpisodeTitle}.mkv` |

The film and TV templates each have a preset list, including TRaSH Guides' Radarr naming
schemes, and a live preview. [Library layout](05-library-layout.md#naming-templates) has
every token.

**Film lookup (TMDb)**, on the same page: a TMDb key, a button to test it, and what to do
when TMDb isn't sure which film a disc is — keep Riparr's name without IDs *(default)*, or
ask you. See [Library layout](05-library-layout.md#film-lookup-tmdb).
| **On unknown disc** | **Use the disc label** *(default)* / Ask me / Skip |

**This is only about the *name*.** Which title gets ripped is a separate setting, under
[Ripping](#ripping) — they used to be one, and answering the naming question also
silently answered the other one.

`Use the disc label` is the default because Riparr's promise is that you put a disc in
and walk away, and most rips land in a folder that gets tidied or compressed later
rather than straight into a library somebody is browsing. A folder named off the disc
label is something you can fix in ten seconds; a queue that stopped at 2am waiting for
you is not. Switch it to `Ask me` if your rips go directly into a library you browse.

## Track selection

Bigger effect on file size than anything else here.

| Setting | Default |
|---|---|
| **Audio languages** | Your locale language + original |
| **Subtitle languages** | Your locale language |
| **Keep forced subtitles** | On — these are the subtitles for alien/foreign dialogue |
| **Keep commentary tracks** | Off |
| **Minimum title length** | 120 seconds — filters menus and logo stings |
| **Rip mode** | Main title *(default)* / All titles / **Full disc backup** — the whole disc as a `VIDEO_TS` or `BDMV` folder, menus and all. DVDs use `dvdbackup` and `libdvdcss`, which are built into the image |
| **When Riparr can't tell which title is the film** | **Use the most likely one** *(default)* / Ask me |
| **On a disc with a 3D version** | **Rip the 2D version** *(default)* / Rip the 3D version |

## Television

| Setting | Notes |
|---|---|
| **Look for season discs** | On. A disc with several titles of the same length is read as a season rather than a film with decoys. Turn it off if you only own films. |
| **Before ripping a season** | **Show me the plan when Riparr isn't sure** *(default)* / Always show me / Never. The default stops **once per season** — on the first disc, where one correction fixes every disc after it — and on any later disc whose order Riparr couldn't read off the disc. Reading the order off the disc is reliable; what it can't settle is whether the numbering matches your episode guide, since a few shows were released on disc in production order. **A disc with no season number always asks**, whatever this is set to, because there is no answer to get on with. |
| **Look up episode names** | On. From [TVmaze](https://www.tvmaze.com), no account needed. Off gives correctly numbered files with no names — Plex and Jellyfin match on the numbers, so they still land correctly. |
| **Specials go in** | `Season 00` *(default)* / `Specials`. Both are read as season zero. Set the season to 0 on the episode plan to file a disc here. |

The episode plan is a table, one row per file that will be written. Untick a row to skip
it, use the arrows to move an episode, type over a name to correct it, or change **first
episode** to shift the whole disc — the numbers and names update together as you go.
Later discs of the same season carry on from where the last one stopped without asking.

Keeping every language and commentary can roughly double file size for no benefit most
people notice.

## Storage & transfer

| Setting | Notes |
|---|---|
| **Mode** | `Straight to your library` *(default)* — MakeMKV writes onto your share as the disc is read, and nothing is staged. No size ceiling and the film is written once. It needs the library bind-mounted at `/srv/library`; if nothing is mounted there, each rip stages in `/srv/staging` by itself and is copied over SMB afterwards — so it is safe to leave on. `Staged first, then sent` is the answer if your NAS sleeps, your network is unreliable, or you want deep verification. `Always burst` and `always stream` force one staged behaviour or the other. |
| **Verify after transfer** | `Quick` *(default)* — asks your library how big the file is and compares it with what was sent. Nearly free, and it catches what actually goes wrong: a truncated transfer, a share that filled up, a write that was refused. `Deep` also reads every byte back and hashes it, so it catches silent corruption too. `Don't verify` trusts the upload. Applies to automatic and manual rips alike. |
| **Keep local copy** | On. Riparr retains the staged copy in `/srv/staging` until it needs the room, so a downstream problem is a re-copy instead of a re-rip. |
| **Space remaining** | Staging space, shown in discs, not gigabytes |
| **Test staging speed** | Measures how fast the staging disk behind `/srv/staging` writes |

**Deep verification is only offered when rips are staged.** It works by reading the
file back off the share and comparing it with the original, so it needs two copies.
Going straight to your library leaves one — hashing it against itself would pass every
time and prove nothing. Switch **Mode** to *Staged first, then sent* if you want it, and
give `/srv/staging` room for two copies of the largest title you rip: the read-back has
to land somewhere, because `smbclient` cannot stream it.

## Handoff

For sending finished rips somewhere else — a transcoder, an automation.

| Setting | Notes |
|---|---|
| **Watch folder mode** | Write to a staging path instead, for Tdarr / Unmanic to pick up |

The completion webhook moved to **Notifications** below, where the rest of the ways
Riparr can reach you now live.

**Riparr does not transcode**, by design. It rips; a transcoder is a separate job. Point
Tdarr or Unmanic at the watch folder and let them do it.

## Notifications

On **Settings → Connect**. This is how Riparr reaches you once you have walked away
from the drive — the drive's own signals only help if you are in the room.

**Tell me when** is the list of events, at the top of the page. Riparr sends every one
you tick to every channel you set up. Four are on by default.

**Channels** below it is four rows, each wearing the mark of the service it configures.
Click a row to open its setup instructions and fields; only one is open at a time. A
channel Riparr has what it needs for shows its mark in full colour with a tick on the
corner, and the row says what it is pointed at — the topic, the address, the host — so
you can see which account you wired it to without opening it.

| Channel | Notes |
|---|---|
| **ntfy** | Least work by far: pick an unguessable topic, install the app, subscribe. No account, no signup |
| **Discord** | A webhook URL, plus your own user ID if you want it to ping you — see below |
| **Email** | SMTP. The most configuration, and works everywhere. Almost certainly needs an *app password*, not your normal one |
| **Webhook** | POSTs JSON — event, title, body, hostname — for Home Assistant, n8n, anything |

Each has a **Save and send a test** button, which saves what is on screen before it
sends, so you are testing what you just typed.

One channel is enough. Setting up two is only worth it if you want a copy of everything
somewhere permanent as well as a notification on your phone.

**The one worth having on:** *The MakeMKV key is about to expire*. A lapsed key is the
usual way a working setup quietly stops working, and it always happens while you are not
looking at the web page.

*A new version of Riparr is available* is on by default too, and is quiet by nature —
each version is announced once, so it amounts to a handful of messages a year. It is
sent at a lower priority than the rest, because nothing is broken.

### Discord, if you want Riparr to tell *you*

A Discord webhook posts into a **channel**, which is a thing you find later. What
makes a phone buzz is being **mentioned**. Riparr does both, and they are separate
settings.

1. **Somewhere to post.** In Discord, **+** at the bottom of the server list →
   **Create My Own** → **For me and my friends**. Nobody else can see it, and a channel
   in it is a private feed your phone treats like any other.
2. **The webhook.** Hover the channel → the gear (**Edit Channel**) → **Integrations**
   → **Create Webhook** → **Copy Webhook URL**. *That URL is a password* — anyone
   holding it can post as Riparr.
3. **Check it.** Press **Check this webhook**. Riparr asks Discord whether it is real
   and tells you what it posts as. A URL that lost its tail in a clipboard otherwise
   fails silently forever.
4. **Mention me.** Turn on **Developer Mode** (User Settings → Advanced), right-click
   your own name → **Copy User ID**, paste it in. For a household, use a *role* ID with
   an `&` in front: `&123…`.

**Ping me for** is deliberately not the same list as **Tell me when**. Everything you
enable above still posts to the channel; only these light up your phone. *A rip
finished* is off by default because it is good news, and good news can wait.

## History

Every attempt, newest first — one row per try, not one per film. If a disc took five
goes, all five are here with what went wrong each time.

| Column | Notes |
|---|---|
| **Attempt** | "try 3 of 5" — the other four are rows you can read |
| **Size** | What actually landed |
| **Took** | Work done, not wall clock: retrying a job a day later does not make it a day long |
| **Where the time went** | The five stages, to scale. The typical bar underneath is the key |

**Where the time went** is the interesting column. Much of a rip can happen before a
single byte is written — MakeMKV decrypts in software, which is CPU work — so a rip that
looks idle for a while is working hard, and this is where you can see that.

### The four retries

Each one appears only when Riparr can actually do it.

| Button | When it shows | What it costs |
|---|---|---|
| **Retry upload** | The rip is still in staging | A re-copy. Minutes, and the disc stays on the shelf |
| **Retry fast verification** | The file is on your library | Seconds. Compares the size — catches a truncated transfer |
| **Retry deep verification** | The file is on your library | As long as the upload took, plus as much free space again as the film. Reads it all back and hashes it |
| **Retry rip** | The rip is gone or never finished | The whole thing. Put the disc back in the tray first |

## Discs

Every disc Riparr has seen, by fingerprint, with its poster.

| Action | Effect |
|---|---|
| **Re-rip** | Rips it again, duplicate flag and all. Leave the disc on the tray — Riparr pulls the tray in itself |
| **Forget** | Drops Riparr's memory of the disc entirely, including any correction you made |

This is what makes Riparr only ask you about a problem disc once, ever. A tile with a
warning triangle is a disc Riparr has seen but never finished a verified rip of.

**Put an already-ripped disc back in** and this page is where you land, with the film
highlighted and the date it went into your library. See
[Ripping discs](06-ripping-discs.md#putting-a-disc-back-in-that-youve-already-ripped) for
what Riparr does when no browser is open — including why the drive's front light can be
blinked but never switched on.

### Already-ripped discs

On **Settings → Ripping**.

| Setting | Notes |
|---|---|
| **Tell me with** | `The drive's own light` (default), `The tray`, `Both`, or `Nothing — just eject` |
| **Try the light** / **Try the tray** | Fires the signal now, with whatever disc is in the tray. Riparr cannot see the result, so watching it is the only test |

## System

| Setting | Notes |
|---|---|
| **Export settings** | Downloads a JSON file. **Do this once you're set up.** Starting again from an empty `/data` volume becomes a 30-second job. |
| **Import settings** | Restore from that file |
| **Change password** | Web interface login. Forgotten it? See [I forgot my password](08-troubleshooting.md#i-forgot-my-password) — nothing else is lost |
| **Update** | Checks for a new version. See [Updates](#updates) below |
| **Logs** | Download a log bundle for bug reports. `docker logs riparr` has the rest |
| **Restart / stop** | Not in the web UI. Use `docker restart riparr`, or `docker compose down` to stop it |

### Updates

Riparr checks the GitHub releases of `ziggy46/riparr-server` every six hours and **tells
you when it finds one — once per version, not every six hours.** It does not install
anything itself.

To update:

```
docker compose pull && docker compose up -d
```

Your settings, shares and history are in the `/data` volume and carry over.

| Setting | Notes |
|---|---|
| **Check for updates automatically** | On by default. Turning it off stops the checking *and* the notification — nothing else changes, and **System → Updates** still checks whenever you go looking |
| *A new version of Riparr is available* | A notification event like any other, on by default, and it can be turned off on its own under Notifications if you would rather find updates yourself |

> **Updating is always your call.** Riparr only tells you a new version exists. Nothing
> is replaced until you pull and rebuild, so it never changes underneath you halfway
> through a disc.

---

[← Ripping discs](06-ripping-discs.md) · [Guide index](README.md) · [Next: Troubleshooting →](08-troubleshooting.md)
