# Namma Veedu — Tamil Nadu Property Guide

**Your next address starts with a better question.**

A chat-first, local Streamlit starter for finding plots, houses and flats in Tamil Nadu, including saved bank-auction records, existing sale listings and project references. It works from local CSV files and does not need a paid listing API.

## What’s included

- Conversational search for city/locality, property type, budget and size, with English/Tamil preference and common Tamil/Tanglish terms.
- Follow-up search context so short requests can refine the previous location, type and budget.
- Optional chat starters for people who are exploring, unsure where to begin, or ready to search; the guide asks for one missing detail at a time and shows up to three chat recommendations.
- Short, empathetic responses to price or location concerns, plus a clear explanation when live human handoff is not available.
- Curated conversation libraries for greetings, empathy, dissatisfaction recovery, price pushback, factual boundaries, clarification and closing. These guide the offline response patterns and optional API few-shot examples; they do not retrain model weights or add API use.
- Separate property search, BAANKNET auction and home-loan areas.
- Illustrative EMI calculation from a user-entered rate, plus official lender links; no rate or approval is invented.
- Sidebar filters and a browsable results list.
- Area conversion among square feet, square metres, cents, acres and grounds.
- Price per square metre when both price and a supported area unit are available.
- Auction date, EMD and possession fields when present in the user-provided source.
- Official auction and bank loan links in `data/sources.csv`.
- Source name, source date, import date and confidence notes on every result.
- Optional OpenAI-powered agent that can call a short allowlist of local property, auction, CMDA, loan-link, area-conversion and EMI tools.
- In-app follow-up reminders that require confirmation and remain scoped to the current browser session.
- The importer deliberately omits borrower/owner names, borrower addresses, bank branch addresses, images and raw scraped text.

## Data and trust labels

`data/properties.csv` is a sanitized normalized copy of records from the local **TN Properties** folder. It includes saved auction and sale records, VGN and StepsStone verified project references, Wisdom project estimates and CMDA approval-register entries. The user’s original files remain unchanged. See [data/schema-reconciliation.md](data/schema-reconciliation.md) for the sheet-by-sheet mapping and record counts.

These files are snapshots. The app does not claim that an auction or sale listing is still open, that a title is clear, or that a loan is approved. Open the source and current bank notice before relying on any detail. Existing sale advertisements do not independently prove a property's ownership history. Project directory records are not offers for a specific available unit. Missing values stay blank; price per square metre is not guessed.

## Setup on Windows

1. Install Python 3.11 or newer if it is not already installed.
2. Open Command Prompt and move into this project folder:

   ```cmd
   cd "C:\Users\nickn\Documents\Codex\2026-10-07\referenced-chatgpt-conversation-this-is-an\property_finder_agent"
   ```

3. Create and activate a virtual environment:

   ```cmd
   py -m venv .venv
   .venv\Scripts\activate.bat
   ```

4. Install the small set of dependencies:

   ```cmd
   python -m pip install -r requirements.txt
   ```

5. Start the app:

   ```cmd
   streamlit run app.py
   ```

Streamlit opens the page in your browser, usually at `http://localhost:8501`.

## Enable Mira with Groq Free Plan

Mira defaults to Groq, using `openai/gpt-oss-20b` hosted by Groq. The OpenAI
Python library is only the compatible client; Groq requests do not use OpenAI
credits. Stay on Groq's Free Plan for this zero-budget project. Free quotas can
change: https://console.groq.com/docs/rate-limits.

Create a Groq API key at https://console.groq.com/keys. From this project folder
in **CMD**, open your existing secrets file (do not overwrite it):

```cmd
notepad .streamlit\secrets.toml
```

Add or update these settings, each once, and keep existing owner/email settings:

```toml
AI_PROVIDER = "groq"
GROQ_API_KEY = "your-private-groq-key"
GROQ_MODEL = "openai/gpt-oss-20b"
```

Save, stop Streamlit with Ctrl+C, then run:

```cmd
.venv\Scripts\python.exe -m streamlit run app.py
```

Refresh the browser. The chat shows **Mira AI · Groq** when a key is configured;
this label does not by itself verify the key. Try a greeting and a property
search. Missing keys and failed requests use the offline helper. After a Groq
rate limit, a new message can retry after 60 seconds; daily limits may last
longer. There is no automatic switch to OpenAI or another paid provider.
Recent conversation, preferences and matching record snippets go to Groq;
the full property file is not uploaded. Never paste a key into chat or commit it.

