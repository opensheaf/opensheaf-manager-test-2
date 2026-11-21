#!/usr/bin/env bash
# Two journals, as OpenSheaf archives, built from real papers of Quantum
# (quantum-journal.org, volume 7, 2023; CC BY 4.0) in the example papers.
# An unofficial demonstration: not made by or for Quantum.
#
#  1. A journal that ACCEPTS a vetted version: the authors keep their papers,
#     with all their versions, in their own archive (here imported from arXiv).
#     The journal keeps exactly the version it vetted as an accepted copy
#     (osheaf accept): a branch of the authors' line under the journal's
#     owner, holding the version's files byte for byte with the evidence of
#     the authors' signatures (section 9.6 of the specification). Its issue is
#     a selection of these copies, pinning the revisions the editors vetted.
#     The authors' later versions change nothing at the journal: a correction
#     is an editorial act (a notice, or the acceptance of a later version,
#     which moves the copy's branch point and adds the revision to the issue).
#     Only the vetted version needs an open licence, so a paper whose first
#     arXiv version is not openly licensed can be accepted, though not
#     mirrored; and the journal still verifies when the authors' archive is gone.
#  2. A journal that REPACKAGES the papers: it deposits its own version of
#     record (its typeset PDF, its DOI, its licence, the authors' agreement)
#     as documents of its own archive, linked to the authors' arXiv versions.
#
#   examples/journals.sh [EXAMPLE-PAPERS-FOLDER] [WORK-FOLDER]
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
W=${2:-$(mktemp -d)}
mkdir -p "$W"
W=$(cd "$W" && pwd)
WORK=$W/work
. "$HERE/examples/common.sh"
EX=$(with_new "$(cd "${1:-$HERE/../example-papers}" && pwd)")
A=$W/authors J=$W/journal-accept V=$W/journal-vor
export OPENSHEAF_LOCATIONS="https://example.org/authors/=$A/;https://example.org/journal-accept/=$J/"
PAPERS="hirche-network-discrimination singal-stabiliser-codes peters-generalization-overfitting"

step "the authors' archive: the Quantum papers from arXiv (every version CC BY), and a paper whose v1 is not openly licensed"
new_archive "$A" "The authors' archive" https://example.org/authors/
osheaf --root "$A" arxiv import "$EX/journal-quantum"
osheaf --root "$A" arxiv import "$EX/arxiv-downloads" 0000.00001
osheaf --root "$A" collect && osheaf --root "$A" index

step "1. a journal that accepts vetted versions: document version 2 of each paper, kept as accepted copies listed by the issue"
new_archive "$J" "An accepting journal (unofficial demonstration with papers of Quantum 7)" \
  https://example.org/journal-accept/
osheaf --root "$J" collection new issue-1 --type selection --title "Volume 7, issue 1" \
  --description "The papers accepted, in the versions the editors vetted."
for p in $PAPERS; do
  osheaf --root "$J" accept "$(uri "$A" "$p" 2)" --selection issue-1 --label "$p"
done

step "a paper whose v1 is under arXiv's licence: a mirror of the whole line is refused, but its vetted v2 is CC BY and can be accepted"
if osheaf --root "$J" mirror "$(uri "$A" fictitious-walks)"; then echo "expected a refusal"; exit 1; fi
osheaf --root "$J" accept "$(uri "$A" fictitious-walks 2)" --selection issue-1 --label fictitious-walks
osheaf --root "$J" collect
python3 - "$J/osheaf.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["index"]["html"]["featured"] = "issue-1"
open(sys.argv[1], "w").write(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
PY
osheaf --root "$J" index
osheaf --root "$J" verify --remote      # also checks every branch point against the authors' archive
osheaf --root "$J" collection status issue-1

step "the authors post a new version: the journal's copies and its issue do not change"
osheaf --root "$A" deposit hirche-network-discrimination "$EX/papers/random-walks/v2/paper.tex" \
  --pdf "$EX/papers/random-walks/v2/paper.pdf" --title "Quantum Network Discrimination" \
  --author "Hirche, Christoph" --changes "A later version by the author (invented, for the demonstration)."
osheaf --root "$A" collect && osheaf --root "$A" index
osheaf --root "$J" collect && osheaf --root "$J" collection update issue-1

step "the editors correct the papers: a notice, and the acceptance of the author's later version"
osheaf --root "$J" notice singal-stabiliser-codes --about 2 --text "An invented erratum, issued by the editors."
osheaf --root "$J" accept "$(uri "$A" hirche-network-discrimination 3)" --selection issue-1 \
  --message "Corrected by the editors: the author's version 3 accepted (an invented correction)."
osheaf --root "$J" collect
osheaf --root "$J" index && osheaf --root "$J" verify --remote
osheaf --root "$J" collection status issue-1

step "the authors' archive disappears: the journal's accepted copies carry their evidence, and still verify"
mv "$A" "$W/authors.gone"
osheaf --root "$J" verify
mv "$W/authors.gone" "$A"

step "2. a journal that repackages: its versions of record, with its licence and the authors' agreement"
new_archive "$V" "A publishing journal (unofficial demonstration with papers of Quantum 7)" \
  https://example.org/journal-vor/
osheaf --root "$V" deposit --from "$EX/deposits/quantum-vor.yaml"
osheaf --root "$V" collect && osheaf --root "$V" index
osheaf --root "$V" verify

printf '\nThe accepting journal is in %s, the publishing journal in %s; the throwaway keys in %s.\n' "$J" "$V" "$WORK"
