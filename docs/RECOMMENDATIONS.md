# Preference-based room recommendations

Status: implemented after explicit user approval of the no-migration policy below.
This decision supersedes the earlier deferred formulas in the contracts.

## Confirmed requirements

`S = 0.30L + 0.30B + 0.15A + 0.15R + 0.10F`, with each factor in [0, 1].
Budget is maximum affordability: rent at or below the maximum earns B = 1.
Preferences may be text-only. No fake coordinates or implicit distance claims.
Find Rooms retains its explicit filtering, independent of recommendation ranking.

`preferences.recommendations.recommendation_candidates` uses existing search
loading and visibility services. Candidates must be available, nonarchived, have
an approved published revision and an active, ordinary, verified Owner. Reserved,
occupied, inactive, unpublished, suspended and otherwise inaccessible rooms are
excluded. Photos/amenities are prefetched and saved state is annotated; candidate
cards must not issue individual database queries for those relationships.

## Approved scoring policy

The proposal called R **Rules**, but TenantPreference stores **Room Type**. The user
approved R = Room Type for this implementation. No tenant rules fields or migrations
are needed. Rules are not scored or inferred.

Exact scoring policy:

- L = 1 when the actual room distance from the validated selected point is less
  than or equal to the selected radius. Outside-radius rooms are excluded before
  scoring. Unresolved points produce no recommendations or scores. There is no
  address substring check or distance decay in this geographic flow.
- B = 1 for rent <= maximum budget; otherwise maximum budget / rent.
- A = selected amenity IDs present / selected amenity IDs; no selected amenities
  earns 1 as an unconstrained preference.
- R = 1 for exact stored room type, else 0. Different types remain eligible.
- F = 1 for exact stored furnishing or Any, else 0.
- Required missing/invalid location, budget or room type means incomplete
  preferences, not a zero score. Any furnishing and empty amenities are complete.
- Rank by unrounded score descending, then publication timestamp descending,
  then listing ID descending. Display rounded S * 100 percent.
- Explanations describe actual factors ("Within your selected area", within budget,
  matched amenity fraction, matching type/furnishing), never guaranteed suitability.

Worked example: within the selected radius, rent Rs 12,000 against Rs 10,000
maximum, 2 of 4 selected amenities, matching type, furnishing Any yields
L=1, B=5/6, A=1/2, R=1, F=1. S=0.30+0.25+0.075+0.15+0.10=0.875,
displayed as 88%. The room remains above budget and its explanation must say so.

## Fallback, loading and validation

Incomplete preferences show Complete Preferences on Home; this opens the existing
onboarding form. Complete preferences rank all eligible rooms, not just exact
matches. No eligible rooms shows an honest empty state. Latest rooms stay only in
Fresh on Roomer. Home uses saved preferences; Home searches and explicit Find Rooms
filters keep their existing behavior and do not use ranking to replace filters.

`recommend_rooms` loads preference amenities once and room/photos/amenities in three
queries, independent of candidate count. It scores in memory, returns the top three,
and uses Decimal arithmetic with half-up whole-percentage display rounding. The
scoring helper receives sets of stored amenity IDs; it performs no queries. No
results, scores or preference changes are persisted.

Focused checks cover exact match, budget boundary/above-budget ratio, partial
amenities, different/text-only locations, Any/empty factors, type mismatches,
publication/availability/owner restrictions, timestamp/ID tie-breaking, bounded
queries, Home percentage rendering and incomplete preferences. Checks use only
isolated test data. No browser verification or broad suite has been performed.

Manual check: save preferences, open Tenant Home, compare the top three against
these formulas, and inspect above-budget/different-location explanations. Change
Profile preferences and return Home; ranking should change. Reserve or deactivate
a listing and refresh; it must disappear. Verify Find Rooms can still clear or
edit filters independently.

## Find Rooms: independent recommendations and all available rooms

Filters stay left and the right column contains two separate horizontal scrolling
rows. Recommended Rooms shows up to six ranked rooms from current validated
search values, using the shared Home scoring service. It shows Preference match
percentages and factual match/difference explanations. Partial preferences earn
neutral full credit; Reset hides recommendations when all criteria are cleared.
A selected point/radius is a geographic eligibility boundary for recommendations
only; every inside-radius room receives full L credit (no distance decay). Invalid or unresolved location filters block
recommendations and display validation, without affecting the catalogue below.

