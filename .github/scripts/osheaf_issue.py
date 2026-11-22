#!/usr/bin/env python3
"""Carry out on the archive the operation described by an issue form, or by
a page's request.

Run by .github/workflows/from-issue.yml, in the root of the archive, after the
workflow has checked that the issue's author may write to the repository
(the issue is read from the event file, GITHUB_EVENT_PATH, never from the
command line); by .github/workflows/from-request.yml with `--request
requests/ID/request.json` (a page's request, such as the OpenSheaf manager's);
and by .github/workflows/setup.yml with the request of the setup.

Specification 0.2. The archive has an owner, which signs every version: in
GitHub's workflows with the current key in the repository secret
OPENSHEAF_SIGNING_KEY (the key ceremony of the README). Works are lines, named
in the archive by their labels (`kpz-uniqueness`, the address of the paper's
page `paper/LABEL/`) and everywhere by their sheaf: URIs. The archive holds
documents, listed by the owner catalogue of their owner (kept by `osheaf collect`), and
collections: reading lists, journal issues, sections, each a line whose
members are kept in collections/LABEL.yaml and pinned by `osheaf collection
sync LABEL`. A member is a line of this archive, by its label, or of any
archive, by its sheaf: URI and the base URL of an archive that holds it. The
forms deposit documents (a new paper with `--new`, or a new version), give
notices, withdraw, give new licences, create collections, and add, vet and
remove their members. A collection that includes a changed collection is
brought up to date in turn (in a selection, the new version is vetted: the
same curator made it; a catalogue follows it). Then `osheaf collect`,
`osheaf index` and `osheaf verify`.

Writes a message for the issue to RESULT_FILE (Markdown), the commit message
to COMMIT_FILE (naming the object versions added, as the git companion asks,
section 6.1) and the issue's new title to TITLE_FILE. Exits 0 on success, 1
on an error the author can fix (explained in RESULT_FILE; the lists are
restored, and the workflow commits nothing), 2 if the issue is not one of the
forms.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import yaml

OSHEAF = shlex.split(os.environ.get("OSHEAF", "osheaf"))
NO_RESPONSE = "_No response_"
LINK = re.compile(r"!?\[([^\]]*)\]\((https?://[^)\s]+)\)")
LABEL = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# sheaf:<name>:<owner>, with an optional document version and query (section 12.1)
SHEAF = re.compile(r"^sheaf:([a-z2-7]{52}):([a-z2-7]{51}[aq])(/v\d+)?(?:\?(.*))?$")
# arXiv identifiers, new (2303.18112) and old (math/0601001, math.PR/0601001),
# with an optional version
ARXIV = re.compile(r"^(?:arxiv:|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)?"
                   r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?(?:\.pdf)?/?$", re.I)
AUTHOR = "I am an author of the paper"
PERMISSION = "The authors gave me permission"
NEW_PAPER = "A new paper"
NEW_VERSION = "A new version of a paper in the archive"
SIGNING_KEY = "OPENSHEAF_SIGNING_KEY"

COLLECTIONS = Path("collections")
KEY_LOG = Path("key-log")
SOURCE_SUFFIXES = {".tex", ".ltx", ".tm", ".md", ".typ", ".lyx", ".rst", ".org", ".txt"}
LICENCES = {"cc-by-4.0", "cc-by-sa-4.0", "cc0-1.0", "gpl-3.0-only", "gpl-3.0-or-later"}
HEADER = """\
# The members of a collection of this archive, in order, for
# `osheaf collection sync LABEL --from collections/LABEL.yaml`: kept by the
# issue forms of this repository (Issues, New issue), the OpenSheaf manager,
# or by hand (see the README). A member is a line of this archive, by its
# label (`label: kpz-uniqueness`), or of any archive, by its sheaf: URI and
# the base URLs of archives that hold it (`uri: sheaf:<name>:<owner>`,
# `at: [https://example.org/papers/]`). In a selection, `revisions` lists the
# document versions vetted (1, 2, ...); in a catalogue, `follow: true` follows
# the line to its latest signed version.
"""

# The heading that identifies each form (a label of one of its fields).
FORMS = {
    "PDF of this version": "deposit",
    "Text of the notice": "notice",
    "Reason for the withdrawal": "withdraw",
    "New licence": "relicense",
    "Label of the new collection": "new_collection",
    "New member": "add",
    "Versions to vet": "vet",
    "Member to remove": "remove",
    "arXiv identifier": "arxiv",
}

# The lines osheaf prints for each object version it adds ("kpz: v3 (document
# version 2) sheaf:...", "reading: v2 (document version 2, 3 members)"),
# gathered for the commit message.
ADDED = re.compile(r"^(\S+): v\d+ (\(|branch of|moves )")
added = []


class Problem(Exception):
    """An error the author can fix, explained in plain words."""


# --- reading the form ------------------------------------------------------

def sections(body):
    out, label, lines_ = {}, None, []
    for line in (body or "").splitlines():
        m = re.match(r"^### (.+?)\s*$", line)
        if m:
            if label is not None:
                out[label] = "\n".join(lines_).strip()
            label, lines_ = m.group(1), []
        elif label is not None:
            lines_.append(line)
    if label is not None:
        out[label] = "\n".join(lines_).strip()
    return {k: ("" if v == NO_RESPONSE else v) for k, v in out.items()}


def field(form, label, required=False):
    value = str(form.get(label, "") or "").strip()
    if required and not value:
        raise Problem(f"The field **{label}** is empty, and it is needed.")
    return value


def lines(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not LINK.fullmatch(l.strip())]


def label_field(form, name, limit=64):
    label = field(form, name, required=True)
    if not LABEL.match(label) or len(label) > limit:
        raise Problem(f"`{label}` is not a valid label: at most {limit} characters, "
                      "lower-case letters and digits, words joined by `-` (for instance "
                      "`kpz-uniqueness`).")
    return label


def archive_url(form, name, required=True):
    url = field(form, name, required)
    if not url:
        return ""
    if not re.match(r"^https://\S+$", url):
        raise Problem(f"**{name}** should be the address of an OpenSheaf archive, the https "
                      f"address of the folder that holds its `opensheaf.json` (for instance "
                      f"`https://mgubi.org/papers/`), not `{url}`.")
    url = re.sub(r"opensheaf\.json$", "", url)
    return url if url.endswith("/") else url + "/"


def versions(form, name, required=False):
    text = field(form, name, required)
    found = re.findall(r"\d+", text)
    if text and (not found or re.sub(r"[\d,;\s]", "", text)):
        raise Problem(f"**{name}** should be document versions, numbers such as `5` or `5, 6`, "
                      f"not `{text}`.")
    return [int(n) for n in found]


def position(form):
    value = field(form, "Position")
    if value and not value.isdigit():
        raise Problem(f"**Position** should be a number (1 for the first), not `{value}`.")
    return int(value) if value else None


def date(form, name):
    value = field(form, name)
    if value and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", value):
        raise Problem(f"The field **{name}** should be a date written as YYYY-MM-DD, not `{value}`.")
    return value


def licence(form, name):
    value = field(form, name)
    m = re.search(r"\(([a-z0-9.-]+)\)\s*$", value)
    if m and m.group(1) in LICENCES:
        return m.group(1)
    if value.lower().startswith("all rights reserved"):
        return "All rights reserved"
    return None


# --- the archive, its lines and its collections ------------------------------

def settings():
    return json.loads(Path("osheaf.json").read_text(encoding="utf-8"))


def save_settings(s):
    Path("osheaf.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def own_base():
    return settings().get("baseUrl", "")


def same_archive(a, b):
    return str(a or "").rstrip("/") == str(b or "").rstrip("/")


def discovery():
    path = Path("opensheaf.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def labels():
    """{label: the entry of the discovery document} of the lines of this archive."""
    return {o["label"]: o for o in discovery().get("objects", []) if o.get("label")}


def catalogues():
    """The labels of the owner catalogues (section 8.1), named in owners of the discovery document."""
    ids = {e.get("catalogue") for e in discovery().get("owners", []) if isinstance(e, dict)}
    return {label for label, o in labels().items() if o.get("id") in ids}


def label_of(name, owner):
    return next((label for label, o in labels().items()
                 if o.get("name") == name and o.get("owner") == owner), None)


def object_dir(entry):
    """The folder of a line (an entry of the discovery document) in the storage root."""
    obj_id = entry["id"]
    if "hash" in settings().get("storageLayout", ""):
        h = hashlib.sha256(obj_id.encode("utf-8")).hexdigest()
        enc = "".join(c if re.match(r"[A-Za-z0-9_-]", c) else "".join(f"%{b:02x}" for b in c.encode("utf-8"))
                      for c in obj_id)
        if len(enc) > 100:
            enc = enc[:100] + "-" + h
        return Path("ocfl") / h[0:3] / h[3:6] / h[6:9] / enc
    return Path("ocfl") / entry["owner"] / entry["name"]


def list_path(label):
    return COLLECTIONS / f"{label}.yaml"


def all_collections():
    return sorted(p.stem for p in COLLECTIONS.glob("*.yaml")) if COLLECTIONS.exists() else []


def collection(form, required):
    """The collection a form names in **In collection**, or '' when it may be
    left empty."""
    label = field(form, "In collection")
    if not label:
        if required:
            known = all_collections()
            raise Problem("Name the collection in **In collection**"
                          + (": the archive's collections are " + ", ".join(f"`{k}`" for k in known)
                             if known else "; the archive has none yet (create one with the form "
                             "**New collection**)") + ".")
        return ""
    if not LABEL.match(label) or not list_path(label).exists():
        known = all_collections()
        raise Problem(f"The archive has no collection `{label}`"
                      + (": its collections are " + ", ".join(f"`{k}`" for k in known)
                         if known else " (none has been created yet)") + ".")
    return label


def load(label):
    data = yaml.safe_load(list_path(label).read_text(encoding="utf-8")) or {}
    if data.get("members") is None:
        data["members"] = []
    return data


def save(label, data):
    path = list_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=200)
    path.write_text(HEADER + text, encoding="utf-8")


def head_file(label, name):
    """A file of the head version of the line LABEL of this archive, as JSON."""
    entry = labels().get(label)
    if entry is None:
        return None
    d = object_dir(entry)
    inv = json.loads((d / "inventory.json").read_text(encoding="utf-8"))
    state = inv["versions"][inv["head"]]["state"]
    digest = next((dg for dg, paths in state.items() if name in paths), None)
    if digest is None:
        return None
    return json.loads((d / inv["manifest"][digest][0]).read_text(encoding="utf-8"))


def document_version(label):
    return head_file(label, "object.json")["documentVersion"]


def document_labels():
    return sorted(k for k, o in labels().items() if o.get("kind") == "document")


def known_document(label):
    """A document of this archive, by its label."""
    entry = labels().get(label)
    if entry is None or entry.get("kind") != "document":
        known = document_labels()
        raise Problem(f"The archive has no paper labelled `{label}`"
                      + (": its papers are " + ", ".join(f"`{k}`" for k in known[:40]) if known else "")
                      + ".")
    return entry


# --- members of collections --------------------------------------------------
# A member is written in collections/LABEL.yaml as {label: L} (a line of this
# archive) or {uri: sheaf:<name>:<owner>, at: [URL, ...]} (a line of any
# archive); it is known by (name, owner).

def parse_sheaf(text):
    """(name, owner, at or '') of a sheaf: URI of a line, or None."""
    m = SHEAF.match(text.strip())
    if not m:
        return None
    query = urllib.parse.parse_qs(m.group(4) or "")
    return m.group(1), m.group(2), (query.get("at") or [""])[0]


def entry_key(entry):
    """(name, owner) of a member written in a collection's file."""
    if isinstance(entry, str):
        entry = {"uri": entry}
    if entry.get("label"):
        o = labels().get(entry["label"])
        return (o["name"], o["owner"]) if o else (None, None)
    parsed = parse_sheaf(str(entry.get("uri", "")))
    return parsed[:2] if parsed else (None, None)


