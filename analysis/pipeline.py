#!/usr/bin/env python3
"""analysis.pipeline"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import math

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
    preference_profile: Dict[str, Any] = Field(default_factory=dict)
    personality_profile: Dict[str, Any] = Field(default_factory=dict)
    correlations: Dict[str, Any] = Field(default_factory=dict)


class Result(BaseModel):
    id: Optional[int]
    text: str
    features: Features
    score: Score


class MappingConfig(BaseModel):
    categories: Dict[str, Mapping[str, float]] = Field(default_factory=dict)
    crossmap: Dict[str, str] = Field(default_factory=dict)
    scenario_weights: Dict[str, float] = Field(default_factory=dict)
    msd_paths: List[str] = Field(default_factory=list)
    lut_files: List[str] = Field(default_factory=list)


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
    if "text" != text_col:
        df["text"] = df[text_col]
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
        scenario_weights = data.get("scenario_weights", {})
        msd_paths = data.get("msd_paths") or []
        lut_files = data.get("lut_files") or []
        # support single string entries
        if isinstance(msd_paths, str):
            msd_paths = [msd_paths]
        if isinstance(lut_files, str):
            lut_files = [lut_files]
        return MappingConfig(
            categories=categories,
            crossmap=crossmap,
            scenario_weights=scenario_weights,
            msd_paths=list(msd_paths),
            lut_files=list(lut_files),
        )


def _normalise_token(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def load_msd_index(paths: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Load MSD (Million Song Dataset) tag/classification information.

    The loader is intentionally flexible – it accepts the original
    ``msd_tagtraum_cd2.cls`` format (tab or whitespace separated track id and
    tag), CSV/TSV files, or JSON documents with either a mapping or list of
    entries.  The resulting structure is a dictionary keyed by a normalised
    token (track id, artist name, or song title) with metadata describing the
    tag hits and provenance path.
    """

    index: Dict[str, Dict[str, Any]] = {}

    for path in paths or []:
        if not path:
            continue
        if not os.path.exists(path):
            continue
        _, ext = os.path.splitext(path)
        ext = ext.lower()
        try:
            if ext in {".json", ".jsonl"}:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                entries: Sequence[Mapping[str, Any]]
                if isinstance(data, Mapping):
                    entries = [dict(track=k, tag=v) for k, v in data.items()]
                else:
                    entries = list(data)
                for entry in entries:
                    tokens = {
                        _normalise_token(entry.get("track")),
                        _normalise_token(entry.get("artist")),
                        _normalise_token(entry.get("title")),
                    }
                    tokens.discard("")
                    if not tokens:
                        continue
                    payload = {
                        "tag": entry.get("tag") or entry.get("genre"),
                        "weight": float(entry.get("weight", 1.0)),
                        "path": path,
                        "raw": entry,
                    }
                    for token in tokens:
                        hits = index.setdefault(token, {"matches": []})
                        hits["matches"].append(payload)
            elif ext in {".csv", ".tsv"}:
                sep = "," if ext == ".csv" else "\t"
                df = pd.read_csv(path, sep=sep)
                for _, row in df.iterrows():
                    tokens = {
                        _normalise_token(str(row.get("track", ""))),
                        _normalise_token(str(row.get("artist", ""))),
                        _normalise_token(str(row.get("title", ""))),
                    }
                    tokens.discard("")
                    if not tokens:
                        continue
                    payload = {
                        "tag": row.get("tag") or row.get("genre"),
                        "weight": float(row.get("weight", 1.0)),
                        "path": path,
                        "raw": row.to_dict(),
                    }
                    for token in tokens:
                        hits = index.setdefault(token, {"matches": []})
                        hits["matches"].append(payload)
            else:
                # fall back to .cls style: track tag ...
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = re.split(r"[\s,]+", line)
                        if len(parts) < 2:
                            continue
                        track_id, tag = parts[0], parts[1]
                        token = _normalise_token(track_id)
                        hits = index.setdefault(token, {"matches": []})
                        hits["matches"].append({
                            "tag": tag,
                            "weight": 1.0,
                            "path": path,
                            "raw": {"track": track_id, "tag": tag},
                        })
        except Exception:
            # For robustness we simply skip unreadable files, leaving a clue in
            # the index for later debugging.
            index.setdefault("__errors__", {}).setdefault(path, 0)
            index["__errors__"][path] += 1
    return index


