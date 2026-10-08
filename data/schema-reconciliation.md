# Property source and field reconciliation

The app normalizes unlike source files into a common record shape. It keeps listing records, project references, auction notices, and approval-register rows distinct; it does not merge similarly named projects because a name match alone is not proof that two records describe the same offer.

## Source workbooks inspected

| Source file | Inspected content | How it is used |
|---|---|---|
| `tamil_nadu_properties( auction).xlsx` and matching `tamil_nadu_properties.csv` | Auction property fields such as price, bank, area, possession, auction dates, EMD, status and source identifiers | The companion CSV supplies BAANKNET snapshots. Public property fields are retained for recognized residential property types. Owner/borrower names and addresses, bank branch addresses, photos and raw IDs are omitted. Rows marked unavailable with no auction date are stored separately as unconfirmed records; Mira offers them only after dated search results are unavailable and the user agrees to review source links. |
| `tamil_nadu_properties(NO broker).xlsx` | `Property_Master` sale records, price in lakhs, area, type, locality and URL | Imported as saved existing-sale advertisements. Current availability and title are not inferred. |
| `StepsStone_Master_Project_Dataset_Field_Verified.xlsx` | `13_Verified_Project_Data` plus audit fields | The 11-field verified subset is used as project references. The broader discovery workbook is not treated as a list of currently available units. |
| `StepsStone_Master_Project_Dataset.xlsx` | Master inventory, raw page index, unresolved URL register and quality sheets | Audited for structure; raw/discovery and unresolved rows are not property offers and are excluded from chat search. |
| `VGN_MASTER_DATASET_PRICE_AREA_AVAILABILITY_AUDITED_2026-10-06.xlsx` | `01_Master_Project_Inventory` and its field/source/availability audit columns | Recognized residential project types are imported as project references. Only explicitly numeric rupee values are used for price filtering; estimates/text remain labeled as supplied. |
| `Wisdom_Properties_Tamil_Nadu_Master.xlsx` | Project master and estimate/verification sheets | Project references are included. Estimated minimum plot prices remain explicitly labeled estimates; no official URL is invented when a row lacks one. |
| `Tamil_Nadu_Property_Market_Master_FINAL.xlsx` | `CMDA_Layout_2024_200` approval register | Imported as approval records for reference, not as a sale listing. These rows are excluded from normal property-for-sale results. |

## Common fields

The normalized file `properties.csv` holds a common identity/title, property type, record kind, location, numeric price when interpretable, original price text/basis, normalized area when supported, project approval/RERA/availability notes, public auction details (including facing, floor, parking, furnishing and loan snapshot fields where supplied), source URL/date, import date, and trust notes. Blank values remain blank. An estimate or project reference is not presented as an available unit. An approval record is not presented as proof of availability or ownership.

## Current import snapshot

The source auction CSV has 6,655 rows: 409 are marked auction-available and have date information; the other 6,246 are marked unavailable and have no auction dates. The importer retains recognized home and plot property types from both groups, while keeping undated/unavailable rows separate from normal results; 1,100 rows with property subtypes outside the portal’s home/plot categories are omitted. The current normalized file contains 5,947 records: 315 dated auction records with future end dates, 29 dated ended auctions, 5,211 auction records with no date and unavailable status, 30 sale advertisements, 162 project references (136 VGN, 15 Wisdom and 11 StepsStone), and 200 CMDA approval-register entries. The undated records are not active listings: Mira asks before showing them, and each card points to the source for direct checking. The app checks dated auctions at load time; it does not connect to a live listings feed.

## Build steps

1. Inspect each workbook’s sheets and headers before mapping fields.
2. Choose a common record shape and preserve each source’s original meaning.
3. Normalize only safe values (such as numeric amounts with known units); keep uncertain values as text or blank.
4. Search and rank records with visible match reasons.
5. Keep auctions, loans and planning approvals in their own user paths.
6. Test parsing, filtering, missing fields, source links and boundaries before running the chatbox.
