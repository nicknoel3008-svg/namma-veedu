# Mira and website regression checks — 9 October 2026

Validation completed locally using the project's existing Python environment.

## Customer feedback implementation and final two runs

Added English/Tamil Share feedback, save confirmation, conversation/reply links, dashboard review, feedback export sheet, complete-chat feedback, and customer-summary counts. Each submission produces an inactive Learning Library Draft; owner edits and Approved/Rejected decisions are preserved. Customer text is never automatically activated as learning guidance.

- Six focused feedback tests passed, covering real temporary-file persistence, validation, failed storage, rerun duplication, Tamil after chat ends, reports and approval gating.
- Full shuffled run 24: **135 passed in 198.715 seconds**.
- Full shuffled run 25: **135 passed in 194.832 seconds**. Testing stopped after this second run as requested.
- Browser QA confirmed the visible saved-for-review message and closed form after submission.
- Final dashboard timings: load 1.068s; filter 1.524s; information panels 1.578–1.702s; follow-up save-to-popup 2.409s; empty-results recovery 1.319s. No measured operation exceeded five seconds. These are local AppTest timings with offline Mira and mocked external writes, not public deployment latency.

The feedback work also corrected hosted record redaction boundaries so generated conversation UUIDs remain intact while identity numbers are redacted. A test fixture's learning-library save signature was corrected during development. No further product failures occurred in the two full runs. Existing Streamlit deprecation notices remain. Changes are local and have not been deployed; provider responses and SMTP delivery were not exercised by these isolated tests.

- Full regression suite: 89 tests passed.
- Follow-up suite, including two additional Streamlit website integration tests: 8 tests passed. The six parser tests also ran in the full suite, giving 91 distinct passing tests overall.
- Local website loaded at http://127.0.0.1:8502 and its initial layout and controls were inspected in a browser.
- Git whitespace checks passed.

Fixed issues:

- Chat email requests now use the current inquiry conversation ID.
- Ordinary requests to share results no longer accidentally start email setup.
- Reminder corrections use the latest time, and a weekday matching today can save for later today.
- Users can decline email consent or switch to an in-app reminder in chat.
- Advance-payment amounts no longer overwrite the remembered purchase budget.
- Buying-process and emotional-support questions take priority over generic preference acknowledgements.
- Filter syncing no longer overwrites the auction action's chat results.
- Negative feedback containing “not helpful” is no longer also flagged as appreciation.
- An isolated chat-ending test now supplies its required preference-clearing dependency.

Email delivery and inquiry logging were mocked for the new website follow-up tests. These checks verify setup and saving, not actual SMTP delivery or live provider response quality. Streamlit emitted deprecation notices for existing UI APIs; they did not cause test failures.

## Continuous end-to-end run

Ran at the user's request and stopped after the requested final cycle, cycle 23. The runner launched a fresh Python process per cycle and shuffled test order. **Final result: 129 tests passed in 182.746 seconds.** The repeating runner and isolated QA preview servers are stopped. Detailed results are stored privately under `data/private/continuous_qa/`; the findings are summarized in `QA_FINDINGS_2026-10-09.md`.

- Two early 98-test cycles passed. Later fresh-process cycles passed 106 and 108 tests as coverage expanded.
- The complete 20-turn mixed-language conversation replay completed without app exceptions. An earlier 60-second harness timeout did not recur in the full replay or a focused three-turn replay.
- Browser QA verified the visible “Follow-up saved” notification after chat saves. The popup is queued until after form reruns and stays visible longer on Streamlit versions supporting that option.
- Actual rendered-toast assertions cover chat reminders, email consent, the manual reminder form, and no popup before consent or after a failed save.
- A temporary SQLite/workbook integration journey verified chat consent, request persistence, conversation metadata, and cancellation when the customer returns. No SMTP email was sent.
- Further fixes cover 24-hour reminder times, corrected days and times, same-weekday rollover, switching follow-up methods, interrupting setup with a search, and avoiding task commands being recorded as customer names.
- Cycle 12 passed all 122 tests. The suite continues to expand and run; this is a checkpoint, not a stop.
- Continuous storage testing caught a generated conversation UUID being partially redacted as an Aadhaar number. The redaction boundary now preserves generated IDs; focused tests still verify Aadhaar and PAN redaction, and the storage journey passed again.
- Ownership explanations are handled without unsolicited property searches. Tool-boundary tests verify that explicit requests for leasehold listings can still search.
- User-dashboard performance is included in recurring QA: initial load, property filtering, information panels, Mira save-to-popup, unchanged reruns, empty results and filter recovery. Timings are appended to `data/private/continuous_qa/dashboard-performance.jsonl`; operations over five seconds are flagged for investigation. These measure local Streamlit AppTest execution with offline Mira and external writes mocked, not deployed browser/network latency or concurrent-user capacity.
- Initial focused dashboard run: load 3.073s, filter 1.376s, panels 1.674–1.767s, save-to-popup 2.587s. An expanded run during parallel suite execution passed all dashboard checks, including zero-count empty results, recovery, and no duplicate reminder/toast on rerun; no measured operation exceeded five seconds.
- Branding now reads Namma Veedu in page title, logo, watermark, Mira policies/greetings, email templates and export filenames. Stable internal IDs and historical records retain their existing identifiers.
- Mira's welcome asks English or Tamil. Chat choices update both UI and conversation language, preserve a pending follow-up, and are excluded from bare-name capture. The 17 website journey tests and two additional focused language checks passed.
- The private blueprint view now shows a connected SVG flowchart, verified in the browser; the written blueprint is downloadable. Isolated owner-dashboard rendering and empty inquiry counts passed, with a focused load time of 1.127s. Recurring owner timings are saved separately from customer-dashboard timings.
