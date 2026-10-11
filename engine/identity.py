import hashlib, json
from collections.abc import Mapping
from types import MappingProxyType


def canonical(value):
    if isinstance(value, str):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda p: str(p[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(
            (canonical(v) for v in value),
            key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=True),
        )
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def digest(prefix, value):
    return (
        prefix
        + hashlib.sha256(
            json.dumps(
                canonical(value),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
    )


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(v) for v in value)
    return value


def memo_property(function):

    def get(instance):
        name = function.__name__
        cache = instance._cache
        if name in cache:
            return cache[name]
        value = function(instance)
        object.__setattr__(instance, "_cache", MappingProxyType({**instance._cache, name: value}))
        return value

    return property(get, doc=function.__doc__)
