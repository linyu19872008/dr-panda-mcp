from __future__ import annotations

from dr_panda_mcp import errors


def test_guidance_message_includes_allowed_and_hint() -> None:
    text = errors.guidance_message(
        "topic x is not within the authorized scope of target demo",
        allowed=["a/b", "c/d"],
        hint="use logsetId/topicId UUIDs",
    )
    assert "allowed: a/b, c/d" in text
    assert "use logsetId/topicId UUIDs" in text


def test_scope_denied_formats_guidance() -> None:
    exc = errors.ScopeDenied(
        "database app is not within the authorized scope of target db",
        allowed=["live", "chat"],
        hint="use a value from scope.allowed_dbs",
    )
    assert "allowed: live, chat" in str(exc)
    assert "scope.allowed_dbs" in str(exc)
    assert exc.code == errors.SCOPE_DENIED


def test_invalid_argument_formats_guidance() -> None:
    exc = errors.InvalidArgument(
        "group is required (the target has multiple allowed groups)",
        allowed=["DEFAULT_GROUP", "dubbo"],
    )
    assert "allowed: DEFAULT_GROUP, dubbo" in str(exc)
    assert exc.code == errors.INVALID_ARGUMENT
