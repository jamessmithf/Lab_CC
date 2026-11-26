#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Helper script to generate input files for PARCS-Python Numerical Integration.
"""

from __future__ import print_function
import argparse
import sys


def generate_input_file(output_path, a=0.0, b=1.0, n=10000000):
    with open(output_path, 'w') as f:
        f.write("{:.15g} {:.15g} {:d}\n".format(a, b, n))
    print("Generated input file: {} (Interval=[{:.15g}, {:.15g}], N={:,})".format(output_path, a, b, n))


def main():
    parser = argparse.ArgumentParser(description="Generate input.txt for PARCS-Python Numerical Integration")
    parser.add_argument("-a", type=float, default=0.0, help="Lower bound (default: 0.0)")
    parser.add_argument("-b", type=float, default=1.0, help="Upper bound (default: 1.0)")
    parser.add_argument("-n", type=int, default=10000000, help="Total integration steps (default: 10,000,000)")
    parser.add_argument("-o", "--output", type=str, default="input.txt", help="Output file path (default: input.txt)")
    parser.add_argument("--all-presets", action="store_true", help="Generate all standard benchmark presets (1M, 10M, 50M, 100M)")

    args = parser.parse_args()

    if args.all_presets:
        presets = [
            ("input_1m.txt", 1000000),
            ("input_5m.txt", 5000000),
            ("input_10m.txt", 10000000),
            ("input_50m.txt", 50000000),
            ("input_100m.txt", 100000000),
        ]
        for filename, n_val in presets:
            generate_input_file(filename, args.a, args.b, n_val)
        # Also create default input.txt pointing to 10M
        generate_input_file("input.txt", args.a, args.b, 10000000)
    else:
        generate_input_file(args.output, args.a, args.b, args.n)


if __name__ == "__main__":
    main()
