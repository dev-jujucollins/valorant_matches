# VLR parser fixtures

`completed.html` is the match-header subtree fetched from
https://www.vlr.gg/594001/ on 2026-09-09. Ads, scripts, and unrelated page
content were omitted. Source date attributes contain UTC date strings.

`live.html`, `upcoming.html`, `tbd.html`, and `malformed.html` are controlled
variants of that saved header, not historical snapshots of those states.
`event.html` is a synthetic index pointing to the fixture variants.
Tests serve these files through mocked HTTP responses; no live network needed.

`champions-tentative.html` is the match-header subtree fetched from
https://www.vlr.gg/753444/100-thieves-vs-t1-valorant-champions-2026-opening-a
on 2026-09-09. It preserves the tentative-date/time-TBD notice and score
placeholder, which must not be interpreted as a completed match or exact start.
