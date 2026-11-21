#!/usr/bin/env bash
# The forms and the manager's requests, for the testing ground of the
# template: the key ceremony of the README with a throwaway owner, then a
# copy of this template set up and kept by requests, each carried out by
# .github/scripts/osheaf_issue.py and committed as the workflow `from
# request` does (a failed request leaves nothing), with the checks of the
# git companion (.github/scripts/commit_check.py) on every commit. The
# requests sign with the key "of the workflows" alone, from the environment,
# as in GitHub's workflows with the secret OPENSHEAF_SIGNING_KEY.
#
#   examples/requests.sh [EXAMPLE-PAPERS-FOLDER] [WORK-FOLDER]
#
# No network is needed: the member of another archive is read from a folder
# (OPENSHEAF_LOCATIONS), and nothing is fetched from arXiv.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
W=${2:-$(mktemp -d)}
mkdir -p "$W"
W=$(cd "$W" && pwd)
WORK=$W/work
. "$HERE/examples/common.sh"
EX=$(with_new "$(cd "${1:-$HERE/../example-papers}" && pwd)")
R=$W/repository M=$W/member-archive SETUP=$W/owner-setup
export OPENSHEAF_LOCATIONS="https://example.org/member/=$M/;https://example.org/repository/=$R/"

step "another archive, whose papers become members of collections"
new_archive "$M" "Example member archive" https://example.org/member/
osheaf --root "$M" deposit --from "$EX/deposits/heat-notes.yaml"
osheaf --root "$M" collect && osheaf --root "$M" index

step "the key ceremony: an owner made on 'the computer' (a scratch archive), a current key for the workflows added"
new_archive "$SETUP" "Owner setup" https://example.org/owner-setup/
OWNER=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["owner"])' "$SETUP/osheaf.json")
CI=$WORK/ci-key
mkdir -p "$CI"
CI_DID=$(XDG_CONFIG_HOME=$CI osheaf --root "$SETUP" key new | grep -o 'did:key:z[1-9A-HJ-NP-Za-km-z]*' | head -1)
set -- "$WORK"/keys/owner-setup/rotation-*.txt
osheaf --root "$SETUP" owner rotate --add "$CI_DID" --rotation-key "$1" --rotation-key "$2" \
  --export "$WORK/keys/owner-setup-2" --no-passphrase --yes
osheaf --root "$SETUP" owner show
# from here on, as in GitHub's workflows: the secret, and no other key
export OPENSHEAF_SIGNING_KEY=$(cat "$CI/opensheaf/keys/$OWNER/"*.key)
export XDG_CONFIG_HOME=$WORK/workflow-config GITHUB_ACTIONS=true GITHUB_REPOSITORY=example/repository

step "a repository made from the template, with the owner's key log in key-log/"
mkdir -p "$R"
(cd "$HERE" && git ls-files -z -- . ':!examples' | xargs -0 tar cf -) | (cd "$R" && tar xf -)
cp -R "$SETUP/ocfl/$OWNER/$OWNER" "$R/key-log"
cd "$R"
git init -q -b main . && git add -A && git -c user.name=example -c user.email=example@example.org commit -qm "From the template"

N=0
# request OPERATION [FIELD=VALUE | @FIELD=FILE]...: a request as the manager
# writes it, carried out as the workflow `from request` does; prints the answer.
request() {
  local op=$1
  shift
  N=$((N + 1))
  local id
  id=$(printf '20261120-0000%02d-test' "$N")
  mkdir -p "requests/$id"
  python3 - "requests/$id" "$op" "$@" <<'PY'
import json, shutil, sys
from pathlib import Path
folder, op, fields, files = Path(sys.argv[1]), sys.argv[2], {}, {}
for arg in sys.argv[3:]:
    name, _, value = arg.partition("=")
    if name.startswith("@"):
        shutil.copyfile(value, folder / Path(value).name)
        files.setdefault(name[1:], []).append(Path(value).name)
    else:
        fields[name] = value
(folder / "request.json").write_text(json.dumps({"operation": op, "fields": fields, "files": files}, indent=2) + "\n")
PY
  git add -A && git -c user.name=example -c user.email=example@example.org commit -qm "Request $id"
  local status=0
  RESULT_FILE=$WORK/result.md COMMIT_FILE=$WORK/commit.txt TITLE_FILE=$WORK/title.txt \
    python3 .github/scripts/osheaf_issue.py --request "requests/$id/request.json" || status=$?
  [ $status -eq 0 ] || { git reset -q --hard HEAD && git clean -fdq; }
  git rm -r -q "requests/$id"
  git add -A
  if [ $status -eq 0 ]; then
    git -c user.name=example -c user.email=example@example.org commit -q -F "$WORK/commit.txt"
    python3 .github/scripts/commit_check.py HEAD~2 HEAD | tail -1
  else
    git -c user.name=example -c user.email=example@example.org commit -qm "Request $id not carried out"
  fi
  printf -- '-- %s: %s\n' "$op" "$([ $status -eq 0 ] && echo done || echo refused)"
  sed 's/^/   /' "$WORK/result.md"
  rm -f "$WORK"/result.md "$WORK"/commit.txt "$WORK"/title.txt
  return $status
}
refused() { if request "$@"; then echo "expected a refusal"; exit 1; fi; }

