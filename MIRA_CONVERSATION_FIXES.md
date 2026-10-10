# Mira conversation and dashboard fixes — 10 October 2026

- Correcting “ignore Porur; show Chennai” now retains Chennai through both conversation and search handlers.
- Requests about displayed properties, suggestions, result totals, and pausing receive contextual responses rather than repeating the preference prompt.
- Mira asks once whether to include auction properties. Yes includes auctions alongside sales; no excludes auctions. Users can subsequently request auctions only or cancel them.
- Multiple property types can be selected together, added, and individually removed without discarding the remaining budget, area, or other preferences. Cancelled filters are cleared from the website controls as well as chat memory.
- Moving to a new city clears an inherited auction-only search unless the customer explicitly requests auctions again.
- The owner dashboard has eight primary KPIs: conversations, user sessions, open follow-ups, feedback received, confirmed interested leads, search match rate, completed follow-ups, and average customer satisfaction. Detailed outcomes remain available in charts, tables, and exports.
- Open follow-ups include saved Mira schedules and owner-marked actions, counted once per conversation. Cancelled or completed schedules do not remain open unless the owner explicitly marks another action needed.
- Follow-up descriptions are included in newly saved records, customer summaries, and exports, alongside the method, status, cadence, and next scheduled time.

Shared-storage inspection confirmed existing follow-up schedule records were present; the previous open-follow-up KPI counted only manually maintained owner statuses. Email requests saved while delivery is disabled remain reviewable but do not send email. In-app reminders remain browser-session notifications.

## Latest Tambaram conversation and result browsing

- Main results retain the complete matching set and display five cards per page with numbered page choices. A changed search or listing category resets pagination to page one. Explicitly accepted undated auction records remain accessible as historical records.
- “Auction properties?” (including the observed “auctiom” typo) explains the auction process and retains the requested area instead of searching the whole catalogue.
- Old undated-auction confirmations expire when the conversation moves on. Source-guidance confirmations are handled before generic property details.
- A selected property's loan-options request retains the property and distinguishes available own funds from a maximum purchase price. The response gives an illustrative arithmetic difference, official lender links, and a useful next question without promising finance.
- Automatic snapshot dates and exports are rebuilt from shared inquiry records in India time when Studio loads. This avoids relying on stale machine-local archive files after migration to Supabase.
