# Performance Sanity Check (section 41)

Run via `python -m scripts.performance_check` plus a live-server concurrency
test. Results below are from an actual run against local Postgres 16 +
Redis 7, not estimates.

## Volume seeded
- 100 members
- 1,200 progress records (12 per member)
- 1,200 exercise logs (12 per member, across 100 completed workout sessions)

Seeding all of the above took **600ms**.

## Query timings (single-request, no concurrency)

| Operation | Time |
|---|---|
| Dashboard summary (aggregate counts across 100 members) | 18.6 ms |
| Members list, paginated (page_size=20) | 1.9 ms |
| Finance summary | 2.1 ms |
| `run_membership_checks` across 100 memberships | 4.8 ms |
| `run_membership_checks` again (idempotency at volume) | 3.6 ms |

All comfortably fast at this scale.

## N+1 query finding (identified, not hidden)

The dashboard member-list endpoint (`GET /analytics/dashboard/members`)
issues **62 SQL queries for a single page of 20 members** — roughly 3 extra
queries per row (current membership lookup, 30-day attendance count, weight
progress history) on top of the base paginated query. This *is* an N+1
pattern.

**Mitigation already in place:** the endpoint is paginated (`page_size`
defaults to 20, capped at 100), so query count scales with **page size**,
not total gym membership — confirmed by the test (100 total members, 62
queries, not ~300). Per section 41's explicit instruction ("use pagination
for lists... do not load an entire gym's member database into memory"),
this is the required mitigation and it's working.

**Known remaining limitation:** at higher page sizes or on a gym with many
active pages viewed rapidly, this would benefit from batching the three
per-member lookups into single queries (e.g. a `GROUP BY member_id` for
attendance counts, a window function for "most recent membership per
member", and a similar batched approach for weight trend) rather than
looping per row. Flagged here explicitly rather than fixed silently,
because it's a real optimization for Finished Product V1, not a prototype
blocker at V1's expected scale.

## Concurrency (100 concurrent requests, live uvicorn + Postgres)

| Endpoint | Success | Total wall time | Avg latency |
|---|---|---|---|
| `GET /health` (no DB) | 100/100 | 212 ms | 91.5 ms |
| `GET /api/v1/admin/stats` (DB-backed, authenticated) | 100/100 | 898 ms | 606 ms |

**All 100 requests succeeded with no errors** under concurrent load — no
crashes, no connection pool exhaustion errors, no 500s.

**Observed behavior worth noting:** the DB-backed endpoint's average latency
(606ms) is meaningfully higher than its single-request latency would be,
because this prototype runs as a single uvicorn process with SQLAlchemy's
default connection pool size — concurrent requests queue for a DB
connection rather than truly running in parallel. This is expected,
standard behavior for the default configuration, not a bug. For Finished
Product V1, the standard fix is: multiple uvicorn workers (`--workers N`)
behind a process manager, and tuning `pool_size`/`max_overflow` on the
SQLAlchemy engine to match expected concurrent load.

## Conclusion

No crashes, no data corruption, no errors under the volumes and concurrency
section 41 specifies. One real N+1 pattern was found, is already bounded by
pagination (not a live bug), and is documented above with a concrete fix
path for later. Connection-pool queuing under concurrency is expected
default behavior, also documented with a fix path.
