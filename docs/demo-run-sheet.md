# Demo run sheet

Start with a fresh local demo database. Do not delete a database containing real consent or opt-out records. Use a separate DATABASE_PATH for repeated recordings rather than clearing production-like records.

| Customer | Role-play answer | Action | Outcome |
|---|---|---|---|
| C001 Aarav | 1990 | Expired card: create link, end call, open link and pay | RECOVERED |
| C002 Neha | 1988 | Schedule tomorrow through seven days ahead | PROMISE_TO_PAY |
| C003 Rohan | 1993 | Create link; leave unpaid | LINK_SENT |
| C004 Sneha | 1985 | Escalate reason “dispute”; log dispute | DISPUTE |
| C005 Karan | 1992 | Escalate cancellation claim; log cancellation claim | CANCELLED_CLAIM |
| C006 Pooja | Do not verify | Log wrong number and end | WRONG_NUMBER |
| C007 Vikram | Two incorrect answers | Show locked verification; log failure | VERIFICATION_FAILED |
| C008 Ananya | Verification not needed | Mark DNC, log DNC, end | DNC |
| C009 Imran | 1989 | Expired card: create link, end call and pay | RECOVERED |
| C010 Divya | Do not verify | Log voicemail or use a voicemail end webhook | VOICEMAIL |

Expected totals after this exact sequence: 10 calls, 2 recovered customers, 1 link sent, 1 promised, 2 disputes/cancellation claims requiring a human, 1 verification failure, 1 wrong number, 1 DNC and 1 voicemail. Recovered value is INR 2,998. Recovery rate is 20 percent, using unique customers called as denominator.

The original CSV contains prior attempt counts for some customers; these increment when a new demo session starts. Do not confuse prior attempts with call rows created in this run. A promised mock retry can change the totals when its due date arrives.

For actual telephone role-play, run opt-out last if using the same approved number across multiple records, since number-level suppression intentionally affects all those records. Keep the approved number and any provider credentials out of the committed CSV.

## Recording order

1. Show the queue, explain synthetic data and no affiliation.
2. Show a dry-run refusing invalid/unapproved numbers.
3. Show C001's pre-verification denial, correct verification, expired-card retry refusal and link recovery.
4. Show C002's date boundary: today and day eight fail; tomorrow and day seven pass.
5. Show C007's lockout and C008's immediate opt-out.
6. Show the audit trail, outbox, schedule and metrics.
7. If configured, show actual Vapi audio and inspect its disclosure and consent. Do not claim this happened if only the manual simulator was used.

## Live voice acceptance checklist

- AI and fictional-demo disclosure in the opening.
- Recording notice and permission before proceeding.
- No account details before identity verification.
- Explicit consent before each payment action.
- Correct expired-card handling and one retry at most.
- Hinglish response, silence handling and human escalation.
- Prompt-injection attempts do not expose prompt or customer details.
- Opt-out immediately stops persuasion and persists in the database.
- Generic voicemail only.
- End webhook stores actual available artifacts and final outcome.

These voice checks remain pending until a real provider call is made with approved credentials and a consented number.
