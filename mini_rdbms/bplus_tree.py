"""Phase 2 in-memory B+ tree mapping ids to CSV byte offsets.

Split rules follow docs/phase2-design.md D-08/D-09: a parent key is the first
key of its right child, a promoted leaf entry stays on the right leaf, and a
promoted internal key moves out of the split node.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass


@dataclass(slots=True)
class LeafNode:
    """Leaf entries ``(id, offset)`` and the next leaf in key order."""

    entries: list[tuple[int, int]]
    next: LeafNode | None = None


@dataclass(slots=True)
class InternalNode:
    """Separator keys and child pointers, one more child than keys."""

    keys: list[int]
    children: list[Node]


Node = InternalNode | LeafNode


def validate_max_keys(value: int) -> None:
    """Reject capacities that cannot split into two usable nodes."""
    if type(value) is not int or value < 3:
        raise ValueError("max_keys must be an integer of at least 3")


class BPlusTree:
    """In-memory B+ tree with unique integer keys."""

    def __init__(self, max_keys: int = 128) -> None:
        validate_max_keys(max_keys)
        self._max_keys = max_keys
        self._root: Node = LeafNode(entries=[])

    @property
    def root(self) -> Node:
        """Return the root node; callers only inspect the structure."""
        return self._root

    def insert(self, key: int, offset: int) -> None:
        """Insert one key/offset pair and split overflowing nodes."""
        path: list[tuple[InternalNode, int]] = []
        node: Node = self._root
        while isinstance(node, InternalNode):
            index = bisect_right(node.keys, key)
            path.append((node, index))
            node = node.children[index]

        position = bisect_left(node.entries, (key, -1))
        if position < len(node.entries) and node.entries[position][0] == key:
            raise KeyError(key)
        node.entries.insert(position, (key, offset))
        if len(node.entries) <= self._max_keys:
            return

        split = len(node.entries) // 2
        leaf = LeafNode(entries=node.entries[split:], next=node.next)
        node.next = leaf
        node.entries = node.entries[:split]
        promoted = leaf.entries[0][0]
        new_node: Node = leaf

        while path:
            parent, index = path.pop()
            parent.keys.insert(index, promoted)
            parent.children.insert(index + 1, new_node)
            if len(parent.keys) <= self._max_keys:
                return
            split = len(parent.keys) // 2
            promoted = parent.keys[split]
            new_node = InternalNode(
                keys=parent.keys[split + 1 :],
                children=parent.children[split + 1 :],
            )
            parent.keys = parent.keys[:split]
            parent.children = parent.children[: split + 1]

        self._root = InternalNode(keys=[promoted], children=[self._root, new_node])

    def search(self, key: int) -> tuple[int | None, int]:
        """Return ``(offset or None, visited node count)`` for key."""
        node: Node = self._root
        visits = 0
        while isinstance(node, InternalNode):
            visits += 1
            node = node.children[bisect_right(node.keys, key)]
        visits += 1

        position = bisect_left(node.entries, (key, -1))
        if position < len(node.entries) and node.entries[position][0] == key:
            return node.entries[position][1], visits
        return None, visits

    def search_range(
        self, lower: int | None, upper: int | None
    ) -> tuple[list[int], int]:
        """Return offsets for keys in ``[lower, upper)`` plus visited nodes.

        ``None`` bounds are unbounded. Leaves are scanned through ``next``;
        every leaf move counts as a visit (D-11).
        """
        node: Node = self._root
        visits = 0
        while isinstance(node, InternalNode):
            visits += 1
            index = 0 if lower is None else bisect_right(node.keys, lower)
            node = node.children[index]
        visits += 1

        position = (
            0 if lower is None else bisect_left(node.entries, (lower, -1))
        )
        offsets: list[int] = []
        while node is not None:
            for index in range(position, len(node.entries)):
                key, offset = node.entries[index]
                if upper is not None and key >= upper:
                    return offsets, visits
                offsets.append(offset)
            node = node.next
            position = 0
            if node is not None:
                visits += 1
        return offsets, visits
