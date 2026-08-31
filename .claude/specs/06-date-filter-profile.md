# Spec: Date Filter On Profile

## Overview
Step 5 made `/profile` read live data from SQLite, but it always shows a
user's *entire* history: the headline numbers, the category bars and the
recent-transactions table are all "all time". This step adds an optional
date-range filter to `/profile` so a signed-in user can ask "what did I
spend in August?" and have all three sections answer for that window
together. It exists now, before add/edit/delete (Steps 7–9), because those
steps extend the same three query helpers — teaching those helpers to take
an optional date range now means Steps 7–9 inherit it for free instead of
growing a fourth query path later. The filter is opt-in: with no query
string, `/profile` behaves exactly as it does today.

## Depends on
- **Step 1** — `database/db.py`, `get_db()`, `init_db()`, the `expenses`
  table with its `date TEXT` column in `YYYY-MM-DD` form
- **Step 3** — sessions carrying `user_id` / `user_name`; the filter is
  scoped to the signed-in user
- **Step 5** — `get_recent_transactions()`, `get_summary_stats()`,
  `get_category_breakdown()`, `_category_totals()`, the `rupees` and `day`
  Jinja filters, and the four-section `profile.html` layout this filter
  sits above

## Routes
No new routes.

`GET /profile` (logged-in) gains two **optional** query-string parameters:

- `start` — inclusive lower bound, `YYYY-MM-DD`
- `end` — inclusive upper bound, `YYYY-MM-DD`

Both may be omitted, given alone, or given together. `GET /profile` with
no query string must render byte-for-byte what it renders today. The
route stays `GET`-only — do **not** add `methods=["GET", "POST"]`; the
filter form submits with `method="get"`.

## Database changes
No database changes. No new tables, columns, indexes or constraints.

`expenses.date` is already `TEXT NOT NULL` in `YYYY-MM-DD`, which sorts
lexicographically the same way it sorts chronologically, so SQL
`date >= ?` and `date <= ?` on plain strings are correct as-is.

The three existing helpers in `database/db.py` gain optional keyword
arguments — signatures change, schema does not:

```python
def get_recent_transactions(user_id, limit=10, start=None, end=None):
def get_summary_stats(user_id, start=None, end=None):
def get_category_breakdown(user_id, start=None, end=None):
```

Each appends `AND date >= ?` and/or `AND date <= ?` to its existing
`WHERE user_id = ?` clause, building the parameter tuple to match. When
both bounds are `None` the emitted SQL and parameters must be identical
to today's, so Step 5's tests keep passing unchanged.

`_category_totals(rows)` is untouched — it aggregates whatever rows it is
given, so it needs no knowledge of the filter.

## Templates
- **Create:** none.
- **Modify:** `templates/profile.html` — insert a new filter section
  between the identity header (section 1) and the headline numbers
  (section 2):
  - `<form class="profile-filter" method="get" action="{{ url_for('profile') }}">`
  - two `<input type="date" name="start">` / `name="end"` fields with
    `<label>`s, each echoing back `{{ start or '' }}` / `{{ end or '' }}`
  - an "Apply" submit button
  - a "Clear" link to `{{ url_for('profile') }}`, rendered **only** when a
    filter is active (`{% if start or end %}`)
  - an error paragraph rendered only when `{% if filter_error %}`
  - when a filter is active, a short caption on the card titles or under
    the stats saying the numbers cover the chosen range
  No other section's markup changes. `base.html` is not touched.

## Files to change
- `app.py` — `profile()` reads `request.args.get("start")` / `("end")`,
  hands them to a new module-level helper, passes the validated range to
  the three DB helpers, and passes `start`, `end` and `filter_error`
  through to the template. New helper `_clean_date_range(start, end)`
  returns `(start, end, error)` — pure `datetime.strptime` validation, no
  SQL, no DB access.
- `database/db.py` — the three optional-argument signatures above and
  their WHERE clauses.
- `templates/profile.html` — the filter form described above.
- `static/css/profile.css` — styles for `.profile-filter` and its
  children.
- `CLAUDE.md` — update the `/profile` row and the `/profile` notes to
  record the optional `start`/`end` params and the extended helper
  signatures.

## Files to create
- `tests/test_date_filter.py` — written in the test phase by the
  test-writer subagent, from this spec rather than from the
  implementation.

No new source files. Per CLAUDE.md, the filter styles belong in the
existing page-scoped `profile.css`, not a new stylesheet and not a
`<style>` block.