def read_discovery(base):
    """The discovery document of the archive at BASE (an https base URL)."""
    try:
        with urllib.request.urlopen(base + "opensheaf.json", timeout=60) as r:
            return json.load(r)
    except Exception as e:
        raise Problem(f"The archive at `{base}` could not be read ({e}): give the address of an "
                      "OpenSheaf archive of specification 0.2, the folder that holds its `opensheaf.json`.")


def member_ref(form, name, archive_name, required=True):
    """The member a form names: a sheaf: URI (with or without its `at`), or a
    label, of this archive or of the archive given in ARCHIVE_NAME. Returns
    (the entry to write, (name, owner), a short text for messages)."""
    text = field(form, name, required)
    if not text:
        return None, (None, None), ""
    archive = archive_url(form, archive_name, required=False)
    if text.startswith("sheaf:"):
        parsed = parse_sheaf(text)
        if parsed is None:
            raise Problem(f"`{text}` is not the sheaf: URI of a line (`sheaf:<name>:<owner>`, "
                          "possibly with `?at=...`).")
        nm, owner, at = parsed
        own = label_of(nm, owner)
        if own:
            return {"label": own}, (nm, owner), f"`{own}`"
        at = archive or at
        if at and not at.startswith("https://"):
            raise Problem(f"The `at` of `{text}` should be the https address of an archive.")
        entry = {"uri": f"sheaf:{nm}:{owner}"}
        if at:
            entry["at"] = [at]
        return entry, (nm, owner), f"`sheaf:{nm[:12]}...`" + (f" ({at})" if at else "")
    if not LABEL.match(text):
        raise Problem(f"**{name}** should be a label (`kpz-uniqueness`) or a sheaf: URI "
                      f"(`sheaf:<name>:<owner>`), not `{text}`.")
    if not archive or same_archive(archive, own_base()):
        o = labels().get(text)
        if o is None:
            raise Problem(f"This archive has no line labelled `{text}`; for a line of another "
                          f"archive, give its address in **{archive_name}**.")
        return {"label": text}, (o["name"], o["owner"]), f"`{text}`"
    o = next((o for o in read_discovery(archive).get("objects", []) if o.get("label") == text), None)
    if o is None:
        raise Problem(f"The archive at `{archive}` has no line labelled `{text}`.")
    return ({"uri": f"sheaf:{o['name']}:{o['owner']}", "at": [archive]}, (o["name"], o["owner"]),
            f"`{text}` of {archive}")


