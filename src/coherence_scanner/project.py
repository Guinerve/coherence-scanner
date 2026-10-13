"""Fair value: the nearest coherent price vector, by minimising KL divergence under the constraints.

For independent Bernoulli prices p_i and candidate q_i the cost is
    sum_i  q_i ln(q_i / p_i) + (1 - q_i) ln((1 - q_i) / (1 - p_i))
subject to: exhaustive sets sum to 1, exclusive sets sum to <= 1, nested pairs q_A <= q_B, equal pairs q_A = q_B.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy.optimize import minimize

EPS = 1e-6


def project(
    prices: Sequence[float],
    exhaustive_sets: Sequence[Sequence[int]] = (),
    exclusive_sets: Sequence[Sequence[int]] = (),
    implies: Sequence[tuple[int, int]] = (),  # (a, b): P(a) <= P(b)
    equal: Sequence[tuple[int, int]] = (),
) -> np.ndarray:
    p = np.clip(np.asarray(prices, dtype=float), EPS, 1 - EPS)

    def kl(q: np.ndarray) -> float:
        q = np.clip(q, EPS, 1 - EPS)
        return float(np.sum(q * np.log(q / p) + (1 - q) * np.log((1 - q) / (1 - p))))

    def grad(q: np.ndarray) -> np.ndarray:
        q = np.clip(q, EPS, 1 - EPS)
        return np.log(q / p) - np.log((1 - q) / (1 - p))

    cons: list[dict[str, Any]] = []
    for s in exhaustive_sets:
        idx = list(s)
        cons.append({"type": "eq", "fun": lambda q, idx=idx: q[idx].sum() - 1, "jac": lambda q, idx=idx: _ind(len(q), idx)})
    for s in exclusive_sets:
        idx = list(s)
        cons.append({"type": "ineq", "fun": lambda q, idx=idx: 1 - q[idx].sum(), "jac": lambda q, idx=idx: -_ind(len(q), idx)})
    for a, b in implies:
        cons.append({"type": "ineq", "fun": lambda q, a=a, b=b: q[b] - q[a], "jac": lambda q, a=a, b=b: _pair(len(q), b, a)})
    for a, b in equal:
        cons.append({"type": "eq", "fun": lambda q, a=a, b=b: q[a] - q[b], "jac": lambda q, a=a, b=b: _pair(len(q), a, b)})

    res = minimize(kl, p.copy(), jac=grad, bounds=[(EPS, 1 - EPS)] * len(p), constraints=cons, method="SLSQP",
                   options={"maxiter": 500, "ftol": 1e-12})
    if not res.success:
        raise ValueError(f"projection failed: {res.message}")
    return res.x


def _ind(n: int, idx: Sequence[int]) -> np.ndarray:
    v = np.zeros(n)
    v[list(idx)] = 1.0
    return v


def _pair(n: int, plus: int, minus: int) -> np.ndarray:
    v = np.zeros(n)
    v[plus], v[minus] = 1.0, -1.0
    return v
