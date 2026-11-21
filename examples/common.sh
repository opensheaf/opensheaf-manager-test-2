# What the example scripts share (sourced by run.sh, collections.sh and
# journals.sh). Specification 0.2: every archive has an owner, whose versions
# are signed with its keys.
#
# The examples make throwaway owners, never real ones: the current keys are
# kept in files of a temporary folder ($WORK/config, OPENSHEAF_KEY_STORE=file),
# never in your system's credential store, and the rotation keys are
# exported unencrypted (--no-passphrase) to $WORK/keys, outside every
# archive. Nothing of them is ever committed. A real owner is made once, by
# hand, as the README says (the key ceremony).

[ -n "${WORK:-}" ] || { echo "common.sh: set WORK first" >&2; exit 1; }
mkdir -p "$WORK/config" "$WORK/keys"
export XDG_CONFIG_HOME="$WORK/config" OPENSHEAF_KEY_STORE=file
# the examples sign with the keys they make, never with a key of the
# environment (a secret of the repository, for instance)
unset OPENSHEAF_SIGNING_KEY OPENSHEAF_PASSPHRASE OSHEAF_TEST_KEYS

step() { printf '\n== %s\n' "$*"; }

# new_archive FOLDER NAME BASE-URL [OPTIONS OF osheaf init...]: an archive
# with a new, throwaway owner.
new_archive() {
  local folder=$1 name=$2 base=$3
  shift 3
  osheaf init "$folder" --name "$name" --base-url "$base" --curator "Example, Ada" \
    --new-owner --export "$WORK/keys/$(basename "$folder")" --no-passphrase --yes "$@"
}

# uri ARCHIVE-FOLDER LABEL [DOCUMENT-VERSION]: the sheaf: URI of a line, with
# the archive's base URL as its at (section 12.1 of the specification).
uri() {
  python3 - "$@" <<'PY'
import json, sys, urllib.parse
folder, label = sys.argv[1], sys.argv[2]
base = json.load(open(f"{folder}/osheaf.json"))["baseUrl"]
o = next(o for o in json.load(open(f"{folder}/opensheaf.json"))["objects"] if o.get("label") == label)
v = f"/v{sys.argv[3]}" if len(sys.argv) > 3 else ""
print(f"sheaf:{o['name']}:{o['owner']}{v}?at=" + urllib.parse.quote(base, safe=""))
PY
}

# object_path ARCHIVE-FOLDER LABEL: the folder of a line in the storage root.
object_path() {
  python3 - "$@" <<'PY'
import json, sys
folder, label = sys.argv[1], sys.argv[2]
o = next(o for o in json.load(open(f"{folder}/opensheaf.json"))["objects"] if o.get("label") == label)
print(f"{folder}/ocfl/{o['owner']}/{o['name']}")
PY
}

# with_new EXAMPLE-PAPERS: a view of the example papers whose deposit files
# seal each new work: the first entry for each label gets `new: yes`
# (specification 0.2, section 10.2: a new label is sealed only when asked).
# The view is made of links to the example papers, with patched copies of
# deposits/, in $WORK/example-papers; the example papers are not changed.
with_new() {
  local src=$1 view=$WORK/example-papers
  rm -rf "$view" && mkdir -p "$view/deposits"
  for f in "$src"/*; do
    [ "$(basename "$f")" = deposits ] || ln -s "$f" "$view/$(basename "$f")"
  done
  python3 - "$src/deposits" "$view/deposits" <<'PY'
import re, sys
from pathlib import Path
src, dest = Path(sys.argv[1]), Path(sys.argv[2])
for f in sorted(src.glob("*.yaml")):
    seen, out = set(), []
    for line in f.read_text(encoding="utf-8").splitlines(keepends=True):
        out.append(line)
        m = re.match(r"^(- |)id:\s*(\S+)", line)
        if m and m.group(2) not in seen:
            seen.add(m.group(2))
            out.append(("  " if m.group(1) else "") + "new: yes\n")
    (dest / f.name).write_text("".join(out), encoding="utf-8")
PY
  echo "$view"
}
