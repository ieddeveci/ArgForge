import json, hashlib
from dataclasses import asdict, is_dataclass


def plain(x):
    if hasattr(x, "to_dict"):
        return plain(x.to_dict())
    if is_dataclass(x):
        return plain(asdict(x))
    if hasattr(x, "items"):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (set, frozenset)):
        return sorted((plain(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    return x


def identity(x):
    return hashlib.sha256(
        json.dumps(plain(x), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def key(a):
    return identity(a.semantic_signature)


def require(result):
    if result.status != "OK":
        raise ValueError("Complete result required: " + result.status)