def find(data, key, text):
    hits = [m for m in data["members"] if entry_key(m) == tuple(key)]
    if not hits:
        raise Problem(f"{text} is not a member of this collection.")
    return hits[0]


def insert(data, member, where):
    if where and 1 <= where <= len(data["members"]):
        data["members"].insert(where - 1, member)
    else:
        data["members"].append(member)


def own_children(label):
    return [m["label"] for m in load(label)["members"]
            if isinstance(m, dict) and m.get("label") and list_path(m["label"]).exists()]


def descendants(label, seen=None):
    seen = set() if seen is None else seen
    for child in own_children(label):
        if child not in seen:
            seen.add(child)
            descendants(child, seen)
    return seen


def parents(label):
    return [c for c in all_collections() if c != label and any(
        isinstance(m, dict) and m.get("label") == label for m in load(c)["members"])]


def vetted(label, key):
    """The document versions of the member KEY (name, owner) that the selection
    LABEL pins now (from its members.json), also when its file names none."""
    members = (head_file(label, "members.json") or {}).get("members", [])
    for m in members:
        if (m.get("name"), m.get("owner")) == tuple(key):
            return [r["documentVersion"] for r in m.get("revisions", [])]
    return []


# --- running osheaf ----------------------------------------------------------

def osheaf(*args):
    result = subprocess.run(OSHEAF + [str(a) for a in args], capture_output=True, text=True)
    if result.returncode != 0:
        out = (result.stderr or result.stdout).strip().splitlines()
        errors = [l for l in out if l.startswith("osheaf: error:")]
        raise Problem("osheaf stopped with this message:\n\n```\n"
                      + "\n".join(errors or out[-15:]) + "\n```")
    added.extend(l.strip() for l in result.stdout.splitlines() if ADDED.match(l.strip()))
    return result.stdout


def sync(label, message):
    """A new version of the collection LABEL from its file, if it changed; a
    catalogue then follows its followed members (as far as their archives can
    be read: an archive that cannot be read now stops nothing)."""
    osheaf("collection", "sync", label, "--from", list_path(label), "--message", message)
    if load(label).get("type") != "selection":
        try:
            osheaf("collection", "update", label)
        except Problem:
            pass