def lookup_msd(artist: Optional[str], song: Optional[str], lyrics: Optional[str], index: Mapping[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return MSD matches for the provided artist/song/lyrics tokens."""

    tokens = {
        _normalise_token(artist),
        _normalise_token(song),
    }
    if lyrics:
        # use a handful of unique words as fallback tokens
        words = list(dict.fromkeys(WORD_RE.findall(lyrics.lower())))
        tokens.update(words[:5])
    tokens.discard("")

    matches: List[Dict[str, Any]] = []
    for token in tokens:
        info = index.get(token)
        if not info:
            continue
        for payload in info.get("matches", []):
            match = dict(payload)
            match["token"] = token
            matches.append(match)
    return matches


def build_scenario_vector(row: Mapping[str, Any], scenario_weights: Mapping[str, float]) -> Dict[str, float]:
    vector: Dict[str, float] = {}
    items: Iterable[Tuple[str, float]]
    if scenario_weights:
        items = scenario_weights.items()
    else:
        # Automatically pick up columns that look like scenario answers (e.g. Q5*)
        auto: List[Tuple[str, float]] = []
        for key in getattr(row, "index", []):
            if not isinstance(key, str):
                continue
            key_lower = key.lower()
            if key_lower.startswith("q5") or "scenario" in key_lower:
                try:
                    auto.append((key, float(row.get(key))))
                except (TypeError, ValueError):
                    continue
        items = auto
    for key, weight in items:
        value = row.get(key)
        try:
            value = float(value)
        except (TypeError, ValueError):
            # If value is missing, fall back to the configured weight which is
            # assumed to be in the 0-3 range mentioned in the user description.
            value = float(weight)
        if not math.isfinite(value):
            value = float(weight)
        vector[key] = value
    return vector


def derive_preference_profile(
    base_scores: Score,
    scenario_vector: Mapping[str, float],
    msd_matches: Sequence[Mapping[str, Any]],
    features: Features,
) -> Dict[str, Any]:
    """Combine MSD matches, scenario weights, and text features."""

    weight_sum = sum(scenario_vector.values()) or 1.0
    scenario_normalised = {
        key: value / weight_sum for key, value in scenario_vector.items()
    }

    genre_weights: Dict[str, float] = {}
    for match in msd_matches:
        tag = str(match.get("tag") or "").lower()
        if not tag:
            continue
        weight = float(match.get("weight", 1.0))
        token = match.get("token", "")
        if token in scenario_vector:
            weight *= 1.5  # emphasise direct scenario ties
        genre_weights[tag] = genre_weights.get(tag, 0.0) + weight

    # normalise genre weights
    total_genre_weight = sum(genre_weights.values()) or 1.0
    genre_distribution = {
        genre: weight / total_genre_weight for genre, weight in genre_weights.items()
    }

    # Combine with base music score as a baseline energy level
    music_energy = base_scores.music or 0.0
    if not math.isfinite(music_energy):
        music_energy = 0.0

    profile = {
        "scenario_vector": scenario_normalised,
        "genre_distribution": genre_distribution,
        "music_energy": music_energy,
        "lexical_density": (
            features.num_words / features.num_chars if features.num_chars else 0.0
        ),
        "vocabulary_size": len(set(features.words)),
        "msd_match_count": len(msd_matches),
    }

    return profile


def derive_personality_profile(
    features: Features,
    base_scores: Score,
    preference_profile: Mapping[str, Any],
) -> Dict[str, Any]:
    """Create a personality profile informed by lexical and musical cues."""

    avg_word_len = features.avg_word_len or 0.0
    vocab_size = preference_profile.get("vocabulary_size", 0)
    lexical_density = preference_profile.get("lexical_density", 0.0)
    music_energy = preference_profile.get("music_energy", 0.0)

    openness = min(1.0, (vocab_size / 200.0) + lexical_density)
    conscientiousness = min(1.0, features.num_words / 500.0)
    extraversion = min(1.0, music_energy / 10.0 + avg_word_len / 10.0)
    agreeableness = min(1.0, base_scores.psych / 10.0 + lexical_density)
    neuroticism = max(0.0, 1.0 - agreeableness)

    profile = {
        "openness": openness,
        "conscientiousness": conscientiousness,
        "extraversion": extraversion,
        "agreeableness": agreeableness,
        "neuroticism": neuroticism,
        "avg_word_len": avg_word_len,
    }

    return profile


def feedback_adjust_preference(
    preference_profile: Dict[str, Any], personality_profile: Mapping[str, Any]
) -> Dict[str, Any]:
    """Adjust the musical preference profile based on derived personality."""

    adjusted = dict(preference_profile)
    openness = personality_profile.get("openness", 0.5)
    agreeableness = personality_profile.get("agreeableness", 0.5)

    distribution = {
        genre: weight * (1.0 + openness * 0.2)
        for genre, weight in adjusted.get("genre_distribution", {}).items()
    }

    if distribution:
        total = sum(distribution.values()) or 1.0
        distribution = {k: v / total for k, v in distribution.items()}
    adjusted["genre_distribution"] = distribution

    # reweight scenario emphasis by agreeableness (softer preferences)
    scenarios = {
        key: value * (1.0 + agreeableness * 0.1)
        for key, value in adjusted.get("scenario_vector", {}).items()
    }
    if scenarios:
        total = sum(scenarios.values()) or 1.0
        scenarios = {k: v / total for k, v in scenarios.items()}
    adjusted["scenario_vector"] = scenarios

    return adjusted


def load_lut_files(paths: Sequence[str]) -> List[Any]:
    """Load lookup/register tables used for correlation building."""

    tables: List[Any] = []
    for path in paths or []:
        if not path or not os.path.exists(path):
            continue
        _, ext = os.path.splitext(path)
        ext = ext.lower()
        try:
            if ext in {".json", ".jsonl"}:
                with open(path, "r", encoding="utf-8") as fh:
                    tables.append(json.load(fh))
            elif ext in {".yml", ".yaml"}:
                with open(path, "r", encoding="utf-8") as fh:
                    tables.append(yaml.safe_load(fh))
            elif ext in {".csv", ".tsv"}:
                sep = "," if ext == ".csv" else "\t"
                tables.append(pd.read_csv(path, sep=sep))
            else:
                # For TTL/OWL or unknown formats we keep the raw text
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    tables.append(fh.read())
        except Exception:
            tables.append({"error": f"Failed to read {path}"})
    return tables


def build_correlation_matrix(
    preference_profile: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
    tables: Sequence[Any],
) -> Dict[str, Any]:
    """Synthesize correlation metrics inspired by PADPNT+ and Wundt/Berlyne."""

    scenario_vector = preference_profile.get("scenario_vector", {})
    genre_distribution = preference_profile.get("genre_distribution", {})

    periodicity = sum(
        weight * (idx + 1) for idx, weight in enumerate(genre_distribution.values())
    )
    synchronicity = sum(
        (idx + 1) * value for idx, value in enumerate(scenario_vector.values())
    )

    openness = personality_profile.get("openness", 0.0)
    agreeableness = personality_profile.get("agreeableness", 0.0)
    neuroticism = personality_profile.get("neuroticism", 0.0)

    tension = max(0.0, neuroticism - agreeableness)
    expression = openness + agreeableness

    correlations = {
        "periodicity": periodicity,
        "synchronicity": synchronicity,
        "tension": tension,
        "expression": expression,
        "tables_loaded": len(tables),
    }

    # incorporate hints from LUT/register tables by simply noting their hashes
    for idx, table in enumerate(tables):
        key = f"table_{idx}_signature"
        try:
            signature = hash(str(table))
        except Exception:
            signature = None
        correlations[key] = signature

    return correlations


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
        mean_energy = sum(
            r.score.preference_profile.get("music_energy", 0.0) for r in results
        ) / count
        mean_tension = sum(
            r.score.correlations.get("tension", 0.0) for r in results
        ) / count
        mean_expression = sum(
            r.score.correlations.get("expression", 0.0) for r in results
        ) / count
        agg = {
            "count": count,
            "mean_psych": mean_psych,
            "mean_music": mean_music,
            "mean_music_energy": mean_energy,
            "mean_tension": mean_tension,
            "mean_expression": mean_expression,
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
    <thead><tr><th>ID</th><th>Text</th><th>Num words</th><th>Psych</th><th>Music</th><th>Energy</th><th>Tension</th><th>Expression</th></tr></thead>
    <tbody>
      {% for r in results %}
      <tr>
        <td>{{ r.id }}</td>
        <td>{{ r.text|e }}</td>
        <td>{{ r.features.num_words }}</td>
        <td>{{ r.score.psych }}</td>
        <td>{{ r.score.music }}</td>
        <td>{{ r.score.preference_profile_music_energy }}</td>
        <td>{{ r.score.correlations_tension }}</td>
        <td>{{ r.score.correlations_expression }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


def render_html(results: List[Result], template: Optional[str] = None) -> str:
    tpl = Template(template or HTML_TEMPLATE)
    serialised: List[Dict[str, Any]] = []
    for r in results:
        data = r.dict()
        score = data.get("score", {})
        pref = score.get("preference_profile") or {}
        corr = score.get("correlations") or {}
        score["preference_profile"] = pref
        score["correlations"] = corr
        score["preference_profile_music_energy"] = pref.get("music_energy")
        score["correlations_tension"] = corr.get("tension")
        score["correlations_expression"] = corr.get("expression")
        serialised.append(data)
    return tpl.render(results=serialised)


class Pipeline:
    """Enhanced analysis pipeline that fuses lexical, psychological, and
    musical datasets.

    In addition to the keyword mapping scores (psych/music) the pipeline now
    performs the following steps for each row:

    * builds a scenario vector from the weighted listening contexts (e.g. Q5)
    * looks up likely genres using Million Song Dataset (MSD) tag files
    * derives a musical preference profile that feeds into a personality model
    * re-injects the personality profile back into the musical preferences to
      emulate the feedback loop described in the PADPNT+/Wundt/Berlyne notes
    * aggregates external lookup/register tables (.csv/.json/.yaml/.ttl/etc.) to
      construct correlation metrics such as periodicity, synchronicity, tension,
      and expression

    The results are stored on the :class:`Score` object and propagated to JSONL,
    aggregate JSON, and HTML report outputs.

    Intended usage: ``Pipeline().run(args)`` where ``args`` is an
    ``argparse.Namespace`` (or dict-like) with attributes ``input`` (path to
    csv), ``jsonl``/``aggregate``/``html`` (output paths or booleans), and
    ``mapping`` (YAML pipeline configuration).
    """

    def __init__(self, mapping_path: Optional[str] = None):
        self.mapping_path = mapping_path
        self.cfg = load_mapping_yaml(mapping_path) if mapping_path else MappingConfig()
        self.msd_index = load_msd_index(self.cfg.msd_paths)
        self.lut_tables = load_lut_files(self.cfg.lut_files)

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
            self.msd_index = load_msd_index(self.cfg.msd_paths)
            self.lut_tables = load_lut_files(self.cfg.lut_files)

        df = load_csv(input_path)
        results: List[Result] = []
        for idx, row in df.iterrows():
            text = str(row["text"])
            feats = extract_features(text)
            score = score_from_mapping(feats.words, self.cfg)
            scenario_vector = build_scenario_vector(row, self.cfg.scenario_weights)
            artist = row.get("artist") or row.get("respondent_artist")
            song = row.get("song") or row.get("song_name")
            lyrics = row.get("lyrics") or text
            msd_matches = lookup_msd(artist, song, lyrics, self.msd_index)
            preference_profile = derive_preference_profile(score, scenario_vector, msd_matches, feats)
            personality_profile = derive_personality_profile(feats, score, preference_profile)
            adjusted_preference = feedback_adjust_preference(preference_profile, personality_profile)
            correlations = build_correlation_matrix(adjusted_preference, personality_profile, self.lut_tables)

            score.preference_profile = adjusted_preference
            score.personality_profile = personality_profile
            score.correlations = correlations
            score.details.update({
                "scenarios": scenario_vector,
                "msd_matches": msd_matches,
            })

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
