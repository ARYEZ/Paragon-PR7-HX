# Paragon PR7-HX: notes for Claude

**Paragon PR7-HX** is the owner's personal hex editor: Python (**PySide6**) that **works the way HxD works**, in the
Paragon family look (PR7-Z ... PR7-AR, PR7-WM `ARYEZ/Paragon-PR7-WM`). Windows 10/11 x64 is the target; it runs on
Linux for tests. The owner writes Python; explain the why.

## How it's built

- `pr7hx/buffer.py` (no Qt): a **piece table** over the file on disk (`FileSource`, read with seek + read; never
  loaded whole): pieces (ORIGINAL | ADDED, start, length), `read`, `overwrite` / `insert` / `delete` / `fill`, Undo /
  Redo as whole piece tuples (`group()` = one step; `join_undo` joins a byte's second hex digit), `changed_ranges` (the
  ADDED pieces: orange). `save` writes a temp file next to the target, then os.replace (the source is closed first:
  Windows won't replace an open file) and the saved file becomes the new original. `DiskSource`: a drive or an image,
  fixed size, reads aligned to the sector size (Windows requires it for \\.\C:), `write_sectors` patches whole sectors
  in place; disk buffers start read-only and never grow or shrink.
- `pr7hx/search.py` (no Qt): HxD's kinds (hex / text in ANSI, UTF-8, UTF-16 LE/BE, case-insensitive via a per-character
  alternation / int 8-64 bit / float 32-64 bit, byte order) as a bytes regex with a known longest match; `find` reads
  CHUNK + overlap so matches across chunk borders are found, forwards or backwards; `find_all`, `replace_all` (one Undo
  step). `encode_number`: signed if it fits, else unsigned.
- `pr7hx/inspect.py` (no Qt): the Data inspector's types (`value`, `rows`) and `encode` for the editable ones.
  `checksums.py` (CRC-32 / MD5 / SHA-1 / SHA-256 / SHA-512, chunked, cancellable), `hexcompare.py` (HxD's compare:
  same offsets, runs of differing bytes, a longer tail is one more run), `export.py` (Copy As), `disks.py` (drives and
  PhysicalDriveN via DeviceIoControl for size and sector size; `open_image`).
- `pr7hx/hexview.py`: `HexView` (QAbstractScrollArea) paints only the rows on screen; past BAR_LIMIT rows a scroll step
  is several rows (a QScrollBar holds an int). HxD's keys; selection = the bytes between anchor and cursor (cursor's
  byte excluded; a mouse drag includes the byte under the pointer). Edits go through `_edit` (PermissionError /
  ValueError -> `refused`). Undo / Copy / Paste keys are passed on to the window.
- `pr7hx/pages.py`: `EditorPage` (view + side panel: INSPECTOR, BOOKMARKS, CHECKSUMS on a thread, inline when `sync`)
  and `ComparePage` (two read-only views scrolled together). `dialogs.py`: Find (radios in QButtonGroups), Go To,
  Select Block, Open Disk, File Compare, Options.
- `pr7hx/main_window.py`: HxD's menus and keys (`_act(..., key=)` into `acts`); every question through `_ask(kind)`
  (tests: `answers`; "say" always goes to `_say`); clipboard holds the raw bytes as `application/x-pr7hx-bytes` plus
  hex text; disks ask before allowing changes and again before Save.
- `pr7hx/shell.py`: "Edit with PR7-HX" = HKCU `Software\Classes\*\shell\PR7HX.Edit`; `base` lets Windows CI use a
  throwaway key. `pr7hx/app.py`: one window per user (QLocalSocket, PR7-R's Windows fix) plus a QLockFile (Explorer
  starts one per selected file); command-line modes never let an error escape; `--selftest OUT.json`, `--register-menu`,
  `--unregister`.
- Installer `installer/pr7hx.iss` (per user, AppId {C612D234-7CDF-4811-BA78-1965A73D44AA} permanent; tasks explorermenu
  (ticked), desktopicon); CI installs it, `tools/verify_install.py installed|uninstalled`. Spec: file details, no UPX,
  PyInstaller's bootloader built in CI, Defender scan. Windows CI also reads the runner's drive C: (tests/test_windows.py).
- Updates: `pr7hx/updates.py` / `update_ui.py` (the family's files, keep them in step); `family.py`: the family's
  AppIds (PR7-HX included). `pr7hx/finish.py`: the family's finish, the same file in every app.

## The look (family rules)

- Theme is PR7-WM's (OBSIDIAN + AURORA). Colours: the family's only (changed bytes orange, differences pink, the
  selection the family red); Inter for the UI, the bytes monospaced; labels UPPER CASE; file names keep their case.
- The PR7-HX mark: PR7 `Logo.cpp` geometry plus H (PR7-HB's) and X (new, `widgets.X_OUTER`); icon "7HX" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Mock-up: `tools/mockup.py` (bytes from
  `tools/mockup_data.py`). Check visuals with `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT`.

## Rules

- Behaviour questions: do what HxD does (layout, keys, Insert / Overwrite, Data inspector, compare).
- Tests: `python -m pytest` (offscreen) on real files and disk images; every save is checked byte for byte. Never the
  real settings (conftest) or, outside CI, the registry or a real disk.
- Releases: bump `__version__` in `pr7hx/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed.
