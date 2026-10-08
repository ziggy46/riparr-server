<div align="center">

<img src="server/static/img/riparr-mark.png" width="96" alt="">

# Riparr Server

**Rip your Blu-rays and DVDs straight onto your NAS, from a Docker container.**

</div>

> [!NOTE]
> **This is an unofficial fork** of [jackharvest/riparr](https://github.com/jackharvest/riparr).
> It runs Riparr in Docker on a server you already have, with an optical drive passed
> through, instead of on a dedicated single-board computer.
> It is not affiliated with or supported by the upstream project; please report problems
> with this fork [here](../../issues), not upstream.

<div align="center">

[Get started](#get-started) · [User guide](docs/guide/README.md) · [Which drive to buy](docs/guide/01-what-you-need.md#which-drive) · [Troubleshooting](docs/guide/08-troubleshooting.md)

</div>

---

Sonarr does your TV. Radarr does your films. Nobody bothered automating the boring part:
getting the discs off your shelf and into your library. That's this.

> **put a disc in → close the tray → walk away → it ejects when it's done**

The MKV lands on your share, named the way Plex and Jellyfin want it, with the disc's
extras beside it if you want them and only the languages you speak. TV box sets are
split into episodes, and music CDs become tagged FLAC albums. Plex, Jellyfin or Emby is
told the moment it's there. The web interface at `http://<server>:9797` is there for
when you want detail.

<img src="docs/img/web-queue.jpg" alt="The Riparr queue, ripping a Blu-ray with Auto Rip on">

<img src="docs/img/web-history.jpg" alt="Riparr history, showing a finished rip on the library share">

---

## Get started

```sh
mkdir riparr && cd riparr
curl -fsSLO https://raw.githubusercontent.com/ziggy46/riparr-server/main/docker-compose.yml
```

In `docker-compose.yml`, set `MAKEMKV_ACCEPT_EULA: "yes"` once you've read
[MakeMKV's licence](https://www.makemkv.com/eula/), and `PUID`/`PGID` to your user (`id`
shows them). Then:

```sh
docker compose up -d
```

**Without Docker**, on Debian or Ubuntu:

```sh
curl -fsSL https://raw.githubusercontent.com/ziggy46/riparr-server/main/deploy/install.sh | sudo bash
```

[Installing without Docker](docs/guide/03-bare-metal.md) says what that puts where, and
how to update and remove it.

Open `http://<server>:9797`. The first start compiles MakeMKV, which takes a few minutes;
`docker logs -f riparr` shows progress. Optical drives are picked up automatically,
including a USB drive plugged in later, with no device names to look up.

**[The full Docker guide](docs/guide/02-docker.md)** covers volumes, ripping straight into
a mounted library, Proxmox, updating and password reset.

## What you'll need

| | |
|---|---|
| **A Linux machine** | amd64 or arm64, running Docker, or Debian/Ubuntu for the direct install. A NAS, a home server, a Proxmox VM or LXC. Not macOS or Windows, except through a Linux VM |
| **An optical drive** | Internal SATA or USB. [Read this before you buy one](docs/guide/01-what-you-need.md#which-drive), especially for 4K |
| **A share** | SMB. Any NAS, or a folder on a computer that's usually on |
| **Staging space** | Room for the biggest disc you rip: ~50 GB for Blu-ray, ~100 GB for 4K |

## What's different from upstream

Upstream Riparr is an appliance: a single-board computer in a printed case, set up from
an SD card by a desktop app. This fork keeps the ripping engine, the interface, TV
detection, verification and notifications, and swaps the appliance parts for things a
server already has:

| Upstream | Riparr Server |
|---|---|
| Preparer app writes an SD card and installs over SSH | `docker compose up -d`, image on ghcr.io — or one command on Debian/Ubuntu |
| Detects real hardware by the board's device tree | Any Linux is real hardware; `RIPARR_MOCK=1` simulates |
| MakeMKV built on the box from the web page | Compiled on the container's first start, once you accept its licence |
| Updates itself in place | Checks for releases; you pull the new image |
| Runs as a dedicated `riparr` account | Runs as your `PUID`/`PGID` |
| Wi-Fi, status LED, restart/shutdown, USB-C socket fix | Removed: the host handles these |
| Mounts the library share as root at boot | Optional bind mount at `/srv/library` |
| Password reset file on the SD card's boot partition | `riparr-reset` file in the `/data` volume |

## Where it's at

Pre-1.0, like upstream. What has and hasn't been tried with real drives and discs, as
opposed to Riparr's simulated drive:

- [x] A DVD, ripped and filed end to end in Docker (an LXC on Proxmox)
- [x] Installing without Docker, on a Linux VM (amd64): MakeMKV built, a DVD scanned and
  ripped through a passed-through USB drive
- [x] MakeMKV's first-run hang on a new drive, worked around on its own
- [x] A Blu-ray (1080p), end to end
- [ ] **Two or more drives ripping at once.** Only tested with the simulated drives, never
  on real hardware, so two MakeMKV runs sharing one USB bus or host are unknown
- [ ] A TV season disc on a real drive
- [ ] 4K UHD discs and LibreDrive
- [ ] **An audio CD on a real drive.** Identifying, encoding to FLAC, tagging and filing are
  tested; reading a physical CD with cdparanoia isn't yet
- [ ] Answering a disc from a phone notification (tested against a stand-in ntfy server)
- [ ] **Keeping only some audio and subtitle languages** with a real MakeMKV. The rules
  Riparr writes are tested; MakeMKV reading them on a real disc isn't yet
- [ ] Extras and the Plex/Jellyfin scan on a real disc and server (tested with the
  simulated drive and a stand-in server)

If you try one of the unticked ones, [an issue](../../issues) saying how it went, with
your drive and host, is genuinely useful.

Deliberate limits:

- **The MakeMKV beta key expires monthly.** That's GuinpinSoft's call. Riparr fetches the
  new one itself when it's published, and tells you it did. Buying a licence makes the
  question go away.
- **No transcoding.** Point Tdarr or Unmanic at your library and let them do it properly.

## Run it from source

```sh
# Just the interface, with a simulated drive and disc (macOS or Linux)
cd server && ./run.sh                       # → http://localhost:8000
RIPARR_MOCK=1 ./run.sh                      # force simulation on Linux
```

## Licence

**[GPL-3.0](LICENSE)**, same as upstream. The interface is built on Sonarr's design
tokens, and copyleft comes along with them. Use it, change it, pass it on. If you pass it
on, ship the source too.

| | |
|---|---|
| Riparr | [jackharvest/riparr](https://github.com/jackharvest/riparr) — GPL-3.0 |
| Design tokens | [Sonarr](https://github.com/Sonarr/Sonarr) — GPL-3.0 |
| Album data | [MusicBrainz](https://musicbrainz.org) — CC0 · covers from the [Cover Art Archive](https://coverartarchive.org) |
| Themes | [theme.park](https://github.com/themepark-dev/theme.park) — MIT · the Windows 98 theme borrows from [98.css](https://github.com/jdan/98.css) — MIT |
| Icons | [Font Awesome Free](https://fontawesome.com/license/free) — CC BY 4.0 · brand marks from [Simple Icons](https://simpleicons.org/) — CC0 |
| Wordmark | [Russo One](server/static/fonts/RussoOne-OFL.txt) — SIL OFL 1.1 |
| Disc reading | [MakeMKV](https://www.makemkv.com/) — proprietary, by GuinpinSoft. **Not shipped with Riparr Server**, and not in the image. The container downloads and compiles it on first start, after you accept its licence. makemkv.com goes down for weeks at a time, so it tries a list of mirrors in order, and every download is checked against a hash pinned in this repo. libdvdcss is fetched and compiled the same way |

Riparr Server isn't affiliated with or endorsed by upstream Riparr, Sonarr, Radarr,
GuinpinSoft or anyone else named here. Those names belong to them.

## On AI

Upstream Riparr was built with a lot of help from an AI coding assistant, and so were
this fork's changes. If you'd rather not run software built that way, that's a fair
choice, and this paragraph is here so you can make it before you install anything.
