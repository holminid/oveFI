#!/usr/bin/env python3
import argparse
import sys
import traceback

def parse_args():
    p = argparse.ArgumentParser(description="Analysis CLI")
    p.add_argument("--input", "-i", type=str, help="Input file or directory", required=False)
    p.add_argument("--jsonl", action="store_true", help="Output JSONL")
    p.add_argument("--aggregate", action="store_true", help="Aggregate results")
    p.add_argument("--html", action="store_true", help="Generate HTML output")
    return p.parse_args()

def main():
    args = parse_args()
    try:
        from analysis.pipeline import Pipeline
    except Exception:
        try:
            from .pipeline import Pipeline
        except Exception as exc:
            print("Failed to import Pipeline from analysis.pipeline:", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
    try:
        pipeline = Pipeline()
        try:
            pipeline.run(args)
        except TypeError:
            pipeline.run()
    except Exception:
        print("Pipeline failed:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()