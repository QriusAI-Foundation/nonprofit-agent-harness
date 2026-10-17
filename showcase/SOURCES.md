# Showcase sources

The showcase reads these documents. None of them is committed to this repository.
`python -m showcase.sources` downloads each one into `showcase/sources/` (gitignored)
and stops if its SHA-256 differs from the value below, because the committed outputs
can only be reproduced from the same bytes.

The agents quote short passages from these documents in their outputs, with the
attribution below. The documents remain the work of their publishers and are used under
their own licences. The outputs under `showcase/runs/` are non-commercial demonstration
material, and the quoted passages keep the source document's licence.

## Training and programme documents

| Slug | Document | Licence | Pages | Approx. tokens |
|---|---|---|---:|---:|
| `who-chw-curriculum` | WHO, *Global curriculum guide for community health workers*, 2025 | CC BY-NC-SA 3.0 IGO | 172 | 158,000 |
| `ifrc-cbhfa-volunteers` | IFRC, *Community-based health and first aid in action: volunteer manual*, 2009 | Non-commercial use with attribution | 346 | 171,000 |
| `pathfinder-chbc-trainers` | Pathfinder International, *Community home-based care for people and communities affected by HIV/AIDS: trainer's guide*, 2006 | May be reproduced with acknowledgement | 748 | 332,000 |
| `alnap-sohs-2022` | ALNAP, *The State of the Humanitarian System*, 2022 edition | CC BY-NC 3.0 | 358 | 257,000 |
| `wdr-2018-learning` | World Bank, *World Development Report 2018: Learning to Realize Education's Promise* | CC BY 3.0 IGO | 240 | 229,000 |
| `wb-vnen-evaluation` | World Bank, *Enhancing School Quality in Vietnam through Participative and Collaborative Learning* (VNEN impact evaluation), 2017 | CC BY 3.0 IGO | 166 | 103,000 |

Token counts are the input tokens Claude reported for a run, rounded.

### URLs and hashes

| Slug | URL | SHA-256 |
|---|---|---|
| `who-chw-curriculum` | https://iris.who.int/server/api/core/bitstreams/38c8b2d1-d82f-413c-b4d2-e7e95d9365ca/content | `2005dd144340e8b8ba28e006d04356bee28e1dfedc9e4e3ba8fb4fd32118e4ba` |
| `ifrc-cbhfa-volunteers` | https://preparecenter.org/wp-content/sites/default/files/145600-3-cbfa-volunteers_lr_1.pdf | `2a2b38f92e14cda840d9d75c61cb3334f54a7ef1dcff2a068936f5f392d55b41` |
| `pathfinder-chbc-trainers` | https://chwcentral.org/wp-content/uploads/2013/11/Community-Home-Based-Care-for-People-and-Communities-living-with-HIV-AIDS-A-Comprehensive-Training-Course-for-Community-Health-Workers-Entire-Trainers-Guide.pdf | `db71a3ceedc4077a8acc76c0b102a3b1b50dc2dbd87b5a82930629ce4e005caa` |
| `alnap-sohs-2022` | https://www.oiren.org/wp-content/uploads/2023/11/State-of-Humanitarian-System-2022_Full-report.pdf | `982ffd712b56d36276c58e399f7d09c788e2e324410484770e1b014ed45bca06` |
| `wdr-2018-learning` | https://documents1.worldbank.org/curated/en/240351507784846426/pdf/120299-WDR-v1-PUBLIC-main.pdf | `091c14411843f9efec16b097e715fdc00e29e18f8973fab4e399500d409a7393` |
| `wb-vnen-evaluation` | https://documents1.worldbank.org/curated/en/339001502818131149/pdf/118675-REVISED-PUBLIC-1708908-VNEN-IE-Web.pdf | `4253431599023da2c296e1574e0bdad624f1a4d8c1b3098b22704d040065ad7f` |

### Attribution

- World Health Organization. *Global curriculum guide for community health workers.*
  Geneva: WHO; 2025. Licence: CC BY-NC-SA 3.0 IGO. This showcase was not created by WHO,
  and WHO does not endorse it.
- International Federation of Red Cross and Red Crescent Societies. *Community-based
  health and first aid in action: volunteer manual.* Geneva: IFRC; 2009.
- Pathfinder International. *Community Home-Based Care for People and Communities
  Affected by HIV/AIDS: A Comprehensive Training Course for Community Health Workers,
  Trainer's Guide.* Watertown, MA: Pathfinder International; 2006. Reproduced with
  acknowledgement.
- ALNAP (2022). *The State of the Humanitarian System.* ALNAP Study. London: ALNAP/ODI.
  © ALNAP/ODI 2022. Licence: CC BY-NC 3.0.
- World Bank. 2018. *World Development Report 2018: Learning to Realize Education's
  Promise.* Washington, DC: World Bank. doi:10.1596/978-1-4648-1096-1. Licence: CC BY 3.0
  IGO.
- Parandekar, Suhas D., Futoshi Yamauchi, Andrew B. Ragatz, Elisabeth K. Sedmik, and
  Akiko Sawamoto. 2017. *Enhancing School Quality in Vietnam through Participative and
  Collaborative Learning.* Washington, DC: World Bank. Licence: CC BY 3.0 IGO.

### Notes

- **ALNAP** comes from a byte-identical mirror. The full-report URL on alnap.org
  returned 404 on 2026-10-17. The licence statement is on page 2 of the PDF itself.
- **WDR 2018**: the harness's `extract` raises pypdf's `LimitReachedError` on page 155
  and loses the whole document. `showcase/sources.py` extracts this one file page by page
  and skips that page, which is recorded in the document metadata. See "Noticed, not
  fixed" in `docs/showcase.md`.
- **IFRC and Pathfinder** state their reuse terms on the document: non-commercial use
  with attribution, and reproduction with acknowledgement.

## Results data (IATI)

Published IATI activity files, fetched once through `IatiClient.activity_xml` (free
tier: 5 calls a minute, 100 a week) and cached in `showcase/sources/iati/`. IATI data is
published for reuse; each file remains the publisher's.

| Slug | IATI identifier | Publisher | SHA-256 of the cached XML |
|---|---|---|---|
| `nlrc-pneumonia-cote-divoire` | NL-KVK-40409352-PRJ08-272-0005 | The Netherlands Red Cross | `41c9510b63234f2691103f808b345bb46a4b2740830b601e419f4be4fef7a39a` |
| `wbtf-rwanda-chw` | XI-IATI-WBTF-P175583 | World Bank Trust Funds | `cddb7938ad04129f3a503204d0aaf80d73db9f5bfba88f27e2258632ae5721ad` |
| `cordaid-teenage-pregnancy-sl` | NL-KVK-41160054-200782 | Cordaid | `0c63c277fa72edccb8fb830bb519a2ccec4b44f3247399a09e6affb6b450313d` |

The Datastore serves the current version of each activity, so a later fetch can return
different XML. The hashes record what these runs read.
