#!/usr/bin/env bash
# The testing ground of the template: builds a throwaway archive from the
# example papers (https://github.com/opensheaf/example-papers) and runs every
# workflow of the tools, including the unusual ones, then checks the archive.
#
#   examples/run.sh [EXAMPLE-PAPERS-FOLDER] [ARCHIVE-FOLDER]
#
# Defaults: ../example-papers next to this repository, and a temporary folder.
# Nothing in this repository is changed. The GitHub workflow `examples` runs it
# on every push; delete examples/ when you start your own archive if you like.
# The archive's owner is a throwaway one, with keys in a temporary folder
# (see common.sh); a real owner is made as the README says.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
A=${2:-$(mktemp -d)/archive}
WORK=$(mktemp -d)
. "$HERE/examples/common.sh"
EX=$(with_new "$(cd "${1:-$HERE/../example-papers}" && pwd)")
O="osheaf --root $A"

step "a new archive with a new owner, from the template's templates"
mkdir -p "$A" && cp -R "$HERE/templates" "$A/templates"
new_archive "$A" "Example papers" https://example.org/examples/ --affiliation "University of Nowhere"

step "ordinary deposits from YAML: Markdown notes, a PDF without sources, TeXmacs papers and slides"
for f in heat-notes lost-sources ibp-exponential meyer-cdt-slides audoly-mec430; do
  $O deposit --from "$EX/deposits/$f.yaml"
done

step "versions out of order: v1, v2, then the submitted manuscript found later (--after 1)"
$O deposit --from "$EX/deposits/random-walks.yaml"

step "a notice about version 1, with the erratum as a file"
$O notice random-walks --about 1 --file "$EX/notices/random-walks-erratum.md" \
  --text "Theorem 1 of version 1 omits the dimension; corrected in version 2."

step "a new version after the notice: the notice and its file stay"
$O deposit random-walks "$EX/papers/random-walks/v2/paper.tex" --pdf "$EX/papers/random-walks/v2/paper.pdf" \
  --extra-source "$EX/papers/random-walks/v2/refs.bib" \
  --extra-source "$EX/papers/random-walks/v2/figures/walk.pdf=figures/walk.pdf" \
  --title "Random walks on a fictitious lattice" --author "Example, Ada|University of Nowhere" \
  --author "Sample, Bo|Institute of Placeholders" --changes "Version 4: the published version." --stage VoR

step "the sources of the PDF-only paper are found: completing version 1 (its number stays)"
$O complete lost-sources --version 1 --source "$EX/papers/lost-sources/paper.tex"

step "description-only versions: a new licence, a link to another record (a placeholder DOI)"
$O relicense lost-sources --rights cc-by-4.0 --method "the author's e-mail of 1 May 2026"
$O relate heat-notes --to doi:10.5281/zenodo.0000000 --relation IsVariantFormOf

step "importing from arXiv (fake downloads, offline), then withdrawing one of the imported papers"
osheaf --root "$A" arxiv import "$EX/arxiv-downloads"
$O withdraw old-conference-paper --reason "Withdrawn by its author (an invented withdrawal)."

step "real openly licensed papers from arXiv (CC BY and CC0, every version)"
osheaf --root "$A" arxiv import "$EX/arxiv-real"

step "real slides from Zenodo (CC BY), one in two versions sharing 20 of their 22 files"
$O deposit --from "$EX/deposits/zenodo-wilde-slides.yaml"
$O deposit --from "$EX/deposits/zenodo-houghton-slides.yaml"

step "the main catalogue, the website, the checks"
$O collect
$O index
$O verify
$O owner show
printf '\nThe example archive is in %s (open %s/index.html); the throwaway keys in %s.\n' "$A" "$A" "$WORK"
