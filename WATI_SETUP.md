# Wati setup for Namma Veedu

Status: delivery adapter prepared; customer sending must remain disabled until onboarding and an allowlisted live test pass. No Wati account, purchase or customer message has been created.

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
7. After that test, configure the same credentials on the worker host and enable sending deliberately. Pending requests remain pending; there is no automatic bulk activation. The existing schedule sends one follow-up three days after saving, when the worker runs. This adapter does not add immediate WhatsApp messages or visit reminders.

## Customer consent

The website already asks for a number with country code and separate explicit WhatsApp consent. Consent is required before scheduling, and the worker excludes rows without an opt-in timestamp. Saved recommendations and the per-schedule stop link are passed to Wati. Cancellation prevents subsequent sends; a request already accepted by a provider cannot be recalled. Errors or ambiguous responses go to Needs review and are not automatically retried.

## Remaining before two-way automation

A public authenticated webhook receiver, verified delivery/read/failure events, STOP reply processing, customer-to-conversation mapping, language-specific template selection, visit reminder templates and reply-driven confirmations/rescheduling still need implementation and Wati account verification. Until then, use the message stop link and Wati inbox for replies. The dashboard reports accepted submissions as delivery unconfirmed. Do not advertise reply STOP automation before it is connected.

Official references:
- https://docs.wati.io/reference/sendtemplatemessage
- https://support.wati.io/en/articles/11463444-how-to-collect-customer-opt-ins-for-whatsapp-messaging
- https://support.wati.io/en/articles/11463225-how-to-track-template-message-delivery-and-message-status-using-wati-webhooks
- https://www.wati.io/pricing/
