import os


def evaluate(*args, **kwargs):
    if os.name == "nt":
        from .windows import evaluate as implementation
    else:
        from engine.isolation import evaluate as implementation
    return implementation(*args, **kwargs)
