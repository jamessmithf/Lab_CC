#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Exhaustive Edge Cases and Numerical Rigor Test Suite for Solver and Baseline.
"""

from __future__ import print_function, division
import sys
import os
import math
from solver import Solver
from baseline import midpoint_rectangle_integrate


class MockAsyncResult(object):
    def __init__(self, value):
        self.value = value


class MockWorkerProxy(object):
    def __init__(self, worker_id):
        self.worker_id = worker_id

    def mymap(self, a, b, n):
        return MockAsyncResult(Solver.mymap(a, b, n))


def run_solver_with_mock(workers_count, a, b, n, input_content=None):
    test_in = "temp_edge_in.txt"
    test_out = "temp_edge_out.txt"

    if input_content is not None:
        with open(test_in, "w") as f:
            f.write(input_content)
    else:
        with open(test_in, "w") as f:
            f.write("{:.6f} {:.6f} {:d}\n".format(a, b, n))

    workers = [MockWorkerProxy(i) for i in range(workers_count)]
    solver = Solver(workers=workers, input_file_name=test_in, output_file_name=test_out)
    solver.solve()

    with open(test_out, "r") as f:
        first_line = f.readline().strip()
        result_val = float(first_line)

    if os.path.exists(test_in):
        os.remove(test_in)
    if os.path.exists(test_out):
        os.remove(test_out)

    return result_val


def test_edge_cases():
    print("=" * 60)
    print("RUNNING EXHAUSTIVE EDGE CASES TEST SUITE")
    print("=" * 60)

    # Test 1: N = 0
    print("\n[Case 1] N = 0 (zero integration intervals)")
    res = run_solver_with_mock(workers_count=4, a=0.0, b=1.0, n=0)
    print("  Result: %.6f (Expected: 0.0)" % res)
    assert res == 0.0, "Failed on N=0"
    print("  -> PASSED")

    # Test 2: a == b (zero-width interval)
    print("\n[Case 2] a == b: interval [2.5, 2.5], N = 1000")
    res = run_solver_with_mock(workers_count=4, a=2.5, b=2.5, n=1000)
    print("  Result: %.6f (Expected: 0.0)" % res)
    assert res == 0.0, "Failed on a == b"
    print("  -> PASSED")

    # Test 3: N < P (fewer steps than workers: N=2, P=4)
    print("\n[Case 3] N < P: N=2 steps with 4 workers")
    res = run_solver_with_mock(workers_count=4, a=0.0, b=1.0, n=2)
    expected = midpoint_rectangle_integrate(0.0, 1.0, 2)
    diff = abs(res - expected)
    print("  Result: %.15f, Sequential: %.15f, Diff: %.6e" % (res, expected, diff))
    assert diff < 1e-14, "Failed on N < P"
    print("  -> PASSED")

    # Test 4: N not divisible by P (e.g. N=10, P=3)
    print("\n[Case 4] N not divisible by P: N=10 steps with 3 workers")
    res = run_solver_with_mock(workers_count=3, a=0.0, b=1.0, n=10)
    expected = midpoint_rectangle_integrate(0.0, 1.0, 10)
    diff = abs(res - expected)
    print("  Result: %.15f, Sequential: %.15f, Diff: %.6e" % (res, expected, diff))
    assert diff < 1e-14, "Failed on non-divisible N"
    print("  -> PASSED")

    # Test 5: Reversed bounds a > b: [1.0, 0.0]
    print("\n[Case 5] Reversed bounds: [1.0, 0.0], N=100000")
    res = run_solver_with_mock(workers_count=2, a=1.0, b=0.0, n=100000)
    exact = -math.pi
    diff = abs(res - exact)
    print("  Result: %.15f, Exact: %.15f, Diff: %.6e" % (res, exact, diff))
    assert diff < 1e-10 and res < 0.0, "Failed on reversed bounds"
    print("  -> PASSED")

    # Test 6: Symmetric interval with negative bound: [-1.0, 1.0]
    print("\n[Case 6] Symmetric interval [-1.0, 1.0], N=1000000")
    res = run_solver_with_mock(workers_count=4, a=-1.0, b=1.0, n=1000000)
    exact = 2.0 * math.pi
    diff = abs(res - exact)
    print("  Result: %.15f, Exact: %.15f, Diff: %.6e" % (res, exact, diff))
    assert diff < 1e-12, "Failed on [-1, 1]"
    print("  -> PASSED")

    # Test 7: Input file with comments, commas, and scientific notation
    print("\n[Case 7] Complex input format: '# comment', commas, '1e6'")
    raw_input = "# Parameter file for numerical integration\n# Bounds\n0.0, 1.0, 1e6\n"
    res = run_solver_with_mock(workers_count=4, a=0, b=0, n=0, input_content=raw_input)
    exact = math.pi
    diff = abs(res - exact)
    print("  Result: %.15f, Exact: %.15f, Diff: %.6e" % (res, exact, diff))
    assert diff < 1e-12, "Failed on complex formatted input"
    print("  -> PASSED")

    # Test 8: Single number input (only N given, defaults to [0, 1])
    print("\n[Case 8] Single-token input: '500000'")
    res = run_solver_with_mock(workers_count=2, a=0, b=0, n=0, input_content="500000\n")
    exact = math.pi
    diff = abs(res - exact)
    print("  Result: %.15f, Exact: %.15f, Diff: %.6e" % (res, exact, diff))
    assert diff < 1e-11, "Failed on single-token input"
    print("  -> PASSED")

    # Test 9: Zero workers fallback (P = 0)
    print("\n[Case 9] Zero workers fallback (P = 0)")
    res = run_solver_with_mock(workers_count=0, a=0.0, b=1.0, n=100000)
    exact = math.pi
    diff = abs(res - exact)
    print("  Result: %.15f, Exact: %.15f, Diff: %.6e" % (res, exact, diff))
    assert diff < 1e-10, "Failed on zero workers fallback"
    print("  -> PASSED")

    # Test 10: Strict consistency: Parallel (4 workers) vs Sequential for N=10,000,000
    print("\n[Case 10] Numerical consistency: Parallel (4 workers) vs Sequential (N=10,000,000)")
    res_par = run_solver_with_mock(workers_count=4, a=0.0, b=1.0, n=10000000)
    res_seq = midpoint_rectangle_integrate(0.0, 1.0, 10000000)
    diff = abs(res_par - res_seq)
    print("  Parallel   : %.15f" % res_par)
    print("  Sequential : %.15f" % res_seq)
    print("  Difference : %.6e" % diff)
    # In floating-point arithmetic, block summation (parallel reduction) and sequential
    # accumulation differ by standard round-off error of order O(sqrt(N) * eps) ~ 10^-13.
    assert diff < 1e-12, "Discrepancy between parallel and sequential implementations!"
    print("  -> PASSED (Values match within floating-point round-off limit ~ 10^-13!)")

    print("\n" + "=" * 60)
    print("ALL 10 RIGOROUS EDGE CASES SUCCESSFULLY PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    test_edge_cases()