P=$EX/papers/random-walks
step "the setup: osheaf init with the owner's key log, and a featured selection"
request setup "Name=A reading list on random walks" Purpose=selection "Curator=Example, Ada" \
  "Description=Papers on random walks." Base\ URL=https://example.org/repository/
[ ! -e key-log ] || { echo "key-log/ should be gone"; exit 1; }
refused setup "Name=Again" "Curator=Example, Ada"

step "deposits: a new paper (--new), a new version, and the mistakes refused"
request deposit "This deposit=A new paper" Label=random-walks "Title=Random walks on a fictitious lattice" \
  "Authors=Example, Ada|University of Nowhere" "Licence=CC BY 4.0 (cc-by-4.0)" \
  "@PDF of this version=$P/v1/paper.pdf" "@Sources=$P/v1/paper.tex" "@Sources=$P/v1/refs.bib" \
  "Main source=paper.tex" "In collection=a-reading-list-on-random-walks" \
  "Date this version became public=2024-03-01"
refused deposit "This deposit=A new paper" Label=random-walks "Title=T" "Authors=Example, Ada" \
  "Licence=CC BY 4.0 (cc-by-4.0)" "@PDF of this version=$P/v2/paper.pdf" "If there are no sources, why=none"
refused deposit "This deposit=A new version of a paper in the archive" Label=random-walk \
  "@PDF of this version=$P/v2/paper.pdf" "If there are no sources, why=none"
request deposit "This deposit=A new version of a paper in the archive" Label=random-walks \
  "@PDF of this version=$P/v2/paper.pdf" "@Sources=$P/v2/paper.tex" "@Sources=$P/v2/refs.bib" \
  "Main source=paper.tex" "What changed (for a new version)=A remark on Stirling's formula." \
  "In collection=a-reading-list-on-random-walks"

step "a notice, a new licence, a withdrawal"
request notice Label=random-walks "Document version it is about=1" "Text of the notice=An invented erratum."
request deposit "This deposit=A new paper" Label=old-notes "Title=Old notes" "Authors=Example, Ada" \
  "Licence=All rights reserved" "@PDF of this version=$P/v1/paper.pdf" "If there are no sources, why=lost"
request relicense Label=old-notes "New licence=CC0 1.0 (cc0-1.0)" "How the authors agreed=I am the only author"
request withdraw Label=old-notes "Reason for the withdrawal=An invented withdrawal."
refused notice Label=nothing-here "Document version it is about=1" "Text of the notice=x"

step "collections: a catalogue inside the selection, members of this archive and of another"
request new_collection "Label of the new collection=group" "Title of the collection=The group's papers" \
  Kind=catalogue "In collection=a-reading-list-on-random-walks"
request add "In collection=group" "New member=random-walks"
request add "In collection=group" "New member=$(uri "$M" heat-notes)"
refused add "In collection=group" "New member=random-walks"
refused add "In collection=group" "New member=a-reading-list-on-random-walks"
request add "In collection=a-reading-list-on-random-walks" \
  "New member=$(uri "$M" heat-notes)" "Versions you vet (selection)=1"

step "a new version of a member of this archive: the catalogue follows, the selection vets it (the curator deposited it)"
request deposit "This deposit=A new version of a paper in the archive" Label=random-walks \
  "@PDF of this version=$P/v1/paper.pdf" "If there are no sources, why=An invented third version." \
  "In collection=a-reading-list-on-random-walks"
osheaf collection status a-reading-list-on-random-walks

step "a new version in the other archive: vetted by request, then removed"
member() { env -u OPENSHEAF_SIGNING_KEY XDG_CONFIG_HOME="$WORK/config" osheaf --root "$M" "$@"; }
member deposit heat-notes "$P/v2/paper.tex" --pdf "$P/v2/paper.pdf" --title "Heat notes" \
  --author "Example, Ada" --changes "An invented new version."
member collect && member index
H=$(uri "$M" heat-notes)
request vet "In collection=a-reading-list-on-random-walks" "Member=${H%%\?*}" "Versions to vet=2"
refused vet "In collection=group" "Member=${H%%\?*}" "Versions to vet=2"
request remove "In collection=group" "Member to remove=${H%%\?*}"
refused remove "In collection=group" "Member to remove=${H%%\?*}"

step "without the secret, nothing is signed, and the answer says why"
SAVED=$OPENSHEAF_SIGNING_KEY
unset OPENSHEAF_SIGNING_KEY
refused notice Label=random-walks "Document version it is about=2" "Text of the notice=x"
export OPENSHEAF_SIGNING_KEY=$SAVED

step "the archive, its history, the checks"
osheaf verify
git log --format='%s' -30
python3 .github/scripts/commit_check.py "$(git rev-list --max-parents=0 HEAD)" HEAD | tail -1
printf '\nThe repository is in %s; the throwaway keys in %s.\n' "$R" "$WORK"
