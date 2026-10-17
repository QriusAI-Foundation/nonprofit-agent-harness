# Readiness scorer on messy answers (demo instrument)

A demo of the demo instrument: `example_instrument()` is not a validated index,
and these organisations are fictional. Each row is `harness score <file>` as it
ran at commit 4369977.

| # | Scenario | Organisation | What `harness score` reported |
|---|---|---|---|
| 01 | complete | Kijani Water Collective | 0.640 Medium; status complete; dimensions 2/2 |
| 02 | duplicate_selection | Rio Claro Youth Theatre | 0.388 Medium; status complete; dimensions 2/2; duplicates dropped {'p1': ['writes_reports']} |
| 03 | none_plus_others | Himalayan Midwives Network | 0.139 Low; status complete; dimensions 2/2 |
| 04 | all_dont_know | Tidewater Literacy Trust | no score no tier; status incomplete; dimensions 0/2; missing dimensions ['Data & Systems', 'People & Skills']; excluded questions ['d1', 'd2', 'p2', 'p3'] |
| 05 | one_dimension_blank | Sahel Seed Savers | no score no tier; status incomplete; dimensions 1/2; missing dimensions ['People & Skills'] |
| 06 | incomplete | Prairie Food Bank Alliance | 0.784 High; status partial; dimensions 2/2 |
| 07 | scale_off_range | Lotus Legal Aid Cambodia | 0.486 Medium; status complete; dimensions 2/2 |
| 08 | unknown_option | Andean Weavers Cooperative | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'd1' has no option 'cloud_hybrid' |
| 09 | empty_values | Baltic Seniors Companion | 0.480 Medium; status partial; dimensions 2/2 |
| 10 | some_dont_know | Mekong Clean Rivers | 0.585 Medium; status complete; dimensions 2/2; excluded questions ['d1', 'p3'] |
| 11 | complete | Harbour Refugee Welcome | 1.000 High; status complete; dimensions 2/2 |
| 12 | duplicate_selection | Pamoja Girls Scholars | 0.623 Medium; status complete; dimensions 2/2; duplicates dropped {'p1': ['manages_spreadsheets']} |
| 13 | none_plus_others | Ostrava Disability Advocacy | 0.659 Medium; status complete; dimensions 2/2 |
| 14 | all_dont_know | Dhaka Street Health | no score no tier; status incomplete; dimensions 0/2; missing dimensions ['Data & Systems', 'People & Skills']; excluded questions ['d1', 'd2', 'p2', 'p3'] |
| 15 | one_dimension_blank | Casa Esperanza Shelter | no score no tier; status incomplete; dimensions 1/2; missing dimensions ['People & Skills'] |
| 16 | incomplete | Fjord Wildlife Rescue | 0.097 Low; status partial; dimensions 2/2 |
| 17 | scale_off_range | Accra Coders for Good | 0.760 High; status complete; dimensions 2/2 |
| 18 | unknown_option | Tamil Nadu Elder Care | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'd2' has no option 'maybe' |
| 19 | empty_values | Pacific Reef Guardians | 0.438 Medium; status partial; dimensions 2/2 |
| 20 | some_dont_know | Lagos Microfinance Women | 0.578 Medium; status complete; dimensions 2/2; excluded questions ['d2'] |
| 21 | complete | Anatolia Earthquake Relief | 0.797 High; status complete; dimensions 2/2 |
| 22 | duplicate_selection | Tbilisi Arts Access | 0.286 Low; status complete; dimensions 2/2; duplicates dropped {'p1': ['builds_dashboards']} |
| 23 | none_plus_others | Kampala Deaf Youth | 0.242 Low; status complete; dimensions 2/2 |
| 24 | all_dont_know | Great Lakes Tenant Union | no score no tier; status incomplete; dimensions 0/2; missing dimensions ['Data & Systems', 'People & Skills']; excluded questions ['d1', 'd2', 'p2', 'p3'] |
| 25 | one_dimension_blank | Quito Urban Gardens | no score no tier; status incomplete; dimensions 1/2; missing dimensions ['People & Skills'] |
| 26 | incomplete | Ulaanbaatar Winter Warmth | 0.418 Medium; status partial; dimensions 2/2 |
| 27 | scale_off_range | Dublin Homeless Outreach | 0.835 High; status complete; dimensions 2/2 |
| 28 | unknown_option | Lusaka Community Radio | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'p2' has no option 'sometimes' |
| 29 | empty_values | Sicily Migrant Legal Desk | 0.452 Medium; status partial; dimensions 2/2 |
| 30 | some_dont_know | Manila Typhoon Ready | 0.461 Medium; status complete; dimensions 2/2; excluded questions ['p2'] |
| 31 | complete | Kigali Clean Cookstoves | 0.588 Medium; status complete; dimensions 2/2 |
| 32 | duplicate_selection | Nordic Mental Health Peer | 0.931 High; status complete; dimensions 2/2; duplicates dropped {'p1': ['writes_reports']} |
| 33 | none_plus_others | Atlas Mountain Schools | 0.037 Low; status complete; dimensions 2/2 |
| 34 | all_dont_know | Waikato River Trust | no score no tier; status incomplete; dimensions 0/2; missing dimensions ['Data & Systems', 'People & Skills']; excluded questions ['d1', 'd2', 'p2', 'p3'] |
| 35 | one_dimension_blank | Colombo Child Rights Forum | no score no tier; status incomplete; dimensions 1/2; missing dimensions ['People & Skills'] |
| 36 | incomplete | Santiago Open Data Library | 0.816 High; status partial; dimensions 2/2 |
| 37 | scale_off_range | Warsaw Refugee Tutors | 0.392 Medium; status complete; dimensions 2/2 |
| 38 | unknown_option | Windhoek Wildlife Scouts | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'p3' has no option 'quarterly' |
| 39 | empty_values | Karachi Women's Clinic | 0.733 High; status partial; dimensions 2/2 |
| 40 | some_dont_know | Highlands Veterans Retreat | 0.443 Medium; status complete; dimensions 2/2; excluded questions ['d2', 'p3'] |
| 41 | complete | Maputo Malaria Watch | 0.170 Low; status complete; dimensions 2/2 |
| 42 | duplicate_selection | Seoul Language Exchange | 0.769 High; status complete; dimensions 2/2; duplicates dropped {'p1': ['manages_spreadsheets']} |
| 43 | none_plus_others | Beirut Food Rescue | 0.395 Medium; status complete; dimensions 2/2 |
| 44 | all_dont_know | Yukon Elders Stories | no score no tier; status incomplete; dimensions 0/2; missing dimensions ['Data & Systems', 'People & Skills']; excluded questions ['d1', 'd2', 'p2', 'p3'] |
| 45 | one_dimension_blank | Arequipa Recyclers Union | no score no tier; status incomplete; dimensions 1/2; missing dimensions ['People & Skills'] |
| 46 | incomplete | Addis Women Farmers | 0.289 Low; status partial; dimensions 2/2 |
| 47 | scale_off_range | Jakarta Mangrove Youth | 0.566 Medium; status complete; dimensions 2/2 |
| 48 | unknown_option | Ljubljana Bike Kitchen | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'd2' has no option 'pending' |
| 49 | empty_values | Port Vila Cyclone Schools | 0.010 Low; status partial; dimensions 2/2 |
| 50 | some_dont_know | Cape Town Township Tutors | 0.813 High; status complete; dimensions 2/2; excluded questions ['p2'] |
