# Verification record

Date: 3 October 2026. The implementation was checked against the attached fictional prompt pack and official Vapi/Razorpay documentation. This record distinguishes performed checks from credential-dependent work.

## Completed checks

- Python 3.12 environment created; dependencies installed and frozen in requirements.lock.
- 42 pytest cases passed. The suite covers two-attempt lockout, Unicode input, denied detail access, per-call reset, customer binding, consent, duplicate requests, atomic concurrent retry, expired instrument handling, date boundaries, invalid outcomes, DNC, shared-number suppression, attempt caps, calling hours, callback/escalation, payment-link expiry, payment idempotency, Razorpay signatures and exact amounts, provider envelopes, duplicate end reports, pending jobs and ambiguous provider responses.
- Full ten-customer isolated-database scenario run passed. Outcomes: C001 RECOVERED, C002 PROMISE_TO_PAY, C003 LINK_SENT, C004 DISPUTE, C005 CANCELLED_CLAIM, C006 WRONG_NUMBER, C007 VERIFICATION_FAILED, C008 DNC, C009 RECOVERED, C010 VOICEMAIL.
- Scenario metrics: 10 started calls, 2 recovered, 1 promised, 2 human-review cases, 1 DNC, 1 no-contact/voicemail, 20 percent recovery rate, INR 2,998 recovered in simulation.
- Python compile checks and both frontend JavaScript syntax checks passed.
- Backend started successfully on localhost. Chromium dashboard interaction verified access-token login, pre-verification denial, successful verification, mock link creation and call closure.

The initial payment-link test exposed a SQL placeholder-count mismatch. It was corrected before the passing run. A Unicode comparison test prompted UTF-8 encoding before constant-time verification comparison. Provider docs prompted support for both flat and nested Vapi tool envelopes and an updated active voice configuration.

## Reproduce

```bash
python -m pytest -q
python -m scripts.run_scenarios
python -m compileall -q app dialer scripts
```

The scenario script always uses a temporary database and overrides provider/payment settings to mock. It cannot place calls or charge money. Tests also use isolated temporary databases.

## Pending external checks

Real Vapi calls, model speech behavior, recording/transcription URLs, a real Razorpay test-account link, cloud deployment and a GitHub remote push are not claimed as completed. They require credentials, account configuration or new-repository creation access. The connected GitHub account was verified as Daniyah-Rehman-20, but its exposed connector does not include repository creation.

The browser simulator is manual. It verifies UI-to-backend behavior but cannot establish AI disclosure timing, Hinglish quality, voicemail detection, silence handling or prompt-injection resistance of a live model. Use the live checklist in demo-run-sheet.md after connecting Vapi.

There is one dependency deprecation warning about Starlette's httpx-based TestClient. It does not fail tests. Python 3.11 is configured in Docker and CI but was not executed in this local Python 3.12 environment. Docker and Render configuration are supplied; an actual Docker image build and Render deployment have not been performed.
