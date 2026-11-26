#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Local unit test and validator for Solver class.
Simulates Pyro4 async RPC behavior with 1, 2, and 4 workers.
"""

from __future__ import print_function
import sys
import os
import math
from solver import Solver


class MockAsyncResult(object):
    """Simulates Pyro4.core.AsyncResult wrapper with .value attribute"""
    def __init__(self, value):
        self.value = value


class MockWorkerProxy(object):
    """Simulates Pyro4 remote proxy object pointing to a Worker Solver instance"""
    def __init__(self, worker_id):
        self.worker_id = worker_id

    def mymap(self, a, b, n):
        # Executes the exposed static method on the worker
        res = Solver.mymap(a, b, n)
        return MockAsyncResult(res)


def test_solver(workers_count, input_file, output_file):
    print("\n" + "=" * 50)
    print("TESTING SOLVER WITH %d WORKER(S)" % workers_count)
    print("=" * 50)

    mock_workers = [MockWorkerProxy(i) for i in range(workers_count)]
    solver = Solver(workers=mock_workers, input_file_name=input_file, output_file_name=output_file)
    solver.solve()

    assert os.path.exists(output_file), "Output file was not created!"

    with open(output_file, 'r') as f:
        content = f.read()

    print("\nGenerated Output File Content:")
    print(content)

    # Validate output correctness
    with open(input_file, 'r') as f:
        a_in, b_in, n_in = [float(x) for x in f.read().split()]

    exact = math.pi if (a_in == 0.0 and b_in == 1.0) else (math.atan(b_in) - math.atan(a_in)) * 4.0

    for line in content.splitlines():
        if "Calculated Integral" in line:
            val = float(line.split(":")[1].strip())
            diff = abs(val - exact)
            print("Numerical Verification: diff = %.6e" % diff)
            assert diff < 1e-10, "Numerical result error too high: %.6e" % diff

    print(">>> Test with %d worker(s) PASSED successfully!" % workers_count)


def main():
    test_input = "test_input.txt"
    test_output = "test_output.txt"

    with open(test_input, 'w') as f:
        f.write("0.0 1.0 1000000\n")

    try:
        for p in [1, 2, 4]:
            test_solver(p, test_input, test_output)
    finally:
        for f in [test_input, test_output]:
            if os.path.exists(f):
                os.remove(f)

    print("\n" + "=" * 50)
    print("ALL SOLVER LOCAL TESTS COMPLETED AND PASSED!")
    print("=" * 50)


if __name__ == "__main__":
    main()
