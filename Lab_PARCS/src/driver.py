#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unified PARCS-Python Benchmark Driver (Python 2.7 & Python 3.x compatible).

Designed to run INSIDE the PARCS master container (docker exec -d) so that
cloud measurements are unaffected by laptop sleep or internet drops, and the
sequential baseline executes in the exact same Python 2.7 environment as PARCS.

For every problem size N in --sizes:
  1. Generates data/n<N>.txt ("0.0 1.0 <N>").
  2. Runs baseline.py --runs times on the same input (reference T_seq and integral).
  3. For every worker count k in --workers (e.g. 1,2,3,4):
     - Enables exactly k workers via Master REST API (/api/worker/<id>/enable|disable).
     - Submits solver.py + input via /api/job --runs times.
     - Reliably resolves job_id from /jobs by unique job_name, retries on transient errors.
     - Downloads output, parses # TIMING {json}, verifies correctness and match with seq.

Outputs written incrementally into --out:
  results.json  Full dataset (params, cluster metadata, per-run & per-worker timings)
  results.csv   One row per individual run
  summary.csv   Aggregated means/std, S(k), E(k), S_1(k), E_1(k), transfer, imbalance, job_wall
  progress.log  Timestamped execution log
  outputs/      Raw output files from every run
  DONE          Marker file created upon successful completion

Usage:
  python driver.py --sizes 10000000,25000000,50000000,100000000 --runs 3 --workers 1,2,3,4 --out /lab/results
