#!/usr/bin/env bash
# Find sounds in CATALOG.csv and download only the archives that hold them.
#
#   ./get-sound.sh удар меча            # search, pick from a numbered list, extract to ./sounds/
#   ./get-sound.sh -n 3 whoosh          # take the first 3 matches without asking
#   ./get-sound.sh -c impacts boom      # only one category
#   ./get-sound.sh -l rain              # list matches only, download nothing
#
# Options:
#   -n N         take the first N matches (no prompt)
#   -c CATEGORY  impacts|whooshes|risers|weapons|nature|animals|ambience|ui|music|other
#   -l           list only
#   -m MAX       show at most MAX matches (default 40)
#   -o DIR       where to extract (default ./sounds)
#   --commercial skip sounds marked NON-COMMERCIAL
#
# Archives come from the release (default v1) through `gh release download`, or plain curl when gh
# is missing or GERZA_USE_GH=0 (set GITHUB_TOKEN for a private repository). Downloaded zips are cached in
# .cache/gerza-sounds/ so a second search in the same archive downloads nothing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${GERZA_REPO:-ramzestate-dev/ramzestate-dev-gerza-sounds}"
TAG="${GERZA_TAG:-v1}"
CATALOG="${GERZA_CATALOG:-$HERE/CATALOG.csv}"
CACHE="${GERZA_CACHE:-$HERE/.cache/gerza-sounds}"
OUT="./sounds"
TAKE=""
CATEGORY=""
LIST_ONLY=0
MAX=40
COMMERCIAL=0

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    -n) TAKE="$2"; shift 2 ;;
    -c) CATEGORY="$2"; shift 2 ;;
    -l) LIST_ONLY=1; shift ;;
    -m) MAX="$2"; shift 2 ;;
    -o) OUT="$2"; shift 2 ;;
    --commercial) COMMERCIAL=1; shift ;;
    -h|--help) usage 0 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage 2 ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "give words to search for, e.g.: $0 удар меча" >&2; exit 2; }
[ -f "$CATALOG" ] || { echo "no catalog at $CATALOG" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is needed" >&2; exit 1; }

MATCHES="$(mktemp)"
trap 'rm -f "$MATCHES"' EXIT
python3 - "$CATALOG" "$CATEGORY" "$COMMERCIAL" "$MAX" "$@" > "$MATCHES" <<'PY'
import csv, math, re, sys
catalog, category, commercial, limit, words = sys.argv[1], sys.argv[2], sys.argv[3] == "1", int(sys.argv[4]), sys.argv[5:]

def stem(w):
    w = w.lower().replace("ё", "е")
    if re.search("[а-я]", w):
        if len(w) <= 3:
            return w
        return w[:len(w) - 1] if len(w) <= 5 else w[:len(w) - 2]   # меча -> меч, ударов -> удар
    return re.sub(r"(es|s|ing|ed)$", "", w) if len(w) > 4 else w

stems = [stem(w) for w in words if w.strip()]
rows = []
with open(catalog, newline="") as f:
    for row in csv.DictReader(f):
        if category and row["category"] != category:
            continue
        if commercial and row["license"] == "NON-COMMERCIAL":
            continue
        tags = row["tags"].lower().replace("ё", "е")
        rows.append((row, tags, " ".join([row["file"].lower(), row["category"], tags])))
# a rarer word says more about what is wanted ("меча" beats "удар"), so it weighs more
df = {s: sum(1 for _, _, hay in rows if s in hay) for s in stems}
weight = {s: math.log((len(rows) + 1) / (df[s] + 1)) + 1 for s in stems}
hits = []
for row, tags, hay in rows:
    found = [s for s in stems if s in hay]
    if found:
        score = sum(weight[s] * (2 if s in tags else 1) for s in found)
        hits.append((len(found), -score, float(row["duration_sec"] or 0), row))
best = max((h[0] for h in hits), default=0)
if best and best < len(stems):
    print(f"no sound has every word; showing the ones with {best} of {len(stems)}", file=sys.stderr)
hits = [h for h in hits if h[0] == best]
hits = [(h[1], h[2], h[3]) for h in hits]
hits.sort(key=lambda h: (h[0], h[1]))
for _, _, r in hits[:limit]:
    print("\t".join([r["file"], r["category"], r["duration_sec"], r["license"], r["archive"], r["tags"]]))
print(f"#TOTAL\t{len(hits)}")
PY

TOTAL="$(grep '^#TOTAL' "$MATCHES" | cut -f2)"
sed -i '/^#TOTAL/d' "$MATCHES"
if [ "$TOTAL" = "0" ]; then echo "nothing found for: $*"; exit 1; fi
SHOWN="$(wc -l < "$MATCHES")"
echo "found $TOTAL, showing $SHOWN:"
awk -F'\t' '{printf "%3d  %-9s %6ss  %-14s %s\n      tags: %s  [%s]\n", NR, $2, $3, $4, $1, $6, $5}' "$MATCHES"
[ "$LIST_ONLY" = 1 ] && exit 0

if [ -n "$TAKE" ]; then
  PICK="$(seq 1 "$(( TAKE < SHOWN ? TAKE : SHOWN ))" | tr '\n' ' ')"
elif [ -t 0 ]; then
  read -r -p "numbers to download (e.g. 1 3 5, 'all', Enter = 1): " PICK
  PICK="${PICK:-1}"
  [ "$PICK" = all ] && PICK="$(seq 1 "$SHOWN" | tr '\n' ' ')"
else
  PICK=1
fi

SELECTED="$(mktemp)"
trap 'rm -f "$MATCHES" "$SELECTED"' EXIT
for i in $PICK; do
  case "$i" in ''|*[!0-9]*) echo "skip '$i' (not a number)" >&2; continue ;; esac
  [ "$i" -ge 1 ] && [ "$i" -le "$SHOWN" ] || { echo "skip $i (no such line)" >&2; continue; }
  sed -n "${i}p" "$MATCHES" >> "$SELECTED"
