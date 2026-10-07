# Changelog

What changed, in the order it changed, in terms of what you'd actually notice.

The section for each version is pulled straight into that version's release notes, so
this file is the release notes. Write it for somebody who wants to know whether to
bother updating.

If updating to a release takes more than `docker compose pull && docker compose up -d`,
put the command in that release's notes on GitHub, on a line of its own:
`<!-- riparr-update: the command -->`. From 0.6.0 on, Riparr shows that instead of its
built-in instruction, on System → Updates and in the update notification. GitHub
doesn't display the line.

---

## 0.8.0

**Fixed: a rip could sit on "Reading the disc" forever.** A Linux-only MakeMKV bug can
hang it at 100% CPU the first time it meets a drive, while fetching that drive's data,
before it reads anything. Riparr now checks for this before MakeMKV's first run on a drive
and, if it hangs, tells MakeMKV to skip that step for the drive (its `sdf_Stop` setting).
DVDs and Blu-rays rip as usual; only 4K LibreDrive features are affected, and System →
Status says when it's in effect. Riparr also addresses drives by their device path
(`/dev/sr0`) rather than MakeMKV's own numbering, and caps the container's open-files
limit, which can cause a similar hang on some Docker hosts.

**See what MakeMKV is doing.** The rip card has a "What MakeMKV is doing" panel with its
latest messages, Disc info shows a scan's progress and how long it's been going, and
MakeMKV's messages go into Riparr's log. A step that sits still no longer looks like
a frozen page.

**Library problems are named.** Instead of "not mounted" for everything, Library and
the rip options say what's actually wrong: nothing mounted there, or mounted but not
writable by the user Riparr runs as (with the owner and the fix).

**A new layout.** The Queue shows the disc being ripped as one large card, phones get
tabs at the bottom, History is grouped by disc, and Settings are shorter. It replaces the
old *arr-style layout; there's no switch back.
- **Queue** shows the disc being ripped as one large card: poster, title, one bar, the
  finish time, and Disc info and Eject on the card. Auto Rip and the rip options move
  to a footer.
- **Phones** get tabs at the bottom (Queue, History, Discs, More) instead of the menu
  button in the top corner. More opens Settings and System, and shows a dot when
  something needs attention.
- **History** shows one line per disc, with how its latest rip went, and every attempt
  underneath when you open it. Old failures of a disc that has since ripped fine no
  longer offer a retry.
- **The disc keeps one shape.** Ripping, finished and already-ripped all use the same
  big card with the poster, with Disc info and Eject on every one. The rip card shows one
  phase line, one bar and one finish time, with a Cancel button. A finished rip shows the
  folder it went to, with the full path a tap away. A failed one has its Retry button
  right there.
- **Settings** keep every control visible and fold the explanations to one line, and the
  Save bar only appears once you've changed something.
- On phones, More opens a sheet from the bottom holding just Settings and System. It
  takes keyboard focus, keeps it until closed, closes with Escape, and can't be reached
  with Tab while it's closed.
- **One progress bar for the whole rip**, from reading the disc to filed, paced by how
  long each step usually takes on your machine, with ticks where steps change and
  "step 3 of 5" beside it. It no longer runs to 100% and starts again for the upload.
- The rip card is laid out like the finished card: a "Ripping" heading, the title with
  its disc type, and the folder it will go to. The "which film is this?" question and
  the empty tray use the same card, each with one row of buttons. Eject comes first and
  Cancel last.
- Screen readers hear "The Matrix (1999) is in your library" when a rip finishes, the
  bar is a real progress bar, focus stays put after Dismiss and Discard, and each
  "More" says what it expands.
- **When Riparr needs you**, the "which film is this?" question uses the same card:
  "Needs you", the film's name, the question, TMDb's suggestions to pick from (typing a
  name is under "Not listed?"), and a full-size Rip it. Eject waits until you've
  answered. From any page, even in a background tab, the browser tab says "(1) Needs
  you", the Queue tab gets a dot, and screen readers hear it.
- With setup unfinished, the Queue card says "Not ready" and lists what's missing, each
  with a Fix link, instead of "Ready" -- with or without a disc in. A disc can't be
  started while something blocks the rip.
- The rip card names each step once, with the same words as History, and puts the
  step's own numbers on one labelled line ("This step: 2.4 GB of 7.8 GB · 3m of a usual
  25m"). "Finishing up" only appears when the whole rip is under a minute from done. It refreshes every second or
  so while ripping. A failed rip is red; a question is amber.
