# gerza-sounds: sound library for video edits

This repository is a searchable library of sound effects (CC0, from OpenGameArt.org) for
putting on video edits. **The sounds are not in git.** They are zip archives attached to the
GitHub release `v1`; git holds only the catalog, the licences and the tools.

## What is where

| Path | What |
|---|---|
| `CATALOG.csv` | one row per sound: `file, category, duration_sec, tags, source, license, archive` |
| release `v1` | `<category>.zip` (or `<category>-1.zip`, `-2.zip`… when a category is split, each under 1.9 GB) |
| `get-sound.sh` | search the catalog, download only the archive(s) needed, extract the chosen files to `./sounds/` |
| `licenses/` | licence / readme texts shipped inside the packs, and `CREDITS.md` (pack, author, page, licence) |
| `sources/opengameart.json` | the packs the library was built from (page, author, licences, file URLs) |
| `tools/build.py`, `.github/workflows/build-release.yml` | rebuild the library and the release |

Categories: `impacts` (hits, booms), `whooshes` (swooshes, transitions), `risers` (build-ups),
`weapons` (swords, metal, knives, guns), `nature` (wind, thunder, rain, water, fire), `animals`,
`ambience` (backgrounds, atmospheres), `ui` (clicks, coins, beeps), `music` (beats, loops, jingles),
`other` (everything else: voices, monsters, magic, retro game sounds…).

## Reading the catalog

- `file` is the path inside the zip named in `archive`; the first folder is the category, the
  second the source pack.
- `tags` holds 2–5 words, English and Russian, separated by `;` (e.g. `sword;меч;metal;металл`).
- `source` is the pack page on OpenGameArt; `license` is `CC0-1.0`, or `NON-COMMERCIAL` when the
  pack's own texts forbid commercial use (do not use those in ads or paid work).
- Search it without downloading anything: `grep -i 'sword' CATALOG.csv | head`, or
  `./get-sound.sh -l меч`.

## Getting sounds

```sh
./get-sound.sh удар меча          # numbered list, pick numbers, files land in ./sounds/
./get-sound.sh -n 3 whoosh        # first 3 matches, no prompt (use this when running unattended)
./get-sound.sh -c impacts -n 1 boom
./get-sound.sh -l дождь           # list only
./get-sound.sh --commercial -n 5 coin   # skip NON-COMMERCIAL sounds
```

It downloads with `gh release download v1 -R ramzestate-dev/ramzestate-dev-gerza-sounds -p <zip>`,
or with curl from `https://github.com/ramzestate-dev/ramzestate-dev-gerza-sounds/releases/download/v1/<zip>`
when `gh` is unavailable. In a Claude cloud session, where `gh` may be limited to search, run it
as `GERZA_USE_GH=0 ./get-sound.sh …` to use curl only. Zips are cached in `.cache/gerza-sounds/`.

## Rules

- **Download only the archives you need.** Find the sound in `CATALOG.csv` first, then fetch the
  one zip in its `archive` column (that is what `get-sound.sh` does). Never download every
  archive "just in case": together they are over a gigabyte.
- Do not commit sounds, zips, `sounds/` or `.cache/` to git.
- Check `license` before using a sound in commercial work; credit authors where you can
  (`licenses/CREDITS.md`).
- To add or change packs: edit `sources/opengameart.json` (CC0 packs only), then run the
  "Build sound library release" workflow; it rebuilds the zips, the catalog and the release.
