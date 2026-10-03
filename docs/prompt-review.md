# Prompt review and engineering decisions

The supplied prompt is a good demo specification, but customer-wide verification flags alone are unsafe for multiple calls. Several described outcomes also assume work that the tool contract does not prove. This implementation resolves those gaps before adding the UI.

| Issue in the source | Decision implemented |
|---|---|
| Verification stored only against the customer | Add calls table; authorize using the active call's verification state; reset for every call |
| No call identifier on tool requests | Direct tools require X-Call-Id; Vapi tools are bound through the authenticated provider call ID |
| LLM can choose arbitrary customer ID | Reject customer/call mismatch; do not trust speech-derived identity |
| No replay handling | Per-call idempotency key with keyed fingerprint; atomic SQLite writes |
| Consent only in prose | Require consent=true for retry, link and scheduling; provider transcript still needs human inspection |
| Expired-card C001 and C009 expected recovered | Recover through a mock payment link; block retry and schedule for expired/paused/revoked instruments |
| Fake predictable /pay/C001 link | Cryptographically random capability URL with 24-hour expiry; GET cannot pay |
| “Sent” and confirmation wording despite console-only SMS | Label delivery demo_log_only; expose an authenticated outbox; never claim real SMS |
| LLM can log RECOVERED directly | Require an actual mock success or signed test payment confirmation |
| Same phone reused across customers | Valid phone-level DNC across records; invalid placeholders stay isolated for simulator scenarios |
| 30-second sleep may overlap active calls | Global active-call lock plus wait-for-end loop and 30-second pause |
| Call creation timeout may have succeeded remotely | Mark uncertain, count conservative attempt, block further calls, provide reconciliation command |
| Shared mutable customer outcome can be overwritten by late reports | Per-call outcomes; update current customer outcome only for matching last call; DNC/recovered precedence |
| Missing schedule column/processor | Durable schedules table and worker; mock execution only |
| Razorpay links can take more than one second | Queue external creation; return pending; do not pretend a pending link is sent |
| Reused reference_id can conflict | customer ID plus unique token suffix within reference length limit |
| Public operational dashboard | Public HTML shell, separate authenticated data API and in-memory operator token |
| Free-host SQLite may disappear | Persistent-disk Render blueprint; disposable free hosting documented separately |
| Recording/transcript details assumed always available | Save HTTPS artifact URLs if present; otherwise show unavailable |
| Company impersonation risk in greeting | Prominent fictional-demo and non-affiliation disclosure in greeting, UI and documentation |

## UX rationale

The main screen is a recovery queue, not a marketing page. A dark navy sidebar anchors navigation; a restrained blue accent identifies actions, with green, amber and rose used for outcome meaning. Financial and call metrics have clear definitions. A dedicated simulator panel follows verify, resolve and close, while preserving server errors visibly. The consent checkbox is mandatory in the UI and a server-side field is mandatory in the API.

The design includes responsive navigation, scrollable data tables, labeled form controls, visible keyboard focus, modal keyboard behavior, loading/error feedback, empty states and a separate payment page. There are no fake recordings, fabricated conversion charts or claims of SMS delivery.

## Scope boundaries

Backend tests demonstrate deterministic rules. They do not establish that an LLM always follows the conversational prompt, that real telephony is available in a given country, or that a deployment meets regulatory requirements. The manual simulator is explicitly labeled and does not claim to be a working browser voice assistant. Real voice comes from the Vapi adapter after user credentials and provider configuration.

Birth-year verification, plaintext fictional CSV answers and a single operator token are demonstration choices. Real customer data must not be imported into this version. No real card, CVV, OTP, UPI PIN or password is collected. No money-moving retry API exists in this code.
