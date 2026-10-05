# Oracle-led stage setup

The custom-stage entry now starts with a natural-language brief. The Oracle
returns either a complete stage proposal or one essential clarification. The
default review shows the setting, decision, simulated speakers, fictional
civilian roles, upcoming trigger, supported duration, and assumptions. Detailed
fields live under **Edit stage details**. **Open advanced controls** exposes the
existing builder on the same draft.

**Review and continue** creates only the local seed and selects its duration.
The existing **Begin the gathering** action still owns creation and execution.
Preset stages, the advanced builder's permissive handoff, public limits, invite
checks, ticketing, and simulation contracts remain in place.

## Contract

`POST /api/parthenon/stage/draft` accepts an additive proposal mode:

```json
{
  "mode": "proposal",
  "brief": "Imagine a city deciding whether AI tutors belong in its schools.",
  "sources": "Optional excerpts and their URLs",
  "current": null
}
```

`current` may be a previously accepted proposal for refinement. The response
uses the existing success envelope and ticket path. `data` contains either
`{"clarification": "One essential question"}` or `{"proposal": {...}}`.
The proposal contains `stage`, `runLength`, `assumptions`, and server-assigned
`sourceBasis`. `stage` uses the existing fields: title, format, era, setting,
topic, speakers, audience, question, and happensNext. Requests with no mode
retain the existing missing-field draft behavior.

Proposal mode validates the whole answer and does not silently clip malformed
output. It uses one model request per explicit ask, with SDK retries and JSON
format fallback disabled for this mode only. A provider without JSON support
returns an error; there is no hidden second request. Cancelling stops the client
from waiting or applying a late answer; it does not promise to cancel provider
work that already started.

The bounded proposal roster has eight existing historical figures. Formats use
1–4 speakers and 8–14 generic civilian roles. Durations are afternoon, day,
threeDays, or week, clamped to public instance limits. Historical anchors and
role names are copied from the existing frontend catalogs into
`stage_roster.json` and `stage_audiences.json`; changes to these catalogs should
keep both copies aligned. The full original roster remains in advanced controls.

## Provenance and voice

Historical speakers are simulations. Their roster notes are canonical; their
new opening words are imagined. Generated civilians use generic fictional
roles, and the prompt forbids inventing private-person beliefs. Contemporary
premises are hypothetical unless the user supplies source context. No browsing
or independent verification occurs. The seed retains supplied excerpts and
URLs, and rejects generated links absent from the supplied context. These
constraints are not a factual-verification service.

Dictation uses browser `SpeechRecognition` only where the API is available in a
secure context. It starts only on an explicit button action, exposes real
start/error/end events, and inserts editable final transcripts into the brief.
It does not provide a continuous spoken conversation or invoke the existing
paid voice-output endpoint. Unsupported browsers use typing or device keyboard
dictation. Some browser implementations send audio to a speech service; this is
disclosed beside the control.

The latest draft is stored locally under `parthenon.oracleSetup.v1`. Editing
while a request is pending prevents the response from overwriting the edits.
Advanced and incomplete drafts survive restoration. Source text is retained
locally with the draft and sent on explicit Oracle asks. The prepared seed also
includes that context when the user later starts the gathering.

## Verification

Run the frontend regression suite from the repository root:

```sh
node --test frontend/src/parthenon/*.test.mjs
```

Run focused backend compatibility checks from `backend` with its test Python:

```sh
python -m pytest -q tests/test_stage_oracle.py tests/test_stage_proposal.py tests/test_public_invite.py tests/test_public_tickets.py tests/test_llm_json_responses.py tests/test_openai_chat_compat.py
```

Build from `frontend`; use `VITE_BASE=/parthenon/` and
`node scripts/check-base.mjs dist /parthenon/` to check the Observatory prefix.

Local verification for this change: **336 frontend tests, 169 backend tests**, root
and prefixed builds passed. The pre-existing large-bundle warning remains.
Eleven isolated browser scenarios passed with no JavaScript errors. They used
fixture proposals and intercepted all API calls.
No live model, real microphone transcription, or simulation was exercised.
Those require separate acceptance checks; fixture-based verification does not
establish live response quality or successful microphone transcription.

The visual pass uses the existing Parthenon typography, gold and night tokens,
square shared controls, and a 900px reading column. English layouts were checked
at 1440, 768, 390, and 320px and Chinese at 390px with the actual brand fonts
loaded. Review and advanced columns align, mobile fields use 16px text, and
controls retain at least 44px touch targets. The new setup copy is complete in
English and Chinese. A separate Astra review found no remaining blocking
design or focused implementation issues after the restoration fixes.
