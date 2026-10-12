# CRM operations

Mira Studio uses section/topic dropdowns and topic search.

- Property advisor setup: save the assigned name and email separately for each property. Enable automatic register emails only for the intended site advisor. Properties with no active assignment show Advisor setup required.
- The existing hosted visit worker creates private property/date registers and sends an email per confirmed booking. Further bookings on that property/date appear in the register. Each booking/time/assignment is processed once. A changed appointment receives a new notification; old-date registers no longer show that booking.
- Changing or disabling an assignment revokes existing property registers. Expiry remains seven days after the appointment date. The register shows names and times, excluding customer contacts and feedback.
- Advisor email delivery history distinguishes queued, sending, sent, needs_review and cancelled. Sent means SMTP submission. Uncertain delivery is not automatically retried.
- Team actions: review missing attendance, conflicting reports, assistance, replacement-time approvals and uncertain customer email tasks. Assignment and task completion remain in Customer CRM's customer/deals/tasks workspace.
- Approve a visit: owner confirms access and availability. Already confirmed appointments do not need approval again.
- WhatsApp confirmations: prepare a message with a saved number, check permission, open WhatsApp and press Send there. Record the send in CRM afterward.
- Actual attendance, professional assistance and unresolved factual disputes still require the responsible person. No attendance is inferred from silence.

No advisor assignments or contacts are invented. Until an active assignment is saved, no advisor email is sent. Customer email reminders and feedback continue independently.
