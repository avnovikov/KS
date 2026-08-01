"""Role / formation recommend engine (ILP).

Import submodules directly (e.g. ``ks.heroes.optimize.catalog``) to avoid
pulling PuLP unless ``recommend`` is used.
"""

__all__ = ["TroopsConfig", "load_troops_config", "recommend"]


def __getattr__(name: str):
    if name in {"TroopsConfig", "load_troops_config"}:
        from ks.heroes.optimize import troops as _troops

        return getattr(_troops, name)
    if name == "recommend":
        from ks.heroes.optimize.recommend import recommend as _recommend

        return _recommend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