def propagate(label, message, seen=None):
    """Bring the collections that include a changed collection up to date: a
    selection vets its new version, a catalogue follows it."""
    seen = set() if seen is None else seen
    for parent in parents(label):
        if parent in seen:
            continue
        seen.add(parent)
        data = load(parent)
        member = next(m for m in data["members"] if isinstance(m, dict) and m.get("label") == label)
        if data.get("type") == "selection":
            dv = document_version(label)
            o = labels()[label]
            revisions = list(member.get("revisions") or vetted(parent, (o["name"], o["owner"])))
            if dv not in revisions:
                member["revisions"] = sorted(revisions + [dv])
            save(parent, data)
            sync(parent, message)
        else:
            member["follow"] = True
            save(parent, data)
            sync(parent, message)
        propagate(parent, message, seen)


# --- attachments ---------------------------------------------------------------

def safe_name(text):
    text = Path(text.strip() or "file").name
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.") or "file"


def download(form, name, folder):
    """The files attached to a field: links in an issue, or files of the
    request's folder (a page's request, see main), copied into folder."""
    files = []
    for fname in form.get("__files__", {}).get(name, []):
        source = (form["__dir__"] / fname).resolve()
        if form["__dir__"].resolve() not in source.parents or not source.is_file():
            raise Problem(f"The file `{fname}` of **{name}** is not in the request.")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_name(Path(fname).name)
        path.write_bytes(source.read_bytes())
        files.append(path)
    for text, url in LINK.findall(form.get(name, "")):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_name(text or url.rsplit("/", 1)[-1])
        n = 1
        while path.exists():
            path = path.with_name(f"{path.stem}-{n}{path.suffix}")
            n += 1
        cmd = ["curl", "-fsSL", "--retry", "3", "-o", str(path)]
        token = os.environ.get("GITHUB_TOKEN")
        if token and url.startswith("https://github.com/"):
            cmd += ["-H", f"Authorization: Bearer {token}"]  # not sent on to other hosts
        result = subprocess.run(cmd + [url], capture_output=True, text=True)
        if result.returncode != 0:
            raise Problem(f"The file `{text}` attached to **{name}** could not be downloaded "
                          f"({result.stderr.strip() or 'curl failed'}).")
        files.append(path)
    return files


def unpack(archive, folder):
    """Extract a zip safely: no absolute paths, no '..', no system files."""
    names = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            parts = Path(info.filename).parts
            if info.is_dir() or not parts or info.filename.startswith("/") or ".." in parts \
                    or parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
                continue
            target = folder / Path(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            names.append(Path(*parts).as_posix())
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) == 1 and all("/" in n for n in names):
        top = tops.pop()
        return folder / top, [n.split("/", 1)[1] for n in names]
    return folder, names


def sources(form, work):
    attached = download(form, "Sources", work / "attached")
    main_name = field(form, "Main source")
    if not attached:
        return None, []
    if len(attached) == 1 and attached[0].suffix.lower() == ".zip":
        root, names = unpack(attached[0], work / "sources")
        if not names:
            raise Problem("The zip of the sources is empty.")
        if main_name:
            if main_name not in names:
                raise Problem(f"The main source `{main_name}` is not in the zip; it holds: "
                              + ", ".join(f"`{n}`" for n in sorted(names)[:30]) + ".")
            main = main_name
        else:
            candidates = [n for n in names if "/" not in n
                          and Path(n).suffix.lower() in SOURCE_SUFFIXES]
            if len(candidates) != 1:
                raise Problem("Say which file of the zip is the main source, in the field "
                              "**Main source** (for instance `paper.tex`).")
            main = candidates[0]
        return root / main, [(root / n, n) for n in names if n != main]
    if len(attached) == 1:
        return attached[0], []
    if not main_name:
        raise Problem("Several source files are attached: put them in one zip, or say which one "
                      "is the main source in the field **Main source**.")
    named = [p for p in attached if p.name == safe_name(main_name)]
    if not named:
        raise Problem(f"The main source `{main_name}` is not among the attached files.")
    return named[0], [(p, p.name) for p in attached if p is not named[0]]


def current_description(label):
    d = head_file(label, "datacite.json")
    if d is None:
        return None, []
    title = (d.get("titles") or [{}])[0].get("title")
    authors = []
    for c in d.get("creators", []):
        aff = [a.get("name") if isinstance(a, dict) else a for a in c.get("affiliation", [])]
        authors.append(c["name"] + (f"|{aff[0]}" if aff and aff[0] else ""))
    return title, authors


# --- the operations ------------------------------------------------------------
# Each returns (collection changed or '', commit subject, issue title, what was done).

