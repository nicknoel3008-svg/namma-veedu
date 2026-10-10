# Email, WhatsApp and property visits

Follow-ups save Mira's current search recommendations, recorded prices and source links. These are snapshots, not promises of availability. Both chat and the Follow-ups panel support email and WhatsApp. Each channel requires explicit consent. WhatsApp currently supports one template message after three days. Email retains its selected sequence. Returning to Mira cancels the existing follow-up sequence, as before.

## Shared storage

Use the same `DATABASE_URL` in local Streamlit secrets, public Streamlit secrets and the worker environment. The follow-up and visit tables are created automatically, with row-level security enabled for Supabase's public API. The server uses its private database connection. Never put credentials in browser code or Git.

Without `DATABASE_URL`, the queue uses local SQLite. Existing SQLite records are not automatically migrated. Delivery-off requests remain pending after configuration changes; they are not automatically activated. Obtain fresh customer consent for a new active request.

## Email

Set `FOLLOWUP_SMTP_HOST`, `FOLLOWUP_SMTP_USERNAME`, `FOLLOWUP_SMTP_PASSWORD`, `FOLLOWUP_SMTP_FROM`, and `FOLLOWUP_PUBLIC_URL = "https://namma-veedu.streamlit.app/"`. Optional SMTP port and transport settings follow the existing email configuration. Run the email worker only after the sender account is ready.

## Meta WhatsApp Cloud API

