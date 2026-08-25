"""Rich drives one Live region per console, so the widgets that need it must
never nest. This used to be a convention in a comment; these tests make it a
rule the code enforces."""

from __future__ import annotations

import pytest

from pixieduster import ui


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", True)
    ui._live_owner.clear()
    yield
    ui._live_owner.clear()


@pytest.mark.parametrize("outer", ["dust", "stages"])
@pytest.mark.parametrize("inner", ["dust", "stages"])
def test_nesting_live_widgets_raises(outer, inner):
    def enter(name):
        return ui.dust() if name == "dust" else ui.stages("t")

    with pytest.raises(ui.LiveConflictError) as exc:
        with enter(outer):
            with enter(inner):
                pass
    assert inner in str(exc.value)
    assert outer in str(exc.value)


def test_sequential_use_is_fine():
    with ui.dust():
        pass
    with ui.stages("t"):
        pass
    with ui.dust():
        pass
    assert ui.live_owner() is None


def test_owner_is_released_after_an_exception():
    with pytest.raises(ValueError):
        with ui.stages("t"):
            raise ValueError("boom")
    assert ui.live_owner() is None


def test_ask_widgets_also_claim_the_region(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "1")
    with pytest.raises(ui.LiveConflictError):
        with ui.dust():
            ui.ask_choice("q", ["a", "b"], 1, 1)


def test_the_real_cli_call_sites_do_not_nest():
    """clone uses stages(); chat uses dust(). Neither wraps the other."""
    import inspect

    from pixieduster import cli

    for fn in (cli.clone, cli.chat, cli.diff):
        src = inspect.getsource(fn)
        assert not ("ui.dust(" in src and "ui.stages(" in src), (
            f"{fn.__name__} uses both dust() and stages(); they cannot nest."
        )
