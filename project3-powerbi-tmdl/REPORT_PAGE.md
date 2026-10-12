# The three-visual report page (built by hand in Desktop)

The committed report (`pbip/KlarixApparel.Report`) is an empty page. Writing PBIR visual files by
hand is slow and easy to get wrong, so the page is built in Desktop in a few minutes, for the
screen recording. It does not need to be saved back to git.

Open `pbip/KlarixApparel.pbip`, make sure the model is refreshed (`make p3-refresh`), then add
three visuals. Use only the **Metrics** table's visible measures and the visible columns: implicit
measures are switched off on purpose, so dragging a raw column into a value well will not sum it.

| # | Visual | Axis | Legend | Value | What it shows |
|---|---|---|---|---|---|
| 1 | Line chart | `Order Date` > `month` | `dim_product` > `category` | `items_sold` | The planted category rename: **Sweaters** stops and **Knitwear** starts in October 2025, so each line looks like a break (a decline to zero and a new line from zero). Filter the visual to the two categories to make it obvious |
| 2 | Line chart | `Order Date` > `month` | `dim_product` > `category_family` | `items_sold` | The same data by family: one continuous line across the rename. This is what `category_family` is for |
| 3 | Line chart | `Signup Date` > `month` | none | `attribution_coverage_rate` | Coverage is about 1.0 until February 2026, then about 0.69 to 0.72 from March 2026: the consent-loss problem is visible, not fixable |

Numbers to expect (read from the live model): for Sweaters and Knitwear, items sold per month are
200 (Aug 2025), 211 (Sep 2025), then 201 and 201 under the new name (Oct and Nov 2025).

Steps in Desktop:

1. **Report view** > **Line chart** (three times).
2. Drag the fields as in the table, using the date table's `month` column.
3. Add a visual-level filter: on visual 1, `category` is `Sweaters` or `Knitwear`; on visual 2,
   `category_family` is `sweaters_knitwear`.
4. Check that the hidden `is_internal` column and the key columns do not appear in the field list.
