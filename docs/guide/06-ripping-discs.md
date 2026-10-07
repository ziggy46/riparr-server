# 6. Ripping Discs

[← Library layout](05-library-layout.md) · [Guide index](README.md) · [Next: Settings reference →](07-settings-reference.md)

Setup is done. You should not need to open the settings again.

---

## The whole thing

1. **Insert disc. Close tray.**
2. **Walk away.**
3. **Disc ejects** when it's finished.
4. **Insert the next one.**

That's it. No button, no clicking, no app.

## How long it takes

It depends almost entirely on your drive and your server's CPU. Blu-ray takes much longer
than DVD, and 4K UHD longer again.

**Much of that time is spent before anything is written.** Commercial discs are
encrypted, and they are unscrambled in software — that is CPU work. Reading and
unscrambling usually takes far longer than writing the film out or sending it to your
library.

So during a rip the drive spins and for a while the progress bar has nothing honest to
show you — that stretch is real work, not a fault. Riparr shows a sweeping bar and a
running clock rather than a percentage it would have to invent.

### The five stages, and why two of them cannot show a percentage

| Stage | What is happening |
|---|---|
| **Reading the disc** | Cataloguing what is on it |
| **Decrypting** | Unscrambling, in software. **Nothing is written yet** |
| **Writing to your library** | The film comes off the disc onto your share |
| **Filing it in your library** | Moving it from the scratch folder into place |
| **Verifying** | Proving it arrived |

Those middle two are named for what is actually happening, so they read differently when
a rip is staged first: the film is saved to the staging folder, then uploaded — which
adds time, because the film gets written twice.

The first two have **no percentage available, and never will**. MakeMKV reports none
during the scan, and the reads go to the drive by a route the operating system cannot
see — so there is no file growing and no disk counter moving to measure. This was checked
rather than assumed.

What Riparr does instead is count. It knows how long **your** setup took the last few
times, so the queue shows the stage you are in, how long you have been in it, and
roughly when to come back. Until two rips have finished it says so plainly rather than
guessing. If a stage runs long it says *"3 min over the usual"* — never "0 min left".

**History** shows the same five stages for every finished rip, to scale, so you can see
where the time actually went.

## What the eject actually means

**The disc ejects when the file has landed in your library and been checked.** Eject means
done.

That is the whole rule.

> **[unresolved] — this is meant to become two rules.** The design (D11) has Riparr
> uploading as it rips and ejecting early when the rip is staged, so you can load the
> next disc while the last one is still travelling. That part is not built yet, so today
> the tray stays shut until the job is completely finished. When it lands, this section
> grows a second case: out of the drive, but still travelling.

## What it does when a disc won't fit

A staged rip is written to `/srv/staging` first, so a title has to fit there with room to
spare. If it doesn't, **Riparr says so before it starts** rather than failing partway
through. A 4K title is ~66 GB.

Going straight to your library has no such ceiling — nothing is staged.

The web UI shows how much room is left in **discs** — "Room for 2 Blu-rays, or 7
DVDs" — not gigabytes.

## What it does with a disc this drive can't read

Puts it straight back out, with the reason on the web page.

