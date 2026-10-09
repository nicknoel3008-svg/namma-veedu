# Namma Veedu website blueprint

**Current version:** 2026-10-09 · **Product workspace:** Mira Studio

This private blueprint explains how the property assistant is assembled. It is a readable product map, not a copy of customer data or a place for secrets.

## 1. Customer experience

1. The Streamlit page loads the Namma Veedu brand, property filters, eight quick actions, and Mira's chat panel.
2. Customers can search saved property and auction records by location, property type, listing kind, budget, size, and BHK.
3. Quick actions show results directly below the action row and hide their result when selected again.
4. Mira keeps the active conversation, matches the customer's language and tone, explains listings, handles corrections, and offers safe follow-up choices.
5. Ending a chat saves its completion state and offers a five-star performance and satisfaction rating.

## 2. Mira's reasoning flow

1. Normalize the user's message and detect language, intent, emotion, preferences, safety concerns, and follow-up requests.
2. Use the local conversation engine for common property, safety, correction, appreciation, and support flows.
3. Search the curated property and source datasets when the request needs records.
4. Use the configured AI provider only with bounded context, approved guidance, and privacy reminders.
5. Return a clear answer with limitations, sources, and a practical next step; never invent availability, guarantees, or private contact details.

## 3. Owner improvement loop

1. Each completed turn can be saved with structured signals, Mira's response, rating, and conversation status.
2. Quality Review groups recurring cues such as missed intent, frustration, unaddressed email requests, and preference corrections.
3. Repeated cues create Draft Learning Library rules.
4. The owner edits and approves a rule; only Approved rules guide future replies.
5. Chat exports and the Learning Library can be reviewed before a new release.

## 4. Data and deployment

- Local development uses the private Excel workbook and JSON Learning Library.
- Hosted deployments can use PostgreSQL/Supabase through the private `DATABASE_URL` secret.
- Aadhaar and PAN patterns are redacted before persistence.
- The owner workspace is local-only and password-gated; public customers never see it.
- The public Streamlit deployment is built from the GitHub repository and can be opened without the owner's CMD window.

## 5. Milestones

- **Step 1:** Property search, saved sources, and the first Mira chat experience.
- **Step 2:** Structured customer signals, follow-ups, chat ending, and Excel exports.
- **Step 3:** Responsive layout, quick actions, correction handling, and customer ratings.
- **Step 4:** Quality Review and owner-approved Learning Library.
- **Step 5:** Mira Studio rename, persistent-storage adapter, migration and health-check commands.

## Keeping this blueprint current

### Customer feedback and reviewed learning

Mira's English and Tamil welcome introduces Share feedback. Customers can submit a category and comment during or after a conversation and receive a saved confirmation. Each submission keeps its conversation ID, language and relevant Mira reply, with identity-number redaction.

Mira Studio shows submissions for review. Inquiry exports include a Customer feedback sheet and customer-summary counts; complete-chat exports include feedback alongside the conversation. Each submission also creates an inactive Learning Library Draft linked by feedback ID. The owner can edit, approve or reject it. Customer comments never become active guidance automatically, and existing review decisions survive draft refreshes.

When a product or architecture change is made, update the relevant section and the current version date in this file in the same commit. The private Mira Studio section reads this file directly and provides a download for the latest approved copy.

## Activation checklist

- **Hosted Mira reasoning:** add `GROQ_API_KEY` and (optionally) `GROQ_MODEL` in Streamlit Secrets. Mira retries rate limits briefly and falls back to the local assistant when the provider is unavailable.
- **Hosted persistence:** add `DATABASE_URL` in Streamlit Secrets, then run the read-only storage health check after migration. The app falls back safely to local files until configured.
- **Email follow-ups:** customers can save an email follow-up request and consent for review without sending anything. Delivery remains disabled until the owner explicitly configures SMTP and a worker.

- Mira collects follow-up details in chat and saves requested in-app reminders or explicitly opted-in email requests without requiring the Follow-ups form.
- A successful follow-up save queues a “Follow-up saved” popup, displayed after the chat rerun so the confirmation remains visible. Tamil uses a localized confirmation.
- The public brand is Namma Veedu. Mira asks for English or Tamil in the welcome message; a direct language choice updates the website and conversation language without clearing pending follow-up details.
- Mira Studio displays the blueprint as a connected SVG flowchart covering language choice, intent branches, follow-up saving, conversation records, quality review and owner-approved learning. The written blueprint remains available to download.
- Conversation checks preserve a buyer’s budget when discussing advance payments and prioritize buying-process or emotional-support questions over generic preference acknowledgements. Mira’s filter syncing preserves chat search results, including auction results.
