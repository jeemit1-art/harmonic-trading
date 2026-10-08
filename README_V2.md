# Harmonic Scanner v2

## Do this in order
1. `pip install -r requirements.txt && python -m pytest tests -q`   (20 tests, ~30s)
2. `python run_universe_backtest.py --market US --n 40 --period 10y`  (needs Yahoo access; repeat per market)
   Read the VERDICT line. NO-GO means the alerts have no demonstrated edge. Do not trade real money.
3. Edit `config.COST_PCT` to your real spread + commission + slippage and rerun step 2.
4. Deploy (below), paper trade >= 2 months, compare live R with the backtest. Only then size up.

## Deploy
- Copy this folder over your repo (keep your own `.git`). Old `trade_state.json` is NOT migrated: close old trades manually.
- Secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; Settings > Actions > Workflow permissions = read and write.
- `.github/workflows/scanner.yml` runs each market after its bars close (UTC cron inside the file).
- Dashboard on Render: set env `STATE_URL=https://raw.githubusercontent.com/<you>/<repo>/main/state_v2.json`
  (and `GITHUB_TOKEN` if the repo is private). No redeploy needed to see fresh state.
- A "SCAN OK <market>" Telegram line arrives every run. If they stop arriving, the system is down.

## Always
Place the STOP as a real order at your broker when you enter. A scanner that runs after the bar closes can never
beat an intraday stop touch; the alerts are for decisions, the broker order is for protection.

## Where things are
- Dashboard (local):  `streamlit run dashboard.py`  ->  http://localhost:8501
- Dashboard (online): deploy on Render (start command `streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0`), set `STATE_URL`.
- Backtest, no install: GitHub repo -> Actions -> "Backtest (manual)" -> Run workflow -> open the run -> read the log / download the artifact.
- Backtest, local:  `python run_universe_backtest.py --market US --n 0 --period 10y`
- Dead tickers:  `python validate_watchlists.py`
