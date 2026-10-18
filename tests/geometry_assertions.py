"""Test-only comparisons of directed polylines in the model's metric CRS."""
from bisect import bisect_right
import math


# One micrometre: above nanometre-scale float64/projection round-trip noise,
# but much stricter than the former 1e-8 degree (~1 mm here) coordinate bound.
PATH_TOLERANCE_M = 1e-6


def assert_same_directed_path(actual, expected):
    """Check endpoints, absolute length and the entire ordered traversal.

    Compare at the union of both polylines' normalized vertex chainages.
    Between these knots both positions are affine in normalized chainage, so
    the norm of their difference cannot exceed its maximum at the endpoints.
    This is a continuous bound, not arbitrary fixed-distance sampling or a
    vertex-count-dependent discrete Frechet/Hausdorff approximation. Repeated
    vertices are retained; only duplicate sampling chainages share a check.
    """
    def prepare(points):
        points = tuple(tuple(p) for p in points)
        if not points or any(len(p) != 2 or not all(math.isfinite(v) for v in p)
                             for p in points):
            raise AssertionError('Expected nonempty finite 2D metric coordinates')
        chainage = [0.0]
        for a, b in zip(points, points[1:]):
            chainage.append(chainage[-1] + math.dist(a, b))
        return points, chainage

    a, ac = prepare(actual)
    b, bc = prepare(expected)

    def within(error, label):
        if not math.isfinite(error) or error > PATH_TOLERANCE_M:
            raise AssertionError(f'{label}: {error:.12g} m > {PATH_TOLERANCE_M:g} m')

    within(math.dist(a[0], b[0]), 'Directed start displacement')
    within(math.dist(a[-1], b[-1]), 'Directed end displacement')
    within(abs(ac[-1] - bc[-1]), 'Path length difference')

    def position(points, chainage, fraction):
        if not chainage[-1] or fraction >= 1:
            return points[-1]
        distance = fraction * chainage[-1]
        if distance >= chainage[-1]:
            return points[-1]
        # Rightmost equal chainage skips zero-length edges for interpolation;
        # it neither edits coordinates nor removes a nonzero edge/backtrack.
        i = min(bisect_right(chainage, distance) - 1, len(points) - 2)
        ratio = (distance - chainage[i]) / (chainage[i + 1] - chainage[i])
        return tuple(x + ratio * (y - x) for x, y in zip(points[i], points[i + 1]))

    knots = {0.0, 1.0}
    for chainage in (ac, bc):
        if chainage[-1]:
            knots.update(d / chainage[-1] for d in chainage)
    for fraction in sorted(knots):
        error = math.dist(position(a, ac, fraction), position(b, bc, fraction))
        within(error, f'Ordered path displacement at chainage fraction {fraction:.12g}')
