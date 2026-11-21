#!/usr/bin/env bash
# Collections, for the testing ground of the template: builds a member archive from
# the example papers (https://github.com/opensheaf/example-papers), then an
# archive of collections with members from it, and goes through the workflows of
# collections, also the unusual ones. Nothing in this repository is changed.
#
#   examples/collections.sh [EXAMPLE-PAPERS-FOLDER] [WORK-FOLDER]
#
# Members are lines of any archive, named by their sheaf: URIs (section 12.1
# of the specification), with the base URL of their archive as `at`. The
# archives here are served nowhere: their base URLs are read from their
# folders (OPENSHEAF_LOCATIONS). Set REAL=https://.../ to add members from a
# real archive of specification 0.2, by their labels there (REAL_LABELS,
# two labels separated by a space; by default two papers of mgubi.org/papers).
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
W=${2:-$(mktemp -d)}
mkdir -p "$W"
W=$(cd "$W" && pwd)
WORK=$W/work
. "$HERE/examples/common.sh"
EX=$(with_new "$(cd "${1:-$HERE/../example-papers}" && pwd)")
M=$W/member-archive C=$W/collection
export OPENSHEAF_LOCATIONS="https://example.org/member/=$M/;https://example.org/reading/=$C/"

# remote_uri BASE-URL LABEL [DOCUMENT-VERSION]: the sheaf: URI of a line of a
# published archive, from its discovery document.
remote_uri() {
  python3 - "$@" <<'PY'
import json, sys, urllib.parse, urllib.request
base, label = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(base + "opensheaf.json") as r:
    o = next(o for o in json.load(r)["objects"] if o.get("label") == label)
v = f"/v{sys.argv[3]}" if len(sys.argv) > 3 else ""
print(f"sheaf:{o['name']}:{o['owner']}{v}?at=" + urllib.parse.quote(base, safe=""))
PY
}

# pin ARCHIVE-FOLDER LABEL OBJECT-VERSION: the URI of one object version of a
# line, pinned by the digest of its inventory (a fixed member of a catalogue).
pin() {
  python3 - "$@" <<'PY'
import hashlib, json, sys, urllib.parse
folder, label, ver = sys.argv[1], sys.argv[2], sys.argv[3]
base = json.load(open(f"{folder}/osheaf.json"))["baseUrl"]
o = next(o for o in json.load(open(f"{folder}/opensheaf.json"))["objects"] if o.get("label") == label)
d = f"{folder}/ocfl/{o['owner']}/{o['name']}"
inv = json.load(open(f"{d}/{ver}/inventory.json"))
path = next(p for dg, ps in inv["versions"][ver]["state"].items() if "object.json" in ps for p in [inv["manifest"][dg][0]])
dv = json.load(open(f"{d}/{path}"))["documentVersion"]
digest = hashlib.sha512(open(f"{d}/{ver}/inventory.json", "rb").read()).hexdigest()
print(f"sheaf:{o['name']}:{o['owner']}/v{dv}?sha512={digest}&at=" + urllib.parse.quote(base, safe=""))
PY
}

step "a member archive, built from the example papers"
new_archive "$M" "Example member archive" https://example.org/member/
osheaf --root "$M" deposit --from "$EX/deposits/random-walks.yaml"
osheaf --root "$M" deposit --from "$EX/deposits/heat-notes.yaml"
osheaf --root "$M" arxiv import "$EX/arxiv-real"
osheaf --root "$M" collect && osheaf --root "$M" index

