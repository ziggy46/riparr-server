# 1. What You Need

[← Guide index](README.md) · [Next: Run it in Docker →](02-docker.md)

---

## Parts

| Part | Notes |
|---|---|
| **A Linux machine** | Running Docker, or Debian/Ubuntu for the [direct install](03-bare-metal.md): a NAS, a home server, a Proxmox VM or LXC. MakeMKV is happiest with 2 GB of RAM to itself, and decrypting a disc is CPU work, so a faster CPU rips faster. amd64 and arm64 both work. macOS and Windows only through a Linux VM. |
| **An optical drive** | See [which drive](#which-drive) below. This is the choice that matters most, and the only one you can get expensively wrong. Two or more drives rip at the same time. |
| **Staging space** | Room for the biggest disc you rip, on top of everything else: about **10 GB for DVDs, 50 GB for Blu-ray, 100 GB for 4K**, under 1 GB for a CD. Each rip is deleted from staging once it's safely in your library. Not needed for rips that go [straight to your library](02-docker.md#optional-rip-straight-into-your-library). |
| **A share** | SMB, on a NAS or any computer that is usually on. This is where finished rips go. |

## Which drive

**This is the expensive mistake to avoid.** Buying the wrong drive is not recoverable in
software, and the listing you buy from will not tell you what you need to know.

There are two separate questions, and shops answer neither clearly.

### 1. What does it read?

| You want to rip | Drive |
|---|---|
| **Music CDs** | Any optical drive. CDs don't need MakeMKV or a key. |
| **DVDs only** | Any DVD drive. Nothing special, nothing to check. |
| **Blu-ray (1080p)** | Any Blu-ray reader. Also nothing special — 1080p Blu-ray is not firmware-sensitive, and every working BD drive does DVDs too. |
| **4K / UHD Blu-ray** | **Specific models, often on specific firmware.** Most Blu-ray drives cannot rip a UHD disc at all, and they do not say so anywhere on the box. |

**Why 4K is different, briefly.** UHD discs use a newer copy protection (AACS 2.0). The
official way past it needs licensed player software on an Intel CPU with a feature called
SGX, running Windows — Riparr runs on Linux, so that route does not exist here at
all. The route that *does* work is MakeMKV's **LibreDrive**, which talks to the
drive's own chipset underneath its firmware, and that works on a specific, finite list of
drives.

So there is no clever software fix available to us, and no drive advertises this. It is a
buying decision.

### 2. Internal or USB?

Either works. **An internal SATA drive** plugs into a spare SATA port on your server and
needs nothing else. **A USB drive** plugs into any USB port. Pick whichever your server
has room for; this is independent of the first question, and there are slim 4K drives and
full-size DVD drives.

### The list

| Drive | Size | Reads | Notes |
|---|---|---|---|
| **LG BU40N** | Slim | DVD · Blu-ray · **4K UHD** | The most commonly confirmed LibreDrive UHD reader, and a common choice in a USB enclosure. |
| **LG BU50N** | Slim | DVD · Blu-ray · 4K on the right firmware | The BU40N's successor, same shape. Newer units ship firmware that closes LibreDrive — check before buying, not after. |
| **LG WH16NS40 / WH16NS60** | Full | DVD · Blu-ray · 4K on the right firmware | The full-size answer, and what most of the UHD ripping community runs. Usually needs crossflashing first. |
| **ASUS BW-16D1HT** | Full | DVD · Blu-ray · 4K on the right firmware | Firmware-dependent in the same way. The external BW-16D1X-U is the same drive in a shell. |
| **Any Blu-ray reader** | Either | DVD · Blu-ray | The cheap half of the shelf, and the whole product for most people. |
| **Any DVD drive** | Either | DVD | The cheapest option. |

**Firmware versions are deliberately not printed here.** They change, and a stale version
number stated with confidence is worse than a pointer to the live one. Before buying for
4K, check MakeMKV's own compatibility list:

> <https://forum.makemkv.com/forum/viewtopic.php?f=19&t=19634>

**Riparr checks this for you once the drive is passed through.** The Queue page tags the drive
with what it reads — `DVD` `Blu-ray` `4K UHD`, lit or not — and **System → Status** says
plainly whether 4K will work, asking MakeMKV directly rather than guessing. If you put a
disc in a drive that cannot read it, Riparr says so and ejects it instead of failing forty
minutes later. The same list lives in `server/riparr/drives.py`, so the advice above and
Riparr's own diagnosis cannot disagree.

### If your drive is SATA but your server has no free port

Put it in a USB enclosure or on a USB-to-SATA adapter, but check first: **"USB to SATA"
on a listing says nothing about optical-drive support.** Many adapters carry an explicit
*"Do NOT support BLU-RAY, CD-ROM, DVD-ROM"* warning. The adapter must **name**
optical/ATAPI support. If the tray opens but Riparr never sees a disc, suspect the adapter
or the cable before the drive.

## Staging space and deep verification

Riparr checks every rip arrived. The normal check compares the size your share reports
with what was sent. It's free, and it catches what actually goes wrong: a truncated
transfer, a share that filled up, a write that was refused.

**Deep** verification goes further. It reads the whole film back off the share and
hashes it, which also catches silent corruption of bytes that did arrive. It needs the
rip to be staged first, and room in staging for the film **twice over**: the rip plus
the read-back. Worth it for an archive you'll never re-rip; overkill for most.

---

[← Guide index](README.md) · [Next: Run it in Docker →](02-docker.md)