## Optional legacy OpenAI agent

Email follow-ups are separate from Groq and advisor callback requests. They need
private SMTP sender settings and a shared app URL so recipients can stop emails.
See the commented settings in `.streamlit/secrets.toml.example`; add your actual
values only to `.streamlit/secrets.toml`. In CMD, validate without sending:

```cmd
.venv\Scripts\python.exe run_followup_worker.py --check
```

The check does not authenticate SMTP or send mail. Users can save an email
follow-up request and consent for owner review while delivery is off; those
records are marked `Saved (email delivery off)` and are never picked up by the
worker. If delivery is enabled later, Windows Task Scheduler must run
`run_followup_worker.py` regularly while the computer is on and connected.
Starting Streamlit alone does not run the email worker. Consented delivery
sequences begin at the next three-day boundary; they do not send immediately.
Saving an advisor callback request with an email contact only records that
request for owner review; it does not create an automated email sequence.

This provider requires explicitly setting `AI_PROVIDER = "openai"` and is not
the recommended setup for the zero-budget project.

The chat continues to use the local phrase-based helper until an API key is configured. OpenAI API usage is billed separately from a ChatGPT subscription. To enable the tool-using agent:

1. Create an API key in your OpenAI developer account. Do not paste the key into chat or add it to source code.
2. In Command Prompt, from this project folder, run:

   ```cmd
   copy .streamlit\secrets.toml.example .streamlit\secrets.toml
   notepad .streamlit\secrets.toml
   ```

3. Replace the placeholder key in `secrets.toml`, save the file, and restart Streamlit.

The actual `secrets.toml` is excluded by `.gitignore`; keep it on your computer and out of any shared repository. When AI is enabled, the user's message and only the matching record snippets needed for the answer are sent to OpenAI for processing. The full property CSV is not uploaded as a file. The agent has no email or calendar connection in this stage.

The selected model defaults to `gpt-5.6-luna`; you can change `OPENAI_MODEL` in the same TOML file if your API project uses a different available model.

## Open the owner dashboard

The live dashboard tab is shown only after owner sign-in. To configure it, open the private `.streamlit/secrets.toml` file in a local editor and add a separate setting:

```toml
OWNER_DASHBOARD_PASSWORD = "choose-a-long-random-password"
```

Keep this value in Streamlit secrets and out of source code or chat. Restart the app, open it in your browser, and enter the password in the **Owner dashboard sign-in** field in the left sidebar. The **Owner dashboard** tab then appears. Use **Sign out of owner dashboard** in the sidebar when finished. If you deploy the app, add `OWNER_DASHBOARD_PASSWORD` through that host's Streamlit secrets settings rather than committing it to the repository.

Completed chat turns are automatically assigned a unique inquiry ID and saved to `data/private/inquiries.xlsx`, with a conversation ID, timestamp, language, user inquiry, Mira's response, search criteria, matching records or tool results, and recent conversation context. The log adds cautious conversation signals, the customer's exact budget or price wording, purchase or offer wording, property type, location and size when available, and owner-maintained satisfaction, interest, follow-up, lead priority, listing, sale outcome, next-action, and advisor-note fields. Signals inferred from chat are indicators, not verified events; the owner fields record confirmed outcomes. Existing workbooks gain new columns automatically. The password-protected dashboard offers all-time, day, month, and year filters for inquiry KPIs and charts. Its Excel download contains only the selected period and an `Export details` sheet that records the chosen filter, start/end dates, and row count. The chat shows the inquiry ID after Mira's reply. Only a signed-in Owner dashboard session exposes the workbook preview and download button. The private data directory is excluded from Git; back it up securely if the log must survive a machine or deployment change. The Excel workbook is stored on the app host, so a hosted deployment should use persistent private storage if inquiry history must survive redeployments.

## Re-import newer files

Owner dashboard downloads use an `Inquiries` sheet with one structured row per conversation. It shows email follow-up consent, property interest, lack of interest, interest stated, follow-up requests and advisor requests as Yes/No fields, with property type, location, extracted budget and preferred size. A separate owner-only `Mira responses` sheet records each reply with its timestamp and response type, without including the customer's raw message. No means no recorded evidence; both interest fields are No when interest is unstated. Email follow-ups indicates recorded consent, not successful email delivery. Older automatic snapshots are converted to this format when downloaded. The private source log remains available for the application's existing analytics and outcome tracking.

