# Debenhams stock alert

A GitHub Actions cron job that watches a single Debenhams product and emails
[duncan.ramsay@gmail.com](mailto:duncan.ramsay@gmail.com) when it goes **back in
stock**.

**Watched product:** Norfolk Leisure "Royce Executive 3m Cantilever with Taupe
Canopy, Cover & Base" — £539.00, SKU `M5060694431646`, sold by Norfolk Leisure
Lifestyle Limited.

[Product page »](https://www.debenhams.com/product/norfolk-leisure-royce-executive-3m-cantilever-with-taupe-canopy-cover-base_p-55c70e19-7f48-4b73-a2e7-6622028fb3c2)

## How it works

- **[`check_stock.py`](check_stock.py)** does a plain HTTPS `GET` of the product
  page with a realistic desktop Chrome `User-Agent`. The stock status is in the
  raw server-rendered HTML, so no headless browser is needed.
  - The page is treated as **OUT OF STOCK** whenever the HTML still contains
    `Out of Stock`.
  - It is treated as **IN STOCK** (the alert condition) when that text is gone
    and/or an "Add to Basket" / "Add to Bag" control appears.
  - If the fetch fails (non-200, timeout, network error) or the expected product
    markup is missing, the script logs the problem, reports status `UNKNOWN`,
    and **never** emails. It will not send a false in-stock alert.
- **[`.github/workflows/stock-check.yml`](.github/workflows/stock-check.yml)**
  runs the script on a `*/30 * * * *` schedule (every 30 min; Actions cron can
  lag a few minutes under load) and on manual `workflow_dispatch`.
- **State guard:** [`state.json`](state.json) records the last known status. The
  email is only sent on the **out → in** transition, so you get one alert rather
  than one every 30 minutes while the item stays in stock. The workflow commits
  the updated `state.json` back to the branch after each run (with `[skip ci]`
  so the commit doesn't trigger another run).

## Required repository secrets

Set these under **Settings → Secrets and variables → Actions → New repository
secret**. Nothing is hardcoded.

| Secret | Description | Example |
| --- | --- | --- |
| `SMTP_SERVER` | SMTP host | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port (implicit TLS) | `465` |
| `SMTP_USERNAME` | SMTP login / from address | `you@gmail.com` |
| `SMTP_PASSWORD` | SMTP password | Gmail **app password** (not your normal password) |

### Using Gmail

1. Enable 2-Step Verification on the Google account.
2. Create an **App password** (Google Account → Security → App passwords) and use
   that 16-character value as `SMTP_PASSWORD`.
3. Use `SMTP_SERVER=smtp.gmail.com`, `SMTP_PORT=465`, and your Gmail address for
   `SMTP_USERNAME`.

Any other SMTP provider works too — just set the four secrets accordingly. The
workflow uses implicit TLS (`secure: true`), which pairs with port `465`. If your
provider needs STARTTLS on port `587`, set `SMTP_PORT=587` and change `secure:
true` to `secure: false` in the workflow.

## The email

- **To:** duncan.ramsay@gmail.com
- **Subject:** `IN STOCK: Royce Executive 3m Cantilever (£539) — Debenhams`
- **Body:** the current price plus the direct product URL.

Delivery is handled by the
[`dawidd6/action-send-mail`](https://github.com/dawidd6/action-send-mail) action.

## Running it manually

Once the secrets are set, go to the **Actions** tab → **Debenhams stock check** →
**Run workflow** to trigger it on demand (`workflow_dispatch`). The run logs show
the detected status; an email is sent only if the item is in stock and wasn't
already flagged as in stock on a prior run.

## Local testing

```bash
python check_stock.py
```

This prints the detected status and writes/updates `state.json`. It sends no
email locally (email is only sent by the workflow step). To force a fresh
transition test, set the seed status back to `OUT_OF_STOCK` in `state.json`.
