# Riparr Server guide

Discs go in, files land on your NAS. Riparr Server runs in Docker on a machine you
already have, with an optical drive passed through to it.

1. **[What you need](01-what-you-need.md).** A Docker host, a share, and **which drive
   to buy**, which is the part people get wrong.
2. **[Run it in Docker](02-docker.md).** Pass the drive through, build, start.
3. **Open `http://<server>:9797`**, point it at your share, put a disc in.

---

| | |
|---|---|
| [What you need](01-what-you-need.md) | The server, the share, and **which drive to buy** |
| [Run it in Docker](02-docker.md) | Device passthrough, volumes, updating, password reset |
| [Connect your library](04-connect-your-library.md) | Shares, and the write test |
| [Library layout](05-library-layout.md) | Naming that Plex and Jellyfin understand |
| [Ripping discs](06-ripping-discs.md) | Auto Rip, queue, what each stage means |
| [Settings reference](07-settings-reference.md) | Every setting, and why it's there |
| [Troubleshooting](08-troubleshooting.md) | When it sulks |

**Pre-1.0**, and an unofficial fork of [Riparr](https://github.com/jackharvest/riparr).
Report problems with this fork [here](https://github.com/ziggy46/riparr-server/issues),
not upstream.