Ending a chat hides and clears the browser's conversation messages and agent history after recording its completion. The customer sees only the ended notice and the option to start a fresh conversation.

Put updated files in `C:\Users\nickn\OneDrive\Documents\TN Properties`, then run:

```cmd
python import_data.py
```

For a different folder:

```powershell
python import_data.py --source-dir "D:\My Property Data"
```

The importer rewrites only this project's `data/properties.csv`; it never writes back to the OneDrive source folder.

## Try the chat

Mira also keeps a session buyer profile with hard search requirements, amenity
preferences, rejected listing IDs, a selected property, and recent corrections.
After results, try “the second one”, “does that have parking?”, “compare these”,
or “skip the second one”. Rejected listings are excluded from future chat searches;
“reconsider the second one” can restore one while that shortlist is still shown.
New shortlists clear ambiguous selections; starting a new conversation clears
the buyer profile and results. No profile is automatically restored next session.

Local meaning-based matching maps phrases such as “fitness centre” to gym and
“elevator” to lift in recorded amenities. Ordinary preferences rank results;
explicit “must have” amenities require positive source evidence. Missing amenities
are unknown, not absent. This is an explainable synonym matcher, not an embedding
service or independent verification. Chat search tools enforce remembered budget,
BHK, location and size before querying. Search recommendation text is built from
returned record fields so unsupported model claims do not become recommendations.
Other free-form AI answers still depend on model behavior and the existing policies.

Mira keeps explicit location, BHK, property type, budget and size preferences within
the browser conversation. Corrections such as “actually I can do 70 lakh” update
the budget while retaining the other preferences. “Any area”, “no budget cap” and
“any BHK” remove the respective constraint; “start over” resets search preferences.
Specific saved localities take priority over a city mentioned in the same sentence.
School, quietness and commute questions retain search context, but these facts are
not verified by the saved inventory. With a working API key, ordinary conversation
goes to the AI instead of the general canned dialogue handlers, with up to 24 recent
messages plus the structured search preferences. Without it, the local helper remains
available. This update does not add live inventory or memory across browser sessions.

- “Show me plots in Chennai under ₹30 lakh”
- “Find upcoming house auctions in Coimbatore”
- “Show resale flats under ₹60 lakh”
- “What’s the largest plot?”
- “Which banks offer a home loan?”
- “Convert 1,200 sq ft to square metres”

Use **Browse listings** for exact filters. Use **Area & price tool** to calculate an indicative rate from entered figures. Use **Auctions, loans & sources** to open official source pages.

## How to interpret the data

- **Auction** — the saved source marked an auction available and its end date has not passed as of import. Recheck the official notice.
- **Auction ended** — kept as a historical record; hidden from normal search unless enabled.
- **Existing sale** — a saved advertisement, not an independently verified ownership-history claim.
- **Project reference** — project-level information, not proof of an individually available property.
- **Approval record** — planning register entry, not a property offer or availability claim.
- **Approx. price / m²** — derived as saved asking/reserve price divided by saved land/advertised area converted to square metres; it is not a sale valuation.
- **Grounds** — conversion uses the common Tamil Nadu convention of 2,400 square feet per ground. Check the relevant deed/local convention.

Without an API key, the app uses a small local phrase parser. With a key, the OpenAI model can choose among the app's allowlisted functions; the application validates and executes those functions. The model cannot directly access files or run arbitrary code. Email delivery remains off unless SMTP and a worker are explicitly configured; email follow-up requests can still be saved for review. Reminder entries last only while the current browser session remains active; this stage does not send background notifications.

## Share with peers

For email/WhatsApp follow-ups, shared queues and property visit requests, see [Follow-up and visit setup](FOLLOWUP_CHANNELS_SETUP.md).

`localhost:8501` is only reachable from this computer. To create a peer-accessible URL, publish the project through a hosting service such as Streamlit Community Cloud, which deploys from a GitHub repository and assigns the app a shareable URL. Keep the repository and app private by default, then invite only the intended viewers. Making the app public can make it searchable on the web, and the bundled property records would be available to anyone who can view the app.

Before publishing, include only this app, its sanitized `data/properties.csv`, `data/sources.csv`, and the files under `assets/`. Do not upload the original workbooks or the `.venv` folder. Deployment instructions are in the [official Streamlit guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy); sharing and visibility options are in [Share your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app).
