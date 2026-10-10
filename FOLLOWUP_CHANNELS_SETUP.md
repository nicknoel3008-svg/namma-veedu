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

## Property visits

Every property card provides **Book a slot**. Customers can select a predefined time or request a custom date and time in IST. The default times are `10:00,12:00,15:00,17:00`; override them with `VISIT_SLOT_TIMES` using comma-separated 24-hour times. These are suggested request slots, not verified owner availability.

Customers provide their name, email or WhatsApp contact, and consent. Requests start as **Requested**, pending owner confirmation. In the authenticated Mira Studio, expand **Property visit requests**, load requests, edit decisions and save. Verify property access before confirming. A confirmed time is blocked for that property. Customers can view and cancel their requests in the same browser. Clearing browser identity prevents recovery of those requests through the customer view; the owner retains them.

Owner decisions do not automatically email or WhatsApp customers. Contact them using the supplied details after reviewing their request. The eight primary dashboard KPIs remain unchanged.

## Verification

Automated tests use temporary SQLite storage and mocked email/Meta transport. Browser QA fixtures disable real messaging and simulate visit writes. Production message delivery requires provider setup and a separately authorized recipient test.
