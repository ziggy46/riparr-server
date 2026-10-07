# 5. Library Layout & Naming

[← Connect your library](04-connect-your-library.md) · [Guide index](README.md) · [Next: Ripping discs →](06-ripping-discs.md)

**About 1 minute.** The defaults are correct for Plex and Jellyfin. If you use either,
accept them and move on.

---

## The defaults

**Movies**
```
Movies/
  Blade Runner (1982)/
    Blade Runner (1982).mkv
```

**TV**
```
TV/
  Twin Peaks (1990)/
    Season 01/
      Twin Peaks - S01E01 - Pilot.mkv
```

**Music** (audio CDs)
```
Music/
  Fleetwood Mac/
    Rumours (1977)/
      01 - Second Hand News.flac
      02 - Dreams.flac
      cover.jpg
```

The discs of a set share the album folder as `1-01`, `1-02`… `2-01`. Each FLAC is tagged
with what MusicBrainz knows and carries the cover inside it. See
[Audio CDs](06-ripping-discs.md#audio-cds).

These follow the conventions Plex, Jellyfin, and Emby all expect. Files land already
matched — no "fix match" pass in Plex afterward.

**Full disc backups** (Settings → Ripping → Titles → *Full disc backup*) keep the whole
disc instead of one file, in the same folder the film would have gone to:

```
Movies/
  Blade Runner (1982)/
    BDMV/            ← a Blu-ray; a DVD gets VIDEO_TS/
    CERTIFICATE/
```

Menus, extras, every audio track, decrypted. Jellyfin and Kodi play the folder as a disc,
and you can turn it into an ISO later without the drive. Plex doesn't play disc folders,
so stick with MKV if Plex is your player. A backup always files as a film, box sets
included — it's the disc, not its episodes.

A backup never goes into a folder that already has something in it. If you already have
`Blade Runner (1982)/` from an MKV rip, the backup goes beside it as
`Blade Runner (1982) - Bluray/`.

## Naming templates

The templates are editable on **Settings → Library**, and understand Radarr and Sonarr's
naming syntax. The dropdown above each one has presets, including the schemes from
TRaSH Guides for [films](https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/)
and [TV](https://trash-guides.info/Sonarr/Sonarr-recommended-naming-scheme/), and a
preview under it shows what the template makes of a sample 4K disc.

| Token | Becomes |
|---|---|
| `{Title}` or `{Movie CleanTitle}` | `Blade Runner` |
| `{Year}` or `{Release Year}` | `1982` |
| `{Source}` | `DVD`, `Bluray`, `UHD` |
| `{Season:00}`, `{Episode:00}` | `01` |
| `{EpisodeTitle}` | `Pilot` |
| `{Quality Full}` | `Remux-2160p`, `Remux-1080p`, `DVD`; `BR-DISK` / `DVD-R` for a full-disc backup |
| `{MediaInfo VideoCodec}` | `HEVC`, `AVC`, `VC1`, `MPEG2` |
| `{MediaInfo VideoBitDepth}` | `10` |
| `{MediaInfo AudioCodec}` | `TrueHD Atmos`, `DTS-HD MA`, `AC3` |
| `{MediaInfo AudioChannels}` | `7.1` |
| `{MediaInfo AudioLanguages}` | `[DE+FR]`: audio languages other than English |
| `{TmdbId}`, `{ImdbId}` | `603`, `tt0133093`, with a [TMDb key](#film-lookup-tmdb); for a season disc, the show's |
| `{TvdbId}` | `81189`: a show's TVDB ID, from TMDb or TVmaze. The TRaSH TV presets put it on the series folder |

Some of TRaSH's tokens aren't in the presets. `{Edition Tags}`, `{Custom Formats}` and
`{Release Group}` have no value for a disc rip, so a template that has them leaves them
out of the name. `{MediaInfo 3D}` and `{MediaInfo VideoDynamicRangeType}` still work, but
are blank on most discs: MakeMKV reports 3D and Dolby Vision, and never HDR10.

**Text inside the braces only appears with the value**, Radarr's way: `{[Quality Full]}`
gives `[Remux-1080p]`, or nothing at all. A group nested inside another keeps its outer
braces, which is how Plex wants IDs: `{tmdb-{TmdbId}}` gives `{tmdb-603}`.

The media tokens come from MakeMKV's description of the title being ripped. The IDs come
from TMDb, when you've given Riparr a key and the match is clear-cut; otherwise they're
left out of the name rather than guessed. A wrong ID is worse than none, since Plex and
Jellyfin trust it over the title.

## Film lookup (TMDb)

With a key from [The Movie Database](https://www.themoviedb.org/settings/api) on
**Settings → Library**, Riparr looks each film up by the name it has for the disc, which
is the volume label, or what you typed. TMDb gives it:

- the film's real title and year, so `BLADE_RUNNER` is filed as `Blade Runner (1982)`
- its TMDb and IMDb IDs, for `{TmdbId}` and `{ImdbId}` and the Plex, Emby and Jellyfin
  presets
- its poster, behind the queue and on the Discs page

**A match is only used when it's clear-cut:** the same title, and the same year (or one
year off, when only one film fits). With no year, only when one film by that name is far
better known than any other. `DUNE` is not clear-cut: there are two well-known films.
**When TMDb isn't sure** decides what happens then: keep the name Riparr had and rip
without IDs (the default), or stop and ask you, with TMDb's suggestions as posters to
pick from and a search box for anything else. A film you pick is remembered for that disc.

Either kind of TMDb key works: the long "API Read Access Token" or the 32-character "API
Key". This product uses the TMDB API but is not endorsed or certified by TMDB.

The zeroes set the padding: `{Season:0}` gives `1`, `{Season:000}` gives `001`.

A file holding two episodes — a double-length premiere or finale — expands
`E{Episode:00}` to `E01-E02` by itself. That is the form Plex and Jellyfin both read as
one file containing two episodes, and you do not need to change the template to get it.

A token Riparr doesn't know is left in the filename as written, rather than blanked — a
template with a typo should produce a visibly odd name, not a file called ` ().mkv`.

## Two copies of the same film

The DVD and the Blu-ray of one film produce the same title, so the default template
sends them to the same filename. **Riparr will not overwrite the first with the
second.** When the destination already exists and it was written by a *different* disc,
the new rip is saved alongside with its source on the end:

```
Movies/Arthur Christmas (2011)/
    Arthur Christmas (2011).mkv          ← the Blu-ray, ripped first
    Arthur Christmas (2011) - DVD.mkv    ← the DVD, ripped later
```

Plex and Jellyfin both read several files in one movie folder as **versions** of the
same film, so you get a "play version" choice rather than two entries. The rip that was
renamed says so on its History row.

Re-ripping the *same* disc still replaces its own file, which is what Rip again is for.

To tag every rip from the start instead, put `{Source}` in the template:
`{Title} ({Year})/{Title} ({Year}) - {Source}.mkv`.

## How Riparr identifies a disc

**A film's name starts from the disc label.** Most Blu-rays carry a usable one —
`BLADE_RUNNER_2049` becomes `Blade Runner 2049`. With a TMDb key (see
[Film lookup](#film-lookup-tmdb) above), that name is looked up and the film's real title,
year and IDs are used — but only when the match is clear-cut.

**DVDs are rougher.** DVD volume labels are frequently garbage like `LOGICAL_VOLUME_ID`.
When the label gives nothing a person would accept as a name, Riparr asks rather than
inventing one.

**It does not guess a year.** A year only appears in a filename if TMDb was sure of it,
it was in brackets on the disc label, or you typed one into the prompt. `Blade Runner
2049.mkv` is a name Plex matches and claims nothing untrue; `Blade Runner (2049).mkv`
would be a confident lie.

**A music CD has no label at all.** Its track layout identifies it on MusicBrainz instead,
which gives the artist, album, year and every track's title. When MusicBrainz doesn't
know the CD, Riparr asks.

**It only asks once per disc.** Riparr remembers your correction against that specific
disc's fingerprint. Rip the same disc on the same box a year later and it already knows.

Television is the case where the numbers have to be right *before* the file is written,
below.

## Two cases worth knowing about

**TV season discs.** Six titles of about 42 minutes each is a season disc, not a film
with five decoys. Riparr rips all six, in order, numbered and named.

The order comes from the disc. Most Blu-ray season discs carry a hidden "play all"
playlist, and that playlist is the disc's own record of what order its episodes go in —
when it's there, the order is a fact and Riparr just uses it. When it isn't, the order
comes from the disc's playlist numbering, which is right on almost every disc but not
all of them.

**Riparr shows you the plan once per season** — on the first disc, where one correction
fixes every disc after it — and again on any later disc whose order it couldn't read off
the disc itself.

The names come from [TMDb](https://www.themoviedb.org) when you've added a TMDb key, and
otherwise from [TVmaze](https://www.tvmaze.com), which needs no account. **Settings →
Ripping → Episode names from** can pin it to one. A box set started under one keeps
numbering correctly under the other. Labels that say "Series 1", as British box sets do,
are read as season 1.

**Disc order and broadcast order don't always agree.** Firefly is the famous one: the
disc opens with "Serenity", but it aired second, so every episode guide numbers "The
Train Job" as S01E01. Riparr always keeps the *disc's* order and only takes *names* from
the lookup — so when the two disagree you see it immediately, on the plan, before
anything is written. Shifting the first episode number renumbers and renames the whole
disc in one move.

**Later discs of the same season need no answer.** Correct disc one, and disc two
carries on from where it stopped.

**A disc that carries each episode twice** — once with the "next time" trailer, once
without — is normal, and Riparr keeps one of each. So is a season welded into a single
four-hour title, which Riparr will tell you about and rip as one file; splitting that
needs MKVToolNix on another machine.

**Decoy titles.** Some studios — Disney and Warner especially — put around a hundred
near-identical fake playlists on a disc specifically to defeat "pick the longest one."
Riparr has heuristics for it and will tell you when it's uncertain rather than silently
ripping a 90-minute loop of the same scene.

## What tracks get kept

Sensible defaults: your language, the main audio track, forced subtitles, no commentary.

Adjustable in [settings](07-settings-reference.md#track-selection) — keeping every dub and
commentary track can easily double file size.

---

[← Connect your library](04-connect-your-library.md) · [Guide index](README.md) · [Next: Ripping discs →](06-ripping-discs.md)
