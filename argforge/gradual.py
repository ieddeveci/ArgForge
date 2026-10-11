METHODS = ("h_categorizer", "max_based", "card_based")


def strengths(
    arguments, defeats, method="h_categorizer", weights=None, tolerance=1e-10, max_iter=10000
):
    if method not in METHODS:
        raise ValueError("method must be one of %s" % (METHODS,))
    arguments = list(arguments)
    weights = (
        {a: 1.0 for a in arguments}
        if weights is None
        else {a: float(weights.get(a, 1.0)) for a in arguments}
    )
    if any(not 0.0 <= w <= 1.0 for w in weights.values()):
        raise ValueError("weights must lie in [0, 1]")
    attackers = {a: [] for a in arguments}
    for x, y in set(defeats):
        attackers[y].append(x)
    degree = dict(weights)
    for _ in range(max_iter):
        new = {}
        for a in arguments:
            incoming = [degree[b] for b in attackers[a]]
            if method == "h_categorizer":
                new[a] = weights[a] / (1.0 + sum(incoming))
            elif method == "max_based":
                new[a] = weights[a] / (1.0 + max(incoming, default=0.0))
            else:
                positive = [v for v in incoming if v > 0]
                new[a] = (
                    weights[a] / (1.0 + len(positive) + sum(positive) / len(positive))
                    if positive
                    else weights[a]
                )
        change = max((abs(new[a] - degree[a]) for a in arguments), default=0.0)
        degree = new
        if change < tolerance:
            return degree
    raise RuntimeError("gradual semantics did not converge within max_iter")
