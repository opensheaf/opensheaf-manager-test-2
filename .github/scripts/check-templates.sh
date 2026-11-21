#!/usr/bin/env bash
# The templates of this repository (templates/) must be byte for byte those
# of the installed opensheaf-py (src/opensheaf/templates/), which `osheaf
# init` copies into a new archive: they drifted apart once. Run by the
# workflow `examples` in the template's own repository; an archive made from
# the template edits its templates freely and does not run it.
set -euo pipefail
cd "$(dirname "$0")/../.."
pkg=$(python3 -c 'import pathlib, opensheaf; print(pathlib.Path(opensheaf.__file__).parent / "templates")')
if diff -r "$pkg" templates; then
  echo "templates/ is the same as $pkg"
else
  echo "templates/ differs from the templates of opensheaf-py ($pkg): copy them (cp $pkg/* templates/)" >&2
  exit 1
fi
