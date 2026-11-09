# VLR parser fixtures

`completed.html` is the match-header subtree fetched from
https://www.vlr.gg/594001/ on 2026-09-09. Ads, scripts, and unrelated page
content were omitted. Source date attributes are named `data-utc-ts` but hold
US Eastern wall time: this page pairs `04:00:00` with the rendered text
"1:00 AM PST" (09:00 UTC).

`live.html`, `upcoming.html`, `tbd.html`, and `malformed.html` are controlled
variants of that saved header, not historical snapshots of those states.
`event.html` is a synthetic index pointing to the fixture variants.
Tests serve these files through mocked HTTP responses; no live network needed.

`champions-tentative.html` is the match-header subtree fetched from
https://www.vlr.gg/753444/100-thieves-vs-t1-valorant-champions-2026-opening-a
on 2026-09-09. It preserves the tentative-date/time-TBD notice and score
placeholder, which must not be interpreted as a completed match or exact start.

`event-listing.html` follows the match rows of
https://www.vlr.gg/event/matches/2766/ as fetched on 2026-11-09. The Team Liquid
and LOUD rows keep that page's teams, scores, status badges, and clock text
(rendered for a US Pacific viewer); VOD/stat tags were omitted. The live,
upcoming, TBD, and plain-link rows and the "Today" tag are controlled variants,
not historical snapshots. The upcoming rows copy the badge markup seen on
https://www.vlr.gg/matches the same day: a bare `ml` class whose status is only
in the `ml-status` text.
