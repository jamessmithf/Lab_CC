#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_comprehensive_edge_tests.py
Full automated verification suite for the 4-Vector Edge Case Test Plan.
"""

import sys
import os
import math
import time
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from solver import Solver
from baseline import midpoint_rectangle_integrate

MASTER_URL = "http://localhost:8080"


class MockAsyncResult(object):
    def __init__(self, value):
        self.value = value


class MockWorkerProxy(object):
    def __init__(self, worker_id):
        self.worker_id = worker_id

    def mymap(self, a, b, n):
        return MockAsyncResult(Solver.mymap(a, b, n))


def run_solver_mock(workers_count, a, b, n, raw_input_bytes=None):
    in_file = "temp_in.txt"
    out_file = "temp_out.txt"

    if raw_input_bytes is not None:
        with open(in_file, "wb") as f:
            f.write(raw_input_bytes)
    else:
        with open(in_file, "w") as f:
            f.write(f"{a:.15g} {b:.15g} {n:d}\n")

    workers = [MockWorkerProxy(i) for i in range(workers_count)]
    solver = Solver(workers=workers, input_file_name=in_file, output_file_name=out_file)
    solver.solve()

    with open(out_file, "r") as f:
        val = float(f.readline().strip())

    if os.path.exists(in_file):
        os.remove(in_file)
    if os.path.exists(out_file):
        os.remove(out_file)

    return val


def run_live_cluster_job(raw_input_bytes, job_name="edge_job", timeout=60):
    solver_path = os.path.join(SCRIPT_DIR, "solver.py")
    files = {
        "solution_file": ("solver.py", open(solver_path, "rb"), "text/x-python"),
        "input_file": ("input.txt", raw_input_bytes, "text/plain")
    }
    data = {"job_name": job_name}

    resp = requests.post(f"{MASTER_URL}/api/job", files=files, data=data, timeout=10)
    resp.raise_for_status()

    # Find the job ID
    latest_id = 0
    for cand in range(1000):
        try:
            r = requests.get(f"{MASTER_URL}/api/job/{cand}/output", timeout=3)
            if r.status_code == 404:
                latest_id = max(0, cand - 1)
                break
            elif r.status_code in (200, 400):
                latest_id = cand
        except Exception:
            break

    # Wait for completion
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{MASTER_URL}/api/job/{latest_id}/output", timeout=5)
            if r.status_code == 200 and "Execution Time" in r.text:
                first_line = r.text.strip().splitlines()[0]
                return float(first_line), r.text
        except Exception:
            pass
        time.sleep(0.5)

    raise TimeoutError(f"Live cluster job {latest_id} timed out after {timeout}s")


def main():
    print("=" * 70)
    print("EXECUTION OF 4-VECTOR COMPREHENSIVE EDGE CASE SUITE")
    print("=" * 70)

    # -------------------------------------------------------------
    # VECTOR 1: Mathematical & Numerical Extremes
    # -------------------------------------------------------------
    print("\n[VECTOR 1] Testing Numerical & Mathematical Extremes...")

    # 1.1 Wide interval [0.0, 1000.0]
    print("  1.1 Wide interval [0.0, 1000.0], N=1,000,000, P=4:")
    res_wide = run_solver_mock(4, 0.0, 1000.0, 1000000)
    exact_wide = 4.0 * (math.atan(1000.0) - math.atan(0.0))
    diff_wide = abs(res_wide - exact_wide)
    print(f"      Calculated: {res_wide:.14f}, Exact: {exact_wide:.14f}, Diff: {diff_wide:.2e}")
    assert diff_wide < 1e-8, "Wide interval error too large"
    print("      -> PASSED")

    # 1.2 Sub-micron interval [0.5, 0.5000001]
    print("  1.2 Sub-micron interval [0.5, 0.5000001], N=100,000, P=2:")
    a_micro, b_micro = 0.5, 0.5000001
    res_micro = run_solver_mock(2, a_micro, b_micro, 100000)
    exact_micro = 4.0 * (math.atan(b_micro) - math.atan(a_micro))
    diff_micro = abs(res_micro - exact_micro)
    print(f"      Calculated: {res_micro:.14e}, Exact: {exact_micro:.14e}, Diff: {diff_micro:.2e}")
    assert diff_micro < 1e-15 or (diff_micro / exact_micro) < 1e-8, "Submicron interval error"
    print("      -> PASSED")

    # 1.3 Asymmetric interval crossing zero [-2.0, 3.0]
    print("  1.3 Asymmetric crossing zero [-2.0, 3.0], N=1,000,000, P=4:")
    res_asym = run_solver_mock(4, -2.0, 3.0, 1000000)
    exact_asym = 4.0 * (math.atan(3.0) - math.atan(-2.0))
    diff_asym = abs(res_asym - exact_asym)
    print(f"      Calculated: {res_asym:.14f}, Exact: {exact_asym:.14f}, Diff: {diff_asym:.2e}")
    assert diff_asym < 1e-12, "Asymmetric interval error"
    print("      -> PASSED")

    # 1.4 Single step N = 1
    print("  1.4 Single step N = 1 on [0.0, 1.0], P=2:")
    res_n1 = run_solver_mock(2, 0.0, 1.0, 1)
    expected_n1 = 4.0 / (1.0 + 0.5**2) * 1.0  # 4 / 1.25 = 3.2
    diff_n1 = abs(res_n1 - expected_n1)
    print(f"      Calculated: {res_n1:.14f}, Expected: {expected_n1:.14f}, Diff: {diff_n1:.2e}")
    assert diff_n1 < 1e-14, "N=1 step error"
    print("      -> PASSED")

    # 1.5 Prime number of steps N = 9,999,991, P=4
    print("  1.5 Prime number of steps N = 9,999,991 with P=4:")
    res_prime = run_solver_mock(4, 0.0, 1.0, 9999991)
    exact_pi = math.pi
    diff_prime = abs(res_prime - exact_pi)
    print(f"      Calculated: {res_prime:.14f}, Exact: {exact_pi:.14f}, Diff: {diff_prime:.2e}")
    assert diff_prime < 1e-12, "Prime step error"
    print("      -> PASSED")

    # -------------------------------------------------------------
    # VECTOR 2: Distributed Topology & Cluster Lifecycle
    # -------------------------------------------------------------
    print("\n[VECTOR 2] Testing Distributed Topology & Odd Worker Counts...")

    for p in [3, 5, 7]:
        print(f"  2.1 Odd worker count P={p}, N=1,000,000:")
        res_odd = run_solver_mock(p, 0.0, 1.0, 1000000)
        diff_odd = abs(res_odd - math.pi)
        print(f"      P={p}: Calculated: {res_odd:.14f}, Diff: {diff_odd:.2e}")
        assert diff_odd < 1e-12, f"Failed on odd workers count P={p}"
        print(f"      -> P={p} PASSED")

    # 2.2 Overprovisioned workers: N=3 with P=8
    print("  2.2 N < P: N=3 steps with P=8 workers:")
    res_few = run_solver_mock(8, 0.0, 1.0, 3)
    expected_few = midpoint_rectangle_integrate(0.0, 1.0, 3)
    diff_few = abs(res_few - expected_few)
    print(f"      Calculated: {res_few:.14f}, Expected: {expected_few:.14f}, Diff: {diff_few:.2e}")
    assert diff_few < 1e-14, "Failed on N < P"
    print("      -> PASSED")

    # -------------------------------------------------------------
    # VECTOR 3: I/O Resilience & Format Hardening
    # -------------------------------------------------------------
    print("\n[VECTOR 3] Testing File Formats & I/O Resilience...")

    # 3.1 UTF-8 BOM from Windows Notepad
    print("  3.1 UTF-8 BOM marker (\\xef\\xbb\\xbf):")
    bom_data = b"\xef\xbb\xbf0.0 1.0 100000\n"
    res_bom = run_solver_mock(2, 0, 0, 0, raw_input_bytes=bom_data)
    assert abs(res_bom - math.pi) < 1e-10, "Failed with UTF-8 BOM"
    print("      -> PASSED (BOM stripped and parsed correctly)")

    # 3.2 Windows CRLF line endings + comments + semicolons
    print("  3.2 Windows CRLF (\\r\\n), semicolons, and comments:")
    crlf_data = b"# Header comment\r\n0.0; 1.0; 100000\r\n# Footer\r\n"
    res_crlf = run_solver_mock(2, 0, 0, 0, raw_input_bytes=crlf_data)
    assert abs(res_crlf - math.pi) < 1e-10, "Failed with Windows CRLF"
    print("      -> PASSED")

    # 3.3 Scientific notation with capital E: 1.0E+06
    print("  3.3 Scientific notation (1.0E+06):")
    sci_data = b"0.0 1.0 1.0E+06\n"
    res_sci = run_solver_mock(4, 0, 0, 0, raw_input_bytes=sci_data)
    assert abs(res_sci - math.pi) < 1e-12, "Failed with scientific notation"
    print("      -> PASSED")

    # 3.4 No trailing newline at EOF
    print("  3.4 Missing trailing newline at EOF:")
    no_eof_data = b"0.0 1.0 50000"
    res_no_eof = run_solver_mock(2, 0, 0, 0, raw_input_bytes=no_eof_data)
    assert abs(res_no_eof - math.pi) < 1e-9, "Failed without trailing newline"
    print("      -> PASSED")

    # 3.5 Partial input: only 2 numbers (interval given, default N)
    print("  3.5 Partial input (2 numbers: interval [0, 1]):")
    partial_data = b"0.0 1.0\n"
    res_partial = run_solver_mock(2, 0, 0, 0, raw_input_bytes=partial_data)
    assert abs(res_partial - math.pi) < 1e-12, "Failed with partial input"
    print("      -> PASSED (Default N=10,000,000 applied)")

    # -------------------------------------------------------------
    # VECTOR 4: Live Docker Cluster Validation (Master + 4 Workers)
    # -------------------------------------------------------------
    print("\n[VECTOR 4] Testing Live PARCS Cluster via HTTP API (http://localhost:8080)...")

    # 4.1 Check master is alive
    try:
        r = requests.get(f"{MASTER_URL}/api/worker", timeout=3)
        workers_info = r.json().get("workers", [])
        print(f"  Live cluster detected with {len(workers_info)} registered workers.")
    except Exception as e:
        print(f"  [ERROR] Live cluster unreachable: {e}")
        sys.exit(1)

    # 4.2 Submit UTF-8 BOM job to live cluster
    print("  4.1 Submitting UTF-8 BOM input job to live cluster...")
    val_bom_live, _ = run_live_cluster_job(b"\xef\xbb\xbf0.0 1.0 1000000\n", job_name="live_bom_test")
    diff_bom_live = abs(val_bom_live - math.pi)
    print(f"      Live result: {val_bom_live:.14f}, Diff: {diff_bom_live:.2e}")
    assert diff_bom_live < 1e-12, "Live BOM test failed"
    print("      -> PASSED")

    # 4.3 Submit 3 consecutive jobs to verify cluster idempotency
    print("  4.2 Testing cluster idempotency (3 consecutive jobs in live cluster)...")
    for j in range(3):
        t_start = time.time()
        val_idem, text_idem = run_live_cluster_job(b"0.0 1.0 5000000\n", job_name=f"live_seq_{j}")
        elapsed = time.time() - t_start
        assert abs(val_idem - math.pi) < 1e-12, f"Idempotency job {j} failed"
        print(f"      Job {j+1}/3 finished in {elapsed:.2f}s (Result: {val_idem:.14f}) -> OK")
    print("      -> PASSED (Cluster cleanly dispatches and resets workers between jobs)")

    print("\n" + "=" * 70)
    print("ALL TESTS IN ALL 4 VECTORS SUCCESSFULLY COMPLETED AND VERIFIED!")
    print("=" * 70)


if __name__ == "__main__":
    main()
