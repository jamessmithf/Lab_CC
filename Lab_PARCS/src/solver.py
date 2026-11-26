#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PARCS-Python Solution Module for Numerical Integration
Method: Midpoint Rectangle Rule (Метод середніх прямокутників)
Target Function: f(x) = 4 / (1 + x^2) on [a, b], exact integral = 4 * (atan(b) - atan(a)).

Author: Viktor Sikora (KNU, Faculty of Computer Science and Cybernetics, TK-42)

Features:
- Shared numerical kernel (integrate_chunk) reused by baseline.py for fair comparison
- Fine-grained timing instrumentation (# TIMING {json}): read, map_wall,
  compute_per_worker, rpc_per_worker, transfer_per_worker, imbalance, reduce, write, total
- Load balancing with arbitrary worker counts (even, odd, N < P)
- Floating point boundary drift elimination
- Full UTF-8 BOM, Windows CRLF, and delimiter resilience
- Compatible with Python 2.7 (PARCS-Python) and Python 3.x
"""

from __future__ import print_function, division
import os
import sys
import time
import math
import json

# Pyro4 decorator handling
try:
    from Pyro4 import expose
except ImportError:
    # Fallback decorator for standalone testing without Pyro4 installed
    def expose(func):
        return func

# Cross-version lazy range iterator (xrange on Python 2.7, range on Python 3.x)
xrange_compat = getattr(__import__('__builtin__'), 'xrange') if sys.version_info[0] < 3 else range


# ---------------------------------------------------------------------------
# Numerical kernel & shared helpers (reused by baseline.py)
# ---------------------------------------------------------------------------

def exact_integral(a, b):
    """Analytical value of integral of 4 / (1 + x^2) on [a, b]."""
    a = float(a)
    b = float(b)
    if a == 0.0 and b == 1.0:
        return math.pi
    return 4.0 * (math.atan(b) - math.atan(a))


def integrate_chunk(a, b, n):
    """
    Computes the definite integral of f(x) = 4 / (1 + x^2) on [a, b]
    using the midpoint rectangle rule with n elementary subintervals.
    """
    a = float(a)
    b = float(b)
    n = int(n)

    if n <= 0 or a == b:
        return 0.0

    h = (b - a) / float(n)
    sub_sum = 0.0

    for i in xrange_compat(n):
        x_mid = a + (i + 0.5) * h
        sub_sum += 4.0 / (1.0 + x_mid * x_mid)

    return sub_sum * h


def verify_result(calculated, a, b, n):
    """
    Verifies numerical result against the midpoint rule theoretical error bound:
        |E_M| <= |b - a|^3 * max|f''(x)| / (24 * N^2), where max|f''(x)| = 8.
    """
    exact = exact_integral(a, b)
    abs_err = abs(calculated - exact)
    rel_err = (abs_err / abs(exact) * 100.0) if exact != 0.0 else 0.0

    if math.isnan(calculated) or math.isinf(calculated):
        return exact, abs_err, rel_err, False

    if n <= 0 or a == b:
        return exact, abs_err, rel_err, (calculated == 0.0)

    # Theoretical midpoint error bound (8 / 24 = 1 / 3) + IEEE-754 rounding tolerance
    err_bound = (abs(b - a) ** 3) / (3.0 * float(n) * float(n)) + 1e-10 * max(1.0, abs(exact))
    ok = abs_err <= err_bound
    return exact, abs_err, rel_err, ok


def read_input_file(input_file_name):
    """
    Reads input parameters (a, b, N) with support for:
    - Multiline and single-line space-separated formats
    - UTF-8 BOM markers (from Windows Notepad)
    - Windows CRLF and Linux LF line endings
    - Comma and semicolon delimiters
    - Scientific notation (e.g. '1e7', '1.0E+07')
    - Comments (lines starting with '#')
    - Fallback defaults if file is missing, empty, or partial
    """
    default_a, default_b, default_n = 0.0, 1.0, 10000000

    if not input_file_name or not os.path.exists(input_file_name):
        print("[Solver] Warning: input file not found. Using defaults: [0.0, 1.0], N=10,000,000")
        return default_a, default_b, default_n

    clean_tokens = []
    try:
        with open(input_file_name, 'rb') as f:
            raw_bytes = f.read()

        if raw_bytes.startswith(b'\xef\xbb\xbf'):
            raw_bytes = raw_bytes[3:]

        raw_text = raw_bytes.decode('utf-8', 'ignore')

        for line in raw_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            line = line.replace(',', ' ').replace(';', ' ')
            clean_tokens.extend(line.split())
    except Exception as e:
        print("[Solver] Warning: Error reading input file (%s). Using defaults." % str(e))
        return default_a, default_b, default_n

    try:
        if len(clean_tokens) >= 3:
            a = float(clean_tokens[0])
            b = float(clean_tokens[1])
            n = int(float(clean_tokens[2]))
            return a, b, n
        elif len(clean_tokens) == 2:
            a = float(clean_tokens[0])
            b = float(clean_tokens[1])
            return a, b, default_n
        elif len(clean_tokens) == 1:
            n = int(float(clean_tokens[0]))
            return default_a, default_b, n
    except ValueError as ve:
        print("[Solver] Warning: Invalid number format in input file (%s). Using defaults." % str(ve))

    return default_a, default_b, default_n


def write_output_file(output_file_name, calculated_integral, a, b, n, num_workers, timing):
    """
    Writes output file:
    - Line 1: Pure numerical value (backward-compatible with programmatic parsers/tests)
    - Line 2: "# TIMING {json}" with full timing breakdown for benchmark driver
    - Remaining lines: Human-readable report for PARCS Web UI inspection
    """
    exact = timing['exact']
    abs_err = timing['abs_error']
    rel_err = timing['rel_error']
    elapsed_sec = timing['total']

    if not output_file_name:
        print("[Output] Integral: %.15f (Exact: %.15f, AbsErr: %.6e, Time: %.4fs)" % (
            calculated_integral, exact, abs_err, elapsed_sec
        ))
        return

    out_dir = os.path.dirname(output_file_name)
    if out_dir and not os.path.exists(out_dir):
        try:
            os.makedirs(out_dir)
        except OSError:
            pass

    with open(output_file_name, 'w') as f:
        # Line 1: Pure numerical value
        f.write("{:.15f}\n".format(calculated_integral))
        # Line 2: Machine-readable JSON timing instrumentation
        f.write("# TIMING " + json.dumps(timing, sort_keys=True) + "\n")
        # Human-readable report
        f.write("=" * 60 + "\n")
        f.write("PARCS-PYTHON NUMERICAL INTEGRATION REPORT\n")
        f.write("=" * 60 + "\n")
        f.write("Calculated Integral   : {:.15f}\n".format(calculated_integral))
        f.write("Exact Analytical (pi) : {:.15f}\n".format(exact))
        f.write("Absolute Error        : {:.6e}\n".format(abs_err))
        f.write("Relative Error        : {:.6e}%\n".format(rel_err))
        f.write("Verification Status   : {}\n".format("OK" if timing['correct'] else "FAILED"))
        f.write("-" * 60 + "\n")
        f.write("Integration Interval  : [{:.6f}, {:.6f}]\n".format(a, b))
        f.write("Total Steps (N)       : {:d}\n".format(n))
        f.write("Active Workers Count  : {:d}\n".format(num_workers))
        f.write("Execution Time        : {:.4f} seconds\n".format(elapsed_sec))
        if 'compute_max' in timing:
            f.write("Max Worker Compute    : {:.4f} seconds\n".format(timing['compute_max']))
        if 'transfer_per_worker' in timing and timing['transfer_per_worker']:
            f.write("Max RPC/Transfer      : {:.4f} seconds\n".format(max(timing['transfer_per_worker'])))
        if 'imbalance' in timing and timing['imbalance'] is not None:
            f.write("Load Imbalance (m/avg): {:.4f}\n".format(timing['imbalance']))
        f.write("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# PARCS-Python Solver
# ---------------------------------------------------------------------------

class Solver(object):
    """
    PARCS-Python Solver class adhering to the platform architecture.
    """

    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.workers = workers or []
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        print("[Solver] Initialized with %d worker(s)" % len(self.workers))

    def solve(self):
        t0 = time.time()
        print("[Solver] Job Started at %s" % time.ctime(t0))
        num_workers = len(self.workers)
        print("[Solver] Number of available workers: %d" % num_workers)

        # 1. Read input configuration
        a, b, n = self.read_input()
        t_read = time.time() - t0
        print("[Solver] Input Parameters: Interval=[%.10g, %.10g], N=%d" % (a, b, n))

        # Edge Case: N <= 0 or a == b
        if n <= 0 or a == b:
            print("[Solver] Edge case encountered: n=%d, interval=[%.6f, %.6f]. Result is 0.0." % (n, a, b))
            exact, abs_err, rel_err, ok = verify_result(0.0, a, b, n)
            timing = {
                'mode': 'parcs',
                'workers': num_workers,
                'a': a, 'b': b, 'n': n,
                'integral': 0.0, 'exact': exact,
                'abs_error': abs_err, 'rel_error': rel_err, 'correct': ok,
                'read': t_read, 'map_wall': 0.0, 'reduce': 0.0,
                'compute_per_worker': [], 'rpc_per_worker': [], 'transfer_per_worker': [],
                'compute_max': 0.0, 'compute_sum': 0.0, 'imbalance': 1.0,
                'steps_per_worker': [], 'write': 0.0, 'total': time.time() - t0,
            }
            self._write_with_final_timing(0.0, a, b, n, num_workers, timing, t0)
            print("[Solver] Job Finished in %.4f seconds" % timing['total'])
            return

        # Edge Case: No workers available -> execute sequential fallback on master
        if num_workers == 0:
            print("[Solver] Notice: No remote workers assigned. Running computation locally on master.")
            t_c0 = time.time()
            res = self.mymap(a, b, n)
            total_integral = res['integral'] if isinstance(res, dict) else float(res)
            t_comp = res['compute_time'] if isinstance(res, dict) else (time.time() - t_c0)
            exact, abs_err, rel_err, ok = verify_result(total_integral, a, b, n)
            timing = {
                'mode': 'parcs_fallback',
                'workers': 0,
                'a': a, 'b': b, 'n': n,
                'integral': total_integral, 'exact': exact,
                'abs_error': abs_err, 'rel_error': rel_err, 'correct': ok,
                'read': t_read, 'map_wall': t_comp, 'reduce': 0.0,
                'compute_per_worker': [t_comp], 'rpc_per_worker': [t_comp],
                'transfer_per_worker': [0.0],
                'compute_max': t_comp, 'compute_sum': t_comp, 'imbalance': 1.0,
                'steps_per_worker': [n], 'write': 0.0, 'total': time.time() - t0,
            }
            self._write_with_final_timing(total_integral, a, b, n, 0, timing, t0)
            print("[Solver] Master sequential job finished in %.4f seconds" % timing['total'])
            return

        # 2. Optimal decomposition and load balancing among workers
        base_n = n // num_workers
        remainder = n % num_workers
        total_h = float(b - a) / float(n)

        subtasks = []
        steps_per_worker = []
        cumulative_steps = 0

        for i in xrange_compat(num_workers):
            worker_n = base_n + (1 if i < remainder else 0)
            steps_per_worker.append(worker_n)
            if worker_n <= 0:
                worker_a = b
                worker_b = b
            else:
                worker_a = a + cumulative_steps * total_h
                cumulative_steps += worker_n
                worker_b = b if (cumulative_steps == n) else (a + cumulative_steps * total_h)
            subtasks.append((worker_a, worker_b, worker_n))

        # 3. Asynchronous MAP dispatch via Pyro4 proxies
        t_map0 = time.time()
        futures = []
        for i in xrange_compat(num_workers):
            worker_a, worker_b, worker_n = subtasks[i]
            print("[Solver] Dispatching Worker %d: subinterval=[%.6f, %.6f], steps=%d" % (
                i, worker_a, worker_b, worker_n
            ))
            futures.append(self.workers[i].mymap(worker_a, worker_b, worker_n))

        print("[Solver] All subtasks dispatched to workers. Awaiting asynchronous results...")

        # Poll futures to capture exact per-worker completion time
        done_at = [None] * num_workers
        if any(hasattr(f, 'ready') for f in futures):
            while None in done_at:
                for i in xrange_compat(num_workers):
                    if done_at[i] is None and (not hasattr(futures[i], 'ready') or futures[i].ready):
                        done_at[i] = time.time()
                if None in done_at:
                    time.sleep(0.002)
        else:
            now = time.time()
            done_at = [now] * num_workers

        mapped = [f.value if hasattr(f, 'value') else f for f in futures]
        t_map = time.time() - t_map0

        # 4. REDUCE partial sums and verify result
        t_red0 = time.time()
        total_integral = self.myreduce(mapped)
        exact, abs_err, rel_err, ok = verify_result(total_integral, a, b, n)
        t_reduce = time.time() - t_red0

        # Collect per-worker timing instrumentation
        rpc_times = [done_at[i] - t_map0 for i in xrange_compat(num_workers)]
        compute_times = [
            m['compute_time'] if isinstance(m, dict) and 'compute_time' in m else rpc_times[i]
            for i, m in enumerate(mapped)
        ]
        transfer_times = [max(0.0, r - c) for r, c in zip(rpc_times, compute_times)]
        compute_sum = sum(compute_times)
        compute_max = max(compute_times) if compute_times else 0.0
        compute_mean = (compute_sum / float(num_workers)) if num_workers > 0 else 0.0
        imbalance = (compute_max / compute_mean) if compute_mean > 0.0 else 1.0

        timing = {
            'mode': 'parcs',
            'workers': num_workers,
            'a': a,
            'b': b,
            'n': n,
            'integral': total_integral,
            'exact': exact,
            'abs_error': abs_err,
            'rel_error': rel_err,
            'correct': ok,
            'read': t_read,
            'map_wall': t_map,
            'compute_per_worker': compute_times,
            'rpc_per_worker': rpc_times,
            'transfer_per_worker': transfer_times,
            'compute_max': compute_max,
            'compute_sum': compute_sum,
            'imbalance': imbalance,
            'steps_per_worker': steps_per_worker,
            'reduce': t_reduce,
            'write': 0.0,
            'total': time.time() - t0,
        }

        print("[Solver] Reduction complete. Final integral: %.15f (correct=%s)" % (total_integral, ok))

        # 5. Write formatted output with finalized write/total timing
        self._write_with_final_timing(total_integral, a, b, n, num_workers, timing, t0)
        print("[Solver] Total Master execution time: %.4f seconds" % timing['total'])
        print("[Solver] Output file successfully written. Job Finished.")

    def _write_with_final_timing(self, calculated_integral, a, b, n, num_workers, timing, t0):
        t_w0 = time.time()
        write_output_file(self.output_file_name, calculated_integral, a, b, n, num_workers, timing)
        timing['write'] = time.time() - t_w0
        timing['total'] = time.time() - t0
        if self.output_file_name:
            write_output_file(self.output_file_name, calculated_integral, a, b, n, num_workers, timing)

    @staticmethod
    @expose
    def mymap(a, b, n):
        """
        Worker task (executed remotely on worker nodes).
        Returns partial integral and pure compute duration on this worker.
        """
        t0 = time.time()
        partial_integral = integrate_chunk(a, b, n)
        return {
            'integral': partial_integral,
            'compute_time': time.time() - t0,
        }

    @staticmethod
    @expose
    def myreduce(mapped):
        """
        Master reduction method.
        Collects partial sums from worker results (supports dict payload and raw float).
        """
        total = 0.0
        for res in mapped:
            val = res.value if hasattr(res, 'value') else res
            if isinstance(val, dict):
                total += float(val.get('integral', 0.0))
            elif val is not None:
                total += float(val)
        return total

    def read_input(self):
        return read_input_file(self.input_file_name)

    def write_output(self, calculated_integral, a, b, n, num_workers, elapsed_sec):
        """Backward-compatible wrapper for direct callers."""
        exact, abs_err, rel_err, ok = verify_result(calculated_integral, a, b, n)
        timing = {
            'mode': 'parcs',
            'workers': num_workers,
            'a': a, 'b': b, 'n': n,
            'integral': calculated_integral, 'exact': exact,
            'abs_error': abs_err, 'rel_error': rel_err, 'correct': ok,
            'total': elapsed_sec,
        }
        write_output_file(self.output_file_name, calculated_integral, a, b, n, num_workers, timing)