"""

from __future__ import print_function, division

import argparse
import csv
import json
import math
import os
import platform
import re
import subprocess
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, 'solver.py')
BASELINE = os.path.join(HERE, 'baseline.py')


class Driver(object):
    def __init__(self, args):
        self.a = args
        self.master = args.master.rstrip('/')
        self.out = args.out
        self.rows = []
        self.cluster_workers = []
        self.tag = time.strftime('%H%M%S')

        for d in (self.out, os.path.join(self.out, 'data'), os.path.join(self.out, 'outputs')):
            if not os.path.isdir(d):
                os.makedirs(d)

        self.logf = open(os.path.join(self.out, 'progress.log'), 'a')

    # ------------------------------------------------------------------ utils
    def log(self, msg):
        line = '[%s] %s' % (time.strftime('%H:%M:%S'), msg)
        print(line)
        sys.stdout.flush()
        self.logf.write(line + '\n')
        self.logf.flush()

    @staticmethod
    def parse_output(path):
        timing = None
        first_val = None
        with open(path, 'r') as f:
            for idx, raw_line in enumerate(f):
                line = raw_line.strip()
                if idx == 0 and line:
                    try:
                        first_val = float(line)
                    except ValueError:
                        pass
                if line.startswith('# TIMING '):
                    timing = json.loads(line[len('# TIMING '):])
        if timing is None:
            raise RuntimeError('No "# TIMING" line found in output file: %s' % path)
        return timing, first_val

    # --------------------------------------------------------------- workers
    def workers(self):
        r = requests.get(self.master + '/api/worker', timeout=10)
        r.raise_for_status()
        return sorted(r.json().get('workers', []), key=lambda w: w['id'])

    def wait_for_workers(self, need):
        deadline = time.time() + self.a.wait_workers
        while True:
            try:
                ws = self.workers()
                if len(ws) >= need:
                    self.cluster_workers = ws
                    self.log('workers registered: %d (%s)' % (
                        len(ws), ', '.join('#%d %s' % (w['id'], w['ip']) for w in ws)
                    ))
                    return
                self.log('waiting for workers: %d of %d registered' % (len(ws), need))
            except Exception as e:
                self.log('master not ready yet: %s' % e)
            if time.time() > deadline:
                raise RuntimeError('Timed out waiting for %d workers' % need)
            time.sleep(5)

    def use_workers(self, k):
        ws = self.workers()
        if len(ws) < k:
            raise RuntimeError('Need %d workers, master has %d' % (k, len(ws)))
        for i, w in enumerate(ws):
            state = 'enable' if i < k else 'disable'
            r = requests.post('%s/api/worker/%d/%s' % (self.master, w['id'], state), timeout=10)
            r.raise_for_status()
        enabled = [w for w in self.workers() if w['enabled']]
        if len(enabled) != k:
            raise RuntimeError('Wanted %d enabled workers, got %d' % (k, len(enabled)))
        return enabled

    # ------------------------------------------------------------------ jobs
    def retry(self, fn, attempts=10):
        for i in range(attempts):
            try:
                return fn()
            except requests.RequestException as e:
                if i == attempts - 1:
                    raise
                self.log('network error, retrying (%d/%d): %s' % (i + 1, attempts, e))
                time.sleep(2)

    def find_job_id(self, name):
        html = requests.get(self.master + '/jobs', timeout=15).text
        found = None
        pattern = re.compile(r'>\s*%s(\s|<|\[)' % re.escape(name.upper()))
        for block in html.split('job-well')[1:]:
            m = re.search(r'data-job-id="(\d+)"', block)
            if m and pattern.search(block):
                found = int(m.group(1))
        return found

    def job_reason(self, job_id):
        html = requests.get(self.master + '/jobs', timeout=15).text
        needle = 'data-job-id="%d"' % job_id
        for block in html.split('job-well')[1:]:
            if needle in block:
                m = re.search(r'\[reason:([^\]]*)\]', block)
                return m.group(1).strip() if m else 'unknown'
        return 'job not found'

    def run_job(self, name, input_path, output_path):
        t0 = time.time()
        with open(SOLVER, 'rb') as sol, open(input_path, 'rb') as inp:
            r = requests.post(
                self.master + '/api/job',
                data={'job_name': name},
                files={
                    'solution_file': ('solver.py', sol, 'text/x-python'),
                    'input_file': ('input.txt', inp, 'text/plain'),
                },
                timeout=60,
            )
        r.raise_for_status()

        job_id = None
        while job_id is None:
            job_id = self.retry(lambda: self.find_job_id(name))
            if job_id is None:
                if time.time() - t0 > 60:
                    raise RuntimeError('Job %s was not found on master /jobs' % name)
                time.sleep(0.1)

        while True:
            r = self.retry(lambda: requests.get('%s/api/job/%d/output' % (self.master, job_id), timeout=60))
            if r.status_code == 200:
                wall = time.time() - t0
                with open(output_path, 'wb') as f:
                    f.write(r.content)
                return job_id, wall
            if r.status_code == 404:
                raise RuntimeError('Job %d (%s) failed: %s' % (job_id, name, self.job_reason(job_id)))
            if time.time() - t0 > self.a.job_timeout:
                try:
                    requests.delete('%s/api/job/%d' % (self.master, job_id), timeout=10)
                except Exception:
                    pass
                raise RuntimeError('Job %d (%s) timed out after %ds' % (job_id, name, self.a.job_timeout))
            time.sleep(0.2)

    # ------------------------------------------------------------ persistence
    def record(self, n, config, run, timing, extra):
        row = {'N': n, 'config': config, 'run': run}
        row.update(extra)
        row['timing'] = timing
        self.rows.append(row)
        self.save()

    def save(self):
        meta = {
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'cluster_workers': self.cluster_workers,
        }
        with open(os.path.join(self.out, 'results.json'), 'w') as f:
            json.dump({'params': vars(self.a), 'meta': meta, 'rows': self.rows}, f, indent=2, sort_keys=True)

        cols = [
            'N', 'config', 'workers', 'run', 'total', 'compute_max', 'compute_sum',
            'transfer_mean', 'transfer_max', 'imbalance', 'job_wall', 'job_id',
            'integral', 'abs_error', 'correct', 'matches_seq',
        ]
        with open(os.path.join(self.out, 'results.csv'), 'w') as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in self.rows:
                fr = flat(r)
                w.writerow([fmt(fr.get(c), c) for c in cols])

        self.save_summary()

    def save_summary(self):
        groups = []
        for r in self.rows:
            key = (r['N'], r['config'])
            if key not in groups:
                groups.append(key)

        cols = [
            'N', 'config', 'workers', 'runs', 'total_mean', 'total_std',
            'compute_max_mean', 'transfer_mean', 'transfer_max_mean',
            'imbalance_mean', 'job_wall_mean',
            'speedup', 'efficiency', 'speedup_1', 'efficiency_1',
            'job_speedup', 'abs_error_mean', 'all_correct',
        ]

        out = []
        seq_mean = {}
        k1_mean = {}

        for n, cfg in groups:
            rs = [flat(r) for r in self.rows if r['N'] == n and r['config'] == cfg]
            tot = [r['total'] for r in rs]
            s = {
                'N': n,
                'config': cfg,
                'workers': rs[0]['workers'],
                'runs': len(rs),
                'total_mean': mean(tot),
                'total_std': std(tot),
                'compute_max_mean': mean([r['compute_max'] for r in rs]),
                'transfer_mean': mean([r.get('transfer_mean') for r in rs]),
                'transfer_max_mean': mean([r.get('transfer_max') for r in rs]),
                'imbalance_mean': mean([r.get('imbalance') for r in rs]),
                'job_wall_mean': mean([r.get('job_wall') for r in rs]),
                'abs_error_mean': mean([r.get('abs_error') for r in rs]),
                'all_correct': all(r['correct'] and r.get('matches_seq', True) for r in rs),
            }
            if cfg == 'seq':
                seq_mean[n] = s['total_mean']
            elif cfg == 'k1':
                k1_mean[n] = s['total_mean']

            base_seq = seq_mean.get(n)
            base_k1 = k1_mean.get(n)
            if cfg != 'seq' and s['total_mean'] and s['workers'] > 0:
                if base_seq:
                    s['speedup'] = base_seq / s['total_mean']
                    s['efficiency'] = s['speedup'] / float(s['workers'])
                    s['job_speedup'] = (base_seq / s['job_wall_mean']) if s['job_wall_mean'] else None
                if base_k1:
                    s['speedup_1'] = base_k1 / s['total_mean']
                    s['efficiency_1'] = s['speedup_1'] / float(s['workers'])
            out.append(s)

        with open(os.path.join(self.out, 'summary.csv'), 'w') as f:
            w = csv.writer(f)
            w.writerow(cols)
            for s in out:
                w.writerow([fmt(s.get(c), c) for c in cols])

    # ------------------------------------------------------------------- main
    def run(self):
        a = self.a
        sizes = [int(x.strip()) for x in a.sizes.split(',') if x.strip()]
        ks = [int(x.strip()) for x in a.workers.split(',') if x.strip()]
        self.log('=== start: sizes=%s interval=[%g, %g] runs=%d workers=%s python=%s' % (
            sizes, a.a, a.b, a.runs, ks, platform.python_version()
        ))
        self.wait_for_workers(max(ks))

        for n in sizes:
            inp = os.path.join(self.out, 'data', 'n%d.txt' % n)
            with open(inp, 'w') as f:
                f.write('%.15g %.15g %d\n' % (a.a, a.b, n))
            self.log('--- N=%d: input %s (%d bytes)' % (n, inp, os.path.getsize(inp)))

            ref_integral = None
            if not a.skip_seq:
                for run in range(1, a.runs + 1):
                    outp = os.path.join(self.out, 'outputs', 'n%d_seq_r%d.txt' % (n, run))
                    subprocess.check_call([sys.executable, BASELINE, inp, outp])
                    timing, _ = self.parse_output(outp)
                    if ref_integral is None:
                        ref_integral = timing['integral']
                    same = abs(timing['integral'] - ref_integral) <= a.tol
                    self.record(n, 'seq', run, timing, {'workers': 0, 'matches_seq': same})
                    self.log('N=%d seq run %d: total %.4fs (compute %.4fs), abs_err=%.2e, correct=%s' % (
                        n, run, timing['total'], timing['compute_max'], timing['abs_error'], timing['correct']
                    ))

            for k in ks:
                enabled = self.use_workers(k)
                self.log('N=%d: %d worker(s) enabled (%s)' % (
                    n, k, ', '.join(w['ip'] for w in enabled)
                ))
                for run in range(1, a.runs + 1):
                    name = 'int-%s-n%d-k%d-r%d' % (self.tag, n, k, run)
                    outp = os.path.join(self.out, 'outputs', 'n%d_k%d_r%d.txt' % (n, k, run))
                    job_id, wall = self.run_job(name, inp, outp)
                    timing, _ = self.parse_output(outp)
                    if ref_integral is None:
                        ref_integral = timing['integral']
                    same = abs(timing['integral'] - ref_integral) <= a.tol
                    self.record(n, 'k%d' % k, run, timing, {
                        'workers': k,
                        'job_id': job_id,
                        'job_wall': wall,
                        'matches_seq': same,
                    })
                    tr_max = max(timing.get('transfer_per_worker') or [0.0])
                    self.log(
                        'N=%d k=%d run %d: total %.4fs (compute_max %.4fs, transfer_max %.4fs, imb %.4f), '
                        'job_wall %.4fs, abs_err=%.2e, correct=%s, matches_seq=%s' % (
                            n, k, run, timing['total'], timing['compute_max'], tr_max,
                            timing.get('imbalance', 1.0), wall, timing['abs_error'],
                            timing['correct'], same
                        )
                    )
                    if not (timing['correct'] and same):
                        self.log('!!! VERIFICATION WARNING in %s' % outp)

        self.use_workers(max(ks))
        open(os.path.join(self.out, 'DONE'), 'w').close()
        self.log('=== all done. Results saved in %s' % self.out)


# -------------------------------------------------------------------- helpers
def flat(row):
    t = row['timing']
    r = dict(row)
    r['total'] = t['total']
    r['compute_max'] = t['compute_max']
    r['compute_sum'] = t['compute_sum']
    r['integral'] = t['integral']
    r['abs_error'] = t['abs_error']
    r['correct'] = t['correct']
    tr = t.get('transfer_per_worker')
    if tr:
        r['transfer_mean'] = sum(tr) / float(len(tr))
        r['transfer_max'] = max(tr)
        r['imbalance'] = t.get('imbalance')
    return r


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / float(len(xs)) if xs else None


def std(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / float(len(xs) - 1))


def fmt(v, col=''):
    if v is None:
        return ''
    if isinstance(v, float):
        if col in ('abs_error', 'abs_error_mean'):
            return '%.6e' % v
        if col == 'integral':
            return '%.15f' % v
        return '%.4f' % v
    return v


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--master', default='http://127.0.0.1:8080', help='Master Web/REST URL')
    p.add_argument('--sizes', default='10000000,25000000,50000000,100000000', help='Comma-separated N values')
    p.add_argument('--a', type=float, default=0.0, help='Lower integration bound')
    p.add_argument('--b', type=float, default=1.0, help='Upper integration bound')
    p.add_argument('--runs', type=int, default=3, help='Repetitions per (N, config)')
    p.add_argument('--workers', default='1,2,3,4', help='Comma-separated worker counts')
    p.add_argument('--out', default=os.path.join(os.path.dirname(HERE), 'benchmarks', 'results-local'),
                   help='Output directory for results')
    p.add_argument('--wait-workers', type=int, default=600, help='Max seconds to wait for workers')
    p.add_argument('--job-timeout', type=int, default=600, help='Max seconds per PARCS job')
    p.add_argument('--tol', type=float, default=1e-11, help='Tolerance for matching sequential integral')
    p.add_argument('--skip-seq', action='store_true', help='Skip sequential baseline runs')
    args = p.parse_args()

    d = Driver(args)
    try:
        d.run()
    except Exception as e:
        d.log('!!! FAILED: %s' % e)
        with open(os.path.join(args.out, 'FAILED'), 'w') as f:
            f.write(str(e) + '\n')
        raise


if __name__ == '__main__':
    main()
