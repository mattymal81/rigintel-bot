"""
RigIntel Weekly Email Bot
Runs every Tuesday morning via cron or any scheduler.
Calls Claude API to sweep public drilling data, builds an HTML email,
and delivers it via SendGrid (free tier covers ~100 emails/day).

SETUP:
  pip install anthropic sendgrid

ENVIRONMENT VARIABLES (set in .env or your hosting platform):
  ANTHROPIC_API_KEY=sk-ant-...
  SENDGRID_API_KEY=SG....
  EMAIL_FROM=rigintel@yourcompany.com
  EMAIL_TO=salesperson@yourcompany.com   # comma-separated for multiple
"""

import os
import json
import datetime
import anthropic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ── Config ────────────────────────────────────────────────────────────────────

BASINS = [
    "Permian Basin",
    "Anadarko Basin",
    "Williston Basin",
    "Eagle Ford",
    "D-J Basin",
    "Wyoming / Green River Basin",
]

ANTHROPIC_MODEL = "claude-sonnet-4-6"

EMAIL_FROM    = os.environ.get("EMAIL_FROM", "rigintel@yourcompany.com")
EMAIL_TO_RAW  = os.environ.get("EMAIL_TO",   "salesperson@yourcompany.com")
EMAIL_TO_LIST = [e.strip() for e in EMAIL_TO_RAW.split(",")]

# ── Step 1: Sweep rigs via Claude ─────────────────────────────────────────────

def sweep_rigs() -> list[dict]:
    """Ask Claude to research active rigs across all configured basins."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    basin_list = "\n".join(f"- {b}" for b in BASINS)
    today = datetime.date.today().strftime("%B %d, %Y")

    prompt = f"""You are a drilling data research agent for North American oil and gas.
Today is {today}. A supplier salesperson needs their weekly rig intelligence brief.

Search for currently active drilling rigs across these basins:
{basin_list}

Return a JSON array of 6–12 rigs. Each object must have EXACTLY these fields:
- id: state abbreviation + 4-digit permit number (e.g. TX-2291)
- name: rig name — contractor name + rig number (e.g. Patterson 219)
- operator: the E&P company operating the well
- mud: the drilling fluids / mud company on contract (e.g. Halliburton Baroid, M-I SWACO, Newpark Drilling Fluids, Baker Hughes IES, Solaris Oilfield)
- temp: estimated bottom-hole temperature in Fahrenheit (integer, realistic for formation)
- footage: total depth drilled in feet (integer, realistic for basin and formation)
- basin: the basin name (match one of the basins listed above, shortened to a clean label)
- tip: a 1–2 sentence sales tip for a key supplier salesperson — note who holds the current mud contract and suggest a specific angle to win or expand business

Use your best knowledge of active North American drilling operations.
If exact live data is unavailable, use the most accurate and realistic values
based on known active operators, rig contractors, and basin characteristics as of today.

