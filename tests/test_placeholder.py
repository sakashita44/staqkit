"""Phase 0 検証用: パッケージインポートテスト。"""

import sard


def test_import() -> None:
    """sardパッケージがインポートできることを検証する。"""
    assert sard.__name__ == "sard"