step "a catalogue in another archive, featured on its home page: members followed or fixed"
# (the main catalogue of an archive lists the lines its own owners write,
# section 8.1 of the specification: collections of others' lines are kept apart)
mkdir -p "$C" && cp -R "$HERE/templates" "$C/templates"
new_archive "$C" "A reading list" https://example.org/reading/
{
  echo "title: The papers of a group"
  echo "description: Members from another archive, followed as they grow, in the curator's order."
  echo "type: catalogue"
  echo "members:"
  echo "  - {uri: \"$(uri "$M" random-walks)\", follow: yes}      # followed"
  echo "  - \"$(pin "$M" heat-notes v1)\"                          # a fixed version"
  echo "  - {uri: \"$(uri "$M" kobayashi-park)\", follow: yes}    # followed, withdrawn later"
  echo "  - {uri: \"$(uri "$M" main)\", follow: yes}              # a collection as a member"
  if [ -n "${REAL:-}" ]; then
    set -- ${REAL_LABELS:-fractional-phi42-mass-gap paracontrolled-distributions}
    echo "  - {uri: \"$(remote_uri "$REAL" "$1")\", follow: yes}"
    echo "  - \"$(remote_uri "$REAL" "$2")\""
  fi
} > "$W/group.yaml"
cat "$W/group.yaml"
osheaf --root "$C" collection sync group --from "$W/group.yaml"
python3 - "$C/osheaf.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["index"]["html"]["featured"] = "group"
open(sys.argv[1], "w").write(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
PY
osheaf --root "$C" index
osheaf --root "$C" verify --remote

step "a selection: a reading list vetting particular document versions"
{
  echo "title: A reading list"
  echo "description: The versions the curator read and recommends."
  echo "type: selection"
  echo "members:"
  echo "  - {uri: \"$(uri "$M" random-walks)\", revisions: [1]}    # the version read"
  echo "  - \"$(uri "$M" heat-notes)\"                             # vetted in its current version"
  echo "  - {uri: \"$(uri "$M" kobayashi-park)\", revisions: [1]}"
  if [ -n "${REAL:-}" ]; then
    set -- ${REAL_LABELS:-fractional-phi42-mass-gap paracontrolled-distributions}
    echo "  - \"$(remote_uri "$REAL" "$2")\""
  fi
} > "$W/reading.yaml"
osheaf --root "$C" collection sync reading --from "$W/reading.yaml"  # a second collection, labelled
osheaf --root "$C" index
osheaf --root "$C" verify --remote

step "a new version in the member archive: the catalogue follows it, the selection reports it"
osheaf --root "$M" deposit random-walks "$EX/papers/random-walks/v2/paper.tex" \
  --pdf "$EX/papers/random-walks/v2/paper.pdf" --title "Random walks on a fictitious lattice" \
  --author "Example, Ada" --changes "A new version, to be followed by the collection."
osheaf --root "$M" collect && osheaf --root "$M" index
osheaf --root "$C" collection update && osheaf --root "$C" index
osheaf --root "$C" collection status reading
osheaf --root "$C" verify --remote

step "the curator reads the new version (document version 4) and vets it too: a new version of the selection"
sed -i.bak 's/revisions: \[1\]}    # the version read/revisions: [1, 4]}/' "$W/reading.yaml"
osheaf --root "$C" collection sync reading --from "$W/reading.yaml"
osheaf --root "$C" index && osheaf --root "$C" verify --remote

step "a member is withdrawn: the catalogue follows the withdrawal; the selection keeps its revision, and both show the withdrawal"
osheaf --root "$M" withdraw kobayashi-park --reason "An invented withdrawal, to try collections."
osheaf --root "$M" collect && osheaf --root "$M" index
osheaf --root "$C" collection update && osheaf --root "$C" index
osheaf --root "$C" collection status reading
osheaf --root "$C" verify --remote

step "updating again changes nothing"
osheaf --root "$C" collection update

step "a member disappears from its archive: verify --remote reports it unavailable (section 8.5)"
heat=$(object_path "$M" heat-notes)
mv "$heat" "$W/heat-notes.removed"
osheaf --root "$C" verify --remote | tee "$W/verify.txt"
grep -q "unavailable" "$W/verify.txt" || { echo "expected the member to be unavailable"; exit 1; }
mv "$W/heat-notes.removed" "$heat"
osheaf --root "$C" verify --remote

step "the website of the collection"
osheaf --root "$C" index
printf '\nThe collection is in %s (open %s/index.html); the throwaway keys in %s.\n' "$C" "$C" "$WORK"
