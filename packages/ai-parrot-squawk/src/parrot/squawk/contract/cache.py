"""Client-side contract cache: answers catalog_* without a round trip; applies handshake deltas."""

from __future__ import annotations

import difflib

from parrot.interagent import CapabilityCategory, ContractDelta, SquawkCapability


class ContractCache:
    """In-memory client-side contract cache."""

    def __init__(self) -> None:
        self._categories: dict[str, CapabilityCategory] = {}

    @property
    def known_hashes(self) -> dict[str, str]:
        return {n: c.hash for n, c in self._categories.items()}

    def apply(self, delta: ContractDelta) -> None:
        for c in delta.changed:
            self._categories[c.name] = c
        for n in delta.removed:
            self._categories.pop(n, None)

    def replace_category(self, category: CapabilityCategory) -> None:
        """STALE_CONTRACT recovery: the server sent the current definition."""
        self._categories[category.name] = category

    def category(self, name: str) -> CapabilityCategory | None:
        return self._categories.get(name)

    def categories(self) -> list[CapabilityCategory]:
        return sorted(self._categories.values(), key=lambda c: c.name)

    def find(self, cap_id: str) -> SquawkCapability | None:
        for c in self._categories.values():
            for cap in c.capabilities:
                if cap.cap_id == cap_id:
                    return cap
        return None

    def search(self, keywords: str, *, limit: int = 15) -> list[SquawkCapability]:
        """Case-insensitive substring over cap_id + description, difflib fill-up to `limit`."""
        if not keywords.strip():
            # Return all caps up to limit if keywords empty
            all_caps: list[SquawkCapability] = []
            for cat in self.categories():
                all_caps.extend(cat.capabilities)
            return all_caps[:limit]

        query = keywords.lower()
        matched_caps: list[SquawkCapability] = []
        matched_cap_ids: set[str] = set()

        # Collect all capabilities ordered by category name then cap_id
        all_caps_map: dict[str, SquawkCapability] = {}
        for cat in self.categories():
            for cap in cat.capabilities:
                all_caps_map[cap.cap_id] = cap

        # Phase 1: Substring hits over cap_id + description
        for cap_id, cap in all_caps_map.items():
            if query in cap_id.lower() or query in cap.description.lower():
                matched_caps.append(cap)
                matched_cap_ids.add(cap_id)
                if len(matched_caps) >= limit:
                    return matched_caps

        # Phase 2: difflib fill-up on remaining cap_ids
        remaining_cap_ids = [cap_id for cap_id in all_caps_map if cap_id not in matched_cap_ids]
        if remaining_cap_ids and len(matched_caps) < limit:
            close_ids = difflib.get_close_matches(
                query, remaining_cap_ids, n=limit - len(matched_caps), cutoff=0.6
            )
            for cid in close_ids:
                matched_caps.append(all_caps_map[cid])

        return matched_caps
