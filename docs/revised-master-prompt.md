REVISED MASTER PROMPT (copy-paste to your code-generation model)

System Intent
Build a browser-based WAV tagging application for Holon/Holonist x Voxglitch (miRack). Version V1 must ship without network/OSC features and deliver precise viewing, playback, tagging, and saving. Version V2 adds a secure, bidirectional OSC integration via a local WebSocket bridge that translates JSON messages to/from UDP OSC for miRack/Voxglitch. Maintain strict RIFF integrity and future extensibility for perceptual/affective metadata.

V1 Functional Requirements (no OSC)
1.File handling and RIFF integrity

•Read local .wav via drag/drop or file picker. Supported at MVP: PCM_16/24/32 and IEEE float32; mono/stereo; 22.05–192 kHz.
•Parse and preserve RIFF chunks; do not alter unknown chunks; keep original order where feasible.
•On save, copy “data” chunk byte-for-byte (no recompression). Rebuild RIFF header and directory; align chunks to even-byte boundaries with pad bytes as per RIFF.
•Write/update:
•“cue ”: sample-accurate cue points.
•“smpl”: loop information. Define loop as [startSample inclusive, endSample exclusive]; support mode normal and ping-pong (store in smpl if compatible, else holn JSON).
•“LIST/INFO”: common textual metadata (INAM name, IART artist, ICMT comments). Do not invent nonstandard INFO fields for musical key/scale.
•“holn” (custom JSON chunk): extended taxonomy (descriptive tags), musical grid extensions (key/scale/tuning/barOffset/swing), regions, affective placeholders. Include holn.schemaVersion = 1.
•Optional: Export sidecar JSON mirroring holn chunk for DAW compatibility; user toggle selects canonical source for extended metadata.
•RF64: read-only support; writing RF64 is out of scope at MVP.

2.Waveform, transport, and editing

•Multiresolution waveform: overview + zoomed viewport; hierarchical peak pyramid (factors 4/16/64/256/1024) computed in a Web Worker with transferable ArrayBuffers; cached in IndexedDB by content hash.
•Transport: play/pause/stop; loop playback A/B; drop markers while playing; smooth scrubbing; show position in samples, ms, SMPTE, and bars/beats once BPM/time signature known.
•Editing: create/move/delete cue points, loop in/out, regions; zero-crossing snap and optional grid snap (user toggles). Undo/redo with history.
•Keyboard: space play/pause; M add marker; L toggle loop; [, ] nudge; Z/X zoom; Cmd/Ctrl+Z/Y undo/redo.

3.Musical grid and tags

•Musical grid fields: bpm, timeSig {num, den}, tuningA4Hz, key, scale, barOffset, swing.
•Descriptive tags (controlled vocab with freeform fallback): genre, mood, function, form section, role, instrumentation, voicing, style/articulation, motif/ornament, timbre adjectives.
•Computed: duration (samples/ms), loop length in samples and bars/beats (if BPM present).
•Accessibility: all controls keyboard-focusable with ARIA labels; high-contrast theme option; colorblind-safe palette.

4.Performance and privacy

•All processing local by default; no telemetry. Memory-safe streaming writer to avoid full-buffer copies.

V2 Functional Requirements (adds OSC integration)
1.Bridge model and security

