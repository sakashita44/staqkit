"""Phase 0 検証用: パッケージインポートテスト。"""

import staqkit


def test_import() -> None:
    """staqkitパッケージがインポートできることを検証する。"""
    assert staqkit.__name__ == "staqkit"