All Available Rooms is an independent catalogue built with empty search filters.
It includes every available, nonarchived listing with a current approved published
revision and an active, ordinary, verified Owner. Reserved, occupied, inactive,
unpublished and otherwise inaccessible listings are excluded. Location, point,
radius, budget, room type, furnishing and amenities never restrict this section.
Its own count and four-per-page pagination cover the entire eligible catalogue,
ordered by publication timestamp descending then ID descending. A room may appear
in both sections. Scrolling applies only to the currently loaded cards in each row.

Apply updates recommendations only. Pagination retains selected values so the
recommendation context survives navigation, but these values do not enter the
catalogue query. Both sections retain independent save/unsave and details links.
Navbar initial entry and Home location overrides still use saved defaults without
writing Profile preferences. Reset and Fresh View All remain unfiltered entries.

The previous strict-filtered Available Rooms behavior is superseded by this
explicit user decision. The shared search_rooms function still supports strict
filtering for its other callers; only Find Rooms' catalogue passes empty filters.
Django system check is required for this change; no broad test suite or browser
checks are claimed.

## Location autocomplete and nearby eligibility

Home, first-search onboarding and Find Rooms share location_autocomplete.js and
POST /accounts/tenant/locations/suggestions/. The active-Tenant-only endpoint
requires CSRF and uses the existing Photon lookup, cache, throttle and timeout.
Suggestions include provider names, locality/city/district/state/country when
available, capped at five places. Requests wait for a 500 ms typing pause and at
least 2.1 seconds since the previous request; stale responses are ignored/aborted.
The combobox supports arrows, Enter, Escape, mouse choice and announced states.

Ordinary location Search requires a selected suggestion. The server verifies its
signed display-name/coordinate pair; text alone, tampered points and old selections
show "Choose a location from the suggestions." and produce no recommendations. The independent catalogue remains available.
Typing immediately clears the selected coordinates/token. Manual map and GPS
points remain explicit alternatives and are validated for paired finite bounds.
No coordinates are invented when lookup fails. Blank Reset and Fresh View All are
still intentionally unfiltered entries.

Existing saved text-only preferences and neighbourhood links use resolve=1/area
entry: one unique provider result can resolve automatically; multiple results
require a location choice. Failure keeps recommendations empty, with lookup retry through
the autocomplete field or manual map selection. It never broadens outside a radius.
Selections pass through first-search onboarding as search-only hidden values;
Profile can remain text-only. Ordinary searches never save Profile changes.

The GET form and pagination retain latitude/longitude, point_location,
resolved_label, location_token, point_source and radius. The default radius is
2 km, displayed on the map as a circle. Apply, pagination and refresh reuse the
selected point rather than repeating lookup. Changing text invalidates it;
GPS callbacks also have a selection-version guard.

Recommendations use the existing server-side Haversine radius boundary. Other
B/A/R/F affect ranking within that boundary; L = 1 for every included room,
regardless of differing locality/address text. Outside rooms are excluded, not
assigned a displayed zero match. There is no distance decay. All Available Rooms ignores this boundary and all other selected
filters. Home's saved-preference recommendations are unchanged.

Configuration: LISTING_GEOCODER_URL defaults to the Photon public demo API. No key,
paid service, new dependency or .env change is needed locally. Existing shared
cache, two-second throttle, six-second timeout, User-Agent and attribution remain.
A shared production cache is required to coordinate limits across workers.
Photon explicitly supports search-as-you-type but requires reasonable usage; its
public demo has no availability guarantee. Use a self-hosted Photon endpoint for
larger workloads. See https://github.com/komoot/photon#demo-server and
https://photon.komoot.io/ for provider capabilities and usage terms.

Validation: Django system check and eleven focused checks passed across targeted runs for scoring,
selection/CSRF/role enforcement, stale/tampered points, radius boundaries,
strict filters, initial navigation, onboarding and persistence. Provider calls
were mocked, and all fixtures were isolated in the test database. Browser
keyboard/touch/layout and live-provider checks remain manual.

