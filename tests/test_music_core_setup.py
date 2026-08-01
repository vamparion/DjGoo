from __future__ import annotations

import pytest

from tools.configure_music_core import validate_prefix, validate_token


def test_discord_token_validation() -> None:
    token = "a" * 24 + "." + "b" * 6 + "." + "c" * 27

    assert validate_token(token) == token
    with pytest.raises(ValueError):
        validate_token("too-short")
    with pytest.raises(ValueError):
        validate_token("a" * 60 + " bad")


def test_command_prefix_validation() -> None:
    assert validate_prefix(" ! ") == "!"
    assert validate_prefix("dj!") == "dj!"

    with pytest.raises(ValueError):
        validate_prefix("")
    with pytest.raises(ValueError):
        validate_prefix("/djgoo")
    with pytest.raises(ValueError):
        validate_prefix("x" * 11)
