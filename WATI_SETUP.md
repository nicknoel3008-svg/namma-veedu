# Wati setup for Namma Veedu

**Inactive: removed from the active to-do list at the owner's request.** Retained as historical reference only. Do not perform the setup or activation steps below unless requested again. The current flow uses manual WhatsApp confirmation and automated email follow-ups.

Status: follow-up and visit adapters prepared. The owner reports Meta approval complete. Local WATI credentials and approved template names are still missing; live delivery has not been verified.

1. Create your account at https://www.wati.io/ and choose a plan only after confirming API access and the reply/delivery webhooks you need. Subscription and messaging fees are separate.
2. Connect your production WhatsApp Business number through Wati onboarding. Ask Wati whether your existing number qualifies for Coexistence; do not delete its WhatsApp account without checking. The previous Meta test number is not an activated Wati production sender.
3. In Wati, submit an English recommendation template. It must have these three body variables in this exact order, named recommendations, resume_url, stop_url:

   Hello from Namma Veedu. Here are Mira's saved recommendations for your property search: {{1}}
   Continue your search: {{2}}
   Stop this follow-up: {{3}}

   Provide realistic sample values when submitting. Meta decides approval and category; do not assume property recommendations qualify for utility pricing. For Tamil, create and approve a separate template; automatic per-customer language selection is not implemented yet.
4. Obtain the API endpoint and token from your Wati workspace. Save credentials in local .streamlit/secrets.toml and Streamlit Secrets, never in Git or chat. The base URL includes the numeric tenant ID and excludes /api/v1. Configure:

```toml
WHATSAPP_PROVIDER = "wati"
FOLLOWUP_WHATSAPP_ENABLED = "false"
WATI_API_BASE_URL = "https://live-mt-server.wati.io/YOUR_NUMERIC_TENANT_ID"
WATI_ACCESS_TOKEN = "YOUR_PRIVATE_TOKEN"
WATI_CHANNEL_NUMBER = "YOUR_BUSINESS_NUMBER_WITH_COUNTRY_CODE_DIGITS_ONLY"
WATI_TEMPLATE_NAME = "YOUR_APPROVED_TEMPLATE_NAME"
FOLLOWUP_PUBLIC_URL = "https://namma-veedu.streamlit.app"
```

5. Keep sending disabled while checking the account, exact template variable names/order and API response schema. With a temporary configuration enabled, use run_followup_worker.py --channel whatsapp --check to validate settings without network calls or sending. This checks configuration only, not template approval or credentials.
6. Next, run an allowlisted test to your own opted-in number, using temporary queue storage. Confirm the response exposes localMessageId or messageId and the handset receives the full recommendations and working stop link. If the response differs, adapt it before customer activation. HTTP acceptance alone is not delivery.
7. After that test, configure the same credentials on the worker host and enable sending deliberately. Pending requests remain pending; there is no automatic bulk activation. The follow-up schedule sends one message three days after saving, when the worker runs.

## WhatsApp visit messages

New WhatsApp bookings have a separate visit-message consent checkbox. Existing bookings are not automatically enrolled. Owner confirmation remains required. Private response links support attendance, cancellation, reschedule requests and feedback; WhatsApp replies are handled in the WATI inbox.

Create three approved templates with four body parameters in this exact order: `name`, `property`, `visit_time`, `response_url`.

- Confirmation: Hello {{1}}, your Namma Veedu visit for {{2}} is confirmed for {{3}}. Confirm attendance, cancel or request a new time: {{4}}
- Reminder: Hello {{1}}, your visit for {{2}} is scheduled for {{3}}. Confirm attendance, cancel or request a new time: {{4}}
- Feedback: Hello {{1}}, how was your visit for {{2}} scheduled for {{3}}? Share attendance, feedback or assistance needs: {{4}}

Store the exact approved names privately:

```toml
VISIT_WHATSAPP_ENABLED = "false"
WATI_VISIT_CONFIRMATION_TEMPLATE = "your_approved_confirmation_template"
WATI_VISIT_REMINDER_TEMPLATE = "your_approved_reminder_template"
WATI_VISIT_REVIEW_TEMPLATE = "your_approved_feedback_template"
```

After configuration and recipient testing, enable `VISIT_WHATSAPP_ENABLED` and schedule `python run_visit_whatsapp_worker.py` every five minutes on a reliable host. `python run_visit_whatsapp_worker.py --check` validates configuration without sending or contacting WATI. This worker has its own enable flag, independent of the recommendation follow-up flag. No new scheduler is installed automatically.

Confirmation becomes due after owner approval, reminder within the final hour, and feedback two hours after the visit until one day afterward. A confirmation accepted in the final hour covers the reminder. Cancelled, rescheduled, nonconsenting and customer-reported purchased visits are excluded. Accepted means provider submission, not handset delivery. Failed or interrupted submissions require manual review and are never automatically retried. Mira Studio shows each WhatsApp submission status.

The recommendation template uses exactly three parameters as documented above. If your approved template has a different structure, align it before enabling delivery.

## Email sender change pending

The existing sender is unchanged until the owner supplies the replacement address. Update SMTP username, authenticated sender, credentials and provider settings together in local secrets, hosted Streamlit secrets and worker-host secrets. Changing only the visible From address may fail provider authentication. Verify the new sender with an authorized recipient test before switching scheduled delivery. Never paste passwords or tokens into chat.

## Customer consent

The website already asks for a number with country code and separate explicit WhatsApp consent. Consent is required before scheduling, and the worker excludes rows without an opt-in timestamp. Saved recommendations and the per-schedule stop link are passed to Wati. Cancellation prevents subsequent sends; a request already accepted by a provider cannot be recalled. Errors or ambiguous responses go to Needs review and are not automatically retried.

## Remaining before two-way automation

A public authenticated webhook receiver, verified delivery/read/failure events, STOP reply processing, customer-to-conversation mapping, language-specific template selection, visit reminder templates and reply-driven confirmations/rescheduling still need implementation and Wati account verification. Until then, use the message stop link and Wati inbox for replies. The dashboard reports accepted submissions as delivery unconfirmed. Do not advertise reply STOP automation before it is connected.

Official references:
- https://docs.wati.io/reference/sendtemplatemessage
- https://support.wati.io/en/articles/11463444-how-to-collect-customer-opt-ins-for-whatsapp-messaging
- https://support.wati.io/en/articles/11463225-how-to-track-template-message-delivery-and-message-status-using-wati-webhooks
- https://www.wati.io/pricing/
