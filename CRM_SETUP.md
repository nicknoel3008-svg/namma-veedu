# Namma Veedu CRM

Open Mira Studio after signing in and expand **Customer relationship management (CRM)**. Click **Load / refresh CRM** to import one lead per recorded conversation. Refresh is idempotent and preserves advisor edits. Separate conversations remain separate leads; names and phone numbers are not used to merge identities.

Search by customer, location or assigned advisor. Filter the pipeline or choose **Show actions due**. Open a lead to record stage, priority, assigned advisor, next action and its date/time in IST. Add notes and review activity history or linked visit records. An action date is an internal work reminder visible in the CRM; it does not send a customer message or create a calendar appointment.

Stages: New, Contacted, Qualified, Visit planned, Negotiating, Closed won, Closed lost. These are manual CRM records. Closed won does not create a verified purchase outcome; continue using the existing purchase verification workflow. Assignments are labels, not new access grants. Existing authenticated Studio users can manage leads.

The CRM uses the existing shared PostgreSQL database when configured, otherwise the private local queue database. Shared CRM tables enable row-level security for the public API. Database credentials stay server-side. No external CRM subscription is required. Local SQLite leads are not automatically migrated to shared storage.

Import captures customer name, location, property type and budget at first import. Refresh discovers new conversations without overwriting existing leads. CRM history records workflow edits and notes. Concurrent stale edits are rejected; refresh before retrying. CRM stages and notes never enroll a customer in email or WhatsApp messaging.

WATI is removed from the active to-do list. Existing messaging settings and email sender remain unchanged. CRM changes must be deployed to the hosted app before appearing there. Hosted PostgreSQL validation is still required before release.

## Customer-to-purchase workflow

1. Customers request their preferred property visit using **Book a slot**. The owner checks availability and approves the slot in existing visit management.
2. For confirmed visits with separate email consent, the email worker processes confirmation, a reminder due one hour before the visit, and feedback due two hours afterward. A confirmation submitted during the final hour also serves as the reminder. The worker must be configured and running; delivery at an exact minute is not guaranteed. WhatsApp activation remains on hold.
3. Customer feedback records actual attendance separately from advance attendance confirmation. CRM labels are Visited, Did not visit, Awaiting response, and Not yet due. Missing feedback is never counted as attendance or rejection.
4. Customers answer property satisfaction and purchase interest independently. Declines require a reason. They can request property-agent or loan assistance with details and consent, or return to Mira with revised preferences and permission. Existing private response links and return-to-Mira flow handle this; WhatsApp replies are not automatically processed.
5. **Linked visits and customer journey** shows the current booking state, attendance, satisfaction, interest, decline reason, requested assistance, advisor progress, revised preferences, next step and reminder due time. Reload the CRM to discover new visits and conversations; visit-only conversations are imported too. Older unlinked visits remain in the existing visit-management view rather than being attached by name.
6. Readiness uses explicit customer evidence: High interest requires reported attendance, satisfaction and purchase interest. Declining one property is not treated as declining all purchases. Customer-reported purchase and owner-recorded purchase remain separate. The readiness level is provisional and has no calibrated probability.

## Sales workspace

Use **Add customer manually** for non-chat leads. Manual leads have no conversation identity and are never automatically merged by name. Under a selected lead, choose **Open customer, deals and tasks workspace**:

- Customer profile: name, email, international phone, preferred location, property type, stated budget and source.
- Property deals: title, property reference/link, INR amount, sales stage, advisor, expected close date and required loss reason for lost deals.
- Advisor tasks: title, advisor, IST due time, priority, and Open/In progress/Completed/Cancelled status.
- Reports and exports: open-deal count, total open pipeline value, team-recorded won value, closed-deal win rate, team tasks due and CSV downloads. Values are INR; no currency conversion or weighted forecast is inferred. Win rate is Won / (Won + Lost); it is not purchase probability.

All Studio users with existing authenticated access can manage this shared workspace. Advisor assignment is a work label and does not restrict record visibility. Edits record the signed-in Studio identity and reject stale concurrent saves. Notes and edits appear in the customer activity history. Customer messaging consent remains managed by the existing follow-up and visit forms.

Zoho integration is removed from the active plan. The earlier ZOHO_CRM_SETUP.md is historical preparation only; no Zoho synchronization is enabled. WATI account setup and activation are removed from the active to-do list. No automatic messaging is triggered by CRM profile, task or deal changes.

## Free WhatsApp messaging

Use **WhatsApp messages — free manual sending → Prepare WhatsApp messages** under a selected CRM lead. This uses official `wa.me` click-to-chat links and no messaging API or provider subscription. Enter the customer's international WhatsApp number, review/edit the draft and confirm the customer agreed to the messages. **Open WhatsApp — review and send** opens the chat; the advisor must press Send there.

General follow-ups are available for leads with a verified number and permission. The selected flow uses a manually sent WhatsApp confirmation plus automated emails: collect the separate follow-up email and email consent on booking. These bookings offer only the WhatsApp confirmation draft; the email worker handles the reminder, feedback request, and one response-based follow-up. WATI is outside the active plan. Other bookings retain manual reminder/feedback drafts. Cancelled, requested and customer-reported purchased visits are excluded. When a visit's booking contact is WhatsApp its number is prefilled; email addresses are never treated as phone numbers.

The CRM shows visits within the final hour in a reminder-due list when the page is loaded or rerun. It is an on-screen worklist, not a background alarm or automatic send. Refresh the CRM near the due time. Reminder messages remain editable before the visit; post-visit reminders are blocked.

After actually pressing Send in WhatsApp, the advisor may check the send declaration and **Record manually sent message**. This adds an advisor-reported entry to CRM history. Opening a chat never records a send, and no delivery/read status is inferred. A recorded send does not suppress the due list; the list reflects the visit time so the team must review history before sending again.

Where a valid public portal URL is configured, visit drafts include the existing private response link. Customer submissions through that link update the visit record and CRM/Mira Studio. Ordinary WhatsApp replies do not update the database automatically; the team must review them and guide the customer to the response page. No customer message is sent by the app itself. WATI/API setup and activation are outside the active plan.