## New dependencies
No new dependencies. `datetime.strptime` is stdlib and `datetime` is
already imported in `app.py` for `_member_since()`.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only
- Parameterised queries only — the date bounds are `?` placeholders,
  never f-strings or string concatenation into SQL
- Passwords hashed with werkzeug (`pbkdf2:sha256`) — unchanged by this
  step, no auth code is touched
- Use CSS variables — never hardcode hex values; `profile.css` must
  consume the `:root` names already in `style.css` (`--ink`,
  `--ink-soft`, `--ink-muted`, `--ink-faint`, `--paper`, `--paper-warm`,
  `--paper-card`, `--accent`, `--border`, `--border-soft`,
  `--radius-sm/-md/-lg`, `--font-display`, `--font-body`, …)
- All templates extend `base.html`
- **No SQL in `app.py`** — a test greps `inspect.getsource(app_module.profile)`
  for `SELECT`, `INSERT`, `UPDATE`, `DELETE` and `get_db(`, comments
  included. The new `_clean_date_range()` helper must stay equally clean
- **Default is all time** — omitting both params must produce today's
  exact output. Do not default to "this month"; several Step 5 tests
  count rendered `<time datetime=` elements and category bars against the
  full seeded set
- **Extend the three helpers, do not add a fourth** — CLAUDE.md is
  explicit that Steps 7–9 build on these same three independent queries
- **No new inline styles** — a test asserts every `style="…"` on the
  rendered page matches `^width: \d+%$` (the breakdown bars). The filter
  form gets classes, not inline CSS
- **No hardcoded URLs** — the form `action` and the Clear link both use
  `url_for('profile')`
- **All money stays ₹** — formatting remains the `rupees` filter's job;
  the query layer returns raw numbers
- **Validation rules:** each bound is parsed independently with
  `datetime.strptime(value, "%Y-%m-%d")`. An empty or missing value is
  simply no bound. A value that fails to parse is dropped and sets
  `filter_error`. If both parse but `start > end`, both are dropped and
  `filter_error` is set — never pass a contradictory range to SQL
- Whatever the user typed is echoed back into the form inputs so a bad
  value is visible and correctable; Jinja autoescaping handles it, no
  `|safe`
- The same validated range feeds all three helpers, so the stats, the
  bars and the table can never disagree about which window they describe
- `get_recent_transactions()` keeps `limit=10` and its
  `ORDER BY date DESC, id DESC` tiebreaker; the filter narrows the rows,
  it does not change the ordering or lift the limit
- PEP 8, snake_case, `abort()` for HTTP errors — not bare string returns
- Do not touch the Step 7–9 stub routes

## Definition of done
Run `python app.py` (port 5001), sign in as `demo@spendly.com` /
`demo123`, and verify each item:

1. `GET /profile` with no query string renders exactly as before — same
   transaction rows, same totals, same bars, no visible change beyond the
   new empty filter form
2. The filter form appears between the identity header and the stat
   cards, with two date inputs, an Apply button, and no Clear link
3. Submitting the form navigates to `/profile?start=…&end=…` — the values
   are in the URL, and the page is reachable by pasting that URL fresh
4. With a range that covers only some seeded expenses, the transactions
   table shows only rows whose date falls inside it, bounds included
5. The three headline numbers (total, count, top category) recompute for
   that same range — total equals the sum of the visible rows
6. The category bars recompute for that range, stay sorted largest-first,
   and their percentages still sum to exactly 100
7. `start` alone filters open-ended forward; `end` alone filters
   open-ended backward
8. A range matching nothing shows the existing empty states ("No
   transactions yet." and "Nothing to break down yet.") with total ₹0.00
   and count 0 — no crash, no traceback
9. Both date inputs are repopulated with the active range after
   submitting, and the Clear link appears; clicking it returns to
   unfiltered `/profile`
10. `?start=not-a-date` shows the error message, does not crash, and
    falls back to unfiltered results
11. `?start=2026-12-01&end=2026-01-01` (start after end) shows the error
    message and falls back to unfiltered results
12. `?start=2026-01-01'--` or similar injection text is rejected as an
    invalid date; the database is unharmed and no SQL error surfaces
13. Signing in as a second user with their own expenses and applying the
    same range shows only that user's rows — the filter never widens
    scoping
14. Visiting `/profile?start=…` while signed out still redirects to
    `/login`
15. All currency on the filtered page renders as ₹ with two decimals; no
    `$` anywhere
16. `pytest` passes — every Step 5 test in `tests/test_profile.py` and
    `tests/test_backend_connection.py` still green, unmodified