def deposit(form, origin):
    what = field(form, "This deposit", required=True)
    if what not in (NEW_PAPER, NEW_VERSION):
        raise Problem(f"**This deposit** is \"{NEW_PAPER}\" or \"{NEW_VERSION}\".")
    new = what == NEW_PAPER
    label = label_field(form, "Label", limit=32 if new else 64)
    cid = collection(form, required=False)
    entry = labels().get(label)
    if new and entry is not None:
        raise Problem(f"`{label}` is already the label of a {entry.get('kind', 'line')} of this archive: "
                      f"for a new version of it, choose \"{NEW_VERSION}\"; for a new paper, another label.")
    if not new:
        known_document(label)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        pdfs = [p for p in download(form, "PDF of this version", work / "pdf")
                if p.suffix.lower() == ".pdf"]
        if not pdfs:
            raise Problem("Attach the PDF of this version to the field **PDF of this version**.")
        main, others = sources(form, work)
        missing = field(form, "If there are no sources, why")
        if main is None and not missing:
            raise Problem("Attach the sources (one file, or a zip), or say why there are none in "
                          "the field **If there are no sources, why**.")
        args = ["deposit", label] + ([main] if main is not None else []) + ["--pdf", pdfs[0]]
        if new:
            args.append("--new")
        if main is None:
            args += ["--no-source", missing]
        if licence_file := field(form, "Licence file"):
            if main is None:
                raise Problem("A **Licence file** must be one of the sources; there are none.")
            if licence_file not in [main.name] + [logical for _, logical in others]:
                raise Problem(f"The licence file `{licence_file}` is not among the sources: give its path "
                              "inside the zip (for instance `LICENSE`).")
            args += ["--licence-file", licence_file]
        for path, logical in others:
            args += ["--extra-source", f"{path}={logical}"]
        title, authors = field(form, "Title"), lines(field(form, "Authors"))
        if not new and (not title or not authors):
            # a new version: what is left empty stays as in the current version
            old_title, old_authors = current_description(label)
            title, authors = title or old_title, authors or old_authors
        if not title or not authors:
            raise Problem("Give the **Title** and the **Authors** (they can be left empty only for "
                          "a new version of a paper already in the archive).")
        args += ["--title", title]
        for author in authors:
            args += ["--author", author]
        if abstract := field(form, "Abstract"):
            (work / "abstract.txt").write_text(abstract + "\n", encoding="utf-8")
            args += ["--abstract-file", work / "abstract.txt"]
        for keyword in re.split(r"[,;\n]", field(form, "Keywords")):
            if keyword.strip():
                args += ["--keyword", keyword.strip()]
        rights = licence(form, "Licence")
        if rights:
            args += ["--rights", rights]
        elif new:
            raise Problem("Choose a **Licence** for a new paper (\"Keep as before\" is for new "
                          "versions). \"All rights reserved\" lets readers read the paper but not "
                          "copy it; CC BY 4.0 lets anyone copy it with credit. Check what your "
                          "publisher allows for papers published in journals.")
        for related in lines(field(form, "Related identifiers")):
            args += ["--related", related]
        if changes := field(form, "What changed (for a new version)"):
            args += ["--changes", changes]
        if available := date(form, "Date this version became public"):
            args += ["--available", available]
        if issued := date(form, "Date the paper first appeared"):
            args += ["--issued", issued]
        args += ["--message", f"Deposit from {origin}"]
        osheaf(*args)
    where = place(form, cid, label)
    kind = "new paper" if new else "new version"
    return (cid, f"Deposit {label}, {kind}{where} ({origin})", f"Deposit: {label}",
            f"`{label}` was deposited ({kind}){where}")


def place(form, cid, label):
    """Adds a document of this archive to the collection cid (if any), or,
    in a selection where it is already, vets its current version."""
    if not cid:
        return ""
    data = load(cid)
    o = labels()[label]
    member = next((m for m in data["members"] if entry_key(m) == (o["name"], o["owner"])), None)
    if member is None:
        entry = {"label": label}
        if data.get("type") != "selection":
            entry["follow"] = True
        insert(data, entry, position(form))
    elif data.get("type") == "selection":
        # the curator deposited this version: it is vetted
        dv = document_version(label)
        member["revisions"] = sorted(set(list(member.get("revisions")
                                              or vetted(cid, (o["name"], o["owner"]))) + [dv]))
    save(cid, data)
    return f" in the collection `{cid}`"


def arxiv(form, origin):
    """A paper from arXiv, with all its versions or some of them, byte for
    byte (osheaf arxiv fetch, then import). Only with the right to
    redistribute it: the author deposits it, or the authors gave permission;
    recorded as the agreement of each version."""
    m = ARXIV.match(field(form, "arXiv identifier", required=True).strip())
    if not m:
        raise Problem("**arXiv identifier** should look like `2303.18112` (or `math/0601001`), "
                      "possibly with a version (`2303.18112v2`) or as the address of its page.")
    aid, version = m.group(1), m.group(2)
    entry = labels().get(field(form, "Label"))
    label = label_field(form, "Label", limit=64 if entry else 32)
    if entry is not None and entry.get("kind") != "document":
        raise Problem(f"`{label}` is a {entry.get('kind')} of this archive, not a paper.")
    grounds = field(form, "Right to deposit it", required=True)
    who = lines(field(form, "Who agreed"))
    if grounds == AUTHOR:
        if len(who) != 1:
            raise Problem("Give your name in **Who agreed** (Family, Given): you deposit it as an author.")
        method = "deposited by an author, from arXiv"
    elif grounds == PERMISSION:
        how = field(form, "How the permission was given")
        if not who or not how:
            raise Problem("Give **Who agreed** (the authors who gave permission, one per line) and "
                          "**How the permission was given** (for instance \"by e-mail, 3 May 2026\").")
        method = f"permission of the authors to deposit it from arXiv: {how}"
    else:
        raise Problem("Choose in **Right to deposit it** why you may deposit this paper: arXiv's "
                      "licence lets arXiv distribute a paper, not others. Only its authors, or "
                      "someone with their permission, can deposit it here.")
    wanted = field(form, "Versions")
    if wanted.lower() in ("", "all", "all versions"):
        wanted = version or ""
    only = [v if v.startswith("v") else f"v{v}" for v in re.split(r"[,\s]+", wanted.lower()) if v]
    if any(not re.fullmatch(r"v\d+", v) for v in only):
        raise Problem("**Versions** should be empty (all), or arXiv's versions: `v1, v3`.")
    cid = collection(form, required=False)
    exists = entry is not None
    with tempfile.TemporaryDirectory() as tmp:
        dl = Path(tmp) / "downloads"
        osheaf("arxiv", "fetch", dl, aid)
        ids = Path(tmp) / "identifiers.json"
        ids.write_text(json.dumps({aid: label}), encoding="utf-8")
        args = ["arxiv", "import", dl, aid, "--identifiers", ids, "--agreement", method]
        for name in who:
            args += ["--agreed-by", name.partition("|")[0].strip()]
        if only:
            args += ["--versions", ",".join(only)]
        if exists:
            args.append("--update")
        out = osheaf(*args)
        if exists and "skipped" in out:
            raise Problem(f"`{label}` is already in the archive, but not as arXiv:{aid}.")
    if label not in labels():
        raise Problem(f"Nothing was imported from arXiv:{aid}:\n\n```\n{out.strip()[-1500:]}\n```")
    where = place(form, cid, label)
    which = f"versions {', '.join(only)}" if only else "all its versions"
    return (cid, f"Import {label} from arXiv:{aid}, {which}{where} ({origin})", f"From arXiv: {label}",
            f"`{label}` was imported from arXiv:{aid} ({which}){where}")