done
[ -s "$SELECTED" ] || { echo "nothing selected"; exit 1; }

fetch() { # zip name -> path in cache
  local zip="$1" dest="$CACHE/$1"
  mkdir -p "$CACHE"
  if [ -s "$dest" ]; then echo "$dest"; return; fi
  echo "downloading $zip from $REPO release $TAG ..." >&2
  if [ "${GERZA_USE_GH:-1}" != 0 ] && command -v gh >/dev/null && gh release download "$TAG" -R "$REPO" -p "$zip" -D "$CACHE" --clobber >&2 2>/dev/null; then
    echo "$dest"; return
  fi
  local auth=()
  [ -n "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ] && auth=(-H "Authorization: Bearer ${GITHUB_TOKEN:-$GH_TOKEN}")
  if curl -fL --retry 3 "${auth[@]}" -o "$dest.part" "https://github.com/$REPO/releases/download/$TAG/$zip" >&2; then
    mv "$dest.part" "$dest"; echo "$dest"; return
  fi
  rm -f "$dest.part"
  echo "could not download $zip (gh not logged in, or no access to $REPO)" >&2
  return 1
}

mkdir -p "$OUT"
for zip in $(cut -f5 "$SELECTED" | sort -u); do
  path="$(fetch "$zip")"
  awk -F'\t' -v z="$zip" '$5 == z {print $1}' "$SELECTED" > "$SELECTED.files"
  python3 - "$path" "$OUT" "$SELECTED.files" <<'PY'
import os, sys, zipfile
archive, out, listing = sys.argv[1:4]
want = [l.strip() for l in open(listing) if l.strip()]
real = os.path.realpath(out)
with zipfile.ZipFile(archive) as z:
    names = set(z.namelist())
    for w in want:
        if w not in names:
            print(f"missing in {os.path.basename(archive)}: {w}", file=sys.stderr)
            continue
        target = os.path.realpath(os.path.join(out, w))
        if not target.startswith(real + os.sep):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with z.open(w) as s, open(target, "wb") as t:
            t.write(s.read())
        print(os.path.join(out, w))
PY
  rm -f "$SELECTED.files"
done