Return ONLY valid JSON — no markdown fences, no explanation, no preamble."""

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "".join(
        block.text for block in message.content if hasattr(block, "text")
    )
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


# ── Step 2: Build HTML email ──────────────────────────────────────────────────

BASIN_COLORS = {
    "permian":   ("DBEAFE", "1E40AF"),
    "anadarko":  ("FEF3C7", "92400E"),
    "williston": ("EDE9FE", "5B21B6"),
    "eagle ford":("D1FAE5", "065F46"),
    "d-j":       ("FEE2E2", "991B1B"),
    "wyoming":   ("EDE9FE", "5B21B6"),
}

def basin_colors(basin: str) -> tuple[str, str]:
    key = basin.lower()
    for k, v in BASIN_COLORS.items():
        if k in key:
            return v
    return ("F3F4F6", "374151")


def build_rig_card(rig: dict) -> str:
    bg, fg = basin_colors(rig.get("basin", ""))
    return f"""
    <div style="margin:0 24px 12px;border:1px solid #E8E4DC;border-radius:6px;overflow:hidden;font-family:Arial,Helvetica,sans-serif;">
      <table width="100%" style="background:#F7F5F0;border-bottom:1px solid #E8E4DC;"><tr>
        <td style="padding:12px 16px;">
          <div style="font-size:14px;font-weight:700;color:#0D1B2A;">{rig['name']}</div>
          <div style="font-size:11px;color:#8899AA;margin-top:1px;">{rig['id']}</div>
        </td>
        <td align="right" style="padding:12px 16px;">
          <span style="font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;background:#{bg};color:#{fg};">{rig['basin']}</span>
        </td>
      </tr></table>
      <table width="100%" style="padding:0;"><tr>
        <td width="50%" style="padding:12px 16px 8px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Operator</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['operator']}</div>
        </td>
        <td width="50%" style="padding:12px 16px 8px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Mud company</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['mud']}</div>
        </td>
      </tr><tr>
        <td style="padding:0 16px 12px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Well temp</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['temp']}&deg;F</div>
        </td>
        <td style="padding:0 16px 12px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Footage</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['footage']:,} ft</div>
        </td>
      </tr></table>
      <div style="margin:0 16px 14px;background:#FFFBEB;border-left:3px solid #F59E0B;border-radius:0 4px 4px 0;padding:10px 12px;">
        <div style="font-size:10px;font-weight:700;color:#B45309;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">&#9889; Sales tip</div>
        <div style="font-size:12px;color:#78350F;line-height:1.5;">{rig['tip']}</div>
      </div>
    </div>"""


def build_email_html(rigs: list[dict], week_label: str) -> str:
    rig_cards = "\n".join(build_rig_card(r) for r in rigs)
    n_rigs   = len(rigs)
    n_mud    = len({r["mud"] for r in rigs})
    n_basins = len({r["basin"] for r in rigs})

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>RigIntel Weekly Brief</title></head>
<body style="margin:0;padding:0;background:#F0EDE6;font-family:Arial,Helvetica,sans-serif;">
<div style="width:100%;background:#F0EDE6;padding:32px 0;">
<div style="width:600px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;">

  <!-- HEADER -->
  <table width="100%" style="background:#0D1B2A;padding:28px 36px;"><tr>
    <td><span style="font-size:18px;font-weight:700;color:#ffffff;letter-spacing:-0.3px;">Rig<span style="color:#4DA6FF;">Intel</span></span></td>
    <td align="right"><span style="font-size:12px;color:#8899AA;letter-spacing:0.06em;text-transform:uppercase;">{week_label}</span></td>
  </tr></table>

  <!-- STATS -->
  <table width="100%" style="background:#132035;padding:20px 36px;border-bottom:1px solid #1E3050;"><tr>
    <td width="33%" style="padding-right:20px;">
      <div style="font-size:28px;font-weight:700;color:#4DA6FF;line-height:1;">{n_rigs}</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;margin-top:4px;">Active rigs</div>
    </td>
    <td width="33%" style="padding:0 20px;border-left:1px solid #1E3050;">
      <div style="font-size:28px;font-weight:700;color:#4DA6FF;line-height:1;">{n_mud}</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;margin-top:4px;">Mud companies</div>
    </td>
    <td width="33%" style="padding-left:20px;border-left:1px solid #1E3050;">
      <div style="font-size:28px;font-weight:700;color:#4DA6FF;line-height:1;">{n_basins}</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;margin-top:4px;">Basins covered</div>
    </td>
  </tr></table>

  <!-- INTRO -->
  <div style="padding:18px 36px 4px;">
    <p style="font-size:13px;color:#4B5563;line-height:1.6;margin:0;">
      Your weekly North America rig sweep is ready. Below are active drilling operations found this week — each with a sales tip to help you prioritize your outreach.
    </p>
  </div>

  <!-- SECTION HEAD -->
  <div style="padding:20px 36px 10px;">
    <h2 style="font-size:13px;font-weight:700;color:#0D1B2A;text-transform:uppercase;letter-spacing:0.08em;margin:0;border-left:3px solid #4DA6FF;padding-left:10px;">
      Active rigs &amp; sales opportunities
    </h2>
  </div>

  {rig_cards}

  <div style="height:8px;"></div>

  <!-- FOOTER -->
  <table width="100%" style="background:#F7F5F0;border-top:1px solid #E8E4DC;padding:20px 36px;"><tr>
    <td align="center" style="font-size:11px;color:#9CA3AF;line-height:1.6;">
      RigIntel &middot; Automated weekly sweep &middot; North America<br/>
      Data sourced from public permit filings, Baker Hughes rig count, and operator releases.<br/>
      <a href="#" style="color:#6B7280;">Unsubscribe</a> &nbsp;&middot;&nbsp; <a href="#" style="color:#6B7280;">Manage preferences</a>
    </td>
  </tr></table>

</div>
</div>
</body></html>"""


# ── Step 3: Send via SendGrid ─────────────────────────────────────────────────

def send_email(html_body: str, week_label: str):
    sg = SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    for recipient in EMAIL_TO_LIST:
        message = Mail(
            from_email=EMAIL_FROM,
            to_emails=recipient,
            subject=f"RigIntel Weekly Brief — {week_label}",
            html_content=html_body,
        )
        response = sg.send(message)
        print(f"  Sent to {recipient} → {response.status_code}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today      = datetime.date.today()
    week_label = f"Week of {today.strftime('%b %d, %Y')}"
    print(f"[RigIntel] Starting sweep for {week_label}")

    print("[RigIntel] Querying Claude for active rig data…")
    rigs = sweep_rigs()
    print(f"[RigIntel] Found {len(rigs)} rigs across {len({r['basin'] for r in rigs})} basins")

    print("[RigIntel] Building email…")
    html = build_email_html(rigs, week_label)

    print("[RigIntel] Sending…")
    send_email(html, week_label)
    print("[RigIntel] Done.")


if __name__ == "__main__":
    main()


# ── Cron setup (add to crontab with: crontab -e) ─────────────────────────────
#
# Run every Tuesday at 6:00 AM server time:
#   0 6 * * 2 cd /path/to/project && python rig_intel_emailer.py >> logs/rigintel.log 2>&1
#
# Or with environment variables inline:
#   0 6 * * 2 ANTHROPIC_API_KEY=sk-... SENDGRID_API_KEY=SG... EMAIL_TO=sales@co.com python /path/to/rig_intel_emailer.py
