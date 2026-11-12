# Level 2 calibration (K0): qwen3-4b, level2_v1

4 LLM traders (cash+shares: 1500+5, 1500+5, 500+15, 500+15) and n ZI bots (1000+10
each), no manipulator. gap = price - rational price, over traded periods only.
Price after news: price level in P7 minus P3 (last trade
price, else 100), compared with the direction of the official
news in P4.

| ZI bots | LLM trades in >= 6 of 12 periods | mean LLM traded periods | median abs gap | pass | periods with ZI-only trades | price after P4 news: with / flat / against |
|---|---|---|---|---|---|---|
| 1 | 1 of 10 | 2.2 | 10.3 | NO | 0 | 3 / 7 / 0 |
| 2 | 1 of 10 | 3.4 | 12.0 | NO | 17 | 4 / 3 / 3 |
| 3 | 3 of 10 | 3.8 | 15.7 | NO | 36 | 5 / 0 / 5 |

Criteria: an LLM trades in >= 6 of 12 periods in most sessions; median abs gap <= 10.
Chosen: 3 ZI bots (no step passes: the one where the LLM traders trade most, as a limitation).

## 1 ZI bots

| session | news P4 | LLM traded periods | traded periods | volume | LLM side share | median abs gap | LLM hold share | invalid | price after P4 news |
|---|---|---|---|---|---|---|---|---|---|
| v130-s101 | bad | 1 | 1 | 2 | 0.50 | 12.0 | 0.85 | 0 | +0.0 (flat) |
| v130-s102 | good | 0 | 0 | 0 | - | - | 0.79 | 0 | +0.0 (flat) |
| v130-s103 | bad | 6 | 6 | 15 | 0.50 | 11.1 | 0.69 | 0 | +0.0 (flat) |
| v130-s104 | good | 4 | 4 | 12 | 0.62 | 3.9 | 0.69 | 0 | +10.2 (with) |
| v130-s105 | bad | 2 | 2 | 8 | 0.50 | 10.0 | 0.81 | 0 | +0.0 (flat) |
| v70-s106 | bad | 1 | 1 | 4 | 0.50 | 20.7 | 0.90 | 0 | +0.0 (flat) |
| v70-s107 | good | 4 | 4 | 8 | 0.50 | 16.0 | 0.69 | 0 | +10.0 (with) |
| v70-s108 | bad | 1 | 1 | 1 | 0.50 | 0.0 | 0.88 | 0 | +0.0 (flat) |
| v70-s109 | bad | 0 | 0 | 0 | - | - | 0.85 | 0 | +0.0 (flat) |
| v70-s110 | good | 3 | 3 | 10 | 0.50 | 2.7 | 0.50 | 0 | +13.5 (with) |

| period | sessions where an LLM traded | median gap |
|---|---|---|
| 1 | 2 of 10 | 2.4 |
| 2 | 0 of 10 | - |
| 3 | 0 of 10 | - |
| 4 | 2 of 10 | 7.5 |
| 5 | 2 of 10 | -5.2 |
| 6 | 1 of 10 | 3.0 |
| 7 | 2 of 10 | 5.0 |
| 8 | 4 of 10 | 7.5 |
| 9 | 2 of 10 | 15.0 |
| 10 | 2 of 10 | 11.2 |
| 11 | 3 of 10 | 15.0 |
| 12 | 2 of 10 | 15.1 |

## 2 ZI bots

