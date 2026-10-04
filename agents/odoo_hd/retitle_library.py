"""Give each Cookbook chapter-book a distinct title in the bookstore catalog."""

import re
import sys
from pathlib import Path
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore

sys.path.insert(0, str(Path(__file__).parent))
from build_cookbook_md import TITLES  # noqa: E402

lib = Bookstore([LibraryLocation(scope="project", root=Path("agents/odoo_hd/library"))])
for card in lib.list_books():
    m = re.search(r"-ch(\d+)-", card.book_id)
    if not m:
        continue
    num = m.group(1)
    card.title = f"Odoo 19 Development Cookbook 6E — Chapter {num}: {TITLES[num]}"
    lib._catalog("project").upsert(card)
    print("RESULT", card.book_id, "->", card.title)