def notice(form, origin):
    label = label_field(form, "Label")
    known_document(label)
    about = field(form, "Document version it is about", required=True)
    if not about.isdigit():
        raise Problem(f"**Document version it is about** should be a number (1, 2, ...), "
                      f"not `{about}`.")
    args = ["notice", label, "--about", about, "--text", field(form, "Text of the notice", True)]
    with tempfile.TemporaryDirectory() as tmp:
        files = download(form, "Full statement (optional)", Path(tmp))
        if files:
            args += ["--file", files[0]]
        args += ["--message", f"Notice from {origin}"]
        osheaf(*args)
    return ("", f"Notice about {label}, version {about} ({origin})",
            f"Notice: {label}, version {about}", f"`{label}` was given a notice")


def withdraw(form, origin):
    label = label_field(form, "Label")
    known_document(label)
    osheaf("withdraw", label, "--reason", field(form, "Reason for the withdrawal", True),
           "--message", f"Withdrawal from {origin}")
    return ("", f"Withdraw {label} ({origin})", f"Withdrawal: {label}",
            f"`{label}` was withdrawn (its files stay in the archive)")


def relicense(form, origin):
    label = label_field(form, "Label")
    known_document(label)
    rights = licence(form, "New licence")
    if rights not in LICENCES:
        raise Problem("Choose the new licence in the field **New licence**.")
    args = ["relicense", label, "--rights", rights, "--method",
            field(form, "How the authors agreed", required=True)]
    args += ["--message", f"New licence from {origin}"]
    osheaf(*args)
    return ("", f"Relicense {label} as {rights} ({origin})", f"Licence: {label}, {rights}",
            f"`{label}` was relicensed as {rights}")


def make_collection(label, title, kind, description, message):
    data = {"title": title}
    if description:
        data["description"] = description
    data.update({"type": kind, "order": "manual", "members": []})
    save(label, data)
    sync(label, message)


def feature(label):
    s = settings()
    s.setdefault("index", {}).setdefault("html", {"templates": "templates"})["featured"] = label
    save_settings(s)


def new_collection(form, origin):
    label = label_field(form, "Label of the new collection", limit=32)
    if list_path(label).exists() or label in labels() or label in catalogues():
        raise Problem(f"`{label}` is already taken in this archive.")
    title = field(form, "Title of the collection", required=True)
    kind = "catalogue" if field(form, "Kind").lower().startswith("catalogue") else "selection"
    parent = collection(form, required=False)
    make_collection(label, title, kind, field(form, "Description"), f"New collection {label} ({origin})")
    if field(form, "Feature it on the home page").lower().startswith("yes"):
        feature(label)
    if parent:
        pdata = load(parent)
        entry = {"label": label}
        if pdata.get("type") != "selection":
            entry["follow"] = True
        insert(pdata, entry, position(form))
        save(parent, pdata)
        where = f" in the collection `{parent}`"
    else:
        where = ""
    return (parent, f"New collection {label}{where} ({origin})", f"Collection: {label}",
            f"the collection `{label}` was created{where}")


def add(form, origin):
    cid = collection(form, required=True)
    data = load(cid)
    entry, key, text = member_ref(form, "New member", "Archive of the new member")
    revisions = versions(form, "Versions you vet (selection)")
    if any(entry_key(m) == key for m in data["members"]):
        raise Problem(f"{text} is already a member of `{cid}`.")
    own = entry.get("label")
    if own and (own in catalogues() or own == cid
                or (list_path(own).exists() and cid in descendants(own))):
        raise Problem(f"`{own}` cannot be a member of itself, or of a collection inside it.")
    if data.get("type") == "selection":
        if revisions:
            entry["revisions"] = revisions
    else:
        if revisions:
            raise Problem(f"Versions are vetted only in a selection; `{cid}` is a catalogue, which "
                          "follows its members. Leave **Versions you vet** empty.")
        entry["follow"] = True
    insert(data, entry, position(form))
    save(cid, data)
    return (cid, f"Add {text.replace('`', '')} to {cid} ({origin})",
            f"Member added to {cid}", f"{text} was added to `{cid}`")


