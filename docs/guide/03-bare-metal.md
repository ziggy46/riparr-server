# 3. Or install it without Docker

[← Run it in Docker](02-docker.md) · [Guide index](README.md) · [Next: Connect your library →](04-connect-your-library.md)

---

Riparr Server can also go straight onto a Debian or Ubuntu machine, run by systemd: the
same packages, MakeMKV build and settings the Docker image has, without the container.
It suits a machine that does nothing else, or a Proxmox LXC or VM where you'd rather not
run Docker inside it.

**Use Docker if you're not sure.** Updating is one command either way, but a container
keeps everything Riparr installs out of the rest of the system. A direct install puts
MakeMKV in `/usr` and its own packages on the machine.

| | |
|---|---|
| **Systems** | Debian 12 or 13, Ubuntu 22.04 or 24.04, on amd64 or arm64. It needs systemd and `apt` |
| **Not** | macOS or Windows. On those, run Riparr in a Linux VM with the drive passed through to it |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ziggy46/riparr-server/main/deploy/install.sh | sudo bash
```

It asks whether you accept [MakeMKV's licence](https://www.makemkv.com/eula/). Say `yes`
once you've read it, and MakeMKV is compiled before the service starts. That takes a few
minutes, once. Press Enter to skip, and nothing reads a disc until you accept it later
(see [Settings](#settings)).

To skip the question, add `--accept-eula` after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/ziggy46/riparr-server/main/deploy/install.sh | sudo bash -s -- --accept-eula
```

From a clone of the repo, `sudo bash deploy/install.sh` installs that checkout instead
of downloading a release.

When it's done it prints the address. Open `http://<machine>:9797` and the setup wizard
takes it from there.

### What it puts where

| | |
|---|---|
| `/opt/riparr` | The code and its Python environment. Replaced on every update |
| `/etc/riparr/riparr.env` | Your settings: port, folders, MakeMKV's licence. Kept on update |
| `/var/lib/riparr` | The database, logs, backups, MakeMKV's key and its compiled build |
| `/var/lib/riparr/staging` | Where a rip is written before it goes to your library |
| `riparr.service` | Runs Riparr as the `riparr` system user, in the `cdrom` group |
| `/usr`, `/usr/local/lib` | MakeMKV and libdvdcss, compiled from source |

`--data DIR` and `--staging DIR` put those two folders somewhere else, on the first
install. `--port N` changes the port.

## The drive

Nothing to pass through: Riparr sees the machine's own drives, including a USB drive
plugged in later. Debian and Ubuntu give optical drives to the `cdrom` group, which the
`riparr` user is in.

`lsscsi -g` lists the drives the machine can see. If Riparr says it can't see one, check
there first. In a **Proxmox LXC**, pass both of the drive's device nodes into the
container (*Resources → Add → Device Passthrough*, for `/dev/sr0` and its `/dev/sg*`).
In a **VM**, pass the drive through as a USB device, or pass its SATA controller through.

## Your library

To rip straight into your library rather than copying over SMB, mount the share at
`/srv/library` (in `/etc/fstab`, say), writable by the `riparr` user. For an SMB share,
that's `uid=riparr,gid=riparr` in the mount options. Then on the Queue page, **Rip
options → Each rip goes → straight to your library**.

Settings → Library says whether the mount is there and writable, and what to fix if not.

## Settings

The few settings that aren't in the web interface are in `/etc/riparr/riparr.env`. After
changing one:

```bash
sudo systemctl restart riparr
```

| Setting | Default | |
|---|---|---|
| `MAKEMKV_ACCEPT_EULA` | `no` | `yes` compiles MakeMKV on the next start. Nothing reads a disc without it |
| `RIPARR_PORT` | `9797` | The web interface's port |
| `RIPARR_HOST` | `0.0.0.0` | The address it listens on. `127.0.0.1` keeps it to this machine, behind a reverse proxy |
| `RIPARR_LIBRARY_MOUNT` | `/srv/library` | Where your library is mounted, to rip straight into it |
| `RIPARR_SCAN_SUBNETS` | | Networks the share scan sweeps, e.g. `192.168.1.0/24` |

The rest of the Docker guide's [environment variables](02-docker.md#settings-you-can-change-with-environment-variables)
work here too, apart from `PUID`, `PGID` and `RIPARR_DEVWATCH`, which are about the
container.

## Logs

```bash
journalctl -u riparr -f
```

They're also on **System → Log Files**, like the Docker version.

## Updating

```bash
sudo /opt/riparr/deploy/install.sh --update
```

It updates from wherever it was installed from: the latest release, or the newest code on
main if you installed with `--edge`. `--release` switches back to releases. Your
settings, data and MakeMKV build are kept. The service also rebuilds MakeMKV on its own
if a system update moves a library it was compiled against, so its next start can take a
few minutes.

**System → Updates** shows the same command when there's a new release.

## Forgot your password

```bash
sudo touch /var/lib/riparr/riparr-reset && sudo systemctl restart riparr
```

The login is cleared and the next visit asks you to create one. Settings, shares and
history are kept.

## Uninstalling

```bash
sudo /opt/riparr/deploy/install.sh --uninstall
```

That removes the service, the code, MakeMKV and libdvdcss, and keeps your data and
settings, so installing again picks up where you left off. Add `--purge` to delete
those and the `riparr` user too.

---

[← Run it in Docker](02-docker.md) · [Guide index](README.md) · [Next: Connect your library →](04-connect-your-library.md)
