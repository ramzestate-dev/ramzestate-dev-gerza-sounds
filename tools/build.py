#!/usr/bin/env python3
"""Build the gerza-sounds library from the sources list.

Downloads every file in sources/opengameart.json, unpacks archives (audio and licence/readme
texts only), converts audio to 128 kbit/s MP3, sorts it into categories, measures each file
with ffprobe, writes CATALOG.csv and licenses/, and packs one zip per category (split into
parts below 1.9 GB).

    python3 tools/build.py --out build [--jobs 8] [--limit N]

Downloads are untrusted: each one is unpacked into its own fresh directory, member paths are
checked to stay inside it, and only audio files and short licence texts are kept.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import zipfile

try:
    import py7zr
except ImportError:  # 7z archives are skipped without it
    py7zr = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = (".wav", ".ogg", ".mp3", ".flac", ".aif", ".aiff", ".m4a", ".opus", ".wma")
TEXT_RE = re.compile(r"(licen[cs]e|readme|read_me|credits?|copying|attribution|copyright|notice|terms)[^/]*$", re.I)
TEXT_EXT = (".txt", ".md", ".rtf", "")
MAX_SECONDS = 120
PART_LIMIT = 1_900_000_000
NC_RE = re.compile(r"non[\s-]?commercial\s+(use\s+|purposes\s+)?only|only\s+(for\s+)?non[\s-]?commercial|"
                   r"for\s+non[\s-]?commercial\s+(use|purposes)|not\s+(be\s+used\s+)?for\s+commercial|"
                   r"no\s+commercial\s+use|personal\s+use\s+only|\bCC[\s-]?BY[\s-]?NC\b|"
                   r"commercial\s+use\s+(is\s+)?(not\s+allowed|not\s+permitted|prohibited|forbidden)", re.I)
# "free for commercial and non-commercial use" is permission, not a restriction
BOTH_RE = re.compile(r"commercial\s*(and|or|&|/|,)\s*(non|personal)|non[\s-]?commercial\s*(and|or|&|/|,)\s*commercial",
                     re.I)


def restricts_commercial(text):
    for m in NC_RE.finditer(text):
        around = text[max(0, m.start() - 80):m.end() + 80]
        if m.group(0).lower().startswith("cc") or not BOTH_RE.search(around):
            return around.replace("\n", " ").strip()
    return None

# ---------------------------------------------------------------- categories and tags
# Order matters: the first category whose keywords match wins.
CATEGORIES = [
    ("risers", ["riser", "rising", "rise", "buildup", "build-up", "build up", "uplifter", "upsweep", "swell",
                "tension", "crescendo", "charge up", "charging", "power up", "powerup", "level up"]),
    ("music", ["music", "beat", "bpm", "drum loop", "drumloop", "melody", "song", "jingle", "fanfare", "theme",
               "tune", "stinger", "chord", "piano", "guitar", "synth loop", "loop music", "victory"]),
    ("ui", ["click", "button", "menu", "select", "hover", "gui", "interface", " ui", "ui ", "ui_", "ui-", "beep",
            "blip", "notification", "notify", "coin", "cash", "money", "purchase", "buy", "sell", "pickup",
            "pick up", "collect", "confirm", "cancel", "error", "toggle", "switch", "typing", "keyboard",
            "register", "chime", "bell ding", "ding", "pop"]),
    ("weapons", ["sword", "blade", "dagger", "knife", "katana", "sabre", "saber", "metal", "clang", "clash",
                 "slash", "stab", "gun", "shot", "pistol", "rifle", "shotgun", "reload", "bullet", "laser",
                 "bow", "arrow", "axe", "weapon", "armor", "armour", "chain", "shield", "cannon", "spear",
                 "unsheath", "sheath", "machine gun", "grenade", "mace", "hammer", "anvil"]),
    ("whooshes", ["whoosh", "woosh", "swoosh", "swish", "swing", "swipe", "swoop", "transition", "sweep",
                  "pass by", "passby", "flyby", "fly by", "wind whoosh", "zip", "throw", "flap"]),
    ("impacts", ["impact", "hit", "punch", "boom", "explosion", "explode", "blast", "thud", "slam", "crash",
                 "smash", "kick", "bang", "bash", "bump", "break", "shatter", "crack", "smack", "slap",
                 "knock", "stomp", "drop", "fall", "collapse", "rumble", "thump", "whack", "hurt", "damage"]),
    ("animals", ["horse", "neigh", "gallop", "bird", "chirp", "tweet", "crow", "owl", "dog", "bark", "cat",
                 "meow", "wolf", "howl", "cow", "moo", "sheep", "goat", "chicken", "rooster", "frog", "insect",
                 "cricket", "bee", "fly buzz", "pig", "duck", "seagull", "gull", "animal", "eagle", "hawk",
                 "lion", "bear", "mouse", "rat", "snake", "hiss", "whale", "dolphin", "bat"]),
    ("nature", ["wind", "thunder", "lightning", "rain", "storm", "water", "river", "stream", "wave", "ocean",
                "sea", "fire", "flame", "burn", "drip", "splash", "waterfall", "snow", "ice", "leaves",
                "rock", "stone", "earthquake", "volcano", "lava", "bubble", "underwater"]),
    ("ambience", ["ambience", "ambiance", "ambient", "atmosphere", "atmos", "background", "room tone",
                  "roomtone", "city", "street", "crowd", "traffic", "cave", "dungeon", "forest", "jungle",
                  "night", "drone", "hum", "tavern", "market", "office", "factory", "space", "engine room",
                  "loop", "soundscape", "environment", "station", "train", "car", "vehicle", "machine"]),
]
RU = {
    "riser": "нарастание", "rising": "нарастание", "rise": "нарастание", "buildup": "нарастание",
    "swell": "нарастание", "tension": "напряжение", "power up": "усиление", "powerup": "усиление",
    "level up": "новый уровень", "charge up": "заряд", "charging": "заряд",
    "music": "музыка", "beat": "бит", "bpm": "бит", "drum loop": "барабанный луп", "melody": "мелодия",
    "song": "песня", "jingle": "джингл", "fanfare": "фанфары", "theme": "тема", "stinger": "стингер",
    "piano": "пианино", "guitar": "гитара", "victory": "победа",
    "click": "клик", "button": "кнопка", "menu": "меню", "interface": "интерфейс", "gui": "интерфейс", "select": "выбор", "hover": "наведение",
    "beep": "писк", "blip": "блип", "notification": "уведомление", "coin": "монета", "cash": "деньги",
    "money": "деньги", "purchase": "покупка", "buy": "покупка", "pickup": "подбор", "collect": "сбор",
    "confirm": "подтверждение", "cancel": "отмена", "error": "ошибка", "switch": "переключатель",
    "typing": "печать", "keyboard": "клавиатура", "chime": "звон", "ding": "дзинь", "pop": "поп",
    "sword": "меч", "blade": "клинок", "dagger": "кинжал", "knife": "нож", "katana": "катана",
    "metal": "металл", "clang": "лязг", "clash": "столкновение", "slash": "рубящий удар", "stab": "укол",
    "gun": "оружие", "shot": "выстрел", "pistol": "пистолет", "rifle": "винтовка", "shotgun": "дробовик",
    "reload": "перезарядка", "laser": "лазер", "bow": "лук", "arrow": "стрела", "axe": "топор",
    "weapon": "оружие", "armor": "броня", "chain": "цепь", "shield": "щит", "cannon": "пушка",
    "spear": "копьё", "sheath": "ножны", "unsheath": "ножны", "hammer": "молот", "grenade": "граната",
    "whoosh": "свуш", "woosh": "свуш", "swoosh": "свуш", "swish": "свист", "swing": "взмах",
    "swipe": "свайп", "transition": "переход", "sweep": "свип", "flyby": "пролёт", "throw": "бросок",
    "flap": "взмах крыльев",
    "impact": "удар", "hit": "удар", "punch": "удар кулаком", "boom": "бум", "explosion": "взрыв",
    "explode": "взрыв", "blast": "взрыв", "thud": "глухой удар", "slam": "хлопок", "crash": "грохот",
    "smash": "разбивание", "kick": "пинок", "bang": "бах", "break": "ломание", "shatter": "осколки",
    "crack": "треск", "slap": "шлепок", "knock": "стук", "stomp": "топот", "drop": "падение",
    "fall": "падение", "rumble": "грохот", "thump": "глухой удар", "hurt": "ранение", "damage": "урон",
    "horse": "конь", "neigh": "ржание", "gallop": "галоп", "bird": "птица", "chirp": "щебет",
    "crow": "ворона", "owl": "сова", "dog": "собака", "bark": "лай", "cat": "кошка", "meow": "мяу",
    "wolf": "волк", "howl": "вой", "cow": "корова", "sheep": "овца", "chicken": "курица",
    "rooster": "петух", "frog": "лягушка", "insect": "насекомое", "cricket": "сверчок", "bee": "пчела",
    "pig": "свинья", "duck": "утка", "seagull": "чайка", "animal": "животное", "eagle": "орёл",
    "lion": "лев", "bear": "медведь", "snake": "змея", "hiss": "шипение", "bat": "летучая мышь",
    "wind": "ветер", "thunder": "гром", "lightning": "молния", "rain": "дождь", "storm": "шторм",
    "water": "вода", "river": "река", "stream": "ручей", "wave": "волна", "ocean": "океан", "sea": "море",
    "fire": "огонь", "flame": "пламя", "burn": "горение", "drip": "капли", "splash": "всплеск",
    "waterfall": "водопад", "snow": "снег", "ice": "лёд", "leaves": "листья", "rock": "камень",
    "stone": "камень", "earthquake": "землетрясение", "lava": "лава", "bubble": "пузыри",
    "ambience": "атмосфера", "ambiance": "атмосфера", "ambient": "атмосфера", "atmosphere": "атмосфера",
    "background": "фон", "city": "город", "street": "улица", "crowd": "толпа", "traffic": "трафик",
    "cave": "пещера", "dungeon": "подземелье", "forest": "лес", "jungle": "джунгли", "night": "ночь",
    "drone": "гул", "hum": "гул", "tavern": "таверна", "market": "рынок", "space": "космос",
    "loop": "луп", "train": "поезд", "car": "машина", "vehicle": "транспорт", "machine": "механизм",
    "footstep": "шаги", "step": "шаги", "door": "дверь", "glass": "стекло", "magic": "магия",
    "spell": "заклинание", "monster": "монстр", "zombie": "зомби", "voice": "голос", "scream": "крик",
    "glitch": "глитч", "retro": "ретро", "8-bit": "8-бит", "jump": "прыжок", "game over": "конец игры",
    "creature": "существо", "roar": "рёв", "growl": "рык", "ghost": "призрак", "wood": "дерево",
    "paper": "бумага", "book": "книга", "lock": "замок", "key": "ключ", "heartbeat": "сердцебиение",
}
EXTRA_TAGS = ["footstep", "step", "door", "glass", "magic", "spell", "monster", "zombie", "voice", "scream",
              "glitch", "retro", "8-bit", "jump", "game over", "creature", "roar", "growl", "ghost", "wood",
              "paper", "book", "lock", "key", "heartbeat"]


def words_in(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)          # camelCase -> camel Case
    text = re.sub(r"([A-Za-z])(\d)|(\d)([A-Za-z])", lambda m: " ".join(g for g in m.groups() if g), text)
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower().replace("-", " ")) + " "


VOICE = ("voice", "voiceover", "female", "male", "announcer", "speech", "spoken", "talk", "says", "vocal")


def has(t, kw):
    k = " " + kw.replace("-", " ").strip() + " "
    if kw.strip() in ("ui",):
        return " ui " in t
    # whole word, allowing plural / -ing / -ed endings
    return re.search(r"\s" + re.escape(kw.replace("-", " ").strip()) + r"(s|es|ing|ed|er)?\s", t) is not None \
        or k in t


def classify(fname, pack_title, pack_tags):
    t_file = words_in(fname)
    if any(has(t_file, v) for v in VOICE) or any(has(words_in(pack_title), v) for v in VOICE):
        return "other"  # spoken lines are not effects
    # the file's own name decides; the pack title only when the name says nothing.
    # Pack tag lists mix many themes, so they never pick a category.
    for t in (t_file, words_in(pack_title)):
        for cat, kws in CATEGORIES:
            if any(has(t, k) for k in kws):
                return cat
        if any(has(t, k) for k in EXTRA_TAGS):
            return "other"  # a known non-category theme (magic, monster, door...)
    return "other"


def tags_for(fname, pack_title, pack_tags, category):
    found = []
    for t in (words_in(fname), words_in(pack_title), words_in(" ".join(pack_tags[:6]))):
        if found:
            break  # the file's own words are enough; pack words only fill in when it has none
        for k in [k for _, kws in CATEGORIES for k in kws] + EXTRA_TAGS:
            if k in RU and has(t, k) and RU[k] not in [RU.get(f) for f in found]:
                found.append(k)
    found = found[:3] or [category.rstrip("s")]
    tags = []
    for k in found:
        tags.append(k)
        if k in RU:
            tags.append(RU[k])
    return ";".join(tags[:5])


# ---------------------------------------------------------------- download and convert
def safe(name, keep=80):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return name[-keep:].lstrip("-.") or "sound"


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=120)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def convert(src, dst):
    d = probe(src)
    if not d or d <= 0.02:
        return False
    args = ["ffmpeg", "-v", "error", "-y", "-i", src, "-vn", "-map_metadata", "-1"]
    if d > MAX_SECONDS:
        args += ["-t", str(MAX_SECONDS), "-af", f"afade=t=out:st={MAX_SECONDS - 2}:d=2"]
    elif d < 0.15:
        args += ["-af", "apad=pad_dur=0.2"]
    args += ["-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k", dst]
    r = subprocess.run(args, capture_output=True, timeout=900)
    return r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 1000


def wanted(member):
    low = member.lower()
    if "__macosx" in low or os.path.basename(member).startswith("._"):
        return None
    if low.endswith(AUDIO):
        return "audio"
    base = os.path.basename(member)
    if TEXT_RE.search(base) and os.path.splitext(low)[1] in TEXT_EXT:
        return "text"
    return None


def extract(archive, dest):
    real = os.path.realpath(dest)
    inside = lambda n: os.path.realpath(os.path.join(dest, n)).startswith(real + os.sep)
    if archive.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            total = 0
            for m in z.infolist():
                kind = wanted(m.filename)
                if m.is_dir() or not kind or not inside(m.filename):
                    continue
                if kind == "text" and m.file_size > 200_000:
                    continue
                total += m.file_size
                if total > 4_000_000_000:
                    break
                target = os.path.join(dest, m.filename)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(m) as s, open(target, "wb") as t:
                    shutil.copyfileobj(s, t)
    elif archive.lower().endswith(".7z") and py7zr:
        with py7zr.SevenZipFile(archive) as z:
            names = [n for n in z.getnames() if wanted(n) and inside(n)]
            if names:
                z.extract(path=dest, targets=names)


def job(args):
    src, url, work, stage = args
    slug = src["slug"]
    tmp = os.path.join(work, re.sub(r"[^A-Za-z0-9]", "", url)[-40:] + str(abs(hash(url)) % 10 ** 8))
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    fname = urllib.parse.unquote(url.rsplit("/", 1)[1])
    raw = os.path.join(tmp, "dl_" + safe(fname))
    rows, texts = [], []
    try:
        for attempt in range(3):
            r = subprocess.run(["curl", "-sS", "--fail", "-L", "--max-time", "1800", "--retry", "3", "-o", raw, url],
                               capture_output=True)
            if r.returncode == 0:
                break
        else:
            return {"url": url, "error": r.stderr.decode()[:200]}
        if raw.lower().endswith((".zip", ".7z")):
            ex = os.path.join(tmp, "x")
            os.makedirs(ex)
            extract(raw, ex)
            os.remove(raw)
            files = [os.path.join(r_, f) for r_, _, fs in os.walk(ex) for f in fs]
        else:
            files = [raw]
        pref = {".wav": 0, ".flac": 1, ".aif": 1, ".aiff": 1, ".ogg": 2, ".opus": 2, ".m4a": 3, ".mp3": 3}
        best = {}
        for f in files:
            if wanted(f) == "text":
                try:
                    texts.append((os.path.basename(f), open(f, errors="replace").read()[:200_000]))
                except OSError:
                    pass
                continue
            if wanted(f) != "audio":
                continue
            key = os.path.splitext(os.path.relpath(f, tmp))[0].lower()
            if key not in best or pref.get(os.path.splitext(f)[1].lower(), 9) < \
                    pref.get(os.path.splitext(best[key])[1].lower(), 9):
                best[key] = f
        picked = sorted(best.values())
        rels = [os.path.relpath(f, tmp) for f in picked]
        common = os.path.commonpath(rels) if len(rels) > 1 else os.path.dirname(rels[0]) if rels else ""
        for f in picked:
            rel = os.path.relpath(f, os.path.join(tmp, common)) if common else os.path.relpath(f, tmp)
            rel = re.sub(r"^(dl_|x/)", "", rel)
            while os.path.splitext(rel)[1].lower() in AUDIO:
                rel = os.path.splitext(rel)[0]
            parts = rel.split(os.sep)
            rel = os.sep.join(parts[-2:])
            name = safe(rel.replace(os.sep, "_"))
            cat = classify(rel, src["title"], src["tags"])
            outdir = os.path.join(stage, cat, slug)
            os.makedirs(outdir, exist_ok=True)
            dst = os.path.join(outdir, name + ".mp3")
            n = 2
            while os.path.exists(dst):
                dst = os.path.join(outdir, f"{name}-{n}.mp3")
                n += 1
            if not convert(f, dst):
                continue
            dur = probe(dst)
            if not dur:
                os.remove(dst)
                continue
            rows.append({"file": os.path.relpath(dst, stage).replace(os.sep, "/"), "category": cat,
                         "duration_sec": f"{dur:.2f}", "tags": tags_for(rel, src["title"], src["tags"], cat),
                         "source": src["page"], "author": src["author"]})
        return {"url": url, "slug": slug, "rows": rows, "texts": texts}
    except Exception as e:  # one bad download must not stop the build
        return {"url": url, "error": repr(e)[:200]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- packing
def pack(stage, rows, dist):
    os.makedirs(dist, exist_ok=True)
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    archives = {}
    for cat, items in sorted(by_cat.items()):
        items.sort(key=lambda r: r["file"])
        total = sum(os.path.getsize(os.path.join(stage, r["file"])) for r in items)
        parts, cur, size = [], [], 0
        for r in items:
            s = os.path.getsize(os.path.join(stage, r["file"])) + 200
            if cur and size + s > PART_LIMIT:
                parts.append(cur)
                cur, size = [], 0
            cur.append(r)
            size += s
        if cur:
            parts.append(cur)
        for i, part in enumerate(parts, 1):
            name = f"{cat}.zip" if len(parts) == 1 else f"{cat}-{i}.zip"
            with zipfile.ZipFile(os.path.join(dist, name), "w", zipfile.ZIP_STORED) as z:
                for r in part:
                    z.write(os.path.join(stage, r["file"]), r["file"])
                    r["archive"] = name
            archives[name] = os.path.getsize(os.path.join(dist, name))
        print(f"{cat}: {len(items)} files, {total / 1e6:.0f} MB, {len(parts)} zip", flush=True)
    return archives


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="only the first N sources (for testing)")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    work, stage, dist = (os.path.join(out, d) for d in ("work", "stage", "dist"))
    for d in (work, stage):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    sources = json.load(open(os.path.join(ROOT, "sources", "opengameart.json")))
    if a.limit:
        sources = sources[:a.limit]
    tasks = [(s, u, work, stage) for s in sources for u in s["files"]]
    by_slug = {s["slug"]: s for s in sources}
    rows, errors, texts = [], [], {}
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for i, res in enumerate(ex.map(job, tasks), 1):
            if "error" in res:
                errors.append(res)
            else:
                rows += res["rows"]
                if res["texts"]:
                    texts.setdefault(res["slug"], []).extend(res["texts"])
            if i % 50 == 0:
                print(f"{i}/{len(tasks)} downloads, {len(rows)} sounds", flush=True)

    # licences: the page licence (CC0 checked when the source list was made) plus any licence or
    # readme text shipped inside the pack; a pack whose texts forbid commercial use is NON-COMMERCIAL.
    lic_dir = os.path.join(ROOT, "licenses")
    shutil.rmtree(lic_dir, ignore_errors=True)
    os.makedirs(lic_dir)
    nc_slugs, nc_why = set(), {}
    for slug, items in texts.items():
        d = os.path.join(lic_dir, slug)
        os.makedirs(d, exist_ok=True)
        seen = set()
        for name, body in items:
            n = safe(name) or "LICENSE.txt"
            if n in seen:
                continue
            seen.add(n)
            open(os.path.join(d, n), "w").write(body)
            why = restricts_commercial(body)
            if why:
                nc_slugs.add(slug)
                nc_why.setdefault(slug, []).append(f"{n}: ...{why}...")
    for s in sources:
        if "CC0" not in s["licenses"]:
            nc_slugs.add(s["slug"])  # never expected: the list holds CC0 packs only
    for r in rows:
        slug = r["file"].split("/")[1]
        r["license"] = "NON-COMMERCIAL" if slug in nc_slugs else "CC0-1.0"

    archives = pack(stage, rows, dist)

    with open(os.path.join(ROOT, "CATALOG.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "category", "duration_sec", "tags", "source", "license",
                                          "archive"], extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["file"]):
            w.writerow(r)
    with open(os.path.join(lic_dir, "CREDITS.md"), "w") as f:
        f.write("# Credits\n\nAll packs come from OpenGameArt.org and are offered under CC0 1.0 "
                "(some also under other licences; this library uses them under CC0). "
                "Packs marked NON-COMMERCIAL ship a text that limits commercial use.\n\n"
                "| Pack | Author | Page | Licence |\n|---|---|---|---|\n")
        used = sorted({r["file"].split("/")[1] for r in rows})
        for slug in used:
            s = by_slug[slug]
            title = s["title"].replace("|", "/")
            f.write(f"| {title} | {s['author']} | {s['page']} | "
                    f"{'NON-COMMERCIAL' if slug in nc_slugs else 'CC0-1.0'} |\n")
    stats = {"sounds": len(rows), "archives": archives, "errors": errors, "non_commercial_packs": nc_why,
             "non_commercial_sounds": sum(1 for r in rows if r["license"] == "NON-COMMERCIAL"),
             "by_category": {c: sum(1 for r in rows if r["category"] == c) for c in sorted({r["category"] for r in rows})}}
    json.dump(stats, open(os.path.join(out, "stats.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != "errors"}, indent=1))
    print("errors:", len(errors))


if __name__ == "__main__":
    sys.exit(main())
