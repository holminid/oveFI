#!/usr/bin/env python3
"""analysis.pipeline"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd
import yaml
from jinja2 import Template
from pydantic import BaseModel, Field, ValidationError

WORD_RE = re.compile(r"\w+")


class Features(BaseModel):
    num_chars: int
    num_words: int
    avg_word_len: float
    words: List[str] = Field(default_factory=list)


class Score(BaseModel):
    psych: float = 0.0
    music: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)


class Result(BaseModel):
    id: Optional[int]
    text: str
    features: Features
    score: Score


class MappingConfig(BaseModel):
    categories: Dict[str, Mapping[str, float]] = Field(default_factory=dict)
    crossmap: Dict[str, str] = Field(default_factory=dict)


def load_csv(input_path: str) -> pd.DataFrame:
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    # Let pandas infer separator/encoding; assume a single text column if present
    df = pd.read_csv(input_path)
    if df.empty:
        return df
    # Try to find a text column
    text_cols = [c for c in df.columns if c.lower() in ("text", "content", "body", "lyrics")]
    if not text_cols:
        # fallback to first column
        text_col = df.columns[0]
    else:
        text_col = text_cols[0]
    df = df[[text_col]].rename(columns={text_col: "text"})
    df = df.dropna(subset=["text"]).reset_index(drop=True)
    return df


def extract_features(text: str) -> Features:
    words = WORD_RE.findall(text)
    num_words = len(words)
    num_chars = len(text)
    avg_word_len = (sum(len(w) for w in words) / num_words) if num_words else 0.0
    return Features(num_chars=num_chars, num_words=num_words, avg_word_len=avg_word_len, words=words)


def load_mapping_yaml(path: str) -> MappingConfig:
    if not path or not os.path.exists(path):
        # return empty config
        return MappingConfig()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    # expect structure: categories: {psych: {keyword: weight, ...}, music: {...}}, crossmap: {...}
    try:
        return MappingConfig(**data)
    except ValidationError:
        # best effort: normalize
        categories = data.get("categories", {})
        crossmap = data.get("crossmap", {})
        return MappingConfig(categories=categories, crossmap=crossmap)


def score_from_mapping(words: Iterable[str], cfg: MappingConfig) -> Score:
    psych_score = 0.0
    music_score = 0.0
    details: Dict[str, Any] = {}
    word_lower = [w.lower() for w in words]
    for cat, mapping in cfg.categories.items():
        s = 0.0
        hits = {}
        for kw, weight in mapping.items():
            # count occurrences
            count = word_lower.count(kw.lower())
            if count:
                s += count * float(weight)
                hits[kw] = count
        details[cat] = {"score": s, "hits": hits}
        if cat.lower() == "psych":
            psych_score = s
        elif cat.lower() == "music":
            music_score = s
        else:
            # other categories could be crossmapped
            pass
    # apply crossmap if present
    # crossmap maps source category -> target (e.g. 'emotion' -> 'psych')
    for src, tgt in cfg.crossmap.items():
        if src in details and tgt in ("psych", "music"):
            try:
                s = float(details[src].get("score", 0.0))
            except Exception:
                s = 0.0
            if tgt == "psych":
                psych_score += s
            elif tgt == "music":
                music_score += s
    return Score(psych=psych_score, music=music_score, details=details)


def write_jsonl(path: str, results: Iterable[Result]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.dict(), ensure_ascii=False) + "\n")


def write_aggregate(path: str, results: Iterable[Result]) -> None:
    results = list(results)
    if not results:
        agg = {"count": 0}
    else:
        count = len(results)
        mean_psych = sum(r.score.psych for r in results) / count
        mean_music = sum(r.score.music for r in results) / count
        agg = {
            "count": count,
            "mean_psych": mean_psych,
            "mean_music": mean_music,
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(agg, fh, ensure_ascii=False, indent=2)


HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Analysis Report</title>
  <style>
    body { font-family: sans-serif; margin: 2rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { padding: 8px; border: 1px solid #ddd; }
  </style>
</head>
<body>
  <h1>Analysis Report</h1>
  <p>Count: {{ results|length }}</p>
  <table>
    <thead><tr><th>ID</th><th>Text</th><th>Num words</th><th>Psych</th><th>Music</th></tr></thead>
    <tbody>
      {% for r in results %}
      <tr>
        <td>{{ r.id }}</td>
        <td>{{ r.text|e }}</td>
        <td>{{ r.features.num_words }}</td>
        <td>{{ r.score.psych }}</td>
        <td>{{ r.score.music }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


def render_html(results: List[Result], template: Optional[str] = None) -> str:
    tpl = Template(template or HTML_TEMPLATE)
    return tpl.render(results=[r.dict() for r in results])


class Pipeline:
    """Simple pipeline that reads a CSV with a text column, extracts features,
    scores against mappings supplied in a YAML file, optionally crossmaps,
    and writes outputs (JSONL per-row, aggregate JSON, and an HTML report).

    Intended usage: Pipeline().run(args) where args is an argparse.Namespace
    with attributes: input (path to csv), jsonl (output path or flag),
    aggregate (output path or flag), html (output path or flag), mapping (yaml path).
    If flags are booleans, default file names are used next to the input file.
    """

    def __init__(self, mapping_path: Optional[str] = None):
        self.mapping_path = mapping_path
        self.cfg = load_mapping_yaml(mapping_path) if mapping_path else MappingConfig()

    def run(self, args: Optional[Any] = None) -> List[Result]:
        # args can be Namespace or dict; provide flexible access
        if args is None:
            raise ValueError("args is required; pass argparse.Namespace or dict-like with input/jsonl/aggregate/html")
        # support both attribute and key access
        def _get(k, default=None):
            if hasattr(args, k):
                return getattr(args, k)
            try:
                return args[k]
            except Exception:
                return default

        input_path = _get("input")
        if not input_path:
            raise ValueError("--input is required")
        mapping_path = _get("mapping") or self.mapping_path
        if mapping_path:
            self.cfg = load_mapping_yaml(mapping_path)

        df = load_csv(input_path)
        results: List[Result] = []
        for idx, row in df.iterrows():
            text = str(row["text"])
            feats = extract_features(text)
            score = score_from_mapping(feats.words, self.cfg)
            res = Result(id=int(idx), text=text, features=feats, score=score)
            results.append(res)

        # outputs
        base_dir = os.path.dirname(os.path.abspath(input_path)) or os.getcwd()
        base_name = os.path.splitext(os.path.basename(input_path))[0]

        # JSONL
        jsonl_flag = _get("jsonl")
        if isinstance(jsonl_flag, str) and jsonl_flag:
            jsonl_path = jsonl_flag
        elif jsonl_flag:
            jsonl_path = os.path.join(base_dir, base_name + ".jsonl")
        else:
            jsonl_path = None

        # aggregate
        agg_flag = _get("aggregate")
        if isinstance(agg_flag, str) and agg_flag:
            agg_path = agg_flag
        elif agg_flag:
            agg_path = os.path.join(base_dir, base_name + ".aggregate.json")
        else:
            agg_path = None

        # html
        html_flag = _get("html")
        if isinstance(html_flag, str) and html_flag:
            html_path = html_flag
        elif html_flag:
            html_path = os.path.join(base_dir, base_name + ".html")
        else:
            html_path = None

        if jsonl_path:
            write_jsonl(jsonl_path, results)
        if agg_path:
            write_aggregate(agg_path, results)
        if html_path:
            html = render_html(results)
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(html)

        return results


# allow running as a script for quick tests
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Run analysis pipeline")
    p.add_argument("--input", "-i", required=True, help="Path to input CSV")
    p.add_argument("--mapping", help="YAML mapping file for scoring")
    p.add_argument("--jsonl", action="store_true", help="Write JSONL output")
    p.add_argument("--aggregate", action="store_true", help="Write aggregate JSON")
    p.add_argument("--html", action="store_true", help="Write HTML report")
    ns = p.parse_args()
    try:
        Pipeline(mapping_path=ns.mapping).run(ns)
    except Exception:
        print("Pipeline run failed", file=sys.stderr)
        raise
