# Namma Veedu: from idea to implementation and improvement

**Updated:** 10 October 2026 · **Owner workspace:** Mira Studio

## The idea and intended outcome

Build a Tamil Nadu property guide where people can explain their needs in English or Tamil, refine choices naturally, understand saved records and save a follow-up directly with Mira. Give the owner a private workspace to review conversations, feedback, outcomes and improvements.

The intended outcome is a useful shortlist and a clear next step. Saved records do not establish current availability. A project reference is not a confirmed unit for sale, and an approval reference is not a sale listing.

## Customer options, implementation and results

| Original need | What we implemented and the options offered | Result and boundary |
| --- | --- | --- |
| A consistent identity | Namma Veedu branding and Mira welcome | Product name matches the public link |
| A welcoming conversation | English or Tamil choice, Tanglish conversation support, feedback introduction | Language changes retain pending preferences and follow-up details |
| Search naturally | Location, multiple property types, BHK, budget, size and multiple listing categories; sidebar controls | Add, replace or cancel individual preferences while retaining the others |
| Include auctions optionally | Mira asks whether to explore auctions alongside sales; decline, auctions only and cancellation supported | Ended auctions hidden by default; undated records require explicit consent and remain unverified historical records |
| Browse every match | Complete result set, five cards per page, numbered pages; current-page map when configured | New searches reset pagination; chat shortlist and full main-page results serve different purposes |
| Understand no matches | Checks identify blocking location, type, category, BHK, budget, size or required details; counts and recorded price context where available | Unknown source details stay unverified; no silent relaxation of preferences |
| Understand a listing | Selected-property references, comparisons, recorded amenities, source links and verification guidance | No invented floor, facing, contact, price or availability claims |
| Explore finance and measurements | Area/price conversion, illustrative EMI and official lender links | Available own funds are separate from the purchase ceiling; calculations do not establish loan approval |
| Save a follow-up in chat | Collect details and save an in-app reminder or explicitly consented email request; form also available | “Follow-up saved” popup follows successful persistence; failed saves must not claim success |
| Share a problem or suggestion | Share feedback during or after chat, category/comment, saved confirmation and reply linkage | Feedback appears in owner reports and creates an inactive learning draft |
| Finish or restart | End chat, satisfaction rating and Start a new conversation | Completion recorded; new conversation clears prior preferences |

The action row includes Find a home, Explore auctions, Set my preferences, Auction guidance, Loans, Area & price, Sources and Follow-up. Selecting an information action again hides its panel.

## How we implemented the conversation

1. **Receive and normalize:** read the message, language and conversation; normalize known spelling errors and detect intent, references, corrections and follow-up details.
2. **Retain preferences:** keep active requirements, multiple selections, rejected records, the selected property and available funds separately. Change the requested field without resetting the conversation.
3. **Choose an action:** handle greetings, language, explanations, safety and follow-ups locally. Ask one useful question when needed; search when requested with usable criteria.
4. **Route safely:** query the saved property/auction catalogue, CMDA references, official source directory and calculators. Hosted reasoning receives bounded context and approved guidance when configured.
5. **Validate facts:** enforce filters and required details, exclude ineligible auctions, distinguish missing values and starting prices, and rank matches. Explain the actual blockers when no records remain.
6. **Respond and save:** give a grounded answer and next step, update complete results and save conversation signals or requested actions. Confirm an action only after its save succeeds.
7. **Recover:** local supported flows handle provider timeouts, rate limits and authentication failures. A configured database failure is reported rather than silently creating separate local records.

Key modules: `conversation_engine.py`, `conversation_memory.py`, `mira_understanding.py`, `buyer_memory.py`, `property_search.py`, `agent_runtime.py`, `chat_followup.py`, `followup_service.py`, `inquiry_log.py`, `mira_feedback.py`, `mira_learning_library.py`, `storage_backend.py` and the Streamlit interface in `app.py`.

## Shared records and owner dashboard

Localhost and the public app use the same Supabase PostgreSQL database when configured with the same private `DATABASE_URL`. Conversation records, feedback and learning approval decisions are shared. The configured database is authoritative; connection failure does not silently switch to local files.

Legacy workbook/library records can be imported without duplicating existing IDs or overwriting cloud review decisions. Historical data appears only if persisted and migrated; connecting storage cannot recover records that were never saved. Property source data remains the curated saved catalogue.

