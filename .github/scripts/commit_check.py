#!/usr/bin/env python3
"""The checks of a repository holding an OpenSheaf archive, from the git
companion of the specification (OpenSheaf archives in git, version 0.2),
between two commits of the published branch:

    python3 .github/scripts/commit_check.py BASE HEAD

- attributes (section 4.1): every archive file of HEAD has text, filter,
  ident, working-tree-encoding, export-subst and merge unset, so that git
  stores and checks it out byte for byte;
- no pointers, links or submodules among the archive files of HEAD (sections
  3 and 4.2): no Git LFS pointer, symbolic link or submodule;
- append-only (section 5.1): from BASE to HEAD, the storage root only grows.
  A file of an existing object may be added; replaced only if it is the
  object's root inventory or its checksum (a new head), or, as a repair
  (section 5.3), when its new bytes have the digest its inventory records;
  removed only with its whole object (a takedown, section 9). Drafts (under
  ocfl/draft/) change freely. The storage root's own files never change.

Every published commit being an archive (section 5.2) is checked by `osheaf
verify`, which the workflows run before they commit; that the versions added
are signed (section 10) is reported by `osheaf verify` too. BASE may be empty
or a commit of zeros (a new branch): only HEAD is checked then. Exits 1 on an
error, printing each.
"""
import hashlib
import json
import re
import subprocess
import sys

ARCHIVE = re.compile(r"^(opensheaf\.json|indexes\.json|(ocfl|names|owners|sha512)/.+)$")
UNSET = ("text", "filter", "ident", "working-tree-encoding", "export-subst", "merge")
LFS = b"version https://git-lfs.github.com/spec/v1"
OBJECT_MARK = "0=ocfl_object_1.1"


def git(*args, binary=False):
    out = subprocess.run(["git", *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8")


def tree(commit):
    """{path: (mode, blob)} of the files of COMMIT."""
    out = {}
    for line in git("ls-tree", "-r", "-z", commit).split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            mode, _, blob = meta.split()
            out[path] = (mode, blob)
    return out


def objects(paths):
    """The folders of the OCFL objects among PATHS (holding 0=ocfl_object_1.1)."""
    return {p[: -len(OBJECT_MARK) - 1] for p in paths if p.startswith("ocfl/") and p.endswith("/" + OBJECT_MARK)}


def object_of(path, roots):
    return next((r for r in roots if path.startswith(r + "/")), None)


def check_head(head, files, errors):
    archive = [p for p in files if ARCHIVE.match(p)]
    for start in range(0, len(archive), 200):
        chunk = archive[start:start + 200]
        out = git("check-attr", *UNSET, "--", *chunk)
        for line in out.splitlines():
            path, attr, value = line.rsplit(": ", 2)
            if value != "unset":
                errors.append(f"{path}: the attribute {attr} is {value}, not unset (git companion, section 4.1: "
                              ".gitattributes)")
    for p in archive:
        mode, blob = files[p]
        if mode == "120000":
            errors.append(f"{p}: a symbolic link among the archive files (section 3)")
        elif mode == "160000":
            errors.append(f"{p}: a submodule among the archive files (section 3)")
        elif int(git("cat-file", "-s", blob)) < 300 and git("cat-file", "blob", blob, binary=True).startswith(LFS):
            errors.append(f"{p}: a Git LFS pointer in place of the file (section 4.2)")


def recorded_digest(head_files, root, path):
    """The digest that the head inventory of the object ROOT records for its content path PATH."""
    inv_path = f"{root}/inventory.json"
    if inv_path not in head_files:
        return None, None
    inv = json.loads(git("cat-file", "blob", head_files[inv_path][1]))
    relative = path[len(root) + 1:]
    for digest, paths in inv.get("manifest", {}).items():
        if relative in paths:
            return inv.get("digestAlgorithm", "sha512"), digest
    return None, None


def check_append_only(base, head, base_files, head_files, errors):
    base_roots, head_roots = objects(base_files), objects(head_files)
    for path, (mode, blob) in base_files.items():
        if not path.startswith("ocfl/"):
            continue
        root = object_of(path, base_roots)
        if path.startswith("ocfl/draft/"):
            continue
        if path not in head_files:
            if root is not None and root not in head_roots and not any(p.startswith(root + "/") for p in head_files):
                continue    # the whole object removed: a takedown (section 9)
            errors.append(f"{path}: removed (git companion, section 5.1: only a takedown removes an object, whole)")
            continue
        if head_files[path][1] == blob:
            continue
        if root is None:
            errors.append(f"{path}: a file of the storage root changed (section 5.1)")
        elif path in (f"{root}/inventory.json", f"{root}/inventory.json.sha512"):
            continue        # a new head
        else:
            algorithm, digest = recorded_digest(head_files, root, path)
            new = git("cat-file", "blob", head_files[path][1], binary=True)
            if digest and algorithm in ("sha512", "sha256") and hashlib.new(algorithm, new).hexdigest() == digest:
                print(f"{path}: repaired (its bytes now have the digest its inventory records, section 5.3)")
            else:
                errors.append(f"{path}: changed (git companion, section 5.1: a file of an object version or a "
                              "witness is never replaced, except by a repair, section 5.3)")


def main():
    if len(sys.argv) != 3:
        sys.exit("commit_check.py BASE HEAD")
    base, head = sys.argv[1], sys.argv[2]
    errors = []
    head_files = tree(head)
    check_head(head, head_files, errors)
    if base and not re.fullmatch(r"0+", base):
        try:
            git("cat-file", "-e", base + "^{commit}")
        except subprocess.CalledProcessError:
            print(f"{base} is not a commit of this clone: append-only not checked")
        else:
            check_append_only(base, head, tree(base), head_files, errors)
    for e in errors:
        print(f"error: {e}")
    print(f"{len(errors)} error(s) from {base[:12] or '(none)'} to {head[:12]}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
