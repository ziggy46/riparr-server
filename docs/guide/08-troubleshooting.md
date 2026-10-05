# 8. Troubleshooting

[← Settings reference](07-settings-reference.md) · [Guide index](README.md)

Organized by **what you actually observed**.

---

## The web UI doesn't load

Riparr is at `http://<server>:9797` — your server's name or IP address, port 9797.

1. **Is the container running?** `docker ps` should list `riparr`. If it isn't there, or
   keeps restarting, read why with `docker logs riparr`.
2. **Is the port published?** `docker-compose.yml` maps `9797:9797`. If you changed the
   left-hand side, use that port instead.
3. **Is a firewall on the host blocking it?** Try from the server itself:
   `curl -I http://localhost:9797`. If that works and other machines can't reach it, it's
   the host firewall or the network, not Riparr.

## It isn't auto ripping

**Open the web UI and read the checklist under the Auto Rip switch.** It lists every
prerequisite whether or not it's met, so the row that isn't green is your answer:

| Row | Means |
|---|---|
| **Riparr can read discs** | MakeMKV is in the image. Red means it was built without `MAKEMKV_ACCEPT_EULA: "yes"` — see [below](#riparr-cant-read-discs) |
| **The MakeMKV key is current** | There's a key and it hasn't lapsed. Amber means it lapses within a week — rips fail the day it does |
| **A drive to read them in** | An optical drive is visible inside the container. A working drive shows up here even with no disc in the tray |
| **Somewhere to put the files** | A library share is configured *and* has been tested |
| **Room to work** | Amber only if `/srv/staging` is too full to rip safely. Rips go straight to your library when it's mounted, so this normally means rips are being staged |

A red row disables the switch entirely and links to the page that fixes it. An amber row
leaves Auto Rip on but explains why a disc you just put in might not get ripped.

**All green and still nothing?** Check the switch is actually on — the checklist tells you
Riparr *could* rip, not that you've asked it to. Then read the next section.

## No drive found

The container only sees the devices you pass to it.

1. **Find the drive on the host:**

   ```
   lsscsi -g
   ```

   The optical drive is the `cd/dvd` line. It has two device nodes: `/dev/srN` and the
   SCSI-generic `/dev/sgN` at the end of the line.
2. **Pass both in** under `devices:` in `docker-compose.yml`. MakeMKV needs the `sg` node
   as well as the `sr` one — passing only `/dev/sr0` is the usual mistake.
3. **Recreate the container:** `docker compose up -d`.

**A USB drive that was unplugged and plugged back in** needs the container restarted —
device nodes are fixed when the container starts. Its `sg` number may also have changed,
so run `lsscsi -g` again and update `devices:` if it has. See
[Run it in Docker](02-docker.md#optional-a-device-name-that-doesnt-move) for a name that
doesn't move.

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

MakeMKV is compiled into the image at build time, and only if you have accepted its
licence. Set the build arg in `docker-compose.yml`:

```
MAKEMKV_ACCEPT_EULA: "yes"
```

then rebuild: `docker compose up -d --build`. The MakeMKV section of the web UI says the
same thing — nothing is installed from there.

**Rips fail with a key error:** paste a current key on the MakeMKV key setting. It is
stored in `/data`, so it survives rebuilds. See
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

The container writes to `/data`, `/srv/staging` and, if you use it, `/srv/library`. If
`docker logs riparr` shows permission errors on one of them, check the ownership and
permissions of the host directory behind that volume or bind mount.

For straight-to-library mode, the host mount of your NAS share must also be writable —
a share mounted read-only on the host is read-only in the container too.

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
3. **Settings → Storage** shows what's held and why

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
