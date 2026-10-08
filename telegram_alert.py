"""
Telegram delivery. PLAIN TEXT on purpose: v1 used parse_mode=Markdown with raw
dict reprs and underscores, which Telegram rejects with HTTP 400 -- and v1 then
advanced state anyway, so the alert was lost forever. v2 queues every alert in
state['outbox'] and only removes it after Telegram answers ok=true.
"""
import requests
import config
import state as st

MAX_ATTEMPTS = 12


def _configured() -> bool:
    return "PASTE_YOUR" not in config.TELEGRAM_BOT_TOKEN and bool(config.TELEGRAM_CHAT_ID) \
        and "PASTE_YOUR" not in config.TELEGRAM_CHAT_ID


def send_message(text: str) -> tuple[bool, str]:
    if not _configured():
        return False, "telegram not configured"
    try:
        r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                          data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:4000],
                                "disable_web_page_preview": True}, timeout=15)
        ok = r.status_code == 200 and r.json().get("ok", False)
        return ok, "" if ok else f"HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, str(e)


def send_photo(image_bytes: bytes, caption: str = "") -> bool:
    if not _configured():
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto",
                          data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                          files={"photo": ("chart.png", image_bytes, "image/png")}, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def flush_outbox(state: dict) -> dict:
    """Deliver queued alerts in order. Undelivered ones stay queued for the next run."""
    sent = failed = 0
    keep = []
    for a in state["outbox"]:
        ok, err = send_message(a["text"])
        if ok:
            sent += 1
            state["alert_log"].append({"t": st.now_iso(), "kind": a["kind"], "ticker": a["ticker"],
                                       "text": a["text"], "queued_at": a["created"]})
        else:
            a["attempts"] += 1
            a["last_error"] = err
            failed += 1
            if a["attempts"] < MAX_ATTEMPTS:
                keep.append(a)
            else:
                st.log_decision(state, "", a["ticker"], "ALERT_DROPPED", f"gave up after {MAX_ATTEMPTS} attempts: {err}")
    state["outbox"] = keep
    return {"sent": sent, "failed": failed}


# ----------------------------------------------------------------------------- formatting
def _side(pos): return "LONG" if pos["direction"] == "bullish" else "SHORT"


def _fmt(x: float) -> str:
    return f"{x:.5f}" if abs(x) < 20 else f"{x:.2f}"


def fmt_signal(pos: dict, ref_close: float, notes: list[str]) -> str:
    risk_pct = abs(ref_close - pos["stop"]) / ref_close * 100
    lines = [f"NEW SIGNAL: {_side(pos)} {pos['ticker']}  ({pos['market']} {pos['timeframe']})",
             f"{pos['pattern']}  quality {pos['quality']}", "",
             f"Reference close: {_fmt(ref_close)}",
             f"ENTRY: at the next bar's open (market)",
             f"DO NOT CHASE beyond: {_fmt(pos['max_chase'])}  (R:R to T2 falls below {config.MIN_RR_T2})",
             f"STOP: {_fmt(pos['stop'])}   (~{risk_pct:.2f}% risk) -> place it at your broker with the entry",
             f"T1 {_fmt(pos['t1'])} (close 1/3, stop to breakeven)",
             f"T2 {_fmt(pos['t2'])} (close 1/3)",
             f"T3 {_fmt(pos['t3'])} (trail the rest)" if not config.USE_TRAILING_STOP_AFTER_T2
             else f"Last third: trail {config.TRAILING_ATR_MULT}x ATR (no fixed T3)",
             f"Time stop: {config.MAX_HOLD_BARS} bars", ""] + notes
    return "\n".join(lines)


def fmt_event(pos: dict, ev: dict) -> str:
    h = f"{pos['ticker']} {_side(pos)} {pos['pattern']}"
    t, px = ev["type"], _fmt(ev["price"])
    msgs = {
        "ENTERED": f"ENTRY MODELLED: {h}\nFilled at the {ev['bar'][:10]} open: {px}. Stop {_fmt(pos['stop'])}. "
                   f"If you could not get near this price, skip the trade.",
        "T1": f"TAKE PROFIT 1: {h}\nT1 hit ({px}). Close 1/3 now. Move stop to breakeven {_fmt(pos['entry'])}.",
        "T2": f"TAKE PROFIT 2: {h}\nT2 hit ({px}). Close another 1/3. Stop now {_fmt(pos['stop'])}.",
        "T3": f"EXIT ALL: {h}\nT3 hit ({px}). Close the remainder. Trade complete.",
        "STOP": f"STOPPED OUT: {h}\nStop hit, fill {px}. Close any remaining position. Result {pos['r_multiple']:+.2f}R.",
        "BE_STOP": f"EXIT (breakeven stop): {h}\nStopped at {px} after banking partial profit. Result {pos['r_multiple']:+.2f}R.",
        "TRAIL_STOP": f"EXIT (trailing stop): {h}\nTrailing stop hit at {px}. Result {pos['r_multiple']:+.2f}R.",
        "TIME_STOP": f"EXIT (time stop): {h}\nHeld {config.MAX_HOLD_BARS} bars without resolving; closing at {px}. Result {pos['r_multiple']:+.2f}R.",
        "INVALIDATED": f"CANCELLED: {h}\n{ev['note']}",
    }
    return msgs.get(t, f"{t}: {h} @ {px}")
