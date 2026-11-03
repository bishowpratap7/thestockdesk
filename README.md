# The Stock Desk 📈

Stock deep dives by country — five years of price history, behavior
statistics and the latest headlines for the big stocks of six markets.
Pick a country, then pick a stock, and see how it actually behaves:
trend, volatility, drawdowns, and what has been moving it.

- Live page: https://bishowpratap7.github.io/thestockdesk/
- Run by **Bishow Pandey** — follow on X: https://x.com/bishowppandey
- Sister desks: The Dev Desk (developer news), Scroll Patrol (trending
  posts & memes), The World Desk (world news)

## Markets covered
United States (default), United Kingdom, Germany, Japan, India, Canada —
each with its headline index (S&P 500, FTSE 100, DAX, Nikkei 225,
Nifty 50, S&P/TSX) and ten large, well-known stocks. Sixty stocks total.

## What a deep dive shows
- Five-year price chart (with a one-year view), weekly closes
- Returns: 1 week, 1 month, 3 months, 6 months, 1 year, 5 years
- 52-week range and where the price sits inside it
- Trend vs the 50-day and 200-day moving averages
- Annualized volatility, deepest slide (max drawdown) of the past year
- Plain-English "How it has behaved" notes, computed from the data
- Latest headlines for the stock and a short company summary

## How it works
- `tools/scan.py` fetches daily price history from the Yahoo Finance
  chart API (no API key), headlines from Yahoo Finance RSS, and company
  summaries from Wikipedia, computes every statistic, and writes
  `data/stocks.json`. It also bakes an SEO summary of all 60 stocks
  into `index.html` and regenerates `feed.xml` and `sitemap.xml`.
- A GitHub Actions loop (`.github/workflows/loop-scan.yml`) re-runs the
  scanner every 30 minutes around the clock and commits only when the
  data changed; each loop job hands off to its successor, so the desk
  stays current without any external scheduler.
- The page is a single static file — no backend, no build step, no
  tracking. If one ticker's feed fails, the desk keeps its last good
  data and flags it stale rather than blanking the market.

## Repos
- `thestockdesk` (public) — the live site, served by GitHub Pages
- `the-stock-desk` (private) — the archive twin

## Disclaimer
The Stock Desk is an educational information page. Prices come from
Yahoo Finance and may be delayed. Nothing here is financial advice or a
recommendation to buy or sell any security. Investing involves risk;
consult a licensed financial adviser before making decisions.
