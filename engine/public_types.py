from dataclasses import dataclass
from .identity import digest


class Extension(frozenset):
    __slots__ = ()

    @property
    def id(self):
        return digest("e_", self)


@dataclass(frozen=True, slots=True)
class Defeat:
    attacker: str
    target: str
    witnesses: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "witnesses", tuple(self.witnesses))

    @property
    def id(self):
        return digest("d_", (self.attacker, self.target))


@dataclass(frozen=True, slots=True)
class ArgumentationFramework:
    arguments: tuple
    attacks: tuple
    defeats: tuple[Defeat, ...]

    def __post_init__(self):
        for name in ("arguments", "attacks", "defeats"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
