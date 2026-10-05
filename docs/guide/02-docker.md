# 2. Run it in Docker

[← What you need](01-what-you-need.md) · [Guide index](README.md) · [Next: Connect your library →](04-connect-your-library.md)

---

Riparr Server is one container: the web interface, the rip queue and MakeMKV. You
build the image yourself, because MakeMKV is proprietary and isn't published inside one.

## 1. Find the drive on the host

The container needs **two** device nodes for the drive:

- the block device, `/dev/sr0`, which Riparr uses to see the tray and the disc
- the SCSI generic node, `/dev/sg*`, which is what MakeMKV actually reads through

On the Docker host:

```bash
sudo apt-get install -y lsscsi
```

```bash
lsscsi -g
```

```
[2:0:0:0]  cd/dvd  HL-DT-ST BD-RE BU40N  1.03  /dev/sr0  /dev/sg2
```

The last two columns are the ones you want. The `sg` number is often **not** 0. Every
disk on the system gets one, so a server with a few drives might put the optical drive
at `sg4`.

## 2. Configure

```bash
git clone https://github.com/ziggy46/riparr-server.git
```

```bash
cd riparr-server
```

Edit `docker-compose.yml`:

```yaml
    build:
      args:
        MAKEMKV_ACCEPT_EULA: "yes"      # you have read https://www.makemkv.com/eula/
    devices:
      - /dev/sr0:/dev/sr0
      - /dev/sg2:/dev/sg0               # host node on the left, from lsscsi -g
```

The container side of the `sg` mapping doesn't matter, so `/dev/sg0` is fine. What
matters is that the host side is the drive.

| Volume | What's in it |
|---|---|
| `./data` → `/data` | The database: settings, shares, rip history. Also the MakeMKV key, backups and logs. **Keep this one.** |
| `./staging` → `/srv/staging` | Where a rip is written before it's copied to your share. Needs room for the biggest disc you rip, about 50 GB for a Blu-ray and 100 GB for a 4K disc. |
| *(optional)* → `/srv/library` | Your library, for [ripping straight into it](#optional-rip-straight-into-your-library). |

## 3. Build and start

```bash
docker compose up -d --build
```

The first build compiles MakeMKV and libdvdcss, which takes a few minutes. Later
builds reuse that layer unless the MakeMKV version changes.

Open `http://<server>:9797` and the setup wizard walks you through creating a login,
entering a MakeMKV key and pointing Riparr at your share.

**The share scan will usually find nothing.** Discovery uses mDNS and a sweep of the
local subnet, and from Docker's bridge network that's Docker's own subnet. Type your
NAS's IP address in the box below the scan instead. To get discovery working, set
`network_mode: host` in `docker-compose.yml` (and remove `ports:`).

```bash
docker logs -f riparr
```

If the drive isn't passed through, the log says so on startup:
`riparr: no optical drive visible in this container`.

## Optional: rip straight into your library

By default a rip is written to `/srv/staging` and then copied to your share over SMB.
That works with no extra setup.

If you'd rather MakeMKV write directly into the library, mount the share on the
host, then bind it in:

```yaml
    volumes:
      - /mnt/nas/media:/srv/library
```

Then set **Each rip goes** to *straight to your library* on the Queue page. Only the
**default** share uses `/srv/library`. If nothing is mounted there when a disc goes
in, that rip stages and copies over SMB instead of failing.

## Optional: a device name that doesn't move

`sg` numbers are handed out in discovery order, so a reboot or a USB drive being
replugged can move the drive from `sg2` to `sg3`, and the container would then be
handed the wrong device. A udev rule on the host gives it a stable name.

Find the model string:

```bash
cat /sys/class/block/sr0/device/model
```

Create `/etc/udev/rules.d/99-riparr.rules`, using your model in place of `BD-RE BU40N`:

```
SUBSYSTEM=="block", KERNEL=="sr[0-9]*", ATTRS{model}=="BD-RE BU40N*", SYMLINK+="riparr-sr"
SUBSYSTEM=="scsi_generic", KERNEL=="sg[0-9]*", ATTRS{model}=="BD-RE BU40N*", SYMLINK+="riparr-sg"
```

```bash
sudo udevadm control --reload && sudo udevadm trigger
```

Then map the stable names in `docker-compose.yml`:

```yaml
    devices:
      - /dev/riparr-sr:/dev/sr0
      - /dev/riparr-sg:/dev/sg0
```

Docker resolves the link when the container starts. A drive that is unplugged and
plugged back in still needs `docker compose restart`, because a container's device
list is fixed when it starts.

## On Proxmox

Docker is happiest on the Proxmox host's guests, not the host itself:

- **A VM.** Pass the drive through as a USB device (for a USB drive) or pass the SATA
  controller through (for an internal one), then run Docker in the VM as above.
- **Docker inside an LXC.** Enable nesting, pass both device nodes into the LXC
  (*Resources → Add → Device Passthrough*, once for `/dev/sr0` and once for the
  `/dev/sg*`), then pass them on to the container as above.

## Settings you can change with environment variables

| Variable | Default | |
|---|---|---|
| `RIPARR_PORT` | `9797` | Port inside the container |
| `RIPARR_API_DOCS` | off | `1` serves the interactive API docs at `/api/docs`, for wiring up dashboards |
| `RIPARR_UPDATE_REPO` | `ziggy46/riparr-server` | Which GitHub repo the update check looks at |
| `RIPARR_MOCK` | off | `1` simulates a drive and disc, for working on the interface without hardware |
| `TZ` | `Etc/UTC` | Timezone for times shown in the interface |

## Updating

```bash
git pull && docker compose up -d --build
```

**System → Updates** tells you when a new release is out. It doesn't install anything
itself. Your data is in `./data` and survives the rebuild.

## Forgot your password

```bash
docker exec riparr touch /data/riparr-reset && docker restart riparr
```

The login is cleared and the next visit asks you to create one. Settings, shares and
history are kept.

---

[← What you need](01-what-you-need.md) · [Guide index](README.md) · [Next: Connect your library →](04-connect-your-library.md)
