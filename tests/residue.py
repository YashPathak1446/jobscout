"""
The residue walker (pilot plan A6): what of a person is still on disk.

Not a test module (discovery collects `test*.py`). A6 uses it to prove a
deleted user left nothing behind, and A7 reuses it verbatim to prove an API key
landed nowhere, which is why it takes needles rather than a user.

It reads **bytes and names, not rows**. A query can only find what the schema
still describes; a deleted SQLite row lingers in the file's free list, and a
row that is gone from every table is still in the bytes. Reading the bytes
also covers a database nobody has written a query for yet — the fifth store
is the one this has to catch, and nobody will have told it about that store.

Case-insensitive, because the pipeline writes a name as `Priya_Raghunathan`
in a filename and `PRIYA RAGHUNATHAN` in a heading, and one of those in a
file is the person surviving just as much as the other.
"""

import os
from pathlib import Path


def spellings(name: str) -> list:
    """
    A person's name as the pipeline might write it: with spaces, underscores,
    hyphens, or run together. Filenames use the underscore form.
    """
    words = name.split()
    return sorted({sep.join(words) for sep in (" ", "_", "-", "")})


def residue(root, needles) -> list:
    """
    Every place under `root` a needle survives, as `"<relative path>: <how>"`.

    Paths (every directory and file name, relative to `root`) and file bytes
    are both searched. Symlinks are listed by name but never followed, so the
    walk cannot wander out of the tree it was asked about. Empty means clean.
    """
    root = Path(root)
    wanted = [(needle, needle.lower().encode("utf-8")) for needle in needles if needle]
    found = []
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(directory, name)
            relative = path.relative_to(root).as_posix()
            lowered = relative.lower().encode("utf-8")
            for needle, raw in wanted:
                if raw in lowered:
                    found.append(f"{relative}: {needle!r} in its path")
            if name in files and not path.is_symlink():
                body = path.read_bytes().lower()
                for needle, raw in wanted:
                    if raw in body:
                        found.append(f"{relative}: {needle!r} in its bytes")
    return sorted(set(found))