•Browser cannot speak UDP; require a local WebSocket bridge (default ws://127.0.0.1:8040) that translates JSON envelopes to UDP OSC and back.
•Bridge connection policy: localhost-only by default; CORS allowlist; optional shared-secret auth passed during handshake; exponential backoff reconnect.
•Handshake:
{ “type”:“hello”, “agent”:“web-tagger@v2”, “proto”:“holon-osc-json@1”, “auth”:”” }
•Envelope schema for all messages:
{
“type”:“osc”,
“dir”:“out”|“in”,
“ts”: <unix_ms>,
“addr”: “/holon/v1/transport/play”,
“args”:[ {“t”:“i”,“v”:1}, {“t”:“f”,“v”:120.0}, {“t”:“s”,“v”:“markerName”} ]
}
•Logging panel with filter and pause; redact secrets.

2.OSC address map (namespace /holon/v1)

•Outgoing (browser → bridge → miRack):
/holon/v1/transport/play            i 1|0
/holon/v1/transport/stop            i 1
/holon/v1/transport/locate          f seconds
/holon/v1/grid/bpm                  f bpm
/holon/v1/grid/timesig              ii numerator denominator
/holon/v1/marker/add                sf name, seconds
/holon/v1/marker/remove             s  markerIdOrName
/holon/v1/loop/set                  ff startSec endSec
/holon/v1/selection/region          ff startSec endSec
/holon/v1/state/commit              s  contentHash  (sent when a save occurs)
•Incoming (miRack → bridge → browser):
/holon/v1/transport/state           i 0|1
/holon/v1/transport/pos             f seconds
/holon/v1/grid/bpm                  f bpm
/holon/v1/grid/timesig              ii numerator denominator
/holon/v1/marker/add                sf name, seconds
/holon/v1/loop/set                  ff startSec endSec
/holon/v1/hello                     s  peerId       (bridge/app ID)
•Version-aware: if a differing namespace is seen, show compatibility warning and suggest fallback to read-only monitoring.

3.State and conflict management

•Maintain “dirty” state in the editor; if incoming messages would alter active edits, display a merge dialog with options: accept remote, keep local, or duplicate as new region.
•Remote lock: when a remote app indicates edit intent (e.g., /holon/v1/state/lock s peerId), show a lock banner; local edits are disabled until released or forced.
•Replay buffer: queue user edits while offline; flush upon reconnect with order preserved.

4.Clocking and timebase

•Default assumption: OSC peer is not a master clock; browser is timebase for UI playback. Use absolute seconds from audio context for locate/play.
•Optionally accept a periodic /transport/pos and smooth to it with low-pass filtering to avoid jitter; do not hard-jump the UI unless drift exceeds threshold.
•Conversion: samples = floor(seconds * sampleRate); bars/beats derived from grid; document rounding.

5.Security and privacy

•Localhost only by default; user toggle to allow LAN with explicit warning.
•Shared-secret auth optional; secrets never logged; origin validation via allowlist.

6.UX for OSC

•Connection widget with states: disconnected → connecting → connected; show peerId and protocol version.
•Quick actions to send play/stop/locate; status mirrors incoming transport.
•Message console with timestamps and payload inspection.

Architecture and Stack (V1 and V2)
•TypeScript SPA (Vite + React or Svelte). Web Audio API for decode/play; AudioWorklet optional for tight loop playback. Workers for RIFF parsing and peak generation. IndexedDB for peaks/state cache.
•Modules:
riff-parser.ts, riff-writer.ts, holn-chunk.ts, audio-engine.ts, waveform-worker.ts, peaks-cache.ts, grid-utils.ts, tags-panel.tsx, transport.tsx, regions.tsx, state.ts, fs-adapter.ts
V2 adds: osc-client.ts (WebSocket), osc-addresses.ts, osc-bridge-proto.ts, osc-log.tsx, osc-state.ts
•Config files: app.settings.json, osc.config.json (host, port, auth, allowLan: false).

Data Schemas (TypeScript)
type Timecode = { samples: number; seconds: number; bars?: number; beats?: number; ticks?: number };
type Marker = { id: string; name: string; type: ‘cue’|‘loopStart’|‘loopEnd’|‘regionStart’|‘regionEnd’|‘user’; t: Timecode; color?: string };
type Loop = { start: Timecode; end: Timecode; mode: ‘normal’|‘pingpong’; xfadeMs?: number };
type MusicalGrid = { bpm?: number; timeSig?: { num: number; den: number }; tuningA4Hz?: number; key?: string; scale?: string; barOffset?: number; swing?: number };
type DescriptiveTags = { genre?: string[]; mood?: string[]; function?: string[]; form?: string[]; role?: string[]; instrumentation?: string[]; voicing?: string[]; style?: string[]; motif?: string[]; timbre?: string[]; notes?: string };
type AffectivePlaceholders = { poms2?: Record<string, number>; mirexClusters?: string[]; hexaco?: Record<string, number>; ocean?: Record<string, number>; moodFluctuation?: number; lutAddresses?: string[]; stats?: Record<string, number> };
type Region = { id: string; name?: string; start: Timecode; end: Timecode; tags?: Partial; musical?: Partial };
type AudioFile = { path?: string; duration: Timecode; channels: number; sampleRate: number; markers: Marker[]; loops: Loop[]; regions: Region[]; tags: DescriptiveTags; musical: MusicalGrid; affective: AffectivePlaceholders; riffMeta: Record<string, unknown> };

RIFF Mapping Precision
•cue : store cue points at exact sample offsets; ensure dwPosition consistency with data chunk format.
•smpl: store loop start/end as [inclusive, exclusive]; loop type mapping documented; if unsupported modes, store in holn only.
•LIST/INFO: map only standard text fields (INAM, IART, ICMT, IPRD, ICRD where applicable). Key/scale live in holn JSON; optionally mirror a human-readable key string in ICMT.
•holn: JSON with schemaVersion=1; includes DescriptiveTags, Regions, MusicalGrid extensions, affective placeholders; include file content hash and lastSaved timestamp for integrity.
•Preserve bext, iXML, id3 chunks as opaque; do not edit.

Milestones
•V1 M1: Project scaffold; load/play; duration; peak pyramid in Worker; IndexedDB cache.
•V1 M2: Markers and loop points; zero-crossing snap; keyboard shortcuts; undo/redo.
•V1 M3: Musical grid; bars/beats ruler; regions; tags panels.
•V1 M4: RIFF write-back (cue/smpl/LIST INFO/holn); streaming writer; sidecar option; round-trip tests; accessibility pass.
•V2 M5: OSC client, handshake, connect UI, logs.
•V2 M6: Transport sync (play/stop/locate/pos) and grid sync (bpm/timesig).
•V2 M7: Marker and loop sync in both directions; conflict and remote lock handling; replay buffer.
•V2 M8: Security hardening (localhost/CORS/secret), reliability tests, latency and jitter smoothing.

Acceptance Criteria
•V1:
•Data chunk is bit-identical post-save (hash match).
•Cue and loop positions are sample-accurate; loop edges are click-free with zero-cross and optional short crossfade.
•Unknown chunks preserved; RF64 read-only handled gracefully.
•Round-trip reload shows identical markers/loops/tags; sidecar mirrors holn exactly.
•2-hour 48k stereo responsiveness remains smooth; UI is accessible via keyboard/ARIA.
•V2:
•WebSocket bridge connection stable with exponential backoff; handshake and protocol version displayed.
•Transport/grid messages reflect accurately; marker/loop edits propagate both ways within 100–200 ms typical LAN latency.
•Conflict resolution UX prevents silent overwrites; replay buffer flushes correctly post-reconnect.
•Security defaults: localhost-only; CORS allowlist; optional shared secret; no logging of secrets.

Testing Plan
•Unit: RIFF parser/writer (chunk order, pad bytes, loop semantics), time conversions, peak generation, holn schema validation.
•Fuzz: malformed WAVs; unexpected chunks; oversized metadata; random cue arrays.
•Integration: load files with existing cue/smpl from multiple tools; verify interop.
•Golden tests: hash-compare data chunk before/after save; verify bar/beat alignment at various BPM/time signatures.
•V2 harness: mock bridge that echoes and simulates delays/drops; deterministic tests for replay buffer and conflict merges; clock-drift scenarios.

Risk Register and Mitigations
•Loop clicks at non-zero crossings → enable zero-cross snap and optional 5–20 ms crossfade; unit tests with synthesized tones.
•Memory pressure during save → streaming writer with bounded buffers; no main-thread copies.
•Bridge instability or LAN exposure → localhost-only by default; explicit allowLan switch; CORS allowlist; auth token; backoff and reconnect.
•Interop ambiguity for musical key → store canonically in holn; do not invent INFO fields.

Deliverables
•Source tree with V1 modules and V2 OSC modules.
•README for V1 usage and V2 bridge setup, security notes, and protocol reference.
•Example WAVs with cue/smpl; example sidecar JSON; mock bridge.

Meta Parameters for the Code-Generation Run
•Audience level: senior
•Depth: production-grade
•Priorities: correctness, UX precision, interop, security, extensibility
•Verbosity: normal, with explanatory comments where non-obvious
•Strictness: balanced defaults with explicit assumptions

END OF REVISED MASTER PROMPT
