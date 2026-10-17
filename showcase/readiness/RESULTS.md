# Readiness scorer on messy answers (demo instrument)

A demo of the demo instrument: `example_instrument()` is not a validated index,
and these organisations are fictional. Each row is `harness score <file>` as it
ran at commit 4d84e6f.

| # | Scenario | Organisation | What `harness score` reported |
|---|---|---|---|
| 01 | complete | Kijani Water Collective | 0.640 Medium; dimensions 2/2; excluded []; unanswered [] |
| 02 | duplicate_selection | Rio Claro Youth Theatre | 0.473 Medium; dimensions 2/2; excluded []; unanswered [] |
| 03 | none_plus_others | Himalayan Midwives Network | 0.139 Low; dimensions 2/2; excluded []; unanswered [] |
| 04 | all_dont_know | Tidewater Literacy Trust | 0.000 Low; dimensions 0/2; excluded ['d1', 'd2', 'p2', 'p3']; unanswered ['d3', 'p1'] |
| 05 | one_dimension_blank | Sahel Seed Savers | 0.010 Low; dimensions 1/2; excluded []; unanswered ['p1', 'p2', 'p3'] |
| 06 | incomplete | Prairie Food Bank Alliance | 0.784 High; dimensions 2/2; excluded []; unanswered ['d3', 'p3'] |
| 07 | scale_off_range | Lotus Legal Aid Cambodia | 0.486 Medium; dimensions 2/2; excluded []; unanswered [] |
| 08 | unknown_option | Andean Weavers Cooperative | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'd1' has no option 'cloud_hybrid' |
| 09 | empty_values | Baltic Seniors Companion | 0.480 Medium; dimensions 2/2; excluded []; unanswered ['d2', 'p1'] |
| 10 | some_dont_know | Mekong Clean Rivers | 0.585 Medium; dimensions 2/2; excluded ['d1', 'p3']; unanswered [] |
| 11 | complete | Harbour Refugee Welcome | 1.000 High; dimensions 2/2; excluded []; unanswered [] |
| 12 | duplicate_selection | Pamoja Girls Scholars | 0.684 High; dimensions 2/2; excluded []; unanswered [] |
| 13 | none_plus_others | Ostrava Disability Advocacy | 0.659 Medium; dimensions 2/2; excluded []; unanswered [] |
| 14 | all_dont_know | Dhaka Street Health | 0.000 Low; dimensions 0/2; excluded ['d1', 'd2', 'p2', 'p3']; unanswered ['d3', 'p1'] |
| 15 | one_dimension_blank | Casa Esperanza Shelter | 0.467 Medium; dimensions 1/2; excluded []; unanswered ['p1', 'p2', 'p3'] |
| 16 | incomplete | Fjord Wildlife Rescue | 0.097 Low; dimensions 2/2; excluded []; unanswered ['p1', 'p3'] |
| 17 | scale_off_range | Accra Coders for Good | 0.760 High; dimensions 2/2; excluded []; unanswered [] |
| 18 | unknown_option | Tamil Nadu Elder Care | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'd2' has no option 'maybe' |
| 19 | empty_values | Pacific Reef Guardians | 0.438 Medium; dimensions 2/2; excluded []; unanswered ['p1', 'p2'] |
| 20 | some_dont_know | Lagos Microfinance Women | 0.578 Medium; dimensions 2/2; excluded ['d2']; unanswered [] |
| 21 | complete | Anatolia Earthquake Relief | 0.797 High; dimensions 2/2; excluded []; unanswered [] |
| 22 | duplicate_selection | Tbilisi Arts Access | 0.349 Medium; dimensions 2/2; excluded []; unanswered [] |
| 23 | none_plus_others | Kampala Deaf Youth | 0.242 Low; dimensions 2/2; excluded []; unanswered [] |
| 24 | all_dont_know | Great Lakes Tenant Union | 0.000 Low; dimensions 0/2; excluded ['d1', 'd2', 'p2', 'p3']; unanswered ['d3', 'p1'] |
| 25 | one_dimension_blank | Quito Urban Gardens | 0.083 Low; dimensions 1/2; excluded []; unanswered ['p1', 'p2', 'p3'] |
| 26 | incomplete | Ulaanbaatar Winter Warmth | 0.418 Medium; dimensions 2/2; excluded []; unanswered ['d2', 'p2'] |
| 27 | scale_off_range | Dublin Homeless Outreach | 0.835 High; dimensions 2/2; excluded []; unanswered [] |
| 28 | unknown_option | Lusaka Community Radio | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'p2' has no option 'sometimes' |
| 29 | empty_values | Sicily Migrant Legal Desk | 0.452 Medium; dimensions 2/2; excluded []; unanswered ['d1', 'p1'] |
| 30 | some_dont_know | Manila Typhoon Ready | 0.461 Medium; dimensions 2/2; excluded ['p2']; unanswered [] |
| 31 | complete | Kigali Clean Cookstoves | 0.588 Medium; dimensions 2/2; excluded []; unanswered [] |
| 32 | duplicate_selection | Nordic Mental Health Peer | 1.000 High; dimensions 2/2; excluded []; unanswered [] |
| 33 | none_plus_others | Atlas Mountain Schools | 0.037 Low; dimensions 2/2; excluded []; unanswered [] |
| 34 | all_dont_know | Waikato River Trust | 0.000 Low; dimensions 0/2; excluded ['d1', 'd2', 'p2', 'p3']; unanswered ['d3', 'p1'] |
| 35 | one_dimension_blank | Colombo Child Rights Forum | 0.467 Medium; dimensions 1/2; excluded []; unanswered ['p1', 'p2', 'p3'] |
| 36 | incomplete | Santiago Open Data Library | 0.816 High; dimensions 2/2; excluded []; unanswered ['d1', 'p3'] |
| 37 | scale_off_range | Warsaw Refugee Tutors | 0.392 Medium; dimensions 2/2; excluded []; unanswered [] |
| 38 | unknown_option | Windhoek Wildlife Scouts | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'p3' has no option 'quarterly' |
| 39 | empty_values | Karachi Women's Clinic | 0.733 High; dimensions 2/2; excluded []; unanswered ['p1', 'p3'] |
| 40 | some_dont_know | Highlands Veterans Retreat | 0.443 Medium; dimensions 2/2; excluded ['d2', 'p3']; unanswered [] |
| 41 | complete | Maputo Malaria Watch | 0.170 Low; dimensions 2/2; excluded []; unanswered [] |
| 42 | duplicate_selection | Seoul Language Exchange | 0.846 High; dimensions 2/2; excluded []; unanswered [] |
| 43 | none_plus_others | Beirut Food Rescue | 0.395 Medium; dimensions 2/2; excluded []; unanswered [] |
| 44 | all_dont_know | Yukon Elders Stories | 0.000 Low; dimensions 0/2; excluded ['d1', 'd2', 'p2', 'p3']; unanswered ['d3', 'p1'] |
| 45 | one_dimension_blank | Arequipa Recyclers Union | 0.083 Low; dimensions 1/2; excluded []; unanswered ['p1', 'p2', 'p3'] |
| 46 | incomplete | Addis Women Farmers | 0.289 Low; dimensions 2/2; excluded []; unanswered ['d3', 'p2', 'p3'] |
| 47 | scale_off_range | Jakarta Mangrove Youth | 0.566 Medium; dimensions 2/2; excluded []; unanswered [] |
| 48 | unknown_option | Ljubljana Bike Kitchen | exit 1: nonprofit_harness.core.errors.InvalidRequest: Question 'd2' has no option 'pending' |
| 49 | empty_values | Port Vila Cyclone Schools | 0.010 Low; dimensions 2/2; excluded []; unanswered ['p1', 'p2'] |
| 50 | some_dont_know | Cape Town Township Tutors | 0.813 High; dimensions 2/2; excluded ['p2']; unanswered [] |
