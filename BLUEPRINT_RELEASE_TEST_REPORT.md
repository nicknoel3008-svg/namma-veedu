# Namma Veedu blueprint and Mira performance review

Date: 10 October 2026 (India time)

Release: implementation commit `600642c` pushed to GitHub main. Public Streamlit startup and authenticated Mira Studio were verified after deployment: the new flowchart/download controls and Mira rating KPI are present, PostgreSQL storage is active, and the automatic snapshot date is 2026-10-10. Public browser verification was read-only; performance numbers below come from local tests.

## Changes

- Expanded the private Studio blueprint into a connected flowchart covering the original idea, implementation, customer options, results, shared storage, owner review, approval-controlled learning and release validation. The complete written blueprint and SVG are downloadable in Studio.
- Kept eight primary KPIs and made Mira performance rating the eighth. It averages the latest rating per conversation, excludes unrated/invalid values and respects the report date filter. Customer satisfaction remains a separate detail.
- Fixed an observed live response about commute versus space: removed an unsupported room-size benchmark, misleading amenity-cost advice and an unverified matching-listing promise. The supported flow now preserves budget/BHK and asks one useful commute question. Strengthened hosted reasoning guidance for the same issue.
- Corrected outdated blueprint descriptions of shared persistence and hosted Studio access.

## Coverage

Final shuffled regression cycle: **159 tests passed in 299.066 seconds**, with no failures. Command: `python -X utf8 tests/run_continuous_qa.py --cycle 102`. The final cycle includes the rating and commute-response changes.

The finite regression cycle covers website journeys, language and preference continuity, multiple preferences, auctions, search evidence boundaries and no-match explanations, pagination, follow-up saving/popups/failures/cancellation, feedback capture, learning drafts and approval, rating aggregation, snapshot dates, privacy redaction, persistence errors and provider fallback.

Real Supabase connectivity was checked read-only: the configured database connected successfully and contained 619 inquiry turns and 16 learning rules at the time of inspection. Automated write/approval journeys use isolated fixtures; production approval decisions were not changed.

The configured hosted provider was also exercised using a synthetic conversation with inquiry writes intercepted. Its general advice response took 7.402 seconds and exposed the quality issue fixed above. Replaying the same question through the corrected local flow took 1.829 seconds, retained Chennai/Flat/3BHK/₹60 lakh and produced no application exception or provider error. These samples are not percentile benchmarks or load tests.

## Local performance measurements

| Operation | Seconds |
| --- | ---: |
| Initial customer page | 1.185 |
| Property filter | 1.330 |
| Follow-up save through confirmation popup | 2.614 |
| Empty-result filter | 1.220 |
| Clear-filter recovery | 1.491 |
| Owner dashboard, empty isolated fixture | 0.781 |

Five listing cards rendered per page. None of the measured local dashboard operations exceeded five seconds. Timings use Streamlit AppTest, isolated data and mocked external writes; they do not measure a production-sized owner database, simultaneous visitors, email delivery or public network latency.

Email delivery was not exercised against real recipients. In-app reminders still require an active browser session. Approved learning is reviewed guidance, not automatic model-weight training.