def vet(form, origin):
    cid = collection(form, required=True)
    data = load(cid)
    if data.get("type") != "selection":
        raise Problem(f"Versions are vetted only in a selection; `{cid}` is a catalogue, which "
                      "follows its members (run **Update the collections** in the Actions tab to "
                      "move them on).")
    _, key, text = member_ref(form, "Member", "Archive of the member")
    member = find(data, key, text)
    new = versions(form, "Versions to vet", required=True)
    old = list(member.get("revisions") or vetted(cid, key)) if isinstance(member, dict) else vetted(cid, key)
    added_ = [v for v in new if v not in old]
    if not added_:
        raise Problem(f"{text} already has the versions {', '.join(map(str, new))} vetted.")
    if not isinstance(member, dict):
        index = data["members"].index(member)
        member = data["members"][index] = {"uri": member}
    member["revisions"] = sorted(old + added_)
    save(cid, data)
    vs = ", ".join(map(str, added_))
    return (cid, f"Vet version {vs} of {text.replace('`', '')} in {cid} ({origin})",
            f"Vetted: version {vs} (in {cid})", f"version {vs} of {text} was vetted")


def remove(form, origin):
    cid = collection(form, required=True)
    data = load(cid)
    _, key, text = member_ref(form, "Member to remove", "Archive of the member")
    member = find(data, key, text)
    data["members"].remove(member)
    save(cid, data)
    return (cid, f"Remove {text.replace('`', '')} from {cid} ({origin})",
            f"Member removed from {cid}", f"{text} was removed from `{cid}`")


def key_log_folder(form, work):
    """The folder of the owner object (the key log) given to the setup: a zip
    attached to the request, or the folder key-log/ of the repository."""
    zips = download(form, "Key log of the owner", work / "attached")
    if zips:
        if len(zips) != 1 or zips[0].suffix.lower() != ".zip":
            raise Problem("Attach the key log of the owner as one zip of its folder.")
        root, _ = unpack(zips[0], work / "key-log")
        return root
    if KEY_LOG.is_dir():
        return KEY_LOG
    raise Problem(
        "The archive needs its owner's key log, made on your computer by the key ceremony of the "
        "README (`osheaf init` with `--new-owner`, then a key for GitHub's workflows): add the "
        "folder of the owner object (`ocfl/<owner>/<owner>/` of the archive where it was made) to "
        "the repository as `key-log/`, or attach it as a zip. The repository secret "
        f"`{SIGNING_KEY}` must hold the current key made for the workflows.")


def github_api(path):
    """A GET of GitHub's API with the workflow's token (GITHUB_TOKEN or
    GH_TOKEN), as JSON, or None if it fails (absent, not allowed)."""
    request = urllib.request.Request(f"https://api.github.com/{path}", headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def redirected_host(url):
    """The host that URL redirects to (a GitHub Pages site with a custom
    domain), or ''."""
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, method="HEAD"), timeout=30)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 307, 308):
            return urllib.parse.urlsplit(e.headers.get("Location", "")).hostname or ""
    except Exception:
        pass
    return ""


def site_url(url):
    """An address of a site as a base URL: https, ending with /."""
    url = re.sub(r"^http://", "https://", url.strip())
    return url if url.endswith("/") else url + "/"


def default_base_url(repo):
    """Where GitHub Pages serve the repository's site, and the rule that
    said so: (a) the repository's own Pages site, if on; (b) the custom
    domain of the owner's Pages (the repository OWNER.github.io: its cname,
    or where https://OWNER.github.io/ redirects), whose project sites are at
    https://DOMAIN/REPOSITORY/; (c) https://OWNER.github.io/REPOSITORY/."""
    owner, name = repo.split("/", 1)
    user = owner.lower()
    own = github_api(f"repos/{repo}/pages") or {}
    if own.get("html_url"):
        return site_url(own["html_url"]), "the address of the repository's GitHub Pages site"
    path = "" if name.lower() == f"{user}.github.io" else f"{name}/"
    domain = (github_api(f"repos/{owner}/{owner}.github.io/pages") or {}).get("cname") \
        or redirected_host(f"https://{user}.github.io/")
    if domain and not domain.lower().endswith(".github.io"):
        return (f"https://{domain.lower()}/{path}",
                f"the domain of the owner's GitHub Pages ({owner}.github.io is served at {domain.lower()})")
    return f"https://{user}.github.io/{path}", "the GitHub Pages address of the owner (no domain of its own found)"


