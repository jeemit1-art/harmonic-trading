# Deployment Guide (No VM Required)

This replaces any VM-based setup (Oracle Cloud, AWS, etc.) with two free,
fully browser-based services. Nothing to install on your computer, no
servers to manage, no networking/VCN configuration of any kind.

- **Scanner** (sends you Telegram alerts) runs on **GitHub Actions** --
  GitHub's own machines run your code on a schedule.
- **Dashboard** (optional, for browsing charts/backtests) runs on
  **Render** -- connect your GitHub repo, they build and host it.

---

## Part 1: Get your code on GitHub

If you haven't already: create a GitHub account, create a new **private**
repository, and upload all the files from the unzipped project folder
(drag-and-drop through the browser works fine -- see earlier instructions
if you need the detailed steps).

## Part 2: Set up the Telegram bot

1. Telegram -> **@BotFather** -> `/newbot` -> copy the **token** it gives you.
2. Message your new bot once (anything) so it knows your chat exists.
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser,
   find `"chat":{"id": 123456789,...}`, copy that number -- it's your **chat ID**.

Keep both handy for the next step.

## Part 3: Add your Telegram credentials as GitHub Secrets

Secrets are how you give the scanner your Telegram token *without* it
being visible in your code -- this is the standard, secure way to do it.

1. On your repo's GitHub page, click **Settings** (top tab bar).
2. In the left sidebar: **Secrets and variables** -> **Actions**.
3. Click **New repository secret**.
   - Name: `TELEGRAM_BOT_TOKEN`
   - Value: paste your real bot token
   - Click **Add secret**
4. Click **New repository secret** again.
   - Name: `TELEGRAM_CHAT_ID`
   - Value: paste your real chat ID
   - Click **Add secret**

## Part 4: Allow the workflow to save its progress

The scanner needs to remember what it already alerted on between runs, so
it needs permission to save a small update back to your repo each time it runs.

1. Still in **Settings**, go to **Actions** -> **General** (left sidebar).
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Click **Save**.

## Part 5: Turn on the scanner

The workflow file (`.github/workflows/scanner.yml`) is already included in
your project -- if you uploaded the whole folder to GitHub, it's already there.
GitHub automatically detects it and starts running it on schedule
(every hour, by default). To find it or trigger it manually:

1. On your repo's GitHub page, click the **Actions** tab.
2. You should see **Harmonic Scanner** listed on the left.
3. Click it, then click **Run workflow** (top right) -> **Run workflow** to
   trigger it immediately as a test, instead of waiting for the next hour.
4. Click into the run that appears to watch its progress. Green check = success.
5. Check your Telegram -- if any patterns were found, you'll see alerts;
   either way, check the run's log (click the run -> click "scan" -> expand
   "Run scanner") to see what it found.

**To change how often it runs:** edit `.github/workflows/scanner.yml` in
your repo (click the file on GitHub -> pencil icon to edit) and change the
`cron: '0 * * * *'` line. Cron format is `minute hour day month weekday`;
`0 * * * *` means "every hour, at minute 0". `0 */4 * * *` would mean
every 4 hours. Commit the change and it takes effect on the next scheduled run.

**Note on timing:** GitHub Actions' free scheduled runs can occasionally
be delayed by a few minutes during high load on their systems (their
scheduler is "best effort" on the free tier). For harmonic pattern
trading on 1h/4h/1d timeframes this delay is immaterial.

---

## Part 6 (optional): Host the dashboard on Render

If you want to view charts, run backtests, or check open trades from a
web browser without running anything locally:

1. Go to **render.com** -> sign up (can use your GitHub account to sign in directly).
2. Click **New** -> **Web Service**.
3. Connect your GitHub account if prompted, then select your repo.
4. Configure:
   - **Name**: anything, e.g. `harmonic-dashboard`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0`
   - **Instance Type**: Free
5. Click **Create Web Service**. Render builds and deploys automatically
   (takes a few minutes the first time).
6. Once live, Render gives you a URL like `https://harmonic-dashboard.onrender.com`
   -- that's your dashboard, accessible from any browser, any device.

**Free tier honest limitation:** the free dashboard "sleeps" after about
15 minutes of no visitors, and takes 30-50 seconds to wake back up the
next time you open it. That's fine for occasional checking; it doesn't
affect the scanner/alerts at all, which run separately on GitHub Actions
regardless of whether the dashboard is awake.

---

## Ongoing costs

- **GitHub Actions**: free for the scanner's usage level (a private repo
  gets 2,000 free minutes/month; a single hourly scan of a modest
  watchlist uses a small fraction of that).
- **Telegram bot**: free.
- **Render dashboard**: free tier as described above.
- **Data (yfinance)**: free, unofficial Yahoo Finance endpoint.

**Total: $0/month**, nothing to install, no server to maintain, no
networking configuration of any kind.
