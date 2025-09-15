System Intent
Implement V2 OSC integration for the Holon/Holonist web tagger targeting the VCV Rack “OSC Sampler” (8 tracks). Default to App-led clock: the web app sets tempo and alignment. Provide an optional Device-led mode that applies BPM changes at author-defined tag points. Maintain V1 local-only viewer/player/tagger with RIFF round-trip untouched.

Functional Requirements
1.Clock Modes
1.1 App-led (default)

•On session start (and on reconnect), send:
setMasterBpm(bpm)  →  masterRestart()
•For any tempo change during performance:
Atomic transaction in exact order:
setMasterBpm(newBpm)
masterRestart()
(optional) batch triggers/locates aligned to bar 1
•Quantization: schedule transactions at the next full bar (bar boundary = beat 1). If a change is requested within less than quantizeGuardMs (e.g., 120 ms) to the next bar, defer to the subsequent bar.
•Latency compensation: scheduler computes sendTime = targetBoundary - networkLatencyMs - deviceGuardMs (e.g., 5–10 ms). Use a tight send loop driven by setTimeout + AudioContext.currentTime sampling or a dedicated timing worker.

1.2 Device-led (optional toggle)
•Build a TempoMap from tags (see 2). For each tempo event, schedule:
setMasterBpm(event.bpm) at the tagged boundary
masterRestart() at the same boundary (or immediately after, within deviceGuardMs)
•Two sub-modes:
A) Region-edge BPM: apply changes at region.start bar boundary
B) Cue-index BPM: apply changes when “cue index K reached” (user triggers cuetrigger → we schedule bpm+restart for the next full bar)
•The app never infers BPM from filenames; it uses authored tags. Filename BPM remains a fallback for load-time hints only.

2.Tempo Map and Tag Semantics

•Input tags (per file/region): bpm:number, timeSig:{num,den}, barOffset:number (bars before first downbeat), swing?:number, tempoChangeAt?:(‘regionStart’|‘cueIndex’), cueIndex?:number.
•Construct TempoMap:
TempoEvent = { id, at: { type:‘bar’|‘time’|‘cue’, bar?:int, timeSec?:number, cueIndex?:int }, bpm, timeSig, action:‘changeTempo’, quantize:‘bar’, restart:true }
•Conversion helpers: samples↔seconds↔bars/beats (honor timeSig, barOffset, bpm); floor for sample indices, round/ceil when scheduling future bars with guard windows.
•Validation: strictly increasing event times; clamp bpm to 20–999; validate cue indices.

3.Device Profile: vcvrack.oscSampler@v1 (write-only)

•Global:
setMasterBpm(bpm:20..999) → /bpm f
masterStop()              → /master/stop i(1)
masterRestart()           → /master/restart i(1)
•Per track n=1..8:
loadSample(n, path:string)         → /track/n/load s
unload(n)                           → /track/n/unload i(1)
trigger(n)                          → /track/n/trigger i(1)
setCuepointIndex(n, idx:int>=0)     → /track/n/cuepoint i
cuetrigger(n)                       → /track/n/cuetrigger i(1)
setVolume(n, v:0..1)                → /track/n/volume f
setPitch(n, s:-1..1)                → /track/n/pitch f
setPan(n, p:-1..1)                  → /track/n/pan f
setMix(n, m:0..1)                   → /track/n/mix f
setLoopMode(n, mode:0|1|2)          → /track/n/loopmode i
setLoopCount(n, count:int>=1)       → /track/n/loopcount i
setGrainSize(n, s:0.005..0.5)       → /track/n/grainsize f
setGrainOverlap(n, o:0..0.9)        → /track/n/grainoverlap f
•Input validation: clamp to documented ranges; disable loopcount input unless mode=1; cuetrigger disabled until a cue index is set.

4.Bridge Contract and Security

•WebSocket to bridge: ws://127.0.0.1:8040 (configurable). Localhost-only by default. Allow LAN via explicit toggle with warning.
•Handshake:
{ “type”:“hello”, “agent”:“holon-web-tagger@v2”, “proto”:“osc-json@1”, “auth”:”” }
•Envelope for sends:
{
“type”:“osc”,
“dir”:“out”,
“ts”: <unix_ms>,
“udpHost”: “127.0.0.1”,
“udpPort”: <7000|7001|8000|8001|9000|9001|57120|57121>,
“addr”: “/track/1/volume”,
“args”: [ { “t”:“f”, “v”:0.8 } ]
}
•Bridge status reports UDP send success/failure (socket-level). UI shows “pending/ok/failed”. Retry once for idempotent setters; never auto-retry triggers.
•Reconnect: exponential backoff with jitter; on reconnect in App-led mode, transactionally resend bpm→restart→state. In Device-led, resume scheduler at next boundary (do not retrofire missed events).

5.Scheduler and Ordering

•A tiny, single-threaded scheduler queues “transactions” each with:
{ at: absoluteTime, priority, steps:[{addr,args}], policy:{quantize:‘bar’, guardMs, orderStrict:true} }
•For App-led setlist start:
Tx0: setMasterBpm → masterRestart
Tx1: per-track loadSample (if using known paths)
Tx2: per-track initial params (volume/pan/pitch/mix/loop)
Tx3: optional synchronized triggers
•Ordering guarantees: steps run in order within a transaction; transactions for the same boundary obey priority (tempo change > restart > triggers > params). Coalesce params where possible.

