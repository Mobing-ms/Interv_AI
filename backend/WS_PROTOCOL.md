# Live interview WebSocket protocol

One endpoint, one server-side state machine (`SessionOrchestrator`).

```
ws(s)://<host>/session/{session_id}/live?token=<credential>[&autostart=false]
```

`ws_url` returned by `POST /session`, `GET /session/{id}` and `POST /guest/start`
already points here, **with `autostart=false`** (pre-check mode, see below).

Deprecated aliases. They still work but will be removed, so don't use them in new code:

| Old URL | Equivalent |
|---|---|
| `/session/{id}/orchestrate` | `/session/{id}/live` |
| `/session/{id}/stream` | `/session/{id}/live?autostart=false` |
| `/session/{id}/stream?orchestrate=true` | `/session/{id}/live` |

## Authentication

`token` must be **one** of:

1. the `session_token` returned when the session was created,
2. the access JWT of the user who owns the session (refresh tokens are rejected),
3. the guest JWT issued by `/guest/start` **for this session**.

Anything else gets close code **1008** (`reason: "Unauthorized"`) before the
handshake completes. The old behaviour (any token longer than 20 characters,
or the literal `demo`, opened any session) is gone.

## Modes

- `autostart=true` (default): the interview starts as soon as the socket opens
  (`connected`, then `avatar_speak` greeting, then the warm-up `question`, ...).
- `autostart=false` (pre-check): the server sends
  `{"type":"connected","state":"PRECHECK",...}` and only answers `ping`,
  `media_chunk`, `calibration_event` and binary frames. The **first other
  message** (e.g. `client_ready`, `heartbeat`, `answer_started`) starts the
  interview, and that message is then handled normally.

## Frames

All frames are JSON text. Every server frame has `type` and `session_id`.
Timestamps are unix seconds (floats). Clients may send milliseconds in
`timestamp`; the server normalises them.

### Client to server

| type | fields | notes |
|---|---|---|
| `heartbeat` | `timestamp?` | server replies `heartbeat_ack` |
| `ping` | | server replies `pong` |
| `client_ready` / `ready` | | avatar finished speaking; starts the answer timer and the server replies `timer_started` |
| `answer_started` | `timestamp?` | |
| `audio_chunk` | `data` (base64 audio), `chunk_id?`, `duration?` (s, default 0.25), `text?` (client-side STT fragment), `is_speech?`, `stream_transcript?` | invalid base64 is dropped (no longer stored as text) |
| *(binary frame)* | raw audio bytes | server replies `binary_chunk_ack` |
| `video_frame` | `frame` or `data` (base64 JPEG) | about 1/s |
| `integrity_event` | `event_type`, `question_id?`, `timestamp?`, `severity?`, `details?` | |
| `answer_ended` | `text?` | manual stop or timer expiry. In CLOSING it is treated as a candidate question |
| `client_query` / `candidate_question` | `text` | during CLOSING/ENDED |
| pre-check only: `media_chunk`, `calibration_event` | | acknowledged with `chunk_ack` / `calibration_ack` |

Unknown types get `{"type":"ack","original_type":...,"ignored":true}`.

**Changed:** `media_chunk` and `calibration_event` are no longer accepted once
the interview has started (they get `ack` with `ignored: true`).

### Server to client

| type | fields |
|---|---|
| `connected` | `status`, `resumed` (bool), `state`, `message`, `timestamp` |
| `state_sync` | `resumed`, `state`, `current_question`, `topic`, `elapsed_time`, `follow_up_count_per_topic`, `context_count` (sent after a reconnect) |
| `avatar_speak` | `text`, `audio_url` (`/session/tts/audio/{key}`; may be `""` if TTS failed), `cache_key`, `language` |
| `question` | `id`, `text`, `time_limit`, `topic`, `subtopic`, `difficulty`, `is_follow_up` |
| `timer_started` | `time_limit`, `started_at`, `question_id` |
| `chunk_ack` | `chunk_id`, `is_speech`, `silence_duration`, `received_at` |
| `binary_chunk_ack` | `chunk_id`, `size`, `is_speech`, `received_at` |
| `transcript_update` | `question_id`, `text`, `words`, `is_partial` |
| `video_frame_ack` | `frame_id`, `received_at` |
| `answer_complete` | `question_id`, `finish_reason` (`vad_silence`), `text`, `word_count` |
| `nudge` | `text`, `reason` |
| `redirect` | `text`, `message` (same as `text`), `question`, `reason` |
| `integrity_event_ack` | `event_id`, `event_type`, `total_events`, `is_flagged` |
| `integrity_warning` | `event_type`, `message`, `severity`, `question_id`, `warning_count` |
| `heartbeat_ack` | `client_timestamp`, `server_timestamp` |
| `pong` | `timestamp` |
| **`keepalive`** (new) | `server_time`. Sent every `WS_SERVER_PING_SECONDS` (default 15 s), even while an answer is being evaluated. No reply needed, so ignore it or use it for liveness |
| `round_end` | `summary` {`total_questions`, `average_score` (**may be `null`**), `topics_covered`, `elapsed_time_seconds`}, `next_state`, `next_url` |
| `error` | `code` (`internal_error` \| `invalid_json`), `detail` (generic text; no server internals) |

After `round_end` the server closes with code **1000**.

## Closing

When the questions are done the server sends a `question` with `topic: "Closing"`
(id 999, "do you have any questions for me?") plus its `avatar_speak`, and **waits**.
Reply with `answer_ended` (or `client_query`) carrying the candidate's question, or empty /
"no" text to skip. The server answers with `avatar_speak`, then sends `round_end`. With no reply
within 90 s it ends on its own. Before this change `round_end` followed the closing line immediately.

## Follow-ups

`question` frames with `is_follow_up: true` build on the previous answer. Vague answers always get
one; partial and strong answers only sometimes. A vague answer to a follow-up moves on.

## Reconnect

Reconnect to the same URL with the same credential. The server restores the
state (`connected` with `resumed: true`, then `state_sync`, then the current
`question` is re-sent if the candidate was answering).

## Liveness

- The server sends `keepalive` every ~15 s. If you see no frames at all for
  ~45 s, treat the socket as dead and reconnect.
- Clients should keep sending `heartbeat` every 5–10 s.
- Evaluation, TTS and disk I/O no longer block the server's event loop, so
  heartbeats and keepalives continue during evaluation.

## Related REST changes

- `POST /session/tts/synthesize` now requires auth (user or guest token), and `text` is limited to 2000 chars.
- `POST /guest/link` now requires proof of the guest session: `guest_token`
  in the body, an `X-Guest-Token` header, or the `guest_token` cookie, matching
  `guest_session_id`. Otherwise you get 403. The same proof is needed for the
  `guest_session_id` field on signup/login; without it the session is not linked.
- Guest tokens can only read their own session. Before, a guest token without
  a `session_id` claim could read any guest session.
- Signal summaries (`/session/{id}/question/{qid}/signals`) return `null` for
  metrics that were not measured, not made-up defaults.
