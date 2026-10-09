# Namma Veedu — website and Mira QA findings

Stopped at the user's request after cycle 23 completed. **All 129 tests passed in 182.746 seconds.** No repeating QA process or isolated QA preview server remains running.

Final local timing sample: customer dashboard load **1.238s**, filter update **1.254s**, panels **1.551–1.714s**, follow-up save-to-popup **2.586s**, empty-result response **0.915s**, filter recovery **1.321s**. Owner dashboard with empty inquiry/rule fixtures loaded in **0.774s**. No sampled operation exceeded the five-second investigation threshold.

## Product bugs found and fixed

| Bug noticed | Fix |
| --- | --- |
| Mira redirected follow-up requests to a form instead of completing them. | Collect missing details in chat and save the requested browser reminder or explicitly consented email request. |
| A success popup disappeared during the chat rerun. | Queue the notification until the final render. Show “Follow-up saved” only after a successful save, with Tamil localization. |
| Email follow-ups could reference the wrong conversation. | Use the current inquiry conversation ID for the saved follow-up. |
| Normal “share these results” requests could start email setup. | Require explicit email intent; collect the address and consent before saving an email request. |
| Follow-up corrections could retain an earlier day or time, and 24-hour times were not handled correctly. | Use the latest supplied day/time, accept 24-hour time, and roll an already-passed weekday time to the following week. |
| Out-of-range relative reminder dates could crash setup. | Catch invalid/overflowing dates and request a valid date without saving. |
| Pending follow-up setup could block a new property search. | Recognize the new search, clear pending setup, and resume the search. |
| Completing/removing reminders could leave stale schedule metadata or update another reminder with the same due time. | Link schedule changes to the reminder ID, clear the next due time, and record Completed/Removed status. |
| Chat cancellation did not remove the saved reminder. | Cancel the latest applicable saved reminder and confirm cancellation in chat. |
| Privacy redaction could corrupt generated conversation UUIDs by treating their digit groups as Aadhaar numbers. | Tighten redaction boundaries; preserve generated IDs while retaining Aadhaar/PAN redaction. |
| Task commands and language choices could be stored as customer names. | Exclude commands and English/Tamil choices from inferred bare names; keep explicit voluntary names supported. |
| Discussing an advance/deposit could overwrite the purchase budget. | Preserve the remembered purchase budget unless the user explicitly changes it. |
| Buying-process and emotional-support questions could receive a generic preference acknowledgement. | Prioritize the relevant guidance before generic preference handling. |
| Sidebar filter synchronization could overwrite auction chat results. | Preserve the pending Mira search/filter synchronization when applying sidebar state. |
| “Not helpful” could be counted as appreciation. | Exclude negative helpfulness feedback from appreciation detection. |
| Live model responses made unsupported leasehold assumptions or returned unrelated listings for ownership explanations. | Add grounded ownership education, clarify lease-specific terms, and block unsolicited listing tool calls for ownership questions. Explicit listing requests still search. |
| Fixed/floating loan explanations could imply an unconditional fixed rate or certainty about cost. | Explain agreed fixed periods/reset clauses and possible EMI/tenure changes without guaranteeing the cheaper option. |
| Sidebar and conversation language could diverge. | Synchronize language memory and UI when English/Tamil is selected in chat or the sidebar; preserve pending follow-up details. |

## Requested experience changes completed

- Replaced the generic greeting with a welcome introducing Mira as the AI property guide.
- Updated visible branding to **Namma Veedu**, including page title, logo, watermark, email templates, Mira policies/greetings and export filenames.
- Mira asks whether the user prefers English or Tamil. Direct answers and phrases such as “I prefer English” update the language.
- Replaced blueprint cards with a connected SVG flowchart in Mira Studio; the written blueprint remains downloadable.
- Added recurring user-dashboard and owner-dashboard performance measurements, empty-result/count checks, filter recovery, panel navigation, and checks against duplicate reminders/popups on rerun.

## Verification and scope

- Full suites run in fresh processes with shuffled order. Browser checks verify visible branding, language switching, follow-up save popup, cancellation and the owner flowchart.
- Storage integration uses real temporary SQLite and Excel files to verify consent, persistence, conversation metadata and cancellation on the customer's return.
- Mixed Tamil/Tanglish conversation replay completed all 20 turns without app exceptions. Configured-site replays and mocked provider tool-boundary tests check reasoning routes and failures.
- Customer-dashboard timing samples cover initial load, filtering, panels, save-to-popup, reruns, empty results and recovery. Owner-dashboard timings use empty inquiry/rule fixtures. Detailed logs are under `data/private/continuous_qa/`.
- Timings measure local Streamlit test execution. They do not establish deployed network latency, browser paint performance or concurrent-user capacity. Cold and warm caches can differ.
- No SMTP email was sent by QA. Browser reminders remain scoped to the browser session. Email requests may be saved pending activation when delivery is off.
- Changes are in the workspace and local previews; no commit, push or deployment was performed in this QA session.

## Test-harness issues distinguished from product bugs

## Feedback follow-up

Implemented Share feedback in English/Tamil, reports and owner-reviewed learning drafts. Extended the UUID-preserving identity-redaction fix to hosted record handling. Six feedback tests and two full shuffled 135-test runs passed; the second run took 194.832 seconds. Browser QA confirmed save success. No additional product bugs were found in these final runs. Testing stopped after the second run at the user's request. See TEST_REPORT.md for scope and dashboard timings.

- Corrected an isolated chat-ending fixture missing its preference-clearing dependency.
- Corrected an incomplete search inventory fixture and Streamlit's image-element assertion.
- Refreshed the isolated browser server when imported modules became stale.
- Earlier host pauses caused test timeouts; subsequent fresh runs passed. Existing Streamlit deprecation notices remain and did not fail the final focused checks.