6.UI Wiring

•Connection panel: UDP port dropdown; secret input; Connect/Disconnect; status chips (disconnected/connecting/connected/degraded); “Reconnect after port change” banner.
•Clock mode toggle: App-led (default) vs Device-led. App-led explains deterministic control; Device-led explains tempo tags behavior and the need to author tag points.
•Tempo Map editor (visible in Device-led): table of tempo events; add/edit/delete; choose at=‘regionStart’ or at=‘cueIndex’; quantize=‘bar’ (fixed); preview of upcoming changes.
•Track grid: path field + “Send to track”; controls (volume/pan/pitch/mix); loop mode/count; grain size/overlap with presets (Percussive/Balanced/Sustained). Trigger/cue controls with clear affordances.
•Global: BPM numeric field; Set BPM; Master Stop; Master Restart; “Apply to all tracks” for static params; “Resend all” button.
•Logging panel: last 200 messages with filter; “verbose” toggle (obfuscate paths and redact auth by default).

7.Path Handling

•MVP path-based loads only. Display normalized “effective path” (do not alter the string sent). Provide “Test path” (send a benign setter first, then attempt load).
•Optional helper (off by default): bridge upload endpoint stores files in a well-known directory; returns the relative path used in /track/n/load. Include collision handling and checksum.

8.Reconnect and Recovery

•Maintain lastSent state. On reconnect:
App-led: Tx: setMasterBpm → masterRestart → reapply params → (optional) user-triggered retriggers.
Device-led: jump scheduler forward; show a toast “resumed at next boundary”; do not retrigger automatically.
•Provide a “Safe resume” dialog: offer to stop all, restart at bar 1, or continue.

9.Tests

•Unit tests: address/arg typing; clamping; envelope shaping; scheduler ordering; bar/beat conversion; device-guard timing.
•Scenario tests:
A) App-led start: bpm→restart→load→params→triggers; verify order and timing gaps.
B) App-led mid-show tempo change at bar boundary: change bpm, restart, retrigger selected tracks.
C) Device-led tempo map with region-edge changes across three regions; verify changes align at bar 1 of each region.
D) Device-led cue-index tempo change: cuetrigger at cue 2 schedules bpm+restart on next bar; verify no early fire.
E) Reconnect during active show: scheduler pauses, resumes at the next boundary; App-led resends bpm→restart first.
F) Rate-limit: aggressive slider drag remains under 60 msgs/s global and 15 msgs/s per track.
G) Port switch: requires explicit reconnect, then state reassertion.
H) Path edge cases: spaces, unicode, backslashes; ensure string passes unmodified.
•Negative tests: out-of-range inputs (pitch, grain, loopcount) are clamped with a user-visible note; refusing cuetrigger without set cue index.

10.Acceptance Criteria

•App-led mode: Every tempo change occurs at the intended bar boundary with ordered bpm→restart; audible sync is stable; triggers after restart are aligned.
•Device-led mode: Tempo map changes fire at designated tag points; no missed or duplicated tempo-change events across reconnects; scheduler never retrofires past events.
•Bridge: localhost-only by default; optional secret; UDP send status surfaced; single retry for idempotent setters; secrets redacted in logs.
•Performance: Scheduler enqueues reliably under UI load; slider coalescing keeps device responsive; no burst exceeds configured caps.
•UX: Clear clock mode descriptions, port change warnings, empty states, and troubleshooting hints.

11.Risks and Mitigations

•No device acknowledgements → optimistic UI with send-status and manual “Resend all”.
•Timing jitter → guard windows, deviceGuardMs, and priority-ordered transactions; option to increase lookahead.
•Path failures → test helper and optional upload flow.
•Overload from slider spam → coalescing + caps.
•User confusion on clock modes → rich inline help and a default App-led mode.

Conformance Matrix (abbreviated)
UI Set BPM → /bpm f → masterRestart i(1) → order strict
Global Stop → /master/stop i(1)
Global Restart → /master/restart i(1)
Track Load → /track/n/load s
Track Unload → /track/n/unload i(1)
Trigger → /track/n/trigger i(1)
Cue select → /track/n/cuepoint i
Cue jump → /track/n/cuetrigger i(1)
Volume/Pan/Pitch/Mix → respective /track/n/* f (coalesced)
Loop mode/count → /track/n/loopmode i, /track/n/loopcount i
Granular params → /track/n/grainsize f, /track/n/grainoverlap f

Deliverables
•osc-bridge-client.ts
•osc-scheduler.ts (transactions, quantization, deviceGuard)
•tempo-map.ts (data types, builders from tags)
•osc-sampler-adapter.ts (device profile)
•osc-panel.tsx (UI), logs panel, clock mode toggle and editor
•tests/*.spec.ts (unit + scenarios)
•README-osc-sampler.md (setup, clock modes, tempo maps, troubleshooting)
•Optional: mock-bridge.js with upload endpoint behind a flag

Meta-Parameters for the Code-Generation Run
Audience: senior full-stack/audio dev
Depth: production-grade
Priorities: deterministic timing, correctness, reliability, UX clarity, security, extensibility
Verbosity: normal with targeted comments
Strictness: balanced; explicit assumptions and clamps

