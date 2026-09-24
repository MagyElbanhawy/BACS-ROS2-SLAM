"""
Trust-weighted SE(2) pose-graph optimisation.

Stands in for the g2o back-end of the parent framework.  The objective is
Eq. (10) of the antecedent paper: sum over edges of theta * e^T Omega e, where
theta scales the information matrix of every inter-robot constraint and equals
one for odometry edges.
"""
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def v2t(v):
    c, s = np.cos(v[2]), np.sin(v[2])
    return np.array([[c, -s, v[0]], [s, c, v[1]], [0.0, 0.0, 1.0]])


def t2v(T):
    return np.array([T[0, 2], T[1, 2], np.arctan2(T[1, 0], T[0, 0])])


def error_and_jacobians(xi, xj, z):
    """Standard SE(2) pose-graph error with analytic Jacobians."""
    Ti, Tj, Z = v2t(xi), v2t(xj), v2t(z)
    e = t2v(np.linalg.inv(Z) @ np.linalg.inv(Ti) @ Tj)
    e[2] = wrap(e[2])

    ci, si = np.cos(xi[2]), np.sin(xi[2])
    Ri = np.array([[ci, -si], [si, ci]])
    dRiT = np.array([[-si, ci], [-ci, -si]])
    cz, sz = np.cos(z[2]), np.sin(z[2])
    RzT = np.array([[cz, sz], [-sz, cz]])

    A = np.zeros((3, 3))
    A[:2, :2] = -RzT @ Ri.T
    A[:2, 2] = RzT @ dRiT @ (xj[:2] - xi[:2])
    A[2, 2] = -1.0

    B = np.zeros((3, 3))
    B[:2, :2] = RzT @ Ri.T
    B[2, 2] = 1.0
    return e, A, B


class PoseGraph:
    def __init__(self):
        self.nodes = []          # list of (3,) arrays
        self.edges = []          # (i, j, z, Omega, weight)
        self._index = {}

    def add_node(self, key, pose):
        if key in self._index:
            return self._index[key]
        self._index[key] = len(self.nodes)
        self.nodes.append(np.asarray(pose, float).copy())
        return self._index[key]

    def idx(self, key):
        return self._index.get(key)

    def add_edge(self, i, j, z, omega, weight=1.0):
        self.edges.append((i, j, np.asarray(z, float), np.asarray(omega, float), float(weight)))

    def degree(self):
        d = np.zeros(len(self.nodes), int)
        for i, j, *_ in self.edges:
            d[i] += 1
            d[j] += 1
        return d

    def optimize(self, iterations=12, tol=1e-6, damping=1e-6):
        """Gauss-Newton with the first node fixed as the gauge anchor."""
        n = len(self.nodes)
        if n == 0 or not self.edges:
            return np.array(self.nodes), None
        X = np.array(self.nodes, float)

        H = None
        for _ in range(iterations):
            rows, cols, vals = [], [], []
            b = np.zeros(3 * n)
            for (i, j, z, om, w) in self.edges:
                if w <= 0.0:
                    continue
                e, A, B = error_and_jacobians(X[i], X[j], z)
                W = w * om
                bi = -(A.T @ W @ e)
                bj = -(B.T @ W @ e)
                b[3 * i:3 * i + 3] += bi
                b[3 * j:3 * j + 3] += bj
                for (M, r, c) in ((A.T @ W @ A, i, i), (A.T @ W @ B, i, j),
                                  (B.T @ W @ A, j, i), (B.T @ W @ B, j, j)):
                    for a in range(3):
                        for bb in range(3):
                            rows.append(3 * r + a)
                            cols.append(3 * c + bb)
                            vals.append(M[a, bb])

            H = sp.coo_matrix((vals, (rows, cols)), shape=(3 * n, 3 * n)).tocsr()
            H = H + damping * sp.eye(3 * n, format="csr")
            # Anchor node 0.
            for k in range(3):
                H[k, k] += 1e6
            b[:3] = 0.0

            try:
                dx = spla.spsolve(H.tocsc(), b)
            except Exception:
                break
            if not np.all(np.isfinite(dx)):
                break

            X += dx.reshape(n, 3)
            X[:, 2] = wrap(X[:, 2])
            if np.linalg.norm(dx) < tol:
                break

        self.nodes = [X[k] for k in range(n)]
        return X, H
