# Zoho CRM connection for Namma Veedu

**Inactive: removed from the project to-do list at the owner's request.** The project now uses its internal CRM. This file is retained only as historical preparation; do not treat the steps below as active work or enable synchronization.

WATI is removed from the active to-do list. The email sender is unchanged.

## Account connection

Install and connect the Zoho CRM integration offered in Codex, using the account and organization that should receive Namma Veedu leads. Complete authorization privately. Never paste passwords, OAuth tokens or client secrets into chat.

Once connected, inspect the organization's Leads module, required fields, field API names and available lead-status values before mapping or uploading records. Do not assume the account uses default fields or the India data center.

The Codex integration permits account work from this chat. It does not itself authenticate the deployed Streamlit application. Persistent website synchronization requires a separate server-side Zoho OAuth configuration using the correct organization and regional Accounts/API domains. That authorization must be completed by the owner. Keep credentials in private local/hosted secrets and never in source control.

## Proposed first integration

Start with explicit owner-selected lead export from Mira Studio to Zoho Leads. Keep Zoho as the sales workspace and Mira Studio as the inquiry and visit source. Do not enable bulk import or background synchronization before validating the mapping with one owner-approved test lead.

| Namma Veedu value | Proposed Zoho destination | Validation needed |
| --- | --- | --- |
| CRM lead ID | Unique custom integration field | Create/identify a unique field and its exact API name |
| Customer name | Required lead name fields | Confirm organization requirements and handling of unnamed conversations |
| Location | City or custom locality field | Confirm field semantics |
| Property type and budget | Custom fields or Description | Confirm types; do not convert free-text budget to invented numeric amounts |
| Conversation ID | Custom reference field | Preserve source linkage |
| Stage | Lead Status, using an explicit mapping | Verify allowed picklist values; exclude incompatible conversion states |
| Assigned advisor | Zoho owner only after identity mapping | A free-text advisor name is not a Zoho user ID |
| Next action and due time | Tasks in a later phase | Confirm task ownership and scheduling requirements |

Do not export chat transcripts, private response links, messaging credentials, or inferred contact details. Existing internal CRM leads contain no dedicated email/phone fields; obtain contact values only from verified source records and establish their relationship to the lead before mapping. Zoho lead status must not enroll customers in messaging or become proof of purchase.

## Reliable website synchronization

Use Zoho's v8 API and OAuth refresh flow. Deduplicate with a unique Namma Veedu lead identifier rather than customer name. Store returned Zoho record IDs and submission status privately. Validate per-record API outcomes rather than treating HTTP success as proof of record creation. Hold ambiguous submissions for reconciliation before retrying. Inspect any Zoho workflows that could send messages on record creation before the first write.

No live Zoho record has been created or modified during connection preparation. No deployed application connection is configured yet.

Official references:
- https://www.zoho.com/crm/developer/docs/api/v8/oauth-overview.html
- https://www.zoho.com/crm/developer/docs/api/v8/refresh.html
- https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html