## Geographic eligibility and Room Details preference summary

Current requirement supersedes earlier outside-radius scoring: every Recommended
Rooms candidate must be inside a validated selected boundary. Search-context
recommendations without a point return no matches. Home recommendations resolve
saved coordinates or a uniquely resolved saved text location. A failed or ambiguous
saved lookup returns no recommendations; no dummy point or global fallback is used.
The preference schema has no stored radius, so saved-preference entries and direct
Room Details visits use the existing 2 km default. Explicit search radii retain
1/2/5 km choices.

Signed, tenant-bound match_context snapshots include both the factor inputs and
latitude/longitude/radius. Room Details validates the signature, form values and
boundary, then checks the current approved listing using the shared server-side
Haversine candidate query. Only geographically eligible available rooms render
"X% Preference match" and the info popover. Direct visits use complete saved
preferences and the saved-location/default-radius resolution described above.
Unresolved, ambiguous, incomplete, invalid, foreign or outside-radius contexts
render no component at all: no zero-score placeholder, error or fallback score.

All Available Rooms stays independent and shows no match UI. Opening an available
room outside the recommendation boundary still displays normal room details and
retains existing request eligibility. A signed match context never grants listing
access or bypasses visibility rules. Weights and B/A/R/F formulas are unchanged. The approved geographic L rule
replaces the earlier text-only location factor: inside-radius eligibility also
earns the full 30 location points.
The Back to Find Rooms URL retains a validated point binding without re-geocoding.

Three focused isolated checks passed across targeted runs for inside/outside
boundaries, unresolved saved locations, absent search points, card/detail score
consistency, foreign/invalid contexts and unchanged normal room access/request
eligibility. Django system check passed. No browser checks or broad suite ran.


## Shared geographic calculation and validation

listings.distance.room_distance_expression supplies the existing SQL Haversine
calculation (mean Earth radius 6371 km). rooms_within_radius annotates distance_km
and uses the inclusive SQL comparison distance_km <= radius. Both recommendation
cards and Room Details obtain this same annotated distance through that query.
score_room uses within_radius on that returned distance and the same radius;
no second coordinate calculation, name matching, rounding tolerance or distance
bonus is introduced. Boundary equality is included. Display rounding never
participates in eligibility or ranking.

Signed match snapshots continue to retain the same point/radius and scoring
inputs, so Details cannot silently substitute another area. Home resolves the
saved point using the existing unique-resolution policy and 2 km default. Failed
or ambiguous resolution produces no scores. All Available Rooms remains outside
this scoring path, with no match UI, and normal available-room access outside a
recommendation radius is unchanged.

Correction example: if B/A/R/F contribute 55 points and text-based L previously
contributed zero, being geographically inside the chosen radius contributes the
missing 30 points, yielding 85%. Different place-name strings do not change this.

Read-only local inspection found the Sanepa listing at 27.681629, 85.310761;
saved preference coordinates were absent. An active search point is carried in the
browser URL/signed context, not persisted as a database search record, so it was
not inferred from matching place names or silently replaced. No real data changed.

Django check and four focused isolated checks passed for inside/outside/exact
boundary distances, SQL/Python boundary agreement, 55-to-85 correction, card/detail
score and distance equality, unresolved points and preserved outside-room access.
No broad suite, browser validation or live-provider lookup ran.

### Saved search-point lifecycle

Profile and first-search onboarding save explicitly selected autocomplete points
through the preference service. Coordinates stay hidden in the form and travel
with their validated selection metadata. Navbar entry signs the persisted point
and restores all saved factors with the default 2 km radius, without geocoding it
again. Ordinary searches never write preferences.

Legacy text-only preferences show location-setup guidance on Find Rooms. Choose
a suggestion (or a manual map point), then explicitly click **Save location**.
That POST is CSRF-protected and preserves the other saved factors and amenities
under the existing user lock. Ambiguous lookup results require a choice; no first
candidate is silently selected. Initial setup guidance is not a submission error.
