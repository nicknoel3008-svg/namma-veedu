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

Owner approval workflow
-----------------------
Mira Studio now has an Owner review panel with Approve all changes. Use each supported section's Add to owner review button first; unsubmitted form edits are not included. Staged dashboard edits remain in the signed-in browser session and should be approved before signing out. Advisor assignments, visit decisions, customer profiles, leads, deals, tasks, notes, customer outcomes, advisor progress, Mira reviews and learning edits use this review step. Learning rules retain the approval status chosen in the editor.

The hosted workers prepare advisor-register and visit-email queues, but each queued message requires explicit Owner approval before submission. Scheduled general email follow-ups and purchase receipts also require approval. Review recipients in the panel. Changing an advisor revokes old links and cancels queued deliveries to the old assignment; newly prepared messages require fresh review. Approving an assignment alone does not authorize future register sharing.

Only reviewed pending items are approved; future reminders and follow-ups appear when due. Expired visit reminders are skipped by the worker. The worker performs actual email submission after approval. WhatsApp sending still requires pressing Send in WhatsApp. Team access/security changes and customer-submitted responses retain their dedicated controls. Successful items save individually; a failed item remains pending and withholds the batch's email approvals.
