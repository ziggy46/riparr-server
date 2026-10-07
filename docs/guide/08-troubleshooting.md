# 8. Troubleshooting

[← Settings reference](07-settings-reference.md) · [Guide index](README.md)

Organized by **what you actually observed**.

---

## The web UI doesn't load

Riparr is at `http://<server>:9797` — your server's name or IP address, port 9797.

1. **Is the container running?** `docker ps` should list `riparr`. If it isn't there, or
   keeps restarting, read why with `docker logs riparr`. Without Docker:
   `systemctl status riparr`, and `journalctl -u riparr` for why.
2. **Is the port published?** `docker-compose.yml` maps `9797:9797`. If you changed the
   left-hand side, use that port instead.
3. **Is a firewall on the host blocking it?** Try from the server itself:
   `curl -I http://localhost:9797`. If that works and other machines can't reach it, it's
   the host firewall or the network, not Riparr.

## It isn't auto ripping

**Open System → Status and read the Health checklist.** (The queue says how many need
attention under the Auto Rip switch and links there.) It lists every prerequisite
whether or not it's met, so the row that isn't green is your answer:

| Row | Means |
|---|---|
| **Riparr can read discs** | MakeMKV has been compiled. Red means `MAKEMKV_ACCEPT_EULA` isn't `"yes"`, or the build failed — see [below](#riparr-cant-read-discs) |
| **The MakeMKV key is current** | There's a key and it hasn't lapsed. Amber means it lapses within a week — rips fail the day it does |
| **A drive to read them in** | An optical drive is visible inside the container. A working drive shows up here even with no disc in the tray |
| **Somewhere to put the files** | A library share is configured *and* has been tested |
| **Room to work** | Amber only if `/srv/staging` is too full to rip safely. Rips go straight to your library when it's mounted, so this normally means rips are being staged |

A red row disables the switch entirely and has a **Fix** button for the page that fixes it. An amber row
leaves Auto Rip on but explains why a disc you just put in might not get ripped.

**All green and still nothing?** Check the switch is actually on — the checklist tells you
Riparr *could* rip, not that you've asked it to. Then read the next section.

## Stuck on "Reading the disc"

Reading an encrypted DVD takes a few minutes at 100% CPU, and some studios fill their
discs with dummy titles that stretch it further. **What MakeMKV is doing** on the rip card
shows its messages; if titles are being added, it's working.

If MakeMKV prints nothing after starting, for many minutes, it has probably hit a
Linux-only MakeMKV bug: it hangs fetching data for a drive it hasn't seen before. Riparr
works round this automatically: before MakeMKV's first run on a drive it checks, and if
MakeMKV hangs it adds `sdf_Stop = "<drive id>"` to MakeMKV's settings
(`data/.MakeMKV/settings.conf`), which skips that step for that drive. System → Status
shows **Drive data: Skipped** when it's in effect. It only costs 4K LibreDrive features.
To undo it, delete that line and restart the container.

## No drive found

1. **Check the host sees it:** `lsscsi -g` on the host should show a `cd/dvd` line. If it
   doesn't, it's a cable, power or USB-adapter problem, not Riparr.
2. **Check the container is allowed optical drives.** `docker-compose.yml` needs:

   ```yaml
   device_cgroup_rules:
     - "b 11:* rmw"
     - "c 21:* rmw"
   ```

   Then `docker compose up -d` to recreate the container. `docker logs riparr` should
   say `optical device /dev/sr0 is present`.
3. **Using `devices:` instead?** Pass **both** nodes from `lsscsi -g`, the `/dev/srN`
   and the `/dev/sgN`, with the same names inside. MakeMKV reads through the `sg` node,
   so passing only `/dev/sr0` is the usual mistake. A USB drive that's been replugged
   needs `docker compose restart` in this setup, and its `sg` number may have changed.

