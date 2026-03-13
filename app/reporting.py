from datetime import date, datetime, timezone

from app.alert_dispatcher import send_text_message
from app.signal_repository import performance_daily


def daily_report_preview(target_date: date | None = None) -> dict:
    target = target_date or datetime.now(timezone.utc).date()
    metrics = performance_daily(target)
    headline = "Forex Daily Summary"
    summary_lines = [
        f"{metrics['total_signals']} signals generated",
        f"{metrics['resolved_signals']} resolved, {metrics['wins']} wins, {metrics['losses']} losses",
        f"Win rate: {metrics['win_rate']}%" if metrics["win_rate"] is not None else "Win rate: n/a",
        f"Open signals: {metrics['open_signals']}",
    ]
    return {
        "date": target.isoformat(),
        "headline": headline,
        "summary_lines": summary_lines,
        "metrics": metrics,
    }


def send_daily_report(target_date: date | None = None) -> bool:
    preview = daily_report_preview(target_date)
    metrics = preview["metrics"]
    message = "\n".join([
        f"*{preview['headline']}*",
        f"Date: `{preview['date']}`",
        f"Signals: `{metrics['total_signals']}`",
        f"BUY / SELL / HOLD: `{metrics['buy_signals']}` / `{metrics['sell_signals']}` / `{metrics['hold_signals']}`",
        f"Resolved: `{metrics['resolved_signals']}`",
        f"Wins / Losses / Neutral: `{metrics['wins']}` / `{metrics['losses']}` / `{metrics['neutral']}`",
        f"Win rate: `{metrics['win_rate']}%`" if metrics["win_rate"] is not None else "Win rate: `n/a`",
        f"Avg return: `{metrics['avg_return_pct']}%`" if metrics["avg_return_pct"] is not None else "Avg return: `n/a`",
        f"Telegram sent: `{metrics['telegram_sent']}`",
        f"Open signals: `{metrics['open_signals']}`",
    ])
    return send_text_message(message)