| session | news P4 | LLM traded periods | traded periods | volume | LLM side share | median abs gap | LLM hold share | invalid | price after P4 news |
|---|---|---|---|---|---|---|---|---|---|
| v130-s101 | bad | 4 | 5 | 30 | 0.78 | 7.9 | 0.81 | 0 | -7.9 (with) |
| v130-s102 | good | 6 | 6 | 13 | 0.46 | 6.2 | 0.58 | 0 | +25.0 (with) |
| v130-s103 | bad | 4 | 7 | 50 | 0.75 | 15.0 | 0.65 | 0 | +7.0 (against) |
| v130-s104 | good | 5 | 7 | 20 | 0.40 | 4.8 | 0.65 | 0 | -15.5 (against) |
| v130-s105 | bad | 2 | 3 | 6 | 0.33 | 10.0 | 0.88 | 0 | +0.0 (flat) |
| v70-s106 | bad | 1 | 3 | 7 | 0.21 | 44.7 | 0.71 | 0 | +15.0 (against) |
| v70-s107 | good | 1 | 4 | 9 | 0.11 | 21.5 | 0.67 | 0 | +30.0 (with) |
| v70-s108 | bad | 2 | 4 | 12 | 0.21 | 10.9 | 0.83 | 0 | -13.8 (with) |
| v70-s109 | bad | 4 | 5 | 17 | 0.41 | 7.7 | 0.90 | 0 | +0.0 (flat) |
| v70-s110 | good | 5 | 7 | 23 | 0.50 | 27.0 | 0.67 | 0 | +0.0 (flat) |

| period | sessions where an LLM traded | median gap |
|---|---|---|
| 1 | 2 of 10 | 6.8 |
| 2 | 0 of 10 | 12.7 |
| 3 | 0 of 10 | -2.0 |
| 4 | 5 of 10 | 10.0 |
| 5 | 4 of 10 | 17.2 |
| 6 | 2 of 10 | 8.0 |
| 7 | 4 of 10 | 17.0 |
| 8 | 6 of 10 | 15.7 |
| 9 | 5 of 10 | 7.2 |
| 10 | 3 of 10 | 10.0 |
| 11 | 2 of 10 | -31.1 |
| 12 | 1 of 10 | 16.3 |

## 3 ZI bots

| session | news P4 | LLM traded periods | traded periods | volume | LLM side share | median abs gap | LLM hold share | invalid | price after P4 news |
|---|---|---|---|---|---|---|---|---|---|
| v130-s101 | bad | 3 | 8 | 30 | 0.30 | 25.4 | 0.67 | 0 | +14.6 (against) |
| v130-s102 | good | 6 | 6 | 20 | 0.47 | 3.2 | 0.54 | 0 | +12.3 (with) |
| v130-s103 | bad | 4 | 10 | 24 | 0.12 | 7.2 | 0.67 | 0 | +30.2 (against) |
| v130-s104 | good | 6 | 8 | 31 | 0.34 | 16.0 | 0.60 | 0 | -20.0 (against) |
| v130-s105 | bad | 2 | 6 | 35 | 0.74 | 19.1 | 0.79 | 0 | -39.1 (with) |
| v70-s106 | bad | 2 | 6 | 17 | 0.18 | 18.1 | 0.75 | 0 | +14.2 (against) |
| v70-s107 | good | 2 | 8 | 30 | 0.22 | 15.4 | 0.71 | 0 | -16.5 (against) |
| v70-s108 | bad | 4 | 8 | 34 | 0.47 | 18.1 | 0.79 | 0 | -24.7 (with) |
| v70-s109 | bad | 3 | 6 | 14 | 0.32 | 19.0 | 0.83 | 0 | -30.1 (with) |
| v70-s110 | good | 6 | 8 | 26 | 0.42 | 11.7 | 0.46 | 0 | +3.9 (with) |

| period | sessions where an LLM traded | median gap |
|---|---|---|
| 1 | 3 of 10 | 3.1 |
| 2 | 0 of 10 | 36.2 |
| 3 | 2 of 10 | 18.5 |
| 4 | 4 of 10 | 16.6 |
| 5 | 3 of 10 | 15.5 |
| 6 | 4 of 10 | 11.1 |
| 7 | 5 of 10 | 16.1 |
| 8 | 1 of 10 | 19.0 |
| 9 | 3 of 10 | -18.0 |
| 10 | 1 of 10 | 5.8 |
| 11 | 8 of 10 | 6.3 |
| 12 | 4 of 10 | 10.3 |