**Docker inside a Proxmox LXC** only sees what the LXC was given, so pass both nodes into
the LXC first. See [Run it in Docker](02-docker.md#on-proxmox).

**Without Docker**, only step 1 applies: Riparr sees the machine's own drives, through the
`cdrom` group. In a VM or an LXC, the drive has to be passed through to it first.

## Nothing happens when I insert a disc

**Nothing happens at all:** the disc wasn't detected.

- Wait 30 seconds — spin-up and reading the table of contents takes a moment
- Try a different disc. A badly scratched or dirty one may not be readable at all.
- **Disc upside down.** It happens.

**The drive works at it and gives up:** it saw the disc but couldn't read it. Clean the
disc.

**Nothing on any disc:** check the Queue page — it reports whether a drive is present at
all. If it isn't, see [No drive found](#no-drive-found).

## Riparr can't read discs

MakeMKV is compiled the first time the container starts, and only once you've accepted
its licence. In `docker-compose.yml`:

```
MAKEMKV_ACCEPT_EULA: "yes"
```

then `docker compose up -d`. Watch `docker logs -f riparr` for `building MakeMKV` and
`built MakeMKV`. If it says `FAILED`, it prints the end of the build log, and the whole
log is in `data/tools/MakeMKV-build.log`. The usual cause is no internet access on that
first start; restart the container to try again. Nothing is installed from the web UI.

**Rips fail with a key error:** paste a current key on the MakeMKV key setting. It is
stored in `/data`, so it survives updates. See
[the MakeMKV key](07-settings-reference.md#makemkv-key).

## The rip failed

The web page says how far it got and why.

- **Clean the disc.** Soft cloth, center outward, never circular.
- **Check for scratches** on the data side
- **Retry.** Riparr already retried internally, but a reseat sometimes helps.
- **Some discs are genuinely unreadable** by some drives. A different drive may work.

Nothing partial is written to your library — you won't get a broken file.

## It ejected immediately — three flashes, or the tray twice

Not an error, and not the disc. You have ripped this one before, and Riparr saved you
half an hour.

**With a browser open** you will already be looking at the answer: the page jumps to
**Discs** and highlights the film, with the date it went into your library.

**Without one**, that is what the signal was: three short flashes of the drive's own
light, three times — or two tray cycles, if you set it that way. Change it on
**Settings → Ripping → Already-ripped discs**,
where **Try the light** and **Try the tray** let you see each one on demand.

**To rip it anyway:** the **Re-rip** button on that film's tile in **Discs**. Leave the
disc on the open tray — Riparr pulls the tray back in itself.

**If it says this about a disc you have never ripped**, Riparr has matched it to
something else by mistake. **Forget** on the same tile clears its memory of it, and the
next insertion is treated as new.

## Paused — library unreachable

Riparr can't reach your library share. The rip is safe and paused mid-flight.

1. **Is the NAS awake?** Drive spin-down and sleep timers are the usual cause.
2. **Settings → Library → Test and save.** This tells you exactly which part is failing.
3. **Did credentials change?** A NAS password rotation will do this.
4. **Is the share full?**

Fix it and Riparr resumes where it stopped. Nothing is lost.

## `NT_STATUS_LOGON_FAILURE` or access denied

**Check the share name before the password.** Many NAS boxes answer a share name they do
not recognise with the same error they use for a bad password. Riparr's error message
prints the exact path it was trying to write to.

Then check:

- **Username format** for a domain account: `DOMAIN\name`, `DOMAIN/name` or
  `name@domain`.
- **Write access.** The account has to be able to write into the folder, not just read
  it. The test write catches this.
- **Guest access.** Leave username and password blank only if the share really allows
  guests.

## Permission denied in the logs

Riparr runs as `PUID`:`PGID` (1000:1000 unless you set them). It fixes the ownership of
`/data` and `/srv/staging` itself on every start, so a permission error is almost
always about `/srv/library`: the host mount of your NAS share has to be writable by that
user. A share mounted read-only on the host is read-only in the container too.

Files Riparr creates are owned by `PUID`:`PGID`. If Plex or Jellyfin can't read them, set
`PGID` to a group they're in, and `UMASK: "002"` to make new files group-writable.

## Everything is slow

**Probably not a fault.** Ripping speed is mostly your drive and your server's CPU:
reading the disc is limited by the drive, and decrypting it is CPU work. Blu-ray takes
far longer than DVD, and 4K longer again.

Genuinely slower than it should be:

- **The server is busy** with something else — other containers, transcodes, backups
- **The NAS is busy** with something else
- **Staged mode on a slow disk.** **Test staging speed** on the Storage settings measures
  the disk behind `/srv/staging`.
- **A USB drive on a slow port or hub.** Plug it straight into the server.

## Names are wrong

- **Check the disc's queue entry** — Riparr flags anything it was unsure about rather than
  guessing
- **TV discs:** correct the first disc of a season and the rest follow — Riparr carries the numbering on from where the last disc stopped
- **Corrections are remembered** per disc, forever. You'll never fix the same disc twice.
- **Consistently wrong across many discs:** check your naming template in
  [settings](07-settings-reference.md#naming)

## It says staging is full

If it happens, something downstream is stuck:

1. **Check the library share** — if uploads have been failing, staging is holding
   everything
2. **Look for stuck rips** in the queue
3. **System → Status → Storage** shows how much room there is, and the sidebar counts
   copies Riparr will clear as room

If the volume behind `/srv/staging` is simply too small for the discs you rip, move it to
a bigger disk.

## The container stopped mid-rip

Fine. Start it again.

Riparr detects the interruption on start and either resumes or cleanly fails that job.
Your library won't have a partial file — Riparr is built assuming this will happen.

## I forgot my password

You don't need to start over. Create an empty file named `riparr-reset` in the `/data`
volume and restart the container:

```
docker exec riparr touch /data/riparr-reset && docker restart riparr
```

Without Docker: `sudo touch /var/lib/riparr/riparr-reset && sudo systemctl restart riparr`.

The web UI asks you to create an account again. Riparr deletes the file as it acts on it.
Only the account is cleared: your shares, settings and every disc it remembers are all
still there.

## Dates and "days left" look wrong

Riparr uses the host's clock. If **System → Status** says the clock can't be right,
Riparr stops making claims that depend on it — including how long your MakeMKV key has
left — rather than stating a confident wrong number. Fix time sync on the host.

## Starting over

**Settings → System → Export settings** first. Then stop the container, clear out the
`/data` volume, start it again and import the file after setup. Takes about a minute.

## Reporting a bug

**Settings → System → Logs** downloads a bundle; **System → Log Files** and **Events** in
the web UI, and `docker logs riparr`, show the rest. Include:

- What Riparr appeared to be doing
- The disc (title, DVD/BD/UHD, studio)
- Your drive model, and whether it's internal or USB
- Your host OS and Docker version

---

[← Settings reference](07-settings-reference.md) · [Guide index](README.md)