Mira Studio is password protected on localhost and the public website when configured. It includes customer summaries, conversations, follow-up descriptions and schedules, feedback, Quality Review, Learning Library, date filters and downloadable reports. Shared inquiry timestamps determine automatic snapshot dates in India time when Studio loads; older file archives remain a fallback.

Inquiry exports include feedback and follow-up details. Complete-chat exports retain feedback alongside conversations. Identity-number patterns are redacted before persistence. This blueprint contains no customer chats or credentials.

## The eight effective KPIs

| KPI | Purpose |
| --- | --- |
| Conversations | Conversations in the selected period |
| Unique user sessions | Distinct saved user/session identifiers, not verified unique people |
| Follow-ups open | Conversations needing a saved or owner-marked follow-up; counted once per conversation |
| Feedback received | Saved feedback submissions |
| Confirmed interested leads | Conversations owner-marked interested; not completed sales |
| Search match rate | Share of conversations with recorded searches finding at least one match |
| Follow-ups completed | Conversations with completed follow-up outcomes |
| Mira rating | Latest customer rating of Mira performance per rated conversation, averaged out of five; unrated and invalid values excluded |

All use the selected date range. Extra catalogue counts and outcome breakdowns belong in charts/tables. No searches and no ratings are shown as absent activity rather than misleading zeros.

## Mira learning and owner approval

1. **Capture evidence:** feedback submissions and saved signals such as corrections, frustration and missed requests.
2. **Review context:** Studio links feedback to the conversation and relevant reply; Quality Review groups recurring issues.
3. **Create a draft:** feedback and repeated quality cues create Learning Library drafts with stable source IDs. Refresh preserves existing review decisions.
4. **Owner decision:** edit the scenario/guidance and approve or reject it. Draft and rejected rules are inactive.
5. **Apply approved guidance:** only approved rules enter bounded hosted reasoning guidance. This is reviewed prompt guidance, not automatic training of model weights. Deterministic search and safety behavior still depends on code.
6. **Fix and test:** issues requiring implementation changes become code fixes with regression and complete website journeys.
7. **Release and measure:** publish verified changes, check public behavior and review later feedback, search outcomes, follow-ups and satisfaction. New evidence starts the loop again.

## Delivery stages and observable outcomes

| Stage | Delivered capability | Evidence to inspect |
| --- | --- | --- |
| Idea to first product | Search, source links and Mira chat | Matching records and sources |
| Conversation to action | Preference memory, follow-ups, completion and ratings | Retained filters, confirmations and saved rows |
| Owner visibility | Studio, reports, summaries and eight KPIs | Password gate and consistent report totals |
| Feedback to improvement | Feedback, quality cues and approval-controlled learning | Linked draft, review status and active approved guidance |
| Local to shared service | Supabase records shared across deployments | Same persisted IDs and decisions |
| Better conversation continuity | Multiple preferences, auction opt-in, property loan context, no-match explanations and pagination | Regression fixtures and user journeys |

These are delivered behaviors and verification points, not a claim of real-world property or commercial success.

## Operational dependencies and current boundaries

- Hosted reasoning needs configured provider credentials; local supported flows remain available without it.
- In-app reminders depend on an active browser session. The email delivery queue has a separate SQLite/worker dependency; shared reporting does not make that queue a shared email service.
- Email requests may be saved while delivery is disabled. Sending needs SMTP, public URL and an active worker. Saved does not mean sent or promise advisor contact.
- Maps need a configured map token; recorded search results and source links work without maps.
- Studio refreshes shared snapshots on load, not continuously in an already open view.
- Tests exercise isolated records and mocked provider responses. Real database, provider and public browser checks are separate verification steps.
- GitHub main deploys to Streamlit. Verify public behavior after each release; restart the host if it retains stale imported modules.

## Complete release test checklist

Welcome/language; searches and corrections; multiple types; auction inclusion/removal; no-match recovery; pagination; listing details, calculations and loan continuity; follow-up save/popup/failure/cancellation; feedback and linked learning draft; approval/rejection and reports; eight KPIs, snapshots and exports; privacy redaction; storage errors; provider fallback; dashboard performance; and public startup/chat after deployment.

Update this document and its connected flowchart when behavior changes. Studio displays both and provides this complete blueprint for download.