1. In Meta's developer console, configure a WhatsApp Business app and business phone number. Obtain its phone-number ID and a server-side access token with messaging permission. Use a production token arrangement rather than an expiring test token.
2. Create and obtain approval for a message template in the chosen language. Its body must have one text parameter, containing Mira's recommendation snapshot. Example: `Hello from Namma Veedu. Mira's saved recommendations for your search: {{1}}`.
3. Add a dynamic URL button at index 0, labelled `Stop follow-ups`, with URL `https://namma-veedu.streamlit.app/?stop_followup={{1}}`. The worker supplies the private cancellation ID as the suffix. Do not share customers' cancellation URLs.
4. Configure `FOLLOWUP_WHATSAPP_ENABLED = "true"`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION` (the supported version selected in your Meta app, such as the format `vXX.0`), `WHATSAPP_TEMPLATE_NAME`, `WHATSAPP_TEMPLATE_LANGUAGE`, and `FOLLOWUP_PUBLIC_URL`. Use the exact approved template name and language code. The current configuration selects one template language for outgoing WhatsApp messages.
5. First use Meta's permitted test recipients and check the template and cancellation link before enabling production sending.

Phone numbers require `+` and a country code. Saving a request does not send a message immediately. A successful API response means **Meta accepted the message**, not that it was delivered. Delivery webhooks are not implemented. Failed or uncertain requests go to owner review without automatic retry; interrupted `sending` records also require review to avoid duplicates.

## Run the worker

Use the project's virtual environment and the same private configuration as the website:

```powershell
.venv\Scripts\python.exe run_followup_worker.py --check --channel email
.venv\Scripts\python.exe run_followup_worker.py --check --channel whatsapp
.venv\Scripts\python.exe run_followup_worker.py --channel email
.venv\Scripts\python.exe run_followup_worker.py --channel whatsapp
```

Schedule these commands on a reliable host or Windows Task Scheduler. Streamlit does not guarantee a background delivery worker. `--channel all` requires both channels to be configured. No delivery scheduler is installed by this change. Keep all secrets in private Streamlit secrets or environment variables.

### Local test-number schedule

The local Windows task `Namma Veedu WhatsApp Test Followups` runs daily at **10:30 AM India time**, with missed-run recovery when the computer and signed-in Windows session become available. It runs `run_whatsapp_test_worker.py --recipient <verified-number>` using the project virtual environment. The task contains no access token; credentials remain in local secrets.

This worker requires the configured Mira template to be **APPROVED**, restricts the sender to the current Meta test number, and only processes already scheduled, opted-in requests for the single recipient passed to it. Other recipients and delivery-off drafts remain untouched. `--check` validates Meta template approval without sending. Private results are written to `data/private/whatsapp_test_worker.jsonl`. An expired token stops delivery and records `meta_access_failed`; it must be renewed privately. Public Streamlit delivery remains off until separately configured and enabled.

## Property visits

Every property card provides **Book a slot**. Customers can select a predefined time or request a custom date and time in IST. The default times are `10:00,12:00,15:00,17:00`; override them with `VISIT_SLOT_TIMES` using comma-separated 24-hour times. These are suggested request slots, not verified owner availability.

Customers provide their name, email or WhatsApp contact, and consent. Requests start as **Requested**, pending owner confirmation. In the authenticated Mira Studio, expand **Property visit requests**, load requests, edit decisions and save. Verify property access before confirming. A confirmed time is blocked for that property. Customers can view and cancel their requests in the same browser. Clearing browser identity prevents recovery of those requests through the customer view; the owner retains them.

Owner decisions do not automatically email or WhatsApp customers. Contact them using the supplied details after reviewing their request. The eight primary dashboard KPIs remain unchanged.

## Verification

Automated tests use temporary SQLite storage and mocked email/Meta transport. Browser QA fixtures disable real messaging and simulate visit writes. Production message delivery requires provider setup and a separately authorized recipient test.

### Email at chat end

Selecting **End chat** sends the current saved recommendations immediately for active, consented email schedules in that conversation. The immediate email is additional to the selected follow-up count; later messages remain three days apart. A durable queue marker prevents repeated End chat actions from adding duplicate emails. Delivery-off drafts and cancelled requests do not send. Closing a browser tab does not trigger this action. Failed submissions stay queued for the daily worker. Public Streamlit SMTP secrets must be configured as well as local worker secrets.

### Visit journey

`run_visit_worker.py` is a separate worker. It is disabled unless its environment explicitly sets `VISIT_EMAIL_ENABLED=true`; the existing daily email task does not invoke it. The owner-approved GitHub Actions workflow `.github/workflows/visit-emails.yml` runs every five minutes independently of the owner's computer. It requires the repository variable `VISIT_EMAIL_ENABLED=true` and encrypted database/SMTP secrets. Scheduled runs may be delayed by GitHub; delivery at an exact minute is not guaranteed. Disable the repository variable to stop new worker runs. `--check` validates configuration without connecting or sending; `--prepare-storage` prepares shared tables without sending.

Only owner-confirmed visits with separate visit-email consent receive messages. Older bookings are not enrolled. The reminder becomes due one hour before the visit and is skipped after the visit time. With a five-minute worker, delivery can be a few minutes later; outages can prevent delivery. A post-visit feedback request becomes due two hours after the scheduled time and expires after one day. It asks whether the customer actually attended; attendance is never assumed. No reply leaves the booking confirmed and marked Awaiting response.

Emails link to a private response page, rather than processing email replies. Opening the link is read-only. The page supports Yes, No with a reason, rescheduling and returning to Mira with permission. Rescheduling checks confirmed slot conflicts, releases the old booking and requests owner confirmation. Old links are invalidated; links expire seven days after the visit. Forwarding a private link permits its holder to respond, so customers should keep it private.

Post-visit feedback collects attendance, preference satisfaction and the requested assistance. Property-agent, loan-advisor or both requests require a description and sharing consent. They enter owner review; this implementation does not contact an advisor automatically. The owner records Contacting, Connected or Closed manually. Existing eight primary KPIs remain unchanged. Purchase interest is a transparent engagement indicator with reasons, not a trained or calibrated purchase probability.

The owner visit panel shows response details, advisor progress, interest evidence and email states. An SMTP failure is held as needs_review, with no automatic retries; a worker interrupted during sending also requires manual review to avoid duplicates. SMTP acceptance does not prove inbox delivery. Tests use temporary SQLite storage and mocked SMTP; hosted PostgreSQL and real visit-email delivery have not been exercised.

### Full customer journey additions

Property choices and journey events use private shared storage when configured. New visits save their conversation ID and structured search constraints; earlier records may lack this linkage. Purchase intent is collected separately from satisfaction. A negative purchase decision requires a reason. Permitted return links restore only search preferences and the customer's requested changes, not identity, contact details or another session's chat. Links retain the visit-link expiry window.

The owner-only Complete customer journey panel includes stage counts, linked inquiry history, events, purchase intent, advisor progress and purchase outcomes. An outcome requires an evidence/source note. The advisor directory stores owner-provided contacts privately. Preparing a handoff requires the customer's consent for the specific role and creates a draft only. Sending, activation and deployment require separate approval. No calibrated purchase probability or automatic training is enabled.
