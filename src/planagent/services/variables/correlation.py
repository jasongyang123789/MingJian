"""Variable-correlation math (Phase 2, Track 3).

Pure stdlib math for the correlation feature; this module imports
nothing from the application, so both the variable validator and the
sampler can use it without creating an import cycle.

A correlation spec is a list of ``(variable_a, variable_b, rho)`` pairs
on a variable set. The sampler realises it as a Gaussian copula: the
correlated variables share one draw of correlated standard normals
(Cholesky factor of the correlation matrix), each mapped through the
standard-normal CDF to a uniform, then through its own marginal's
inverse CDF. Marginals are therefore preserved exactly (up to the
numerical inversion of the beta-PERT CDF), while the joint draw carries
the specified dependence. Pearson correlation of the sampled values is
*approximately* the specified rho: exact for normal marginals, slightly
attenuated for bounded/skewed marginals (triangular, beta-PERT) and for
Bernoulli (threshold) marginals — the copula fixes the rank (Spearman)
dependence, and the Pearson value follows from the marginals.

No numpy is introduced (the sampler is stdlib-only by design); the
Cholesky factorisation and the regularised incomplete beta function are
implemented here in a few dozen lines each.
"""

from __future__ import annotations

import math
import random

#: Cholesky pivots at or below this magnitude count as zero (a singular
#: but still positive-semidefinite matrix, e.g. rho == 1.0 exactly).
_CHOLESKY_TOLERANCE = 1e-12

#: Continued-fraction convergence for the incomplete beta function.
_BETA_EPSILON = 3e-14
_BETA_MAX_ITERATIONS = 200
_BETA_FPMIN = 1e-300


def build_correlation_matrix(
    variable_ids: list[str],
    pairs: list[tuple[str, str, float]],
) -> list[list[float]]:
    """Build the correlation matrix for ``variable_ids`` from ``pairs``.

    Unspecified off-diagonal entries are 0 (independent). Duplicate
    pairs must already have been rejected by the caller; a later pair
    wins if one slips through.
    """

    index = {var_id: position for position, var_id in enumerate(variable_ids)}
    size = len(variable_ids)
    matrix = [[1.0 if row == col else 0.0 for col in range(size)] for row in range(size)]
    for first, second, rho in pairs:
        row, col = index[first], index[second]
        matrix[row][col] = float(rho)
        matrix[col][row] = float(rho)
    return matrix


def cholesky(matrix: list[list[float]]) -> list[list[float]]:
    """Lower-triangular Cholesky factor of a correlation matrix.

    Raises :class:`ValueError` when the matrix is not positive
    semidefinite (a negative pivot beyond tolerance). Singular PSD
    matrices (a zero pivot, e.g. rho == 1.0) factorise fine: the
    corresponding row is all zeros past the diagonal, so the two
    variables draw the identical normal and hence the identical
    uniform — perfect positive dependence, as specified.
    """

    size = len(matrix)
    factor = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for col in range(row + 1):
            total = matrix[row][col] - sum(factor[row][k] * factor[col][k] for k in range(col))
            if row == col:
                if total < -_CHOLESKY_TOLERANCE:
                    raise ValueError(
                        "Correlation matrix is not positive semidefinite: "
                        f"negative pivot {total!r} at index {row}."
                    )
                factor[row][col] = math.sqrt(total) if total > 0.0 else 0.0
            else:
                if factor[col][col] == 0.0:
                    if abs(total) > _CHOLESKY_TOLERANCE:
                        raise ValueError(
                            "Correlation matrix is not positive semidefinite: "
                            f"non-zero off-diagonal {total!r} against a zero pivot."
                        )
                    factor[row][col] = 0.0
                else:
                    factor[row][col] = total / factor[col][col]
    return factor


def is_positive_semidefinite(matrix: list[list[float]]) -> bool:
    """True when ``matrix`` admits a Cholesky factorisation."""

    try:
        cholesky(matrix)
    except ValueError:
        return False
    return True


def standard_normal_cdf(value: float) -> float:
    """Phi, the standard-normal CDF, via :func:`math.erf`."""

    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def correlated_uniforms(matrix: list[list[float]], rng: random.Random) -> list[float]:
    """One correlated uniform draw per matrix row, in row order.

    Draws ``len(matrix)`` independent standard normals from ``rng``
    (``rng.gauss``), correlates them with the Cholesky factor, and maps
    each through Phi. The result is deterministic for a given seed: the
    same ``rng`` state always yields the same uniforms. Uniforms are
    clamped into ``(0, 1)`` so downstream inverse CDFs never see an
    exact endpoint.
    """

    factor = cholesky(matrix)
    size = len(matrix)
    independent = [rng.gauss(0.0, 1.0) for _ in range(size)]
    uniforms: list[float] = []
    for row in range(size):
        correlated = sum(factor[row][col] * independent[col] for col in range(row + 1))
        uniform = standard_normal_cdf(correlated)
        uniforms.append(min(max(uniform, 1e-12), 1.0 - 1e-12))
    return uniforms


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's
    algorithm, Numerical Recipes ``betacf``)."""

    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETA_FPMIN:
        d = _BETA_FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _BETA_MAX_ITERATIONS + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETA_FPMIN:
            d = _BETA_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETA_FPMIN:
            c = _BETA_FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETA_FPMIN:
            d = _BETA_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETA_FPMIN:
            c = _BETA_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _BETA_EPSILON:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b) for a, b > 0."""

    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_beta = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    front = math.exp(log_beta) / a
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x)
    return 1.0 - math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + b * math.log(1.0 - x)
        + a * math.log(x)
    ) / b * _beta_continued_fraction(b, a, 1.0 - x)


def beta_ppf(probability: float, alpha: float, beta: float) -> float:
    """Inverse CDF of Beta(alpha, beta) by bisection on the CDF.

    Sixty bisection steps pin the quantile to ~1e-18 of the unit
    interval — far tighter than any downstream rounding. Deterministic:
    no randomness is involved.
    """

    low, high = 0.0, 1.0
    for _ in range(60):
        mid = 0.5 * (low + high)
        if regularized_incomplete_beta(alpha, beta, mid) < probability:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)
