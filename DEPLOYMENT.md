# Deployment Guide

## 1. Run locally first (do this before touching a VM)

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

Open the URL it prints (usually http://localhost:8501). Use the **Scan Now**
and **Backtest** tabs to sanity-check the system on real tickers before you
rely on it for anything.

## 2. Set up the Telegram bot (5 minutes)

1. Open Telegram, message **@BotFather**, send `/newbot`, follow the
   prompts. It gives you a token like `123456789:ABCdefGhIJKlmnoPQRstuVWXyz`.
2. Paste that token into `config.py` -> `TELEGRAM_BOT_TOKEN`.
3. Send your new bot any message (e.g. "hi") so it knows your chat exists.
4. Visit this URL in your browser (with your real token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Find `"chat":{"id": 123456789, ...}` in the JSON response, copy that
   number into `config.py` -> `TELEGRAM_CHAT_ID`.
6. Test it:
   ```bash
   python3 -c "from telegram_alert import send_telegram_message as s; s('Test alert from harmonic scanner')"
   ```
   You should get a message on Telegram within seconds.

## 3. Cloud VM setup (Oracle Cloud Free Tier -- $0/month)

1. Sign up at oracle.com/cloud/free (needs a card for verification, won't
   be charged on the Always Free tier).
2. Create a VM instance: shape = "VM.Standard.A1.Flex" (ARM, Always Free
   eligible), 1-2 OCPUs / 6GB RAM is plenty. Image = Ubuntu 22.04 or 24.04.
3. Open port 8501 in the VM's security list/network security group if you
   want to access the dashboard remotely (Scanner alone doesn't need any
   open ports -- it just pushes to Telegram).
4. SSH in and set up:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git
   git clone <your-repo-or-scp-the-folder-here>
   cd harmonic_trading
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
5. Edit `config.py` with your real Telegram token/chat ID.

## 4. Schedule the scanner (cron)

Runs every hour by default (matches `SCAN_INTERVAL_MINUTES` in config,
though cron itself is what actually controls timing -- keep them in sync):

```bash
crontab -e
```
Add:
```
0 * * * * cd /home/ubuntu/harmonic_trading && /home/ubuntu/harmonic_trading/venv/bin/python3 scanner.py >> scanner.log 2>&1
```
For forex (which trades outside standard equity hours), you may want a
tighter interval, e.g. every 30 min: `*/30 * * * *`.

## 5. Run the dashboard persistently (systemd)

Create `/etc/systemd/system/harmonic-dashboard.service`:
```ini
[Unit]
Description=Harmonic Trading Dashboard
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/harmonic_trading
ExecStart=/home/ubuntu/harmonic_trading/venv/bin/streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now harmonic-dashboard
```
Visit `http://<your-vm-public-ip>:8501`. Consider putting this behind a
password (Streamlit doesn't have built-in auth) via an nginx reverse proxy
with basic auth, since it'll be reachable by anyone who finds the IP.

## 6. Ongoing costs

- Oracle Cloud Always Free VM: **$0/month**, no time limit.
- Telegram bot: **$0**.
- Data (yfinance): **$0**, but it's Yahoo's unofficial endpoint -- it can
  rate-limit or change without notice. If it ever gets flaky, drop in a
  paid data source (e.g. Twelve Data, Polygon.io, or your broker's API) by
  writing a new class in `data_sources.py` with the same `.fetch()` signature.

Total: **effectively free** to run continuously.
