#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Baseline Sequential Implementation of Numerical Integration
using the Midpoint Rectangle Rule (Метод середніх прямокутників).

Reuses the exact same computational kernel (integrate_chunk) and I/O format
from solver.py so that sequential and PARCS timings are strictly comparable
in the same Python 2.7 / 3.x environment.

Usage:
  # File mode (used by driver.py, identical input/output format to PARCS):
  python baseline.py input.txt output.txt

  # CLI benchmark mode:
  python baseline.py -a 0.0 -b 1.0 -n 10000000 -r 3
"""

from __future__ import print_function, division
import os
import sys
import time
import argparse
import json

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from solver import (  # noqa: E402
    integrate_chunk,
    verify_result,
    read_input_file,
    write_output_file,
)

# Ensure timer compatibility across Python 2 and Python 3
timer = time.time

# Cross-version lazy range iterator (xrange on Python 2.7, range on Python 3.x)
xrange_compat = getattr(__import__('__builtin__'), 'xrange') if sys.version_info[0] < 3 else range

# Backward-compatible alias used by unit/edge test suites
midpoint_rectangle_integrate = integrate_chunk


def run_file_mode(input_path, output_path):
    """
    Runs a single sequential pass reading from input_path and writing
    output_path with identical # TIMING {json} format to Solver.solve().
    """
    t0 = time.time()
    a, b, n = read_input_file(input_path)
    t_read = time.time() - t0

    t_c0 = time.time()
    calculated = integrate_chunk(a, b, n)
    t_compute = time.time() - t_c0

    t_r0 = time.time()
    exact, abs_err, rel_err, ok = verify_result(calculated, a, b, n)
    t_check = time.time() - t_r0

    timing = {
        'mode': 'sequential',
        'workers': 0,
        'a': a,
        'b': b,
        'n': n,
        'integral': calculated,
        'exact': exact,
        'abs_error': abs_err,
        'rel_error': rel_err,
        'correct': ok,
        'read': t_read,
        'map_wall': t_compute,
        'compute_max': t_compute,
        'compute_sum': t_compute,
        'imbalance': 1.0,
        'reduce': t_check,
        'write': 0.0,
        'total': time.time() - t0,
    }

    t_w0 = time.time()
    write_output_file(output_path, calculated, a, b, n, 0, timing)
    timing['write'] = time.time() - t_w0
    timing['total'] = time.time() - t0
    write_output_file(output_path, calculated, a, b, n, 0, timing)

    print("sequential: N=%d, compute=%.4fs, total=%.4fs, abs_err=%.3e, correct=%s" % (
        n, t_compute, timing['total'], abs_err, ok
    ))
    return timing


def run_benchmark(a, b, n, repeats=3):
    """
    Runs integration multiple times and collects timing statistics.
    """
    a = float(a)
    b = float(b)
    n = int(n)

    exact_value, _, _, _ = verify_result(0.0, a, b, 0)

    if n <= 0 or a == b:
        return {
            "a": a, "b": b, "n": n, "repeats": repeats,
            "integral_value": 0.0, "exact_value": exact_value,
            "abs_error": abs(0.0 - exact_value), "rel_error": 0.0,
            "avg_time_sec": 0.0, "min_time_sec": 0.0, "all_times": [0.0] * repeats
        }

    times = []
    integral_val = 0.0

    for _ in xrange_compat(repeats):
        start_time = timer()
        integral_val = integrate_chunk(a, b, n)
        elapsed = timer() - start_time
        times.append(elapsed)

    avg_time = sum(times) / float(len(times))
    min_time = min(times)

    exact_value, abs_error, rel_error, _ = verify_result(integral_val, a, b, n)

    return {
        "a": a,
        "b": b,
        "n": n,
        "repeats": repeats,
        "integral_value": integral_val,
        "exact_value": exact_value,
        "abs_error": abs_error,
        "rel_error": rel_error,
        "avg_time_sec": avg_time,
        "min_time_sec": min_time,
        "all_times": times
    }


def main():
    # Support simple 2-positional-arg invocation: python baseline.py input.txt output.txt
    if len(sys.argv) == 3 and not sys.argv[1].startswith('-') and not sys.argv[2].startswith('-'):
        run_file_mode(sys.argv[1], sys.argv[2])
        return

    parser = argparse.ArgumentParser(
        description="Sequential Baseline Numerical Integration (Midpoint Rectangle Rule)"
    )
    parser.add_argument("-a", type=float, default=0.0, help="Lower bound of integration (default: 0.0)")
    parser.add_argument("-b", type=float, default=1.0, help="Upper bound of integration (default: 1.0)")
    parser.add_argument("-n", type=int, default=10000000, help="Number of integration steps (default: 10,000,000)")
    parser.add_argument("-r", "--repeats", type=int, default=3, help="Number of repetitions for timing (default: 3)")
    parser.add_argument("--input", dest="input_file", type=str, default=None,
                        help="Run in file mode reading (a, b, N) from input file")
    parser.add_argument("--output-file", dest="output_file", type=str, default=None,
                        help="Output report file path for --input file mode")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("-o", "--output", type=str, default=None, help="Save JSON results to specified file")

    args = parser.parse_args()

    if args.input_file:
        if not args.output_file:
            parser.error("--output-file is required when --input is specified")
        run_file_mode(args.input_file, args.output_file)
        return

    results = run_benchmark(args.a, args.b, args.n, args.repeats)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("=" * 60)
        print("  SEQUENTIAL BASELINE NUMERICAL INTEGRATION")
        print("  Method: Midpoint Rectangle Rule (Середні прямокутники)")
        print("=" * 60)
        print("  Interval [a, b]       : [{:.4f}, {:.4f}]".format(results["a"], results["b"]))
        print("  Steps (N)             : {:,}".format(results["n"]))
        print("  Repeats               : {}".format(results["repeats"]))
        print("-" * 60)
        print("  Calculated Integral   : {:.15f}".format(results["integral_value"]))
        print("  Exact Analytical (pi) : {:.15f}".format(results["exact_value"]))
        print("  Absolute Error        : {:.6e}".format(results["abs_error"]))
        print("  Relative Error        : {:.6e}%".format(results["rel_error"]))
        print("-" * 60)
        print("  Average Execution Time: {:.4f} sec".format(results["avg_time_sec"]))
        print("  Minimum Execution Time: {:.4f} sec".format(results["min_time_sec"]))
        print("=" * 60)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print("Results saved to: {}".format(args.output))


if __name__ == "__main__":
    main()
