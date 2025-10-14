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
    prompts: List[str] = Field(default_factory=list)
    musical_forms: Dict[str, Any] = Field(default_factory=dict)
    instrumentation_profile: Dict[str, Any] = Field(default_factory=dict)


class Result(BaseModel):
    id: Optional[int]
    text: str
    features: Features
    score: Score
    matrix_row: Dict[str, Any] = Field(default_factory=dict)


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


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _normalise_energy(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    # assume the incoming music score is roughly in a 0-10 range
    return _clamp(value / 10.0)


def _normalise_expression(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    # expression comes from the sum of two 0-1 traits
    return _clamp(value / 2.0)


def _normalise_tension(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return _clamp(value)


def _top_label(weights: Mapping[str, float], default: str = "multi-genre") -> str:
    if not weights:
        return default
    try:
        return max(weights.items(), key=lambda item: item[1])[0]
    except Exception:
        return default


def infer_mirex_cluster(
    preference_profile: Mapping[str, Any], correlations: Mapping[str, Any]
) -> str:
    energy = _normalise_energy(preference_profile.get("music_energy", 0.0))
    expression = _normalise_expression(correlations.get("expression", 0.0))
    tension = _normalise_tension(correlations.get("tension", 0.0))

    if energy >= 0.7 and tension >= 0.5:
        return "Cluster 5 – Fiery / Tense"
    if energy >= 0.6 and expression >= 0.6:
        return "Cluster 2 – Joyful / Uplifting"
    if energy <= 0.3 and tension <= 0.3:
        return "Cluster 3 – Calm / Reflective"
    if expression >= 0.5 and tension <= 0.4:
        return "Cluster 1 – Passionate / Warm"
    return "Cluster 4 – Sophisticated / Complex"


def derive_gems_profile(
    preference_profile: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
    correlations: Mapping[str, Any],
) -> List[str]:
    energy = _normalise_energy(preference_profile.get("music_energy", 0.0))
    openness = _clamp(float(personality_profile.get("openness", 0.0)))
    tension = _normalise_tension(correlations.get("tension", 0.0))
    agreeableness = _clamp(float(personality_profile.get("agreeableness", 0.0)))

    gems: List[str] = []
    if energy >= 0.6:
        gems.append("Joyful Activation")
    if tension >= 0.5:
        gems.append("Tension")
    if agreeableness >= 0.5 and tension <= 0.4:
        gems.append("Tenderness")
    if openness >= 0.6:
        gems.append("Transcendence")
    if not gems:
        gems.append("Peacefulness")
    return gems


def derive_poms2_states(
    personality_profile: Mapping[str, Any], correlations: Mapping[str, Any]
) -> List[str]:
    tension = _normalise_tension(correlations.get("tension", 0.0))
    expression = _normalise_expression(correlations.get("expression", 0.0))
    extraversion = _clamp(float(personality_profile.get("extraversion", 0.0)))
    neuroticism = _clamp(float(personality_profile.get("neuroticism", 0.0)))

    states: List[str] = []
    if tension >= 0.5 or neuroticism >= 0.5:
        states.append("Tension-Anxiety")
    if expression >= 0.6 and extraversion >= 0.5:
        states.append("Vigor-Activity")
    if neuroticism <= 0.4 and tension <= 0.3:
        states.append("Calmness")
    if expression <= 0.4:
        states.append("Fatigue-Inertia")
    if not states:
        states.append("Neutral")
    return states


def build_padpndt_axes(
    preference_profile: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
    correlations: Mapping[str, Any],
) -> Dict[str, float]:
    energy = _normalise_energy(preference_profile.get("music_energy", 0.0))
    openness = _clamp(float(personality_profile.get("openness", 0.0)))
    agreeableness = _clamp(float(personality_profile.get("agreeableness", 0.0)))
    neuroticism = _clamp(float(personality_profile.get("neuroticism", 0.0)))
    tension = _normalise_tension(correlations.get("tension", 0.0))

    padpndt = {
        "pleasure": _clamp((agreeableness + (1.0 - neuroticism)) / 2.0),
        "arousal": energy,
        "dominance": _clamp((openness + agreeableness) / 2.0),
        "polarity": _clamp(1.0 - tension),
        "novelty": openness,
        "temporal": _clamp(0.5 + (energy - tension) / 2.0),
    }

    # Extend to 8th/9th optional axes by blending lexical richness if present
    vocab_size = float(preference_profile.get("vocabulary_size", 0.0))
    lexical_density = float(preference_profile.get("lexical_density", 0.0))
    padpndt["complexity"] = _clamp(vocab_size / 400.0)
    padpndt["stability"] = _clamp(1.0 - tension)
    padpndt["flow"] = _clamp((lexical_density + energy) / 2.0)
    return padpndt


CONTEXTUAL_FIELDS = {
    "age",
    "gender",
    "location",
    "country",
    "city",
    "occupation",
    "locale",
    "device",
    "time_of_day",
    "environment",
}


def infer_musical_forms(
    preference_profile: Mapping[str, Any],
    correlations: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
) -> Dict[str, Any]:
    """Infer musical forms/functions from the derived preference state."""

    energy = _normalise_energy(preference_profile.get("music_energy", 0.0))
    tension = _normalise_tension(correlations.get("tension", 0.0))
    expression = _normalise_expression(correlations.get("expression", 0.0))
    openness = _clamp(float(personality_profile.get("openness", 0.0)))
    scenario = _top_label(preference_profile.get("scenario_vector", {}), default="listening" )

    if energy >= 0.7 and tension <= 0.4:
        primary_form = "kinetic suite"
        function_focus = "momentum building"
    elif tension >= 0.6:
        primary_form = "dramatic arc"
        function_focus = "cathartic release"
    elif expression >= 0.6:
        primary_form = "narrative tableau"
        function_focus = "expressive storytelling"
    else:
        primary_form = "ambient flow"
        function_focus = "immersive continuity"

    if openness >= 0.6:
        secondary_form = "modular variations"
    elif energy <= 0.4:
        secondary_form = "drone-based meditation"
    else:
        secondary_form = "binary contrast"

    expression_modes: List[str] = []
    if expression >= 0.6:
        expression_modes.append("expansive phrasing")
    if tension >= 0.5:
        expression_modes.append("dynamic surges")
    if energy <= 0.3:
        expression_modes.append("sustained atmospherics")
    if not expression_modes:
        expression_modes.append("balanced motifs")

    return {
        "primary_form": primary_form,
        "secondary_form": secondary_form,
        "functional_focus": function_focus,
        "expression_modes": expression_modes,
        "scenario_anchor": scenario,
        "energy_level": energy,
        "tension_level": tension,
        "expression_level": expression,
    }


def collect_contextual_descriptors(row: Mapping[str, Any]) -> List[str]:
    descriptors: List[str] = []
    for key in CONTEXTUAL_FIELDS:
        try:
            value = row.get(key)
        except AttributeError:
            value = None
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        value_str = str(value).strip()
        if not value_str:
            continue
        descriptors.append(f"{key}: {value_str}")
    return descriptors


TONAL_CENTRES = [
    "C",
    "G",
    "D",
    "A",
    "E",
    "B",
    "F#",
    "C#",
    "F",
    "Bb",
    "Eb",
    "Ab",
]


CHARPENTIER_DEGREE_SEQUENCE = [
    ("I", 1.0),
    ("V", 0.85),
    ("II", 0.65),
    ("III", 0.55),
    ("VI", 0.5),
    ("IV", 0.45),
    ("VII", 0.35),
]


def extract_instrumentation_entries(tables: Sequence[Any]) -> List[Dict[str, Any]]:
    """Harvest instrumentation hints from arbitrary LUT/register payloads."""

    entries: List[Dict[str, Any]] = []
    for table in tables or []:
        if isinstance(table, pd.DataFrame):
            lowered = {col.lower(): col for col in table.columns}
            if "instrument" in lowered:
                instrument_col = lowered["instrument"]
                form_col = lowered.get("form") or lowered.get("musical_form")
                role_col = lowered.get("role")
                mood_col = lowered.get("mood") or lowered.get("affect")
                for _, row in table.iterrows():
                    instrument = str(row.get(instrument_col, "")).strip()
                    if not instrument:
                        continue
                    entry = {
                        "instrument": instrument,
                        "form": str(row.get(form_col, "")).strip() if form_col else "",
                        "role": str(row.get(role_col, "")).strip() if role_col else "",
                        "mood": str(row.get(mood_col, "")).strip() if mood_col else "",
                    }
                    entries.append(entry)
            continue

        if isinstance(table, Mapping):
            if "instrumentation" in table:
                payload = table["instrumentation"]
                if isinstance(payload, Mapping):
                    for key, value in payload.items():
                        if isinstance(value, Mapping):
                            entries.append({
                                "instrument": str(key),
                                "form": str(value.get("form", "")),
                                "role": str(value.get("role", "")),
                                "mood": str(value.get("mood", "")),
                            })
                elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
                    for item in payload:
                        if isinstance(item, Mapping):
                            entries.append({
                                "instrument": str(item.get("instrument", "")),
                                "form": str(item.get("form", "")),
                                "role": str(item.get("role", "")),
                                "mood": str(item.get("mood", "")),
                            })
            elif "instruments" in table and isinstance(table["instruments"], Sequence) and not isinstance(table["instruments"], (str, bytes)):
                for item in table["instruments"]:
                    if isinstance(item, Mapping):
                        entries.append({
                            "instrument": str(item.get("name", "")),
                            "form": str(item.get("form", "")),
                            "role": str(item.get("role", "")),
                            "mood": str(item.get("mood", "")),
                        })
            continue

        if isinstance(table, Sequence) and not isinstance(table, (str, bytes)):
            for item in table:
                if isinstance(item, Mapping) and "instrument" in item:
                    entries.append({
                        "instrument": str(item.get("instrument", "")),
                        "form": str(item.get("form", "")),
                        "role": str(item.get("role", "")),
                        "mood": str(item.get("mood", "")),
                    })

    return [entry for entry in entries if entry.get("instrument")]


def infer_tonality_profile(
    padpndt_axes: Mapping[str, float],
    preference_profile: Mapping[str, Any],
    correlations: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
) -> Dict[str, Any]:
    """Estimate tonal centres using a Charpentier-style weighting approach."""

    pleasure = float(padpndt_axes.get("pleasure", 0.5)) if padpndt_axes else 0.5
    novelty = float(padpndt_axes.get("novelty", 0.5)) if padpndt_axes else 0.5
    dominance = float(padpndt_axes.get("dominance", 0.5)) if padpndt_axes else 0.5
    temporal = float(padpndt_axes.get("temporal", 0.5)) if padpndt_axes else 0.5
    depth = float(padpndt_axes.get("stability", 0.5)) if padpndt_axes else 0.5

    energy = _normalise_energy(preference_profile.get("music_energy", 0.0))
    tension = _normalise_tension(correlations.get("tension", 0.0))
    expression = _normalise_expression(correlations.get("expression", 0.0))
    openness = _clamp(float(personality_profile.get("openness", 0.0)))

    brightness = _clamp((pleasure * 0.6) + (energy * 0.3) - (tension * 0.2) + (openness * 0.1))
    key_index = int(round(brightness * (len(TONAL_CENTRES) - 1)))
    key_center = TONAL_CENTRES[key_index]

    if novelty >= 0.75 and dominance <= 0.45:
        mode = "synthetic"
    elif expression >= tension + 0.1:
        mode = "major"
    elif tension >= 0.55:
        mode = "minor"
    else:
        mode = "modal"

    charpentier_weights: List[Dict[str, Any]] = []
    stress_modifier = _clamp(tension + (1.0 - depth) / 2.0)
    for degree, base_weight in CHARPENTIER_DEGREE_SEQUENCE:
        weight = base_weight + (expression * 0.1) - (stress_modifier * 0.05)
        if degree in {"II", "VII"} and novelty >= 0.65:
            weight += 0.1
        charpentier_weights.append({
            "degree": degree,
            "weight": round(_clamp(weight, 0.1, 1.2), 3),
        })

    modulation_bias = []
    if novelty >= 0.6:
        modulation_bias.append("mediant excursions")
    if temporal >= 0.6:
        modulation_bias.append("dominant pivots")
    if not modulation_bias:
        modulation_bias.append("tonic centric")

    return {
        "key_center": key_center,
        "mode": mode,
        "charpentier_weights": charpentier_weights,
        "tonal_ambiguity": round(1.0 - depth + novelty * 0.2, 3),
        "modulation_bias": modulation_bias,
    }


def derive_instrumentation_palette(
    musical_forms: Mapping[str, Any],
    tonality_profile: Mapping[str, Any],
    padpndt_axes: Mapping[str, float],
    preference_profile: Mapping[str, Any],
    correlations: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
    lut_tables: Sequence[Any],
    msd_matches: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Generate ensemble, instrument, and role guidance for stem prompts."""

    energy = _normalise_energy(preference_profile.get("music_energy", 0.0))
    tension = _normalise_tension(correlations.get("tension", 0.0))
    expression = _normalise_expression(correlations.get("expression", 0.0))
    novelty = float(padpndt_axes.get("novelty", 0.5)) if padpndt_axes else 0.5
    potency = float(padpndt_axes.get("dominance", 0.5)) if padpndt_axes else 0.5
    depth = float(padpndt_axes.get("stability", 0.5)) if padpndt_axes else 0.5

    primary_form = str(musical_forms.get("primary_form", "modular form"))
    secondary_form = str(musical_forms.get("secondary_form", "contrast section"))
    expression_modes = list(musical_forms.get("expression_modes", []))
    scenario = str(musical_forms.get("scenario_anchor", "listening"))

    if energy >= 0.75 or potency >= 0.65:
        ensemble_size = "large ensemble"
        primary_instruments = ["drum kit", "electric bass", "synth brass"]
        supporting_instruments = ["strings (violins)", "hybrid pads", "auxiliary percussion"]
    elif tension >= 0.6:
        ensemble_size = "cinematic chamber"
        primary_instruments = ["string quartet", "low brass", "granular percussion"]
        supporting_instruments = ["piano", "analog synth drones", "bass clarinet"]
    elif energy <= 0.35 and depth >= 0.55:
        ensemble_size = "intimate ensemble"
        primary_instruments = ["felt piano", "cello", "soft electronics"]
        supporting_instruments = ["alto flute", "bowed vibraphone", "subtle pulses"]
    else:
        ensemble_size = "chamber hybrid"
        primary_instruments = ["piano", "synth arpeggiator", "live drums"]
        supporting_instruments = ["guitar textures", "strings (violas)", "modular bass"]

    if "dynamic surges" in expression_modes and "granular percussion" not in supporting_instruments:
        supporting_instruments.append("granular percussion")
    if "expansive phrasing" in expression_modes and "french horn" not in supporting_instruments:
        supporting_instruments.append("french horn")
    if "sustained atmospherics" in expression_modes and "long-tail pads" not in supporting_instruments:
        supporting_instruments.append("long-tail pads")

    tempo = int(round(70 + energy * 80 - tension * 25 + novelty * 10))
    tempo = max(48, min(168, tempo))

    if novelty >= 0.7 and energy >= 0.5:
        time_signature = "7/8"
    elif expression >= 0.6 and tension <= 0.4:
        time_signature = "12/8"
    elif energy <= 0.4:
        time_signature = "3/4"
    else:
        time_signature = "4/4"

    if tension >= 0.65:
        dynamic_profile = "terraced swells with accent thrusts"
    elif expression >= 0.6:
        dynamic_profile = "arching crescendi and decrescendi"
    else:
        dynamic_profile = "gentle undulation with restrained peaks"

    texture = "layered counterpoint" if expression >= 0.6 else "sparse harmonic beds"
    if ensemble_size == "large ensemble":
        texture = "stratified grooves with melodic overlays"

    timbre_focus = "warm acoustic and hybrid tones"
    if novelty >= 0.65:
        timbre_focus = "processed acoustic timbres with spectral splashes"
    elif tension >= 0.6:
        timbre_focus = "granular strings and low brass resonance"

    role_assignments: Dict[str, str] = {}
    for idx, instrument in enumerate(primary_instruments):
        if idx == 0:
            role_assignments[instrument] = f"lead motifs shaped by {primary_form}"
        elif idx == 1:
            role_assignments[instrument] = "rhythmic foundation with adaptive syncopation"
        else:
            role_assignments[instrument] = "harmonic glue bridging sections"
    for instrument in supporting_instruments:
        if instrument not in role_assignments:
            role_assignments[instrument] = f"textural support reinforcing {secondary_form}"

    lut_entries = extract_instrumentation_entries(lut_tables)
    form_tokens = {primary_form.lower(), secondary_form.lower(), scenario.lower()}
    lut_matches: List[Dict[str, Any]] = []
    for entry in lut_entries:
        entry_form = str(entry.get("form", "")).lower()
        entry_mood = str(entry.get("mood", "")).lower()
        if entry_form and any(token in entry_form for token in form_tokens if token):
            lut_matches.append(entry)
        elif entry_mood and any(token in entry_mood for token in form_tokens if token):
            lut_matches.append(entry)
        if len(lut_matches) >= 6:
            break

    playing_styles: List[str] = []
    if expression_modes:
        playing_styles.extend(expression_modes)
    if novelty >= 0.7:
        playing_styles.append("extended techniques and spectral modulations")
    if tension >= 0.6:
        playing_styles.append("accented bowing and bowed cymbals")
    if energy >= 0.7:
        playing_styles.append("driving syncopated grooves")
    if not playing_styles:
        playing_styles.append("balanced articulation")

    key_center = tonality_profile.get("key_center", "C")
    mode = tonality_profile.get("mode", "modal")
    tonality_desc = f"{key_center} {mode}".strip()

    stem_prompts: List[str] = []
    expression_phrase = ", ".join(expression_modes) if expression_modes else "balanced motifs"
    for instrument in primary_instruments + supporting_instruments:
        role = role_assignments.get(instrument, "textural support")
        stem_prompts.append(
            (
                f"Create a dedicated stem for {instrument} performing {role} in {tonality_desc} at ~{tempo} BPM "
                f"within a {time_signature} pulse, honouring {expression_phrase}."
            )
        )

    genre_tags = []
    for match in msd_matches or []:
        tag = match.get("tag")
        if not tag:
            continue
        if tag not in genre_tags:
            genre_tags.append(tag)
        if len(genre_tags) >= 5:
            break

    return {
        "ensemble_size": ensemble_size,
        "primary_instruments": primary_instruments,
        "supporting_instruments": supporting_instruments,
        "tempo_bpm": tempo,
        "time_signature": time_signature,
        "dynamic_profile": dynamic_profile,
        "playing_styles": playing_styles,
        "texture": texture,
        "timbre_focus": timbre_focus,
        "role_assignments": role_assignments,
        "tonality": dict(tonality_profile),
        "stem_prompts": stem_prompts,
        "lut_matches": lut_matches,
        "genre_tags": genre_tags,
        "scenario": scenario,
        "forms": {
            "primary": primary_form,
            "secondary": secondary_form,
        },
    }


def _safe_identifier(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def generate_prompts(
    respondent_id: Optional[Any],
    preference_profile: Mapping[str, Any],
    personality_profile: Mapping[str, Any],
    correlations: Mapping[str, Any],
    row: Mapping[str, Any],
    musical_forms: Mapping[str, Any],
    instrumentation: Optional[Mapping[str, Any]] = None,
    padpndt_axes: Optional[Mapping[str, float]] = None,
    tonality_profile: Optional[Mapping[str, Any]] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    instrumentation = instrumentation or {}
    padpndt_axes = padpndt_axes or build_padpndt_axes(preference_profile, personality_profile, correlations)
    tonality_profile = tonality_profile or instrumentation.get("tonality") or {}

    mirex_cluster = infer_mirex_cluster(preference_profile, correlations)
    gems_profile = derive_gems_profile(preference_profile, personality_profile, correlations)
    poms2_states = derive_poms2_states(personality_profile, correlations)

    genre = _top_label(preference_profile.get("genre_distribution", {}))
    scenario = _top_label(preference_profile.get("scenario_vector", {}), default="daily listening")
    identifier = _safe_identifier(respondent_id, row.get("respondent_id"), row.get("id"))
    contextual = collect_contextual_descriptors(row)
    context_phrase = ", ".join(contextual) if contextual else "no specific contextual metadata"

    padpndt_desc = ", ".join(
        f"{axis}: {value:.2f}" for axis, value in padpndt_axes.items()
    )
    gems_phrase = ", ".join(gems_profile)
    poms_phrase = ", ".join(poms2_states)

    header = identifier or "the respondent"
    primary_form = musical_forms.get("primary_form", "adaptive piece")
    secondary_form = musical_forms.get("secondary_form", "contrast section")
    function_focus = musical_forms.get("functional_focus", "responsive narrative")
    expression_modes = ", ".join(musical_forms.get("expression_modes", []))

    ensemble = instrumentation.get("ensemble_size", "flexible ensemble")
    primary_instruments = ", ".join(instrumentation.get("primary_instruments", [])) or "modular instrumentation"
    supporting_instruments = ", ".join(instrumentation.get("supporting_instruments", [])) or "adaptive layers"
    tempo_bpm = instrumentation.get("tempo_bpm")
    time_signature = instrumentation.get("time_signature", "4/4")
    playing_styles = ", ".join(instrumentation.get("playing_styles", [])) or "balanced articulation"
    tonality_desc = "{} {}".format(
        tonality_profile.get("key_center", "C"),
        tonality_profile.get("mode", "modal"),
    ).strip()

    tempo_phrase = (
        f"tempo ≈ {tempo_bpm} BPM" if tempo_bpm is not None else "tempo following adaptive BPM"
    )
    instrumentation_summary = (
        f"{ensemble} built around {primary_instruments} with support from {supporting_instruments}, "
        f"{tempo_phrase} in {time_signature}, tonality {tonality_desc}, styles {playing_styles}"
    ).strip()

    prompts = [
        (
            f"For {header}, craft a {genre} composition for {scenario} that aligns with the "
            f"{mirex_cluster} mood cluster, emphasising GEMS-45 qualities of {gems_phrase} "
            f"and balancing POMS2 states of {poms_phrase}. Shape it as a {primary_form} "
            f"focused on {function_focus}."
        ),
        (
            f"Using PADPNDT+ axes ({padpndt_desc}), generate a multi-section work that adapts to "
            f"the listener's profile, weaving transitions that respond to {context_phrase}. "
            f"Employ {secondary_form} gestures with expression modes of {expression_modes}."
        ),
        (
            f"Design an adaptive prompt set where section one mirrors {gems_phrase}, section two "
            f"eases any {poms_phrase} states, and the finale resolves toward the {mirex_cluster} signature mood, "
            f"delivered through {primary_form} leading into {secondary_form}."
        ),
        (
            f"Arrange instrumentation as {instrumentation_summary}. Layer stems so each part can react to the PADPNDT+ "
            f"contours while maintaining the {tonality_desc} centre."
        ),
    ]

    metadata = {
        "mirex_cluster": mirex_cluster,
        "gems_profile": gems_profile,
        "poms2_states": poms2_states,
        "padpndt_axes": dict(padpndt_axes),
        "primary_genre": genre,
        "primary_scenario": scenario,
        "contextual_descriptors": contextual,
        "respondent_id": identifier,
        "musical_forms": dict(musical_forms),
        "instrumentation": dict(instrumentation),
        "instrumentation_summary": instrumentation_summary,
        "stem_prompts": list(instrumentation.get("stem_prompts", [])),
        "tonality_profile": dict(tonality_profile),
    }

    return prompts, metadata


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


def _sorted_items(mapping: Mapping[str, float]) -> List[Tuple[str, float]]:
    return sorted(mapping.items(), key=lambda item: (-item[1], item[0]))


def flatten_result(result: Result) -> Dict[str, Any]:
    """Create a flattened, columnar view of the respondent analysis."""

    row: Dict[str, Any] = {
        "respondent_id": result.score.details.get("prompts_metadata", {}).get("respondent_id")
        or result.score.details.get("respondent_id")
        or result.id,
        "source_index": result.id,
        "text": result.text,
        "num_words": result.features.num_words,
        "num_chars": result.features.num_chars,
        "avg_word_len": result.features.avg_word_len,
        "psych_score": result.score.psych,
        "music_score": result.score.music,
        "msd_match_count": result.score.preference_profile.get("msd_match_count", 0),
    }

    preference = result.score.preference_profile
    personality = result.score.personality_profile
    correlations = result.score.correlations
    prompt_meta = result.score.details.get("prompts_metadata", {})
    forms = result.score.musical_forms or prompt_meta.get("musical_forms", {})

    for trait, value in personality.items():
        row[f"personality_{trait}"] = value

    for name, value in correlations.items():
        row[f"correlation_{name}"] = value

    for axis, value in prompt_meta.get("padpndt_axes", {}).items():
        row[f"padpndt_{axis}"] = value

    row["mirex_cluster"] = prompt_meta.get("mirex_cluster")
    for idx, facet in enumerate(prompt_meta.get("gems_profile", []), start=1):
        row[f"gems_{idx}"] = facet
    for idx, state in enumerate(prompt_meta.get("poms2_states", []), start=1):
        row[f"poms2_{idx}"] = state

    scenarios = preference.get("scenario_vector", {})
    for idx, (name, value) in enumerate(_sorted_items(scenarios), start=1):
        row[f"scenario_{idx}_name"] = name
        row[f"scenario_{idx}_weight"] = value

    genres = preference.get("genre_distribution", {})
    for idx, (name, value) in enumerate(_sorted_items(genres), start=1):
        row[f"genre_{idx}_name"] = name
        row[f"genre_{idx}_weight"] = value

    row["lexical_density"] = preference.get("lexical_density")
    row["vocabulary_size"] = preference.get("vocabulary_size")
    row["music_energy"] = preference.get("music_energy")

    row["prompt_primary"] = (result.score.prompts or [None])[0]
    for idx, prompt in enumerate(result.score.prompts, start=1):
        row[f"prompt_{idx}"] = prompt

    if forms:
        row["form_primary"] = forms.get("primary_form")
        row["form_secondary"] = forms.get("secondary_form")
        row["form_function"] = forms.get("functional_focus")
        row["form_scenario_anchor"] = forms.get("scenario_anchor")
        row["form_energy_level"] = forms.get("energy_level")
        row["form_tension_level"] = forms.get("tension_level")
        row["form_expression_level"] = forms.get("expression_level")
        for idx, mode in enumerate(forms.get("expression_modes", []), start=1):
            row[f"form_expression_mode_{idx}"] = mode

    instrumentation = result.score.instrumentation_profile or prompt_meta.get("instrumentation", {})
    if instrumentation:
        row["instrumentation_ensemble_size"] = instrumentation.get("ensemble_size")
        row["instrumentation_tempo_bpm"] = instrumentation.get("tempo_bpm")
        row["instrumentation_time_signature"] = instrumentation.get("time_signature")
        row["instrumentation_dynamic_profile"] = instrumentation.get("dynamic_profile")
        row["instrumentation_texture"] = instrumentation.get("texture")
        row["instrumentation_timbre_focus"] = instrumentation.get("timbre_focus")
        row["instrumentation_summary"] = prompt_meta.get("instrumentation_summary")
        for idx, instrument in enumerate(instrumentation.get("primary_instruments", []), start=1):
            row[f"instrument_primary_{idx}"] = instrument
        for idx, instrument in enumerate(instrumentation.get("supporting_instruments", []), start=1):
            row[f"instrument_support_{idx}"] = instrument
        for idx, style in enumerate(instrumentation.get("playing_styles", []), start=1):
            row[f"playing_style_{idx}"] = style
        for idx, (inst, role) in enumerate(instrumentation.get("role_assignments", {}).items(), start=1):
            row[f"instrument_role_{idx}_instrument"] = inst
            row[f"instrument_role_{idx}_role"] = role
        tonality = instrumentation.get("tonality") or prompt_meta.get("tonality_profile", {})
        if tonality:
            row["tonality_key_center"] = tonality.get("key_center")
            row["tonality_mode"] = tonality.get("mode")
            row["tonality_ambiguity"] = tonality.get("tonal_ambiguity")
            for idx, degree in enumerate(tonality.get("charpentier_weights", []), start=1):
                row[f"tonality_degree_{idx}"] = degree.get("degree")
                row[f"tonality_degree_{idx}_weight"] = degree.get("weight")
            row["tonality_modulations"] = ", ".join(tonality.get("modulation_bias", []))
        for idx, match in enumerate(instrumentation.get("lut_matches", []), start=1):
            row[f"instrument_lut_{idx}_instrument"] = match.get("instrument")
            row[f"instrument_lut_{idx}_role"] = match.get("role")
            row[f"instrument_lut_{idx}_form"] = match.get("form")
        for idx, tag in enumerate(instrumentation.get("genre_tags", []), start=1):
            row[f"instrument_genre_tag_{idx}"] = tag

    contextual = prompt_meta.get("contextual_descriptors", [])
    for idx, descriptor in enumerate(contextual, start=1):
        row[f"context_descriptor_{idx}"] = descriptor

    msd_matches = result.score.details.get("msd_matches", [])
    for idx, match in enumerate(msd_matches[:5], start=1):
        row[f"msd_{idx}_tag"] = match.get("tag")
        row[f"msd_{idx}_weight"] = match.get("weight")
        row[f"msd_{idx}_token"] = match.get("token")

    stem_prompts = prompt_meta.get("stem_prompts")
    if stem_prompts is None:
        stem_prompts = instrumentation.get("stem_prompts", []) if instrumentation else []
    for idx, stem in enumerate(stem_prompts, start=1):
        row[f"stem_prompt_{idx}"] = stem

    row["lut_table_count"] = result.score.correlations.get("tables_loaded", 0)

    # Ensure column count surpasses 44 by appending summary hints
    row["summary_profile"] = ", ".join(filter(None, [
        row.get("mirex_cluster"),
        row.get("form_primary"),
        row.get("form_function"),
    ]))

    return row


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
        mean_prompt_count = sum(len(r.score.prompts or []) for r in results) / count
        agg = {
            "count": count,
            "mean_psych": mean_psych,
            "mean_music": mean_music,
            "mean_music_energy": mean_energy,
            "mean_tension": mean_tension,
            "mean_expression": mean_expression,
            "mean_prompt_count": mean_prompt_count,
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
    <thead><tr><th>ID</th><th>Text</th><th>Num words</th><th>Psych</th><th>Music</th><th>Energy</th><th>Tension</th><th>Expression</th><th>Primary Prompt</th></tr></thead>
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
        <td>{{ r.score.primary_prompt }}</td>
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
        prompts_list = score.get("prompts") or []
        score["primary_prompt"] = prompts_list[0] if prompts_list else ""
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
    * generates respondent-level prompt sets that summarise the mood clusters
      (MIREX), emotional facets (GEMS-45, POMS2), and PADPNDT+ axes for musical
      composition systems
    * infers tonal centres and instrumentation palettes that map forms to
      ensembles, timbres, and stem-level prompts using LUT/register guidance
    * flattens every respondent into a 44+ column matrix row aligning scenarios,
      MSD-derived genres, musical forms, and contextual descriptors for
      downstream LUT/register matching

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
        self.result_matrix = pd.DataFrame()

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
            padpndt_axes = build_padpndt_axes(adjusted_preference, personality_profile, correlations)
            musical_forms = infer_musical_forms(adjusted_preference, correlations, personality_profile)
            tonality_profile = infer_tonality_profile(
                padpndt_axes,
                adjusted_preference,
                correlations,
                personality_profile,
            )
            instrumentation_palette = derive_instrumentation_palette(
                musical_forms,
                tonality_profile,
                padpndt_axes,
                adjusted_preference,
                correlations,
                personality_profile,
                self.lut_tables,
                msd_matches,
            )
            prompts, prompt_metadata = generate_prompts(
                row.get("respondent_id"),
                adjusted_preference,
                personality_profile,
                correlations,
                row,
                musical_forms,
                instrumentation_palette,
                padpndt_axes,
                tonality_profile,
            )

            score.preference_profile = adjusted_preference
            score.personality_profile = personality_profile
            score.correlations = correlations
            score.prompts = prompts
            score.musical_forms = musical_forms
            score.instrumentation_profile = instrumentation_palette
            score.details.update({
                "scenarios": scenario_vector,
                "msd_matches": msd_matches,
                "prompts_metadata": prompt_metadata,
                "musical_forms": musical_forms,
                "instrumentation_profile": instrumentation_palette,
                "tonality_profile": tonality_profile,
                "padpndt_axes": padpndt_axes,
                "stem_prompts": instrumentation_palette.get("stem_prompts", []),
            })
            res = Result(id=int(idx), text=text, features=feats, score=score)
            res.matrix_row = flatten_result(res)
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

        # Maintain an in-memory dataframe-style matrix for downstream use
        self.result_matrix = pd.DataFrame([r.matrix_row for r in results]) if results else pd.DataFrame()

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