def setup(form, origin):
    """Set the archive up (osheaf init with an existing owner, whose key log
    was made by the key ceremony), for the workflow "Set up the archive" and
    for a page, which cannot start workflows."""
    if Path("osheaf.json").exists():
        raise Problem("The archive is already set up.")
    repo = os.environ.get("GITHUB_REPOSITORY", "owner/archive")
    if base := field(form, "Base URL"):
        base, rule = site_url(base), "as given"
    else:
        base, rule = default_base_url(repo)
    title = field(form, "Name", required=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = key_log_folder(form, Path(tmp))
        try:
            inv = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
            _, owner, again = inv["id"].split(":")
            assert owner == again
        except Exception:
            raise Problem("The key log given is not the folder of an owner object: it should hold the "
                          "`inventory.json` of `sheaf:<owner>:<owner>` (copy `ocfl/<owner>/<owner>/` of the "
                          "archive where the owner was made).")
        if given := field(form, "Owner"):
            if given != owner:
                raise Problem(f"The key log given is that of the owner `{owner}`, not `{given}`.")
        args = ["init", ".", "--owner", owner, "--key-log", folder, "--name", title, "--base-url", base,
                "--curator", field(form, "Curator", required=True)]
        for label, option in (("Affiliation", "--affiliation"), ("Contact", "--contact")):
            if value := field(form, label):
                args += [option, value]
        osheaf(*args)
    if wallet := field(form, "Key wallet"):
        # a hint, in osheaf.json, of the wallet that holds the owner's keys (as the manager records it)
        osheaf("key", "wallet", "--owner", owner, "--add", wallet)
    if KEY_LOG.is_dir():
        shutil.rmtree(KEY_LOG)   # now in the storage root, at ocfl/<owner>/<owner>/
    purpose = field(form, "Purpose").lower() or "papers"
    if purpose in ("selection", "catalogue"):
        label = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32].strip("-") or "collection"
        if label in catalogues():
            label += "-collection"
        make_collection(label, title, purpose, field(form, "Description"),
                        f"The collection is set up ({origin})")
        feature(label)
        done = (f"the archive was set up, owned by `{owner}`, with the collection `{label}` featured "
                "on its home page")
    else:
        done = f"the archive was set up, owned by `{owner}`"
    done += (f". Its base URL is {base} ({rule}); if that is not where its site is served, change "
             "`baseUrl` in `osheaf.json` and run `osheaf index`")
    return ("", f"Set up the archive: {title} ({origin})", f"Setup: {title}", done)


OPERATIONS = {"setup": setup, "deposit": deposit, "notice": notice, "withdraw": withdraw, "relicense": relicense,
              "new_collection": new_collection, "add": add, "vet": vet, "remove": remove, "arxiv": arxiv}


def snapshot():
    files = [Path("osheaf.json")] + (sorted(COLLECTIONS.glob("*.yaml")) if COLLECTIONS.exists() else [])
    return {p: p.read_text(encoding="utf-8") for p in files if p.exists()}


def restore(saved):
    for p in (list(COLLECTIONS.glob("*.yaml")) if COLLECTIONS.exists() else []):
        if p not in saved:
            p.unlink()
    for p, text in saved.items():
        p.write_text(text, encoding="utf-8")


def read_request(path):
    """A page's request: requests/ID/request.json, with the operation, the
    fields of the corresponding form (by their labels), and the files
    attached to fields, in the request's folder."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    form = {k: str(v) for k, v in (data.get("fields") or {}).items()}
    form["__files__"] = {k: list(v) for k, v in (data.get("files") or {}).items()}
    form["__dir__"] = path.parent
    return data.get("operation"), form, f"request {path.parent.name}"


def check_signing_key():
    """In GitHub's workflows, the owner's versions are signed with the key in
    the repository secret OPENSHEAF_SIGNING_KEY: without it, nothing can be
    deposited."""
    if os.environ.get("GITHUB_ACTIONS") and not os.environ.get(SIGNING_KEY, "").strip():
        raise Problem(
            f"The repository secret `{SIGNING_KEY}` is not set, so the archive's workflows cannot sign "
            "for its owner. Make the owner's key for the workflows on your computer and store it as that "
            "secret (Settings, Secrets and variables, Actions), as the README says (the key ceremony).")


def main():
    result_file = Path(os.environ.get("RESULT_FILE", "result.md"))
    if len(sys.argv) == 2 and sys.argv[1] == "--base-url":
        # for the workflow "Set up the archive": the base URL and its rule
        base, rule = default_base_url(os.environ.get("GITHUB_REPOSITORY", "owner/archive"))
        print(f"BASE_URL={base}\nBASE_RULE={rule}")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--request":
        kind, form, origin = read_request(sys.argv[2])
        if kind not in OPERATIONS:
            result_file.write_text(f"Unknown operation `{kind}`.\n", encoding="utf-8")
            return 1
    else:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        issue = event["issue"]
        form = sections(issue.get("body"))
        kind = next((FORMS[h] for h in FORMS if h in form), None)
        origin = f"issue #{issue['number']}"
        if kind is None:
            result_file.write_text("This issue is not one of the archive's forms.\n",
                                   encoding="utf-8")
            return 2
    saved = snapshot() if Path("osheaf.json").exists() else {}
    try:
        check_signing_key()
        if kind != "setup" and not Path("osheaf.json").exists():
            raise Problem("The archive is not set up yet: set it up first (the workflow **Set up "
                          "the archive** in the Actions tab, or the manager's setup).")
        cid, message, title, done = OPERATIONS[kind](form, origin)
        if why := field(form, "Why (optional)"):
            message += f": {why}"
        osheaf("collect")
        if cid:
            sync(cid, message)
            propagate(cid, message)
        osheaf("index")
        osheaf("verify")
    except Problem as p:
        restore(saved)
        result_file.write_text(
            f"Nothing was changed in the archive.\n\n{p}\n\n"
            + ("Edit this issue to correct it, then close and reopen it to try again.\n"
               if origin.startswith("issue") else "Correct it and send the request again.\n"),
            encoding="utf-8")
        return 1
    result_file.write_text(
        f"Done: {done}.\n\nThe archive's site, <{own_base()}>, shows it once GitHub Pages has "
        "published it (usually within a few minutes).\n", encoding="utf-8")
    body = "\n".join(dict.fromkeys(added))
    Path(os.environ.get("COMMIT_FILE", "commit.txt")).write_text(
        message + "\n" + (f"\n{body}\n" if body else ""), encoding="utf-8")
    Path(os.environ.get("TITLE_FILE", "title.txt")).write_text(title + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
