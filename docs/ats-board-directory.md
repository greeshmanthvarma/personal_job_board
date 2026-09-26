# Public ATS board directory

Union of the September 2026 Common Crawl board list (`CC-MAIN-2026-39`) and the LastRound AI ATS company directory (`lastroundai-ats-company-directory-2026-08`, CC-BY-4.0). LastRound dates are July–August 2026. September dates are 4–17 Sep 2026. This is not a vendor customer list.

A board is one `ats_vendor` plus `board_slug`, and the slug match ignores case. When both files list the same board, the September row is kept: its `source_date`, `confirmed`, and `http_status` stay, and `company_name` is filled from LastRound when September left it blank. `source` on those rows is `commoncrawl:CC-MAIN-2026-39+lastround-2026-08`. LastRound-only rows use `source` `lastround-2026-08`, take `source_date` from LastRound `last_crawled`, set `confirmed` to `unchecked`, and leave `http_status` blank. September-only rows keep their original `source`.

Unchecked rows were not reconfirmed for this merge. The only confirmed values are the September sample: 53 yes and 12 no. The other 12853 rows are unchecked, including every LastRound-only row.

4592 boards that appear in both files had a blank September `company_name`. Those names now come from LastRound. September-only rows keep a blank name when September had none.

## Counts

| Vendor | Boards | September only | LastRound only | Both |
| --- | ---: | ---: | ---: | ---: |
| Greenhouse | 6889 | 1923 | 2174 | 2792 |
| Ashby | 3910 | 1054 | 1069 | 1787 |
| Lever | 2119 | 6 | 2091 | 22 |
| Total | 12918 | 2983 | 5334 | 4601 |

## Lever gap

The September file had 28 Lever boards. LastRound listed 2113 Lever boards, and 2091 of those were absent from September. The merge adds those 2091 Lever boards, which takes Lever from 28 to 2119. Of the union, 2091 are LastRound only, 22 are in both files, and 6 are September only (`Arcade`, `catalist`, `mammothbiosci`, `NexGenAnimalHealth`, `spin`, `veeva`). The added Lever rows stay unchecked. Their dates are the July–August 2026 LastRound crawl dates, not a September reconfirmation.

LastRound AI, [ATS Company Directory](https://datahub.io/lastroundai-hiring-data/lastroundai-hiring-data/ats-directory), dataset `lastroundai-ats-company-directory-2026-08`, crawled July–August 2026, CC-BY-4.0.
