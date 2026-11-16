"""Phase 2 B+ tree contract tests (T-01..T-19).

근거: docs/phase2-design.md §5, §8.1.
분할 규칙은 D-08(부모 키 = 오른쪽 자식의 첫 키), D-09(p = (max_keys+1)//2)를 따른다.
"""

from __future__ import annotations

import pytest

from mini_rdbms.bplus_tree import BPlusTree, InternalNode, LeafNode


def offset_for(key: int) -> int:
    """테스트용 바이트 위치. 실제 CSV 오프셋처럼 1 이상이다."""
    return 100 + key


def build(keys, *, max_keys: int = 3) -> BPlusTree:
    tree = BPlusTree(max_keys=max_keys)
    for key in keys:
        tree.insert(key, offset_for(key))
    return tree


def leaf_entries(tree: BPlusTree) -> list[list[int]]:
    node = tree.root
    while isinstance(node, InternalNode):
        node = node.children[0]
    entries: list[list[int]] = []
    while node is not None:
        entries.append([entry[0] for entry in node.entries])
        node = node.next
    return entries


def depth(tree: BPlusTree) -> int:
    level = [tree.root]
    count = 0
    while level:
        count += 1
        following = []
        for node in level:
            if isinstance(node, InternalNode):
                following.extend(node.children)
        level = following
    return count


def _first_key(node) -> int:
    while isinstance(node, InternalNode):
        node = node.children[0]
    return node.entries[0][0]


def _leaves_by_pointer(node) -> list:
    if isinstance(node, LeafNode):
        return [node]
    leaves = []
    for child in node.children:
        leaves.extend(_leaves_by_pointer(child))
    return leaves


def _leaves_by_link(node) -> list:
    while isinstance(node, InternalNode):
        node = node.children[0]
    leaves = []
    while node is not None:
        leaves.append(node)
        node = node.next
    return leaves


def assert_invariants(tree: BPlusTree, max_keys: int) -> None:
    """D-08/D-09가 만드는 구조 불변식을 검사한다."""
    by_pointer = _leaves_by_pointer(tree.root)
    by_link = _leaves_by_link(tree.root)
    assert len(by_pointer) == len(by_link)
    assert all(left is right for left, right in zip(by_pointer, by_link))

    keys = [entry[0] for leaf in by_pointer for entry in leaf.entries]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))

    def check(node) -> None:
        if isinstance(node, LeafNode):
            assert len(node.entries) <= max_keys
            return
        assert 0 < len(node.keys) <= max_keys
        assert len(node.children) == len(node.keys) + 1
        assert node.keys == sorted(node.keys)
        for index, key in enumerate(node.keys):
            assert _first_key(node.children[index + 1]) == key
        for child in node.children:
            check(child)

    if isinstance(tree.root, InternalNode):
        check(tree.root)


# ---------------------------------------------------------------------------
# 검색
# ---------------------------------------------------------------------------

def test_T_01_empty_tree_returns_no_offset() -> None:
    tree = BPlusTree(max_keys=3)

    assert tree.search(0) == (None, 1)


def test_T_02_search_returns_inserted_offsets() -> None:
    tree = build(range(6))

    for key in range(6):
        assert tree.search(key) == (offset_for(key), 2)


def test_T_03_missing_key_still_walks_to_leaf() -> None:
    tree = build(range(6))

    assert tree.search(99) == (None, 2)


# ---------------------------------------------------------------------------
# 분할 구조
# ---------------------------------------------------------------------------

def test_T_04_first_leaf_split() -> None:
    tree = build(range(4))

    assert isinstance(tree.root, InternalNode)
    assert tree.root.keys == [2]
    assert leaf_entries(tree) == [[0, 1], [2, 3]]


def test_T_05_split_relinks_leaves() -> None:
    tree = build(range(4))

    left, right = tree.root.children
    assert isinstance(left, LeafNode) and isinstance(right, LeafNode)
    assert left.next is right
    assert right.next is None


def test_T_06_internal_node_split() -> None:
    tree = build(range(10))

    assert isinstance(tree.root, InternalNode)
    assert tree.root.keys == [6]
    first, second = tree.root.children
    assert isinstance(first, InternalNode) and isinstance(second, InternalNode)
    assert first.keys == [2, 4]
    assert second.keys == [8]
    assert leaf_entries(tree) == [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]


def test_T_07_tree_grows_by_one_level() -> None:
    tree = build(range(10))

    assert depth(tree) == 3
    for key in range(10):
        assert tree.search(key) == (offset_for(key), 3)


def test_T_08_reverse_insertion_builds_same_shape() -> None:
    tree = build(range(9, -1, -1))

    assert tree.root.keys == [6]
    assert leaf_entries(tree) == [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
    assert_invariants(tree, 3)


def test_T_09_negative_keys_are_ordered() -> None:
    tree = build(range(-5, 6))

    for key in range(-5, 6):
        assert tree.search(key) == (offset_for(key), depth(tree))
    assert_invariants(tree, 3)


def test_T_10_duplicate_key_is_rejected() -> None:
    tree = build(range(4))
    original = tree.search(2)[0]

    with pytest.raises(KeyError):
        tree.insert(2, 999)

    assert tree.search(2)[0] == original


# ---------------------------------------------------------------------------
# 범위 조회
# ---------------------------------------------------------------------------

def test_T_11_range_excludes_upper_bound() -> None:
    tree = build(range(10))

    offsets, _ = tree.search_range(2, 6)

    assert offsets == [offset_for(key) for key in (2, 3, 4, 5)]


def test_T_12_range_without_lower_bound() -> None:
    tree = build(range(10))

    offsets, _ = tree.search_range(None, 3)

    assert offsets == [offset_for(key) for key in (0, 1, 2)]


def test_T_13_range_without_upper_bound() -> None:
    tree = build(range(10))

    offsets, _ = tree.search_range(7, None)

    assert offsets == [offset_for(key) for key in (7, 8, 9)]


def test_T_14_range_crosses_leaves() -> None:
    tree = build(range(10))

    offsets, _ = tree.search_range(1, 9)

    assert offsets == [offset_for(key) for key in range(1, 9)]


def test_T_15_empty_range_returns_nothing() -> None:
    tree = build(range(10))

    offsets, _ = tree.search_range(5, 5)

    assert offsets == []


def test_T_16_range_visit_count_includes_leaf_moves() -> None:
    tree = build(range(10))

    _, visits = tree.search_range(0, 10)

    assert visits == 7


# ---------------------------------------------------------------------------
# 설정 검증
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [2, True, "3"])
def test_T_17_invalid_max_keys_is_value_error(value) -> None:
    with pytest.raises(ValueError):
        BPlusTree(max_keys=value)


# ---------------------------------------------------------------------------
# 규모
# ---------------------------------------------------------------------------

def test_T_18_ten_thousand_keys_stay_consistent() -> None:
    tree = BPlusTree(max_keys=3)
    for key in range(10_000):
        tree.insert(key, offset_for(key))

    assert_invariants(tree, 3)
    for key in range(10_000):
        assert tree.search(key)[0] == offset_for(key)


def test_T_19_default_capacity_splits() -> None:
    tree = BPlusTree(max_keys=128)
    for key in range(10_000):
        tree.insert(key, offset_for(key))

    assert depth(tree) == 3
    assert len(_leaves_by_link(tree.root)) == 156
    assert tree.search(5_000) == (offset_for(5_000), 3)
    assert_invariants(tree, 128)
