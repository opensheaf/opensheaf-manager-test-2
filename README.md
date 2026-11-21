# An OpenSheaf archive

> [!WARNING]
> **Draft.** OpenSheaf 0.2 is a draft specification. Until version 1.0, any
> revision may change the format in incompatible ways. Archives and collections made now
> may have to be rebuilt or migrated, and the tools follow the latest draft.
> Do not rely on it yet for anything you cannot redo.

A template for an archive of papers, and for collections of papers from any
archive: your own papers, every version with its sources and PDF, fixed by
digests and signed by you, with standard metadata, a website with a page per
paper (read by Google Scholar), and optionally DOIs from Zenodo; and
collections, such as a reading list, a journal issue or the papers of a
group, which pin papers of any OpenSheaf archive without copying them. A
repository can be mainly an author's archive, mainly a collection, or both.
The archive is plain files in a git repository, following the
[OpenSheaf specification](https://opensheaf.org), version 0.2 (an
[OCFL](https://ocfl.io) storage root with [DataCite](https://datacite.org)
metadata), and
[OpenSheaf archives in git](https://opensheaf.org/opensheaf-git-0.2.html),
and is kept with [opensheaf-py](https://github.com/opensheaf/opensheaf-py)
(the `osheaf` command).

What the specification calls a *line* is a paper with all its versions. In
the archive it has a *label*, chosen by you (`kpz-uniqueness`), which is the
address of its page, `paper/kpz-uniqueness/`; everywhere, it is named by its
*sheaf URI*, `sheaf:<name>:<owner>`, made once when the paper is first
deposited, and shown on its page. Every version is signed by the archive's
*owner*, a keyed identity (yours), whose *key log* is kept in the archive:
anyone can check that the versions are yours, wherever they find a copy.

There are two ways to keep the archive: from the browser, without git
(next sections), or with the `osheaf` command (sections 1 to 6). Both give
the same archive, and can be mixed. Either way, the owner is made once, on
your computer: the key ceremony.

## The key ceremony: the owner and its keys

An owner has two kinds of keys (section 6 of the specification):

- **current keys** sign the versions of your papers: one on your computer,
  kept in its credential store (the macOS keychain, for instance), and one
  for GitHub's workflows, which keep the archive when you use the browser,
  kept as the repository secret `OPENSHEAF_SIGNING_KEY`;
- **rotation keys**, three, of which any two sign a change of keys (adding
  or retiring a current key, exposing a stolen one). They are made once,
  exported, encrypted under a passphrase, to a folder outside the repository
  (a USB stick) and printed on sheets, and kept apart from your computer and
  from each other. They are never stored on the computer, never in the
  repository, never in GitHub: whoever holds two of them can change your
  keys.

So the owner is made on your computer, never by a workflow. Install the
tools once (Python 3.9 or later):

```
pipx install "opensheaf[validate] @ git+https://github.com/opensheaf/opensheaf-py"
```

Then, in a clone of your repository (section 1), with the settings of
[archive.yaml](archive.yaml) edited (the name, the address, your name, and
where the rotation keys go):

1. **The owner.** Plug in the USB stick named in `archive.yaml` (`export`)
   and run

   ```
   osheaf init . --from archive.yaml
   ```

   It asks for a passphrase (twice), writes the three rotation keys to the
   folder `export` names, prints a sheet for each (print them), and asks you
   to type back the check of each key once it is put away. It prints the
   owner name, `owner <OWNER>`, and makes the current key of this computer.
   It also writes the archive: `osheaf.json`, the storage root `ocfl/` (with
   the owner's key log at `ocfl/<OWNER>/<OWNER>/`), the empty main
   catalogue, the discovery document `opensheaf.json` and the website.

2. **A current key for the workflows**, made in a temporary folder, never in
   your credential store:

   ```
   ci=$(mktemp -d)
   OPENSHEAF_KEY_STORE=file XDG_CONFIG_HOME="$ci" osheaf key new
   ```

   It prints the key's `did:key:z6Mk...`, called `did:key:CI` below, and
   keeps its seed in a file under `$ci`.

3. **Add it to the key log**: a new version of the key log, signed by two
   rotation keys, which commits three new ones (the first three are used up:
   destroy them once this is done, and keep the new ones as you kept the
   first):

   ```
   osheaf owner rotate --add did:key:CI \
     --rotation-key /Volumes/USB/opensheaf-keys/rotation-<OWNER16>-<k1>.txt \
     --rotation-key /Volumes/USB/opensheaf-keys/rotation-<OWNER16>-<k2>.txt \
     --export /Volumes/USB/opensheaf-keys-2 --print
   ```

   (any two of the three files; it asks for their passphrase, then for the
   passphrase of the new ones.)

4. **The secret.** The key's seed, one line of base64, becomes the repository
   secret `OPENSHEAF_SIGNING_KEY`: on GitHub, **Settings**, **Secrets and
   variables**, **Actions**, **New repository secret**, name
   `OPENSHEAF_SIGNING_KEY`, and as its value the line printed by
   `cat "$ci"/opensheaf/keys/*/*.key`; or, with the GitHub command line,

   ```
   gh secret set OPENSHEAF_SIGNING_KEY -R USER/papers < "$ci"/opensheaf/keys/*/*.key
   rm -rf "$ci"
   ```

   Then delete the temporary folder: the key now lives only in GitHub.

5. **Publish**: `osheaf verify`, then `git add -A && git commit -m "The
   archive and its owner" && git push`.

`osheaf owner show` describes the key log: two current keys (this computer
and the workflows), with threshold 1, so that either signs, and the
rotation keys committed. The key of the workflows is exposed whenever the
repository is: anyone who can change its workflows can sign with it. That is
the price of keeping the archive from the browser; see
[When something goes wrong](#when-something-goes-wrong) for what to do then.

**Without a clone** (to keep the archive from the browser only): do steps 1
to 4 in a scratch folder anywhere outside a repository,

```
osheaf init owner-setup --name "Jane Doe" --base-url https://janedoe.github.io/papers/ \
  --curator "Doe, Jane" --new-owner --export /Volumes/USB/opensheaf-keys --print
cd owner-setup
```

then steps 2 to 4 there, and copy the owner's key log out of it:

```
cp -R ocfl/<OWNER>/<OWNER> ~/Desktop/key-log
```

In your repository on GitHub: **Add file**, **Upload files**, drag the
folder `key-log` (its files and folders are kept), and commit. The setup
(next section) makes the archive with this owner and removes `key-log/`.
The scratch folder can be deleted; the current key of your computer stays
in its credential store, for depositing from the command line later.

An owner may keep several archives: an archive set up with an existing owner
copies its key log from another archive (`owner:` and `key-log:` in
`archive.yaml`, or `key-log/` from `ocfl/<OWNER>/<OWNER>/` of that archive).

## From the browser

1. Press **Use this template** on GitHub, for instance as a repository called
   `papers`.
2. Do the key ceremony (previous section): the owner's key log in the
   repository as `key-log/`, and the secret `OPENSHEAF_SIGNING_KEY`.
3. In your repository: **Actions**, **Set up the archive**, **Run
   workflow**, and fill in the form: the name, what the repository is mainly
   for (**papers**; a **selection**, such as a reading list or a journal
   issue, whose curator vets particular versions; or a **catalogue**, which
   follows its members whatever their authors add), and your name; the rest
   can stay empty. For a selection or a catalogue, it creates that
   collection and features it on the home page. It sets the archive up with
   the owner of `key-log/`. It cannot turn GitHub Pages on (the workflow's
   token may not): turn it on yourself, before or after the run, in
   **Settings**, **Pages**, **Build and deployment**, Source **Deploy from a
   branch**, branch `main`, folder `/ (root)`, **Save**; the first line of
   the run's page says so. The form's last field, the base URL, is where the
   site is served; left empty, it is the address of the repository's Pages
   site if Pages is on already, otherwise, if your `USER.github.io` site has
   a domain of its own (such as `example.org`), `https://example.org/papers/`,
   otherwise `https://USER.github.io/papers/`. The run's page says which rule
   it used; if the address is wrong, change `baseUrl` in `osheaf.json` and
   run `osheaf index` (the contact, if not given, is the base URL too). (An
   archive set up on your computer, step 5 of the ceremony, needs this only
   for the labels of the issue forms and Pages: the workflow then checks the
   secret and does the rest.)
4. To deposit a paper: **Issues**, **New issue**, **New deposit**. Choose
   **A new paper**, give it a label (permanent, the address of its page), fill
   in the form and drag in the PDF and the sources (best as one zip: GitHub
   does not accept every kind of file, such as `.tex`, as an attachment),
   then submit. The workflow `from issue` deposits the paper, signs it,
   publishes the site and answers in the issue with the link to the paper's
   page. A new version: the same form, **A new version of a paper in the
   archive**, with the paper's label.
5. Notices, withdrawals and new licences have forms of their own (**Notice**,
   **Withdrawal**, **New licence**).
6. Collections:
   - **New collection**: a selection or a catalogue of this archive, possibly
     inside another (a section of a reading list, an issue of a journal),
     possibly featured on the home page;
   - **Add a member**: a paper (or a collection) of any OpenSheaf archive,
     this one included: its label in this archive, or its sheaf URI (shown
     on its page), or its label in another archive with that archive's
     address; and, in a selection, the versions you vet;
   - **Vet a new version** (selections) and **Remove a member**;
   - a deposit can also name a collection to join (**In collection**).

   When a collection inside another changes, the collections that include it
   follow (in a selection, its new version is vetted). To follow new versions
   of the members: **Actions**, **Update the collections**, **Run workflow**;
   a catalogue moves on, a selection never changes by itself and the run's
   page lists the versions you have not vetted.

Only the owner of the repository and its collaborators can change the
archive this way; issues opened by others are answered and closed. What is
attached to an issue is public at once. If something is wrong, the workflow
says so in the issue and changes nothing: edit the issue, then close and
reopen it to try again. Each issue stays as the record of what was done.
Without the secret `OPENSHEAF_SIGNING_KEY`, nothing can be signed: the
workflows say so, and change nothing.

## From another page: the OpenSheaf Manager

The [OpenSheaf Manager](https://manager.opensheaf.org/) does the same from
a page, with forms, the files picked from your computer, and the archive's
papers and collections listed. Sign in with GitHub there (installing the
OpenSheaf app on this repository), or give a fine-grained personal access
token limited to this repository (*Contents: read and write*). Each
operation is sent as a request, `requests/ID/request.json` with the files
attached; the workflow `from request` carries it out with `osheaf`, as it
does the issue forms, and writes its answer to `requests/results/ID.json`
(the last 100 answers are kept; older ones stay in the history). The
manager never makes or sees keys: its setup page guides the key ceremony,
and takes the owner's key log as a zip of the folder `key-log`. A repository
made from the template before the manager existed needs the template's
`.github/` folder brought up to date.

## 1. Make your copy

Press **Use this template** on GitHub (for instance a repository called
`papers`), clone it, and install the tools (Python 3.9 or later):

```
pipx install "opensheaf[validate] @ git+https://github.com/opensheaf/opensheaf-py"
```

## 2. Set it up

In your clone, edit [archive.yaml](archive.yaml) and do the
[key ceremony](#the-key-ceremony-the-owner-and-its-keys); its first step is

```
osheaf init . --from archive.yaml
```

or, with the settings on the command line,

```
osheaf init . --name "Papers of Jane Doe" --base-url https://janedoe.github.io/papers/ \
  --curator "Doe, Jane" --affiliation "Example University" --contact https://example.org/~jane \
  --new-owner --export /Volumes/USB/opensheaf-keys --print
```

- `--base-url` is where the site is served: with GitHub Pages,
  `https://USER.github.io/REPOSITORY/`, or, if your `USER.github.io` site
  has a domain of its own, `https://DOMAIN/REPOSITORY/` (the repository's
  **Settings**, **Pages** shows the address once Pages is on). An archive is
  named by no identifier of its own: its lines are named by their sheaf
  URIs, and the archive by where it is served.
- `--new-owner` makes the owner; `--owner OWNER --key-log DIR` uses an
  existing one, whose key log is copied from DIR, the folder of its owner
  object in another archive.

This writes `osheaf.json` (the settings, with the owner), the storage root
`ocfl/` (one folder per owner, `ocfl/<owner>/`, with its key log and its
lines), the main catalogue, the discovery document `opensheaf.json`, the
indexes (`names/`, `owners/`, `sha512/`) and the website.

## 3. Deposit a paper

Describe the paper in a YAML file, as in
[deposits/example.yaml](deposits/example.yaml), and run

```
osheaf deposit --from deposits/kpz-uniqueness.yaml
osheaf collect
osheaf index
osheaf verify
git add -A && git commit -m "Deposit kpz-uniqueness" && git push
```

Files and options are read as text, relative to the YAML file; a list of
entries deposits several papers or versions in order. The same can be done on
the command line:

```
osheaf deposit kpz-uniqueness paper.tex --pdf paper.pdf --new \
  --extra-source refs.bib --extra-source figures/fig1.pdf=figures/fig1.pdf \
  --title 'Energy solutions of KPZ are unique' \
  --author "Doe, Jane|Example University" --author "Roe, Richard|Another University" \
  --abstract-file abstract.txt --rights cc-by-4.0 \
  --related "IsIdenticalTo:arxiv:1508.07764"
```

- The label (`kpz-uniqueness`) is permanent and appears in the address of
  the paper's page: short (at most 32 characters), lower case, words joined
  by `-`. A new paper is deposited with `--new` (`new: yes` in the YAML
  file), which makes its sheaf URI, printed by the deposit; without `--new`,
  an unknown label is refused, so that a mistyped label never makes a new
  paper.
- Sources are any files (LaTeX, Markdown, ...); `--extra-source FILE=PATH`
  puts a file at the path the main source refers to. The PDF is yours: the
  archive keeps exactly the files you give. A paper whose sources are lost can
  be deposited as a PDF alone (`--no-source "the sources were lost"`).
- Titles and abstracts are plain text with mathematics in `$...$`.
- Licence: `--rights cc-by-4.0` (or `cc0-1.0`, or a statement such as
  "All rights reserved", the default); check what your publisher allows for
  papers published in journals.
- A new version: deposit again with the same label, without `--new`
  (`--changes "..."` says what changed; abstract, keywords and licence are
  kept unless given). A version written earlier but never public (a
  submitted manuscript) is deposited with `--created DATE`; one found later
  goes in its place in the history with `--after N`.
- Dates: `--available DATE` when the version became public (default today),
  `--issued DATE` when the paper first appeared anywhere.
- Every version is signed with the current key of your computer, and
  records the digest of the version before it.

A paper on arXiv can be deposited with all its versions, byte for byte,
only by one of its authors or with the authors' permission (arXiv's licence
lets arXiv distribute it, not others), which is recorded with each version:

```
osheaf arxiv fetch downloads 2303.18112
echo '{"2303.18112": "kpz-uniqueness"}' > downloads/identifiers.json
osheaf arxiv import downloads --agreement "deposited by an author" --agreed-by "Doe, Jane"
```

(`identifiers.json` gives each arXiv paper its label.) From the browser, the
issue form **From arXiv** and the manager do the same.

Nothing deposited is ever changed: corrections are new versions, and a
licence or a link is changed by a description-only version
(`osheaf relicense`, `osheaf relate`). `osheaf --help` lists everything.

## 4. Collections

A collection is a line of the archive, signed by its owner, that lists
papers (and other collections) of any OpenSheaf archive, each pinned by the
SHA-512 digest of an inventory, so that it fixes exactly what it lists and
anyone can check it (section 8 of the specification):

- a **selection** vets particular versions: a reading list the versions you
  read and recommend, a journal issue the versions its editors accepted. Its
  members pin those versions (their *revisions*), and nothing changes unless
  you change it;
- a **catalogue** follows its members whatever their authors add: the papers
  of a group, the lines a repository preserves.

The main catalogue of the archive lists the archive's own papers and is kept
by `osheaf collect`; other collections are kept apart, each with its members
in `collections/LABEL.yaml`:

```yaml
title: A reading list on stochastic quantisation
description: Papers on the stochastic quantisation of Euclidean field theories.
type: selection
order: manual
members:
  - {label: kpz-uniqueness}
  - {uri: "sheaf:<name>:<owner>", at: [https://mgubi.org/papers/], revisions: [5]}
```

A member of this archive is given by its label; a member of any archive by
its sheaf URI (on its page, or `osheaf resolve`), with `at`, the addresses
of archives that hold it (as many as you like: mirrors too). `revisions`
lists the document versions you vet (1, 2, ...); a member without it is
vetted in its current version when first synced, and keeps that revision.
For a catalogue write `type: catalogue`, and `follow: true` on the members
that follow their lines (the issue forms set it); a member without it stays
at the version first pinned. Then

```
osheaf collection sync reading-list --from collections/reading-list.yaml
osheaf index
osheaf verify --remote
```

`sync` reads each member from its archive, checks it against its owner's
key log and signatures, pins the revisions you vet (or, in a catalogue, the
latest signed version), and caches a citation, so that the list stays
readable even if a member's archive disappears.
`osheaf collection update` moves the followed members of catalogues on, and
lists, for a selection, the versions not yet vetted; `osheaf collection
status reading-list` gives each member's status (verified, contested,
unavailable, ...). To show a collection first on the home page, before the
archive's own papers, set `"featured": "reading-list"` under `index.html` in
`osheaf.json`.

## 5. Publish

On GitHub: **Settings → Pages → Deploy from a branch**, branch `main`, folder
`/ (root)`. The site is then at the base URL you chose. Every push is
checked by the workflow `verify`: `osheaf verify` (with the JSON Schemas and
an independent OCFL validator), and the checks of
[OpenSheaf archives in git](https://opensheaf.org/opensheaf-git-0.2.html)
(`.github/scripts/commit_check.py`: the attributes of
[.gitattributes](.gitattributes), which keep git from changing the archive's
files, no Git LFS pointers or links, and that the storage root only grows).
The workflows that change the archive run the same checks before they push.

Readers check the archive in the browser with the
[OpenSheaf Explorer](https://opensheaf.org/explorer/): the home page links
to it, and links name a paper by its label,

```
https://opensheaf.org/explorer/?url=https://USER.github.io/papers/#/object/kpz-uniqueness
https://opensheaf.org/explorer/?url=https://USER.github.io/papers/#/collection/reading-list
https://opensheaf.org/explorer/?url=https://USER.github.io/papers/#/owner/<OWNER>
https://opensheaf.org/explorer/?url=https://USER.github.io/papers/#/verify
```

or, on a page of the site, a button:

```html
<script src="https://opensheaf.org/explorer/embed.js" data-archive="../../"
        data-object="kpz-uniqueness"></script>
```

(`data-collection`, `data-owner` and `data-verify` likewise; `data-archive`
is the archive's folder relative to the page.) The Explorer reads the
archive from another site, so the archive's files must allow cross-origin
requests (`Access-Control-Allow-Origin: *`): the discovery document, the
storage root (with the owner's key log), the indexes, and the pages it
links to. GitHub Pages sends this header for every file; on a server of
your own, add it (for Apache, `Header set Access-Control-Allow-Origin "*"`;
for nginx, `add_header Access-Control-Allow-Origin *;`). Files must be
served byte for byte (no conversion of line endings).

## 6. Make it yours

- The look: edit `templates/index.html`, `templates/paper.html`,
  `templates/collection.html`, `templates/owner.html` and
  `templates/style.css` (placeholders like `{{title}}`, `{{sheaf_uri}}`,
  `{{owner}}`), then `osheaf index`. A landing page must keep showing the
  sheaf URI of its paper (appendix A.3 of the specification): `osheaf
  verify` checks it.
- DOIs: `osheaf zenodo LABEL` deposits the current version of a paper on
  Zenodo and records its DOI (on the Zenodo sandbox, on a copy, unless
  `--production`; tokens in the macOS keychain, see `osheaf zenodo --help`).
- Papers from arXiv: `osheaf arxiv fetch downloads --author YOUR_ARXIV_ID`,
  then `osheaf arxiv import downloads` (every version, with arXiv's files and
  licences; see the README of opensheaf-py).
- Copies of others' papers (`osheaf mirror`), branches (`osheaf branch`),
  accepted copies for a journal (`osheaf accept`), drafts: see the
  [specification](https://opensheaf.org), the README of opensheaf-py and the
  [FAQ](https://github.com/opensheaf/opensheaf.github.io/blob/main/FAQ.md).

## When something goes wrong

Each of these is done on your computer, in a clone, with the rotation keys
you keep (the latest ones: those of the last `--export`), then pushed.

- **The repository is compromised** (someone else could push to it, change
  a workflow, or read its secrets): expose the key of the workflows at once,
  which makes what it alone signed *contested* (section 6.3 of the
  specification), and give the workflows a new key:

  ```
  git pull
  ci=$(mktemp -d)
  OPENSHEAF_KEY_STORE=file XDG_CONFIG_HOME="$ci" osheaf key new      # did:key:NEW
  osheaf owner expose did:key:CI --add did:key:NEW \
    --rotation-key /Volumes/USB/opensheaf-keys-2/rotation-<OWNER16>-<k1>.txt \
    --rotation-key /Volumes/USB/opensheaf-keys-2/rotation-<OWNER16>-<k2>.txt \
    --export /Volumes/USB/opensheaf-keys-3 --print
  gh secret set OPENSHEAF_SIGNING_KEY -R USER/papers < "$ci"/opensheaf/keys/*/*.key
  rm -rf "$ci"
  osheaf verify                          # lists the contested versions
  osheaf sign LABEL --version vN         # for each contested version that you made
  git add -A && git commit -m "The key of the workflows exposed" && git push
  ```

  `osheaf sign` signs again, with the key of your computer, a version you
  know you made; one you did not make stays contested, never the latest
  signed version of its paper (or is taken down, `osheaf takedown`).
  Repair the repository first (its collaborators, its workflows, its
  tokens), or the new key is exposed in turn.
- **The secret is lost or changed by mistake** (GitHub never shows it
  again): make a new key for the workflows as in step 2 of the ceremony, and
  `osheaf owner rotate --add did:key:NEW --retire did:key:CI ...`.
- **Your computer is lost or stolen**: from another computer, `osheaf key
  new` (its own key) and `osheaf owner expose did:key:OLD --add did:key:NEW
  ...`.
- **A rotation key is lost**: with two of the three left, `osheaf owner
  rotate ...` commits three new ones at once. With fewer, the owner can no
  longer change its keys: that is why there are three.

`osheaf owner show` says which keys are current, exposed or retired; the
site shows it on the owner's page, `owner/<OWNER>/`.

## A testing ground

`examples/run.sh` builds a throwaway archive from the
[example papers](https://github.com/opensheaf/example-papers) (invented
papers, TeXmacs papers and slides from tm-forge, fake arXiv downloads) and
runs every workflow of the tools, also the unusual ones: versions deposited
out of order, a notice with an erratum, a version after a notice, the sources
of a PDF-only version found later, a new licence, an arXiv import, a
withdrawal. Clone the example papers next to your repository and run

```
examples/run.sh
```

to see what each command does (the archive goes to a temporary folder; this
repository is not changed). Its owner is a throwaway one: its keys are made
in a temporary folder, never in your credential store, and its rotation keys
are exported unencrypted there (`examples/common.sh`). The workflow
`examples` runs it on every push and every week, together with the scripts
below, and keeps the archives they built as artifacts. Delete `examples/`
when you start your own archive if you like.

`examples/collections.sh` builds a member archive from the
[example papers](https://github.com/opensheaf/example-papers) and two
collections with members from it, given by their sheaf URIs: a catalogue
(followed members, a fixed version, a member that is itself a collection)
and a selection (a reading list). It goes through their workflows: a new
version, followed by the catalogue and only reported by the selection until
the curator vets it; a withdrawal, followed by one and shown by both; a
member that disappears and is reported unavailable by `verify --remote`.
`REAL=https://.../` adds members from a published archive of specification
0.2.

`examples/requests.sh` goes through the key ceremony with a throwaway owner,
sets a copy of this template up, and keeps it with requests as the manager
sends them, carried out by the script of the issue forms and committed as
the workflow `from request` does, with the checks of the git companion on
every commit: deposits of new papers and versions, mistakes refused, notices,
licences, withdrawals, collections inside collections, members of another
archive, vetting, removal, and a missing secret.

### Journals

`examples/journals.sh` builds two journals from real papers of
[Quantum](https://quantum-journal.org) (volume 7, 2023, CC BY 4.0; an
unofficial demonstration, not made by or for Quantum):

- a journal that **accepts** vetted versions: the authors keep every version
  in their own archive; the journal keeps exactly the version it vetted as
  an accepted copy (`osheaf accept URI --selection issue-1`): a branch of
  the authors' line under the journal's owner, holding the version's files
  byte for byte with the evidence of the authors' signatures. Its issue is
  a selection of these copies, pinning the revisions the editors vetted.
  The authors' later versions change nothing at the journal: a correction
  is an editorial act (a notice, or the acceptance of a later version,
  which moves the copy's branch point and adds the revision to the issue).
  Only the vetted version needs an open licence, so a paper whose first
  arXiv version is not openly licensed (and could not be mirrored as a
  whole) can be accepted; and the journal still verifies when the authors'
  archive is gone;
- a journal that **repackages** the papers: it deposits its versions of record
  (its typeset PDF, its DOI, its licence, the authors' agreement in
  `object.json`) as papers of its own archive, linked to the authors'
  arXiv versions.

## Licence

This template (the pages, style and workflow) is dedicated to the public
domain under [CC0 1.0](LICENSE): use it as you like. The papers you deposit
carry the licences you give them; the archive's metadata is placed under CC0,
as the specification asks.