- The drive's details (model, device, what it reads) moved into **Disc info**; the card
  shows them only when there's no disc.
- On phones every button, toggle and "More" link is at least 44px tall.
- **History** answers "is it in my library?" first ("In your library · last attempt
  cancelled"), shows the path once, offers retries only for attempts since the last
  good rip, and folds long runs of successful rips. Cancelled rips are counted
  apart from failed ones and aren't shown in red. Pressing Cancel twice no longer shows
  an error.

**TMDb for TV.** With a TMDb key, season discs look the show up on TMDb as well as films:
the episode names, plus the show's TMDb, TVDB and IMDb IDs. Without a key, TVmaze is used
as before. **Settings → Ripping → Episode names from** can pin it to one. A box set
started under one keeps its episode numbering under the other.

**TRaSH Guides presets for TV.** The episode template has TRaSH's Sonarr schemes for
Standard, Plex, Emby and Jellyfin. The Plex, Emby and Jellyfin ones put the TVDB ID on
the series folder, for example `Breaking Bad (2008) {tvdb-81189}/Season 01/…`. There's
a new `{TvdbId}` token.

**Riparr asks when it isn't sure which show.** A label like `THE_OFFICE_S2D1` matches
the US (2005), UK (2001) and other versions. Riparr now only picks a show by itself when
one clearly matches: your earlier pick for that box set, the only show with that name,
or one far better known than the rest. Otherwise the disc stops and asks, even if it
isn't the first disc of the season, and the list shows each show's year and country.
Under "Never — just rip it" it carries on with its best guess and says so on the job.

**"Series 1" labels.** British box sets label seasons "Series 1"; that's now read as
season 1, so `SHERLOCK_SERIES_1` is *Sherlock*, season 1.

## 0.7.1

**A calmer rip.**
- The card shows one progress bar and one percentage. Its finish time and the stage
  line underneath always agree: both say "finishing up" for the last minute, and
  "taking longer than usual" when a stage runs well over.
- Stages are named for how the rip is travelling: a staged rip says "Saving to
  staging", not "Writing to your library".
- The raw "burst" badge is gone.
- The finished card shows Rip, Upload and Check ticked off.

**Clearer status.**
- Auto Rip says what it needs ("Needs a working MakeMKV key and a tested share first").
- The header warning names the key ("MakeMKV key: No key entered"), and its tooltip
  lists the actual problems.
- The phone menu dot turns red for a blocking problem.

**The queue leads with the disc on desktop too**, with Auto Rip and the rip options
below it.

**Less to read.**
- Settings help shows one line, with **More** for the rest.
- On History, a rip that worked keeps its checks under a **⋯** button instead of two
  buttons on every row.
- Release notes on System → Updates are formatted instead of raw text.
- Library explains the mount once instead of twice.

**One name for each thing.** The checks after a rip are the **size check** and the
**full check** everywhere. The old "always burst" and "always stream" transfer modes are
gone from Settings, since both meant "staged first, then sent". A setup already using
one keeps it.

**Smaller fixes.**
- Undo says what it undoes ("Forgot The Matrix (1999)"), and doesn't run out while
  you're pointing at it.
- History calls a repeat of a disc that already worked a "re-rip".
- The setup wizard's last step says what you skipped.
- Header buttons fit on one line.

## 0.7.0

**Films are looked up on TMDb.** Add a free key from themoviedb.org on Settings → Library
and Riparr finds each film's real title and year, its TMDb and IMDb IDs, and its poster.
`BLADE_RUNNER` becomes `Blade Runner (1982)`. A match is only used when it's clear-cut;
when it isn't, Riparr either keeps the name it had or asks you, with TMDb's suggestions to
pick from — your choice.

**Naming presets, based on TRaSH Guides'.** Settings → Library has a preset list for each
template, with TRaSH Guides' Radarr schemes for Standard, Plex, Emby and Jellyfin
(trimmed to what a disc rip can fill), and a live preview. Templates understand Radarr's
syntax, and new tokens fill in from the disc: quality (`Remux-2160p`), video and audio
codecs, channels, bit depth, audio languages, and the TMDb and IMDb IDs.

**See what Riparr will do before it does it.** A rip on the queue shows the path it will
be saved as, so a wrong name or preset is caught before a long rip. **Disc info** on the
queue shows every title MakeMKV found, with its streams and what Riparr makes of them,
and copies it as text for a bug report.

**A live log.** System → Log Files shows the log as it's written, with debug lines on
request, pause and clear. **Diagnostics** downloads one zip of the logs, recent events,
the last MakeMKV scan and your settings, with passwords, tokens and keys removed.

**Works on a phone.** Every page fits a phone's screen: the queue puts the disc and the
rip first, the menu closes when you tap outside it, wide tables scroll inside their own
box, and text fields no longer make iPhones zoom in. "Add to Home Screen" opens Riparr as
an app of its own.

**Adding a share works the same everywhere.** Settings → Library → Add a share now has the
setup wizard's flow: scan your network, pick the server, list its shares and pick one,
then test and save. "List shares" now says how many it found and shows them as buttons,
instead of hiding them in the field.

**A finished rip stays on the queue.** When a rip is done, the queue shows the film with
its poster, where it was saved, its size, how long it took and whether the check passed,
until the next disc goes in. A failed rip shows why, with a link to History.

**The queue is easier to use.**
- A disc you've already ripped says so as soon as it's in the tray, with **Rip it again**,
  instead of a Rip button that would only refuse it.
- The transfer and check settings are folded into one **Rip options** line, which says
  what will really happen. For example, it says "staged" when the library isn't mounted.
- The page no longer refreshes under you while you're using a dropdown, and keeps your
  place when it does refresh.
- **Search** works: it finds a disc on Discs and History.

**Settings pages.**
- Save sits at the bottom of the window and says when you have unsaved changes.
- Leaving with unsaved changes asks first, and **Discard** puts the page back.
- Long explanations fold to two lines with **More**.

**Accessibility.**
- Primary buttons are darker, so their text is readable.
- Errors stay on screen until you dismiss them, and messages are announced to screen
  readers.
- The Auto Rip switch, the menus and the queue's controls are named for screen readers.
- Everything you can reach with the keyboard shows a focus outline.

**A second round from the UI review.**
- **Phones:** the page no longer scrolls sideways. A header warning ("Newer key
  published", "No share") pushed the header wider than the screen. The header now shows
  one warning at most, hidden on phones, where the menu button gets a dot instead. The
  menu button is bigger, the drive line no longer covers the tray's buttons, and pages
  open at the top.
- **One answer to "is something wrong":** the Auto Rip checklist moved to System →
  Status, where Health lists every check with a **Fix** button. The queue, the System
  badge and the header warning all count the same list.
- **Undo:** forgetting a disc or removing a share can be undone for a few seconds.
- **The queue:** a rip stays on the card while it uploads instead of flicking back to
  the tray, and clicking quickly between pages no longer leaves the wrong page showing.
- **Smaller fixes:**
  - History and Discs show the year.
  - Search only filters Discs and History; press Enter elsewhere to open Discs.
  - System → Updates no longer calls an older release "Latest".
  - Error messages stay clear of the Save bar.
  - Setup has a Back button and no longer pre-fills "admin".
  - Setup reports a MakeMKV key it couldn't save.

**Which build you're on.** The version in the sidebar, on System → Status and on System
→ Updates now says **latest** (a release) or **edge** (the newest code on main, with the
commit it was built from).

**Better TMDb matches from disc labels.**
- `HEAT` finds *Heat* (1995), not *The Heat*.
- Edition words are ignored: `ALIEN_DIRECTORS_CUT` finds *Alien*.
- A year without brackets counts as the year: `DUNE_2021` finds *Dune* (2021).
- Titles that end in a year, like *Wonder Woman 1984* and *Blade Runner 2049*, still
  find the right film.

**Fixed:** a re-rip could lose the film's year and TMDb match, so `Dune (2021)` was saved
again as `Dune/Dune.mkv`. A disc now remembers both.

## 0.6.0

**Coming from 0.5.1?** Its update message says `git pull && docker compose up -d --build`;
don't use that as-is. Your edited `docker-compose.yml` stops `git pull`, and the licence
setting has moved. Run `git stash && git pull` (or download the new
`docker-compose.yml`), set `MAKEMKV_ACCEPT_EULA: "yes"`, `PUID` and `PGID` under
`environment:`, then `docker compose pull && docker compose up -d`. Keep your `data`
folder. The first start compiles MakeMKV and changes the owner of `data` and `staging`.

**A ready-made image.** `ghcr.io/ziggy46/riparr-server`, for amd64 and arm64. No more
building it yourself: download `docker-compose.yml` and `docker compose up -d`.

**MakeMKV compiles on the first start**, into your `data` folder, once
`MAKEMKV_ACCEPT_EULA` is `"yes"` in the container's environment. It's no longer in the
image, because MakeMKV's licence has to be accepted by whoever runs it. Later starts take
seconds. libdvdcss is compiled the same way.

**Optical drives are found on their own.** The compose file now allows optical drives as
a class (`device_cgroup_rules`) instead of naming device nodes, and the container makes
the nodes itself. No more looking up `/dev/sg` numbers, and a USB drive can be unplugged
and replugged without restarting the container. `devices:` still works if you prefer it.

**Files belong to you.** Riparr runs as `PUID`/`PGID` (default 1000) instead of root, so
the database, staged rips and anything in a bind-mounted library are owned by your user.
`UMASK` sets their permissions.

**The share scan can see your LAN.** From inside Docker the setup wizard was scanning
Docker's own network and finding nothing. Type your network into the new box under the
scan (e.g. `192.168.1.0/24`), or set `RIPARR_SCAN_SUBNETS`.

## 0.5.1 — Riparr Server, first release

**Runs in Docker.** `docker compose up -d --build` builds an image with MakeMKV, dvdbackup
and libdvdcss compiled in. Pass the drive's `/dev/sr*` and `/dev/sg*` through and open
port 9797. See docs/guide/02-docker.md.

**Real hardware is any Linux.** Upstream decided it was on real hardware by looking for an
ARM board's device tree, so on an x86 server it would silently simulate a drive. Linux now
means real hardware; `RIPARR_MOCK=1` asks for simulation.

**Removed the appliance parts:** the Preparer and SD card flashing, Wi-Fi management and
connection recovery, the status LED, restart and shut down, the USB-C socket fix, the
systemd helper units, installing MakeMKV from the web page, and the in-place updater.
System → Updates still checks for new releases, of this fork.

**Smaller changes.** Wording about "the card" is now about staging. The password reset file
goes in the `/data` volume. `RIPARR_STAGING` sets the staging path, and `RIPARR_API_DOCS=1`
turns the API docs on.

## 0.5.0

**Full disc backups.** Settings → Ripping → Titles → **Full disc backup** keeps the whole
disc instead of one MKV: the `VIDEO_TS` or `BDMV` folder with the menus, extras and every
audio track, decrypted. It lands in your Movies folder where the film would have gone.
Jellyfin and Kodi play it as a disc, and you can make an ISO from it later. Blu-rays and
4K discs go through MakeMKV. DVDs use dvdbackup, which installs itself on the box a few
minutes after this update. Until it has, DVDs rip as MKV and the job tells you so.

**Raspberry Pi 3, 4 and 5.** The Preparer's board list now has the Pi 3 Model A+, 3
Model B, 3 Model B+, 4 / 400 and 5. They won't fit the printed case, but the card setup
is the same as every other board. All marked beta.

**Raspberry Pi cards set themselves up again.** Current Raspberry Pi OS stopped reading
the settings file the Preparer wrote, so a Pi card booted with no Wi-Fi and no login.
The Preparer now writes the files Raspberry Pi OS actually reads. That fixes the Zero 2 W
too.

**The Wi-Fi list matches your board.** On a 2.4 GHz-only board (the Pi Zero 2 W and the
Pi 3 Model B) the Preparer greys out networks its radio can't see.

**Staged rips keep their year.** A film you named with a year, like "Spirited Away
(2001)", lost the year if it was ripped to the card first and sent to your library later.

One thing to know on a Raspberry Pi: adding extra Wi-Fi networks from Settings → Network
isn't supported there yet. The network you set up with keeps working.

## 0.4.5

**The Linux Preparer works.** Before this, it closed the moment you opened it. It now
writes the card, finds the box and installs Riparr, the same as on a Mac or PC. It uses
the GTK and WebKit your desktop already has.

**Linux on ARM gets its own download**, for Raspberry Pi desktops and ARM laptops.

**Cards written on newer Ubuntu boot.** Ubuntu 25.10 and later ship a `dd` that can
write a damaged card while reporting success. The Preparer writes the card itself now,
and its read-back check reads the card rather than a copy in memory.

**Setup finds the box faster on busy networks.** If your box doesn't answer to its
name, setup goes looking for it by address. On a network with lots of devices that
search could run out of time before reaching the box. It's quicker now, and it tries
the address the box was last seen at first.

**Your SD card reader shows up on Linux** even when Linux doesn't report it as
removable hardware.

---

## 0.4.4

**The Preparer works on Windows, start to finish.** It writes the Orange Pi card, finds
the box on your network and installs Riparr on it, the same as on a Mac. Windows will
warn you that the app isn't commonly downloaded and that its publisher is unknown. It's
unsigned; choose Keep, then Yes.

**No more hanging at 100%.** After checking a freshly written card, the Preparer could
sit on "Checking the card" forever even though the card was done. That happened on Macs
too. It now moves straight on to the next step.

**Fresh installs start properly.** A new box could fail its first start with a
"readonly database" error. It doesn't any more.

**The window fits the screen on Windows**, at any display scaling, and the wording talks
about your PC rather than a Mac.

---

## 0.4.3

**The Windows Preparer can put MakeMKV on the card.** With the MakeMKV download in your
build folder, writing a card on Windows failed unless you were an administrator or had
Developer Mode on. It now works for everyone.

---

## 0.4.2

**Riparr reads the key from makemkv.com itself.** While GuinpinSoft isn't selling
licences, its purchase page publishes the current beta key, and that is now the first
place Riparr looks. It is their own site and it answers in about a second. The backup
key service is asked alongside it for the expiry date and as a second opinion, and the
forum, which can take minutes, only when those two don't settle it. Riparr renews a key
by itself only when makemkv.com or its forum stands behind it.

**No Buy button when there's nothing to buy.** When makemkv.com isn't selling licences,
the renewal message says so, and that their site asks everyone to use the free key for
now. When sales reopen, the Buy button comes back.

**No more false "The install stopped unexpectedly".** Installing or upgrading MakeMKV
could show that for a moment while it was working fine, and the page stopped following
the build. It no longer does.

---

## 0.4.1

**The MakeMKV key renews itself.** The free beta key runs out at the end of every month,
and until now a box stopped reading discs until somebody pasted in the new one. Riparr
now checks every six hours and, when GuinpinSoft publishes the next key, puts it in for
you. It only ever swaps a beta key for a beta key: a bought key is never touched, and if
the forum and the backup source disagree about the new key, nothing changes. You can
turn this off in **Settings → General**.

The next time you open the web page after a renewal, Riparr tells you once, along with a
link to buy MakeMKV. Riparr reads discs because of MakeMKV, and buying a licence is how
the people who make it get paid. A bought key also never runs out. Dismiss the message
and it stays away until the next renewal.

**MakeMKV 2.0.0, and a way to upgrade to it.** New boxes install 2.0.0. A box that
already has an older MakeMKV shows **MakeMKV 2.0.0 is available** under
**System → Updates** and **Settings → General**, with one button to upgrade. The build
runs on the box and takes about half an hour. The version you have keeps working until
the new one has finished building, and a disc going in while it builds is asked to wait.

**Installing MakeMKV from the web page works on every box.** It used to work only if the
Preparer had put the MakeMKV download on the card. Without it, the box had nothing to
download and gave up.

**The Preparer only copies the MakeMKV version the box will install.** An older download
in your build folder is left off the card instead of being copied and ignored. When it
finds a box that is already running, it also says if that box's MakeMKV or key is out of
date.

---

## 0.4.0

**TV box sets work.** Put a season disc in and Riparr rips every episode on it, in
order, numbered and named — instead of ripping one file and quietly discarding the rest,
which is what it did before.

Six titles of about the same length is a season disc, not a film with five decoys.
Riparr finds the episodes, throws out the "play all" title and the duplicate playlists
most discs carry, and works out what order the episodes go in.

**The order comes from the disc.** Most Blu-ray season discs carry a hidden "play all"
playlist, and it is the disc's own record of what order its episodes go in — so when
it's there, the order is a fact, not a guess, and Riparr gets it right without asking.
When it isn't there, Riparr falls back to the disc's playlist numbering and shows you
the plan before it rips anything.

**Episode names come from [TVmaze](https://www.tvmaze.com)**, which needs no account and
no API key.

**Disc order and broadcast order don't always agree,** and Riparr always keeps the
disc's. Firefly is the famous case — the disc opens with "Serenity", which aired second.
Riparr takes the sequence from the disc and only the names from the lookup, so you see
the disagreement on the plan, before anything is written, rather than a year later.
Changing **first episode** renumbers and renames the whole disc in one move.

**Correct the first disc of a season and the rest follow.** Riparr shows you the plan
once per season, on the first disc; disc two carries on from where disc one stopped with
nothing to answer.

The episode plan is a table, one row per file that will be written. Untick a duplicate,
move an episode with the arrows, type over a name, change where the numbering starts —
the numbers update as you go, so what's on screen is what will be written.

New settings under **Settings → Ripping → Television**: whether to look for season discs
at all, when to stop and show you the plan (the default asks only when Riparr isn't
sure), whether to look up episode names, and where specials go.

**The naming templates fill `{Season:00}`, `{Episode:00}` and `{EpisodeTitle}`,** which
the settings page has listed as "not yet" since the first release. A double-length
premiere or finale becomes `S01E01-E02` on its own, which is what Plex and Jellyfin read
as one file holding two episodes.

**Two things a season disc can do that Riparr still can't.** A season welded into a
single four-hour title gets ripped as one file — Riparr says so, but splitting it needs
MKVToolNix on another machine. And nothing here reads production or DVD ordering; the
disc's own order is what you get, which is usually what you want from a disc.

---

## 0.3.9

**A 3D Blu-ray no longer rips the 3D version by mistake.** A 3D disc carries both cuts
of the film at exactly the same length, and Riparr picked the longest title — so it
picked the 3D one, which is roughly twice the size and which most players will not use.
It now takes the smaller of two titles that are the same length, which is the 2D cut.
**Settings → Ripping → On a disc with a 3D version** switches it back if you want 3D.

**Riparr stops less.** "When a disc can't be identified" was one setting doing two
jobs — what to call the film, *and* which title on the disc is the film. So a 3D disc
stopped the queue and asked, saying the studio was probably hiding the real title,
which was not what was happening.

They are two settings now:

- **Ripping → When Riparr can't tell which title is the film.** New, and it defaults to
  **use the most likely one** rather than asking. Riparr remembers what you pick for a
  disc, so a wrong guess costs one correction, not one per disc.
- **Naming → When a disc can't be identified.** Now only about the name, and it now
  defaults to **use the disc label**. Most rips land somewhere that gets tidied later
  rather than straight into a library, and a folder you rename in ten seconds beats a
  queue that stopped overnight waiting for you.

**Both defaults only apply to a box that never set them.** If you have been through
setup, your existing choices stand — change them on those two pages if you want the new
behaviour.

**And when it does ask, it says which thing is unclear** — whether it can't name the
disc, or can't tell which title is the film, and whether the two titles it is looking at
are a 2D/3D pair rather than a studio hiding something.

---

## 0.3.8

**The page now waits for the box and reloads itself after an update.** It used to hand
back "Riparr is restarting" and then sit there showing the old version number, so the
only way to see whether it had worked was to reload by hand — which looks exactly like
the bug where it genuinely hadn't.

It covers the page while the box is away and comes back on the new version by itself.
A service restart is about two seconds and a whole-box restart about a minute, and it
now waits the right amount for each rather than always assuming the slow one.

**Also fixes the "restart it yourself" button never appearing.** On a box that can't
restart itself, the update is finished and one restart away — that case had a button and
the button was wired into the wrong place on the page, so nobody ever saw it.

---

## 0.3.7

**The Wi-Fi recovery is yours to tune now.** It was fixed at three minutes, which is a
guess about your network rather than a fact about it. **Settings → Network → If the
connection drops** has a switch, a number of minutes, and a separate switch for whether
Riparr may restart the box as a last resort.

Everything follows from the one number: it reconnects at **N** minutes, reloads the
Wi-Fi driver at **2N**, and restarts the box at **4N**.

**Shorten it if your access point changes channel often.** On 5 GHz the higher channels
are shared with radar, and an access point on one has to move when it detects any —
this board's Wi-Fi driver does not reliably follow, which leaves the box sitting on a
channel nothing is using. **Lengthen it if your router reboots on a schedule**, or the
box will spend its time recovering from outages that were going to end by themselves.

Changes apply within the minute; nothing needs restarting. And a restart still never
interrupts a rip — it waits for the disc.

---

## 0.3.6

**Fixes an update that failed with "Could not install packages due to an OSError".**
Nothing was wrong with the box, the virtualenv or the download — the update was being
run from a directory that no longer existed.

Riparr runs from `/opt/riparr/server`, and installing an update *moves* that directory
aside before putting the new one in place. A running program follows the directory it is
standing in, so Riparr ended up inside the backup copy — and the next update deleted that
backup, leaving it standing nowhere. Everything it then tried to run failed instantly,
including `pip`, so the update rolled itself back.

It now steps somewhere stable before it starts, which also protects rips: `makemkvcon`
would have failed the same way in the same window.

**If you already have a box in this state**, restart Riparr once from the account menu
before updating — that puts it back on solid ground. This release then prevents it
recurring.

This only bit boxes where the previous bug (0.3.5) stopped updates restarting, because
that is what left the old program running long enough to have its floor removed twice.

---

## 0.3.5

**In-place updates from the web page actually restart now.** They have been swapping the
code correctly and then not restarting, so the box kept serving the old version and the
page kept showing the old version number. The message said *"Riparr is restarting"* and
nothing was restarting.

The cause: Riparr runs as an unprivileged account and cannot restart itself — both
`systemctl restart` and `systemd-run` come back *Access denied*. The updater tried those
two and fell back to a backgrounded shell, which **exits 0 whether or not the command
inside it works**, with the refusal sent to `/dev/null`. So it always looked like it had
succeeded. Three updates in a row failed this way with three successes in the log.

Restarting now goes through a privileged request, like every other thing Riparr needs
root for. If that isn't installed yet it restarts the whole box instead, which works on
every box. And if neither is possible it **says so** and gives you a Restart button,
rather than claiming a restart it never arranged.

Nothing was ever lost to this. The new version was always correctly on the box — it just
wasn't running yet, and the next restart would have picked it up.

---

## 0.3.4

**System → Tasks now checks itself.** Riparr is two halves: the application, which
updates itself, and a set of systemd units and root-side scripts that mount your share,
recover the Wi-Fi and let the web page ask for privileged things. Riparr cannot update
that second half on its own — it runs unprivileged and cannot write a system file — so
until now the two could drift apart with nothing anywhere saying so.

That is not hypothetical. `riparr-library.service` had never been installed by any
installer, on any box, so no share was mounted at boot — and the only symptom was a
perfectly good share reported as permanently lost, which looks like a network fault and
sends you to re-enter credentials that were never wrong.

There's a **System components** panel at the top of the Tasks page now. It lists any
part that is missing or out of date, says what each one does in plain terms, and has a
button that installs them. No terminal.

**The one case the button can't fix, and why.** If the part that installs the other
parts is itself missing, it cannot install itself — that's the security model, not an
oversight: Riparr runs as an unprivileged account with no sudo, and every privileged
action goes through a fixed, root-owned script it cannot modify. Weakening that would
mean a web service that can run anything as root. On such a box the panel says so and
points you at the fix, which is **"Update it in place" in the Riparr Preparer** on your
computer — a button in the app you already have, not an SSH session. It keeps your
settings, shares and history.

Boxes set up with 0.3.4 or later never hit that case.

---

## 0.3.3

**Your share can be reconnected from the page now.** If the NAS slept, the router
rebooted, or a cable moved, a configured share went to "not mounted" and stayed there —
and the only way back the interface offered was deleting the share and typing its
password in again, to fix something that was never wrong with it. There's a
**Reconnect** button on the Library page and next to the warning on the Queue page. It
takes about a second.

**And the underlying reason it dropped is fixed.** The unit that mounts your shares at
boot, `riparr-library.service`, existed but *nothing had ever installed it* — on the
reference box `/srv/library` did not exist at all. So shares were mounted only by
whatever had mounted them last, and never came back after a reboot. They mount at boot
now, and after every update.

**The Wi-Fi can die without telling anyone, and now the box notices.** On the reference
unit the radio stopped passing traffic and stayed that way for 17.5 hours. The box was
never down — it logged an unbroken hourly heartbeat the whole time — but nothing could
reach it. The kernel logged nothing about the radio in a seven-day boot, and
systemd-networkd logged nothing either: the driver leaves the link looking connected
when its firmware wedges, so there is no event to react to.

There's now a watchdog that pings your router once a minute. If nothing answers it
re-associates after 3 minutes, reloads the Wi-Fi driver after 5, and reboots after 10.
**It will not reboot during a rip** — it waits for the disc to finish, because the box
is already unreachable and rebooting would additionally cost you the work in progress.

Wi-Fi power saving was already off, and wasn't the cause. If this keeps happening, check
whether your router has put the 5 GHz band on a **DFS channel** (100–140): a radar event
makes the access point change channel, and this board's Wi-Fi driver does not always
follow. Channels 36–48 or 149–165 avoid it.

**Rips now go straight to your library by default.** They used to land on the SD card
first and get sent afterwards. Writing to your share directly is about twice as fast on
this hardware (18 MB/s against the card's 9.4), there's no size ceiling — a 22 GB Blu-ray
never did fit on a 32 GB card — and the card stops having tens of gigabytes pushed
through it every disc.

Nothing to set up, and nothing to switch back. **If your library isn't connected when a
disc goes in, that rip stages on the card by itself** and is sent when the share
reappears. If you'd rather always stage — a NAS that sleeps, patchy Wi-Fi — *Each rip
goes → onto the card first* on the Queue page. If you'd already chosen a mode, yours is
kept. **So an 8 GB card is genuinely enough**, and a bigger one buys nothing unless you
want deep verification.

**Deep verification is no longer offered when rips go straight to your library.** It
works by reading the file back off the share and comparing it against the original, and
going direct leaves one copy rather than two — so it was hashing a file against itself
and reporting a success it hadn't earned. It's still there for staged rips. Choosing it
alongside direct rips now switches it to the size check and says so.

**Storage says the card isn't the limit** when rips go direct, instead of counting how
many Blu-rays fit on a card the films never touch. And a disc refused for space tells
you your share is away, rather than telling you to buy a bigger card.

**Updates from the web page now install system changes.** This is the one behind several
of the above. The in-app updater replaced Riparr itself but never touched systemd units
or the root-side helper scripts — so any release that added one shipped the file and
installed nothing, on every box that updated from the web page. A freshly written card
got it; an updated box didn't. That is why the mount unit was missing. There's one
definition now, used by both the installer and the updater.

**One-time step for existing boxes.** Yours predates the piece that applies system
changes, so this update will tell you to finish it by running the installer once over
SSH: `sudo bash /opt/riparr/tools/install.sh`. It keeps your database, settings and
shares, and it's what installs the mount unit, the Reconnect bridge and the watchdog.
From the next release onward this is automatic.

**Guide corrected.** It described a "Riparr Slim" and a "Riparr Full" — two products that
were never built — and quoted 30 W and 100 W supplies, both guesses. The measured unit
peaks at **18 W**, and what matters is voltage: the trigger board needs to ask your brick
for 15 V or 20 V, which USB-C only guarantees at **45 W and above**. 12 V isn't a standard
USB-C voltage at all. The parts are all named now, including the data-only SATA bridge
and the right-angle cable.

---

## 0.3.1

**Small SD cards work now.** The Preparer was reserving 8.5 GB for the system and calling
anything under about 12 GB "too small". The system actually uses 2.3 GB — measured on a
running box, where a 32 GB card has 26 GB free. **An 8 GB card runs Riparr fine.** Card
size only decides how much room there is to stage a rip, and if you set *Each rip goes →
straight to your library* it stops mattering at all.

**Guide rewritten** around building one: what it costs, what's inside, how it's wired,
then the walkthrough. The reference pages are still there, further down, for when
something surprises you.

**The macOS install instructions were wrong.** Right-click → Open hasn't been enough for a
while. You have to let it get refused, then approve it in System Settings → Privacy &
Security.

---

## 0.3.0

**One version number.** The box and the Preparer used to have separate versions, which
was confusing and caused three update failures in a row. They're the same number now.

**The Preparer tells you what it's about to do.** Point it at a box that's already
running and it now says which version is on there, which version it's going to install,
and that your login, settings, rip history and MakeMKV build all survive. Button reads
**Update to 0.3.0** instead of a vague "set it up".

**Check for updates without restarting the app.** There's a **now** button next to the
checkbox in the Preparer's sidebar. It answers even when there's nothing to install.

**Updating the box actually works.** The old updater couldn't replace itself and, worse,
could delete the box's Python environment while reporting that nothing had changed. A box
that hit that kept running but wouldn't have survived its next reboot. Fixed, and covered
by a test that runs on every build.

**Card writing works from the packaged app.** It never had — the app couldn't reach its
own card writer, and reported it as a permissions problem, which it wasn't.

**Wi-Fi bands show up.** The button that asks macOS for Location Services was there all
along and was being hidden. Remembered networks are folded away separately from the ones
actually in range, so you're not scrolling past thirty hotel networks.

**The "your card is ready" screen makes sense now.** What's done on the left, what you
need to do on the right, and the Continue button stays locked until the box actually
appears on the network — no more clicking it before you've plugged anything in.

**macOS will say your card is unreadable after writing it.** That's normal and it's now
said up front. Click **Ignore**. Never **Initialise**.

---

## 0.2.x

Groundwork, mostly invisible: self-update on both halves, the appliance payload shipped
inside the Preparer, MakeMKV fetched and verified at setup instead of by hand, and a
first pass at the Wi-Fi and update plumbing that 0.3.0 finished.

---

## 0.1.x

First public releases. Card writing, unattended setup over SSH, the web interface, Auto
Rip, library shares, notifications, and the LED.