A DVD drive cannot read a Blu-ray, and **most Blu-ray drives cannot read a 4K UHD disc** —
4K needs one of a small number of specific drives, which is covered in
[what you need](01-what-you-need.md#which-drive). Riparr checks before it starts, so this
costs you ten seconds rather than forty minutes.

The Queue page tags your drive with what it reads — `DVD` `Blu-ray` `4K UHD` — and
**System → Status** says whether 4K will work on it, asking MakeMKV directly.

## Putting a disc back in that you've already ripped

Riparr recognises it and gives it straight back. It does not spend another half hour
finding out what you already know.

The one exception is a change of format. A disc you ripped to an MKV isn't a duplicate
once you've switched to **Full disc backup** — that's the reason you'd put it back in —
so it's ripped again as a backup.

**If a browser is open**, the page jumps to **Discs**, names the film and when it landed
in your library, and highlights it. The **Rip again** button is right there on the tile: if
you meant it — a bad rip, a changed setting, a better drive — press it. Leave the disc on
the open tray and Riparr pulls the tray back in for you.

**If nobody is looking at a browser**, Riparr has to say it with the drive. Two ways, on
**Settings → Ripping → Already-ripped discs**:

| | |
|---|---|
| **The drive's own light** *(default)* | Three short flashes, three times |
| **The tray** | Opens and closes twice — unmissable across a room |

A word on the light, because it is not what it looks like. **Nothing can switch an
optical drive's front light on.** There is no such command in any standard, and the
handful of manufacturer-specific ones are guesses that have no business running on your
drive. What that light reports is the drive *reading* — so Riparr reads the disc in a
rhythm, and the light follows. It works on every drive and it asks nothing of yours.

Riparr cannot see the result. **Try the light** and **Try the tray** on that settings
page fire the signal on demand with any disc in the tray, so you can watch it once and
decide which you prefer.

## Feeding it a stack

Load discs back to back — rip, eject, next. When rips are staged, there has to be room in
`/srv/staging` for the one you're putting in; the web UI shows how many more fit.

## More than one drive

Plug in a second drive and Riparr uses both: each rips its own disc, **at the same time**.
The Queue shows a card for each drive, with its own Rip, Eject and Disc info, and Auto
Rip picks up a disc in either tray. It's the quickest way through a box set.

The two share the staging folder. If a disc won't fit until the other drive's rip has
finished writing, it waits in its tray ("Waiting for room in staging") and starts on its
own when there's room. It's only refused if it wouldn't fit even then. Uploads to your
library still go one at a time.

In Docker, the compose file's `device_cgroup_rules` already allow every optical drive. If
you list devices yourself instead, list both nodes (`/dev/srN` and its `/dev/sgN`) for
each drive.

## Audio CDs

Put a music CD in and Riparr rips it as an album, in FLAC, without MakeMKV:

1. **It works out which album it is.** A CD has no name on it, only where each track
   starts. That layout is enough for [MusicBrainz](https://musicbrainz.org) to recognise
   it, and MusicBrainz gives the artist, the album, the year it first came out and every
   track's title. The cover comes from the Cover Art Archive.
2. **It reads every track with cdparanoia**, the standard careful CD reader: it reads
   each part more than once and corrects what doesn't match. When it can't fully correct
   a scratch, the finished card says which tracks may have a click or a gap.
3. **It encodes each track to FLAC** while the next one is being read, tagged with the
   names and MusicBrainz IDs that Plex, Plexamp, Jellyfin and Picard read, with the cover
   inside each file.
4. **It files the album** under Settings → Library → Music:

       Music/Fleetwood Mac/Rumours (1977)/01 - Second Hand News.flac
                                          …
                                          cover.jpg

   The discs of a set share one album folder, numbered `1-01`, `1-02`… `2-01`, so the
   whole set sorts in order. An album with the same name that's actually a different
   album goes beside it as `Rumours (1977) (2)`.

**When MusicBrainz doesn't know the CD**, or knows several albums it could be, the card
says *Needs you*: pick one of its suggestions, search MusicBrainz by album and artist, or
type the names yourself. The notification has the suggestions as buttons, like a film's.
Riparr remembers your answer, and the CD is recognised as already ripped if it goes back
in.

A CD doesn't need a MakeMKV key. A data CD, with no music on it, is refused straight away.

## Reading the drive without a browser

The disc itself is the signal. It stays in while there's work to do and comes back out
when there isn't.

| The drive is | What that means |
|---|---|
| Tray shut, drive quiet | Idle, ready for a disc |
| Tray shut, drive working | Ripping |
| Tray shut, drive quiet, still busy on the page | Uploading to your library |
| Disc ejected | Done, or it gave up — the page says which |
| Disc ejected almost immediately | You've ripped this one before |

If you want to know without walking over, set up **notifications** — Discord or a webhook,
on **Settings → Notifications**. That's the honest answer when you are not sitting at the
web page: it tells you where you actually are.

## The web page

The web UI at `http://<server>:9797` shows what's in progress, what's queued, what's
waiting on you, and how much room is left — in **discs**, not gigabytes.

The Queue page is the landing page and it is one screen: the **Auto Rip** switch, then
either the queue or the tray. The tray is the disc currently loaded, the drive holding
it, and — if there is no drive — why not. **Refresh** and **Eject** are top right.

You don't need to watch it. It's there for when a disc comes back out sooner than you
expected and you want to know why.

## When something fails

**Bad disc.** Riparr retried and couldn't read it. Clean the disc, try again.
The web page says how far it got and where it failed. Nothing partial is left in your
library.

**Whatever went wrong, start at History.** Every attempt is a row with its own reason,
and each row offers only the retries that would actually help:

- **Retry upload** — the rip is still in staging, so this skips the disc entirely.
  Minutes, not half an hour. This is the one you want after a network hiccup.
- **Size check again** / **Full check** — the file reached your library but the check
  did not finish. Neither touches the disc. On a rip that worked, these are under the
  **⋯** button at the end of its row.
- **Retry rip** — the rip is gone. Put the disc back in the tray first.

If only *Retry rip* is offered, the staged copy has been cleaned up and the disc is the
only remaining source.

**Duplicate.** You've ripped this disc before. Ejected immediately rather
than spending hours doing it again. See above.

**Library unreachable.** NAS asleep, network down, credentials changed.
The rip is safe and paused. Fix the share and it picks up where it stopped.

**Nothing happened at all.** See [troubleshooting](08-troubleshooting.md).

## If the container stops mid-rip

Fine. Riparr expects it. An interrupted rip is detected the next time the container
starts and either resumes or is failed cleanly. You won't get a corrupt file in your
library.

---

[← Library layout](05-library-layout.md) · [Guide index](README.md) · [Next: Settings reference →](07-settings-reference.md)
