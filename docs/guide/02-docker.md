# 2. Run it in Docker

[← What you need](01-what-you-need.md) · [Guide index](README.md) · [Next: Connect your library →](04-connect-your-library.md)

---

Riparr Server is one container: the web interface, the rip queue, and MakeMKV. The
image is published at `ghcr.io/ziggy46/riparr-server` for amd64 and arm64.

MakeMKV is proprietary, so it isn't in the image. The container compiles it on its
**first start**, into your `data` folder, once you've said you accept its licence. Later
starts reuse that build and take seconds. libdvdcss, which DVDs need, is compiled the
same way.

## 1. Get the compose file

```bash
mkdir riparr && cd riparr
```

```bash
curl -fsSLO https://raw.githubusercontent.com/ziggy46/riparr-server/main/docker-compose.yml
```

Or clone the repo, which you'll want if you'd rather build the image yourself.

## 2. Configure

Edit `docker-compose.yml`:

```yaml
    environment:
      MAKEMKV_ACCEPT_EULA: "yes"   # you have read https://www.makemkv.com/eula/
      PUID: "1000"                 # your user and group on the host: run `id`
      PGID: "1000"
```

**PUID and PGID** decide who owns everything Riparr writes: the database in `./data`,
rips in `./staging`, and files in a bind-mounted library. Set them to your user, so you
can manage those files without `sudo`, and so Plex or Jellyfin can read them.

| Volume | What's in it |
|---|---|
| `./data` → `/data` | Settings, shares, rip history, the MakeMKV key, backups, logs, and the compiled MakeMKV. **Keep this one.** |
| `./staging` → `/srv/staging` | Where a rip is written before it's copied to your share. Needs room for the biggest disc you rip: about 50 GB for a Blu-ray, 100 GB for 4K. |
| *(optional)* → `/srv/library` | Your library, for [ripping straight into it](#optional-rip-straight-into-your-library). |

## 3. Start it

```bash
docker compose up -d
```

```bash
docker logs -f riparr
```

The first start prints `building MakeMKV` and takes a few minutes, depending on your
CPU. Then the web interface comes up. Open `http://<server>:9797` and the setup wizard
walks you through creating a login, entering a MakeMKV key and pointing Riparr at your
share.

**The share scan.** The wizard looks for SMB servers on Riparr's own network, and inside
Docker that's Docker's internal network, not your LAN. Type your LAN in the box under
the scan, e.g. `192.168.1.0/24`. Riparr remembers it once it finds something. Or set
`RIPARR_SCAN_SUBNETS` in the compose file, or just type the NAS's address.

## The drive

The compose file doesn't name any device. Instead it lets the container use optical
drives as a class:

```yaml
    device_cgroup_rules:
      - "b 11:* rmw"     # /dev/sr*  (optical drives)
      - "c 21:* rmw"     # /dev/sg*  (SCSI generic; MakeMKV reads through this)
```

A small watcher inside the container makes the device nodes for whatever optical
drives the host has, and only optical drives. Other disks are never exposed. So:

- you don't need to look up `/dev/sg` numbers, which change between boots
- a USB drive can be plugged in, unplugged and replugged without restarting anything
- the log says `optical device /dev/sr0 is present` when a drive appears

**If you'd rather name the drive yourself**, remove `device_cgroup_rules` and use
`devices:` instead. Find the nodes with `lsscsi -g` on the host and keep the same names
inside:

```yaml
    devices:
      - /dev/sr0:/dev/sr0
      - /dev/sg2:/dev/sg2
```

Without the watcher, a replugged drive needs `docker compose restart`, and its `sg`
number may have changed.

## Optional: rip straight into your library

By default a rip is written to `/srv/staging` and then copied to your share over SMB.
That works with no extra setup.

If you'd rather MakeMKV write directly into the library, mount the share on the
host, then bind it in:

```yaml
    volumes:
      - /mnt/nas/media:/srv/library
```

Then open **Rip options** on the Queue page and set **Each rip goes** to *straight to
your library*. Only the
**default** share uses `/srv/library`. If nothing is mounted there when a disc goes
in, that rip stages and copies over SMB instead of failing. The mount has to be writable
by `PUID`/`PGID`.

## On Proxmox

Run Docker in a VM or an LXC, not on the Proxmox host itself:

- **A VM.** Pass the drive through as a USB device (for a USB drive) or pass the SATA
  controller through (for an internal one), then run Docker in the VM as above.
- **Docker inside an LXC.** Enable nesting, and pass both device nodes into the LXC
  (*Resources → Add → Device Passthrough*, once for `/dev/sr0` and once for the
  `/dev/sg*`). Inside the LXC, use the `devices:` form above.

## Settings you can change with environment variables

| Variable | Default | |
|---|---|---|
| `MAKEMKV_ACCEPT_EULA` | `no` | `yes` compiles MakeMKV on start. Nothing reads a disc without it |
| `PUID` / `PGID` | `1000` | The user and group Riparr runs as and writes files as. `0` runs as root |
| `UMASK` | `022` | Permissions on new files. `002` makes them group-writable |
| `RIPARR_SCAN_SUBNETS` | | Networks the share scan sweeps, e.g. `192.168.1.0/24` |
| `RIPARR_DEVWATCH` | on | `0` turns off the drive watcher, if you use `devices:` |
| `RIPARR_PORT` | `9797` | Port inside the container |
| `RIPARR_API_DOCS` | off | `1` serves the interactive API docs at `/api/docs`, for wiring up dashboards |
| `RIPARR_UPDATE_REPO` | `ziggy46/riparr-server` | Which GitHub repo the update check looks at |
| `RIPARR_MOCK` | off | `1` simulates a drive and disc, for working on the interface without hardware |
| `TZ` | `Etc/UTC` | Timezone for times shown in the interface |

## Updating

```bash
docker compose pull && docker compose up -d
```

**System → Updates** tells you when a new release is out. It doesn't install anything
itself. If a new release pins a newer MakeMKV, the first start after updating compiles
it, the same as the very first start did.

## Building the image yourself

From a clone of the repo:

```bash
docker compose build && docker compose up -d
```

## Forgot your password

```bash
docker exec riparr touch /data/riparr-reset && docker restart riparr
```

The login is cleared and the next visit asks you to create one. Settings, shares and
history are kept.

---

[← What you need](01-what-you-need.md) · [Guide index](README.md) · [Next: Connect your library →](04-connect-your-library.md)
