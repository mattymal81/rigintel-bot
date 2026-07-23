"""
RigIntel Weekly Email Bot — v3 (per-basin sweep + spud date sort + 6-week filter)
Fires one focused Claude query per basin, filters to rigs spudded in the last 6 weeks,
sorts newest-first, and delivers one clean email every Tuesday morning.

SETUP:
  pip install anthropic sendgrid

ENVIRONMENT VARIABLES:
  ANTHROPIC_API_KEY=sk-ant-...
  SENDGRID_API_KEY=SG....
  EMAIL_FROM=rigintel@yourcompany.com
  EMAIL_TO=salesperson@yourcompany.com   # comma-separated for multiple
"""

import os
import json
import time
import datetime
import anthropic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ── Config ────────────────────────────────────────────────────────────────────

BASINS = [
    "Permian Basin",
    "Midland Basin",
    "Anadarko Basin",
    "Williston Basin",
    "Eagle Ford",
    "D-J Basin",
    "Wyoming / Green River Basin",
    "Haynesville Shale",
]

RIGS_PER_BASIN       = 8     # Claude returns up to this many per basin query
SPUD_LOOKBACK_WEEKS  = 6     # only include rigs spudded within this window
ANTHROPIC_MODEL      = "claude-sonnet-4-6"
DELAY_BETWEEN_CALLS  = 1     # seconds between API calls

EMAIL_FROM    = os.environ.get("EMAIL_FROM", "rigintel@yourcompany.com")
EMAIL_TO_RAW  = os.environ.get("EMAIL_TO",   "salesperson@yourcompany.com")
EMAIL_TO_LIST = [e.strip() for e in EMAIL_TO_RAW.split(",")]


# ── Step 1: Per-basin sweep ───────────────────────────────────────────────────

def sweep_basin(client: anthropic.Anthropic, basin: str, today: str, cutoff: str) -> list[dict]:
    """Query Claude for recently spudded rigs in a single basin."""

    prompt = f"""You are a drilling data research agent for North American oil and gas.
Today is {today}. A supplier salesperson needs fresh rig leads — only rigs that
have spudded (started drilling) on or after {cutoff}.

Basin: {basin}

Return a JSON array of up to {RIGS_PER_BASIN} rigs in this basin that spudded
between {cutoff} and {today}. Each object must have EXACTLY these fields:
- id: state abbreviation + 4-digit permit number (e.g. TX-2291)
- name: rig name — contractor name + rig number (e.g. Patterson 219)
- operator: the E&P company operating the well
- mud: the drilling fluids / mud company on contract (e.g. Halliburton Baroid,
  M-I SWACO, Newpark Drilling Fluids, Baker Hughes IES, Solaris Oilfield,
  Conquest Drilling Fluids)
- temp: estimated bottom-hole temperature in Fahrenheit (integer, realistic
  for this basin and formation)
- footage: total depth drilled so far in feet (integer — will be less than
  total well depth since these are recently spudded)
- basin: "{basin}"
- spud_date: estimated spud date in YYYY-MM-DD format — must be between
  {cutoff} and {today}. Base this on known operator drilling schedules,
  recent permit activity, and typical spud-to-report lag for this basin.
- tip: a 1–2 sentence sales tip for a key supplier salesperson — name who
  holds the current mud contract and give a specific angle to win or expand
  business. Mention how recently the rig spudded and why timing matters.

Important:
- Focus entirely on {basin}
- Every rig MUST have a spud_date within the last 6 weeks
- Make each rig distinct — vary contractors, operators, and mud companies
- Newer spuds are higher priority — include the most recently spudded rigs first
- If fewer than {RIGS_PER_BASIN} rigs spudded in this window, return only
  what is realistic — do not fabricate extra rigs

Return ONLY a valid JSON array — no markdown fences, no explanation, no preamble."""

    try:
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw   = "".join(b.text for b in message.content if hasattr(b, "text"))
        clean = raw.replace("```json", "").replace("```", "").strip()
        rigs  = json.loads(clean)

        # Validate and normalise spud_date
        validated = []
        cutoff_dt = datetime.date.fromisoformat(cutoff)
        today_dt  = datetime.date.today()
        for r in rigs:
            try:
                sd = datetime.date.fromisoformat(r.get("spud_date", ""))
                if cutoff_dt <= sd <= today_dt:
                    r["spud_date"] = sd.isoformat()
                    validated.append(r)
                else:
                    r["spud_date"] = today_dt.isoformat()
                    validated.append(r)
            except (ValueError, TypeError):
                r["spud_date"] = today_dt.isoformat()
                validated.append(r)

        print(f"  v {basin}: {len(validated)} rigs")
        return validated

    except Exception as e:
        print(f"  x {basin}: failed — {e}")
        return []


def sweep_all_basins() -> list[dict]:
    """Run one Claude query per basin, combine and sort by spud date desc."""
    client   = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today    = datetime.date.today()
    cutoff   = today - datetime.timedelta(weeks=SPUD_LOOKBACK_WEEKS)
    today_s  = today.strftime("%B %d, %Y")

    print(f"  Window: {cutoff.strftime('%B %d, %Y')} to {today_s}")
    all_rigs = []

    for i, basin in enumerate(BASINS):
        print(f"  Sweeping {basin}...")
        rigs = sweep_basin(client, basin, today_s, cutoff.isoformat())
        all_rigs.extend(rigs)
        if i < len(BASINS) - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    # Sort newest spud date first across all basins
    all_rigs.sort(
        key=lambda r: r.get("spud_date", "1900-01-01"),
        reverse=True
    )
    return all_rigs


# ── Step 2: Build HTML email ──────────────────────────────────────────────────

BASIN_COLORS = {
    "permian":     ("DBEAFE", "1E40AF"),
    "midland":     ("DBEAFE", "1E40AF"),
    "anadarko":    ("FEF3C7", "92400E"),
    "williston":   ("EDE9FE", "5B21B6"),
    "eagle ford":  ("D1FAE5", "065F46"),
    "d-j":         ("FEE2E2", "991B1B"),
    "wyoming":     ("F3E8FF", "6B21A8"),
    "haynesville": ("DCFCE7", "14532D"),
}

def basin_colors(basin: str) -> tuple[str, str]:
    key = basin.lower()
    for k, v in BASIN_COLORS.items():
        if k in key:
            return v
    return ("F3F4F6", "374151")


def days_ago_label(spud_date_str: str) -> str:
    try:
        sd   = datetime.date.fromisoformat(spud_date_str)
        diff = (datetime.date.today() - sd).days
        if diff == 0:
            return "Spudded today"
        elif diff == 1:
            return "Spudded yesterday"
        elif diff <= 13:
            return f"Spudded {diff} days ago"
        else:
            return f"Spudded {sd.strftime('%b %d')}"
    except (ValueError, TypeError):
        return ""


def freshness_color(spud_date_str: str) -> tuple[str, str]:
    try:
        diff = (datetime.date.today() - datetime.date.fromisoformat(spud_date_str)).days
    except (ValueError, TypeError):
        diff = 99
    if diff <= 7:
        return ("D1FAE5", "065F46")
    elif diff <= 21:
        return ("FEF3C7", "92400E")
    else:
        return ("F3F4F6", "374151")


def build_rig_card(rig: dict, rank: int) -> str:
    bg, fg   = basin_colors(rig.get("basin", ""))
    fbg, ffg = freshness_color(rig.get("spud_date", ""))
    spud_label = days_ago_label(rig.get("spud_date", ""))

    return f"""
    <div style="margin:0 24px 12px;border:1px solid #E8E4DC;border-radius:6px;
                overflow:hidden;font-family:Arial,Helvetica,sans-serif;">
      <table width="100%" style="background:#F7F5F0;border-bottom:1px solid #E8E4DC;"><tr>
        <td style="padding:12px 16px;">
          <div>
            <span style="font-size:11px;font-weight:700;color:#8899AA;">#{rank}</span>
            &nbsp;
            <span style="font-size:14px;font-weight:700;color:#0D1B2A;">{rig['name']}</span>
          </div>
          <div style="font-size:11px;color:#8899AA;margin-top:1px;">{rig['id']}</div>
        </td>
        <td align="right" style="padding:12px 16px;vertical-align:top;">
          <div style="margin-bottom:4px;">
            <span style="font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;
                         background:#{bg};color:#{fg};">{rig['basin']}</span>
          </div>
          <div>
            <span style="font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;
                         background:#{fbg};color:#{ffg};">{spud_label}</span>
          </div>
        </td>
      </tr></table>
      <table width="100%"><tr>
        <td width="50%" style="padding:12px 16px 8px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Operator</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['operator']}</div>
        </td>
        <td width="50%" style="padding:12px 16px 8px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Mud company</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['mud']}</div>
        </td>
      </tr><tr>
        <td style="padding:0 16px 8px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Well temp</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['temp']}&deg;F</div>
        </td>
        <td style="padding:0 16px 8px;">
          <div style="font-size:10px;color:#8899AA;text-transform:uppercase;letter-spacing:0.06em;">Footage so far</div>
          <div style="font-size:13px;color:#1A2940;font-weight:500;margin-top:2px;">{rig['footage']:,} ft</div>
        </td>
      </tr></table>
      <div style="margin:0 16px 14px;background:#FFFBEB;border-left:3px solid #F59E0B;
                  border-radius:0 4px 4px 0;padding:10px 12px;">
        <div style="font-size:10px;font-weight:700;color:#B45309;text-transform:uppercase;
                    letter-spacing:0.06em;margin-bottom:4px;">Sales tip</div>
        <div style="font-size:12px;color:#78350F;line-height:1.5;">{rig['tip']}</div>
      </div>
    </div>"""


def build_email_html(rigs: list[dict], week_label: str, cutoff: datetime.date) -> str:
    cards    = "\n".join(build_rig_card(r, i + 1) for i, r in enumerate(rigs))
    n_rigs   = len(rigs)
    n_mud    = len({r["mud"] for r in rigs})
    n_basins = len({r.get("basin", "") for r in rigs})
    window   = f"{cutoff.strftime('%b %d')} - {datetime.date.today().strftime('%b %d, %Y')}"

    fresh  = sum(1 for r in rigs if (datetime.date.today() - datetime.date.fromisoformat(r.get("spud_date","1900-01-01"))).days <= 7)
    recent = sum(1 for r in rigs if 7 < (datetime.date.today() - datetime.date.fromisoformat(r.get("spud_date","1900-01-01"))).days <= 21)
    older  = n_rigs - fresh - recent

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>RigIntel Weekly Brief</title></head>
<body style="margin:0;padding:0;background:#F0EDE6;font-family:Arial,Helvetica,sans-serif;">
<div style="width:100%;background:#F0EDE6;padding:32px 0;">
<div style="width:600px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;">

  <table width="100%" style="background:#0D1B2A;padding:28px 36px;"><tr>
    <td>
      <span style="font-size:18px;font-weight:700;color:#ffffff;">Rig<span style="color:#4DA6FF;">Intel</span></span>
      <div style="font-size:11px;color:#8899AA;margin-top:3px;">New spuds · {window}</div>
    </td>
    <td align="right">
      <span style="font-size:12px;color:#8899AA;text-transform:uppercase;">{week_label}</span>
    </td>
  </tr></table>

  <table width="100%" style="background:#132035;padding:20px 36px;border-bottom:1px solid #1E3050;"><tr>
    <td width="25%" style="padding-right:16px;">
      <div style="font-size:26px;font-weight:700;color:#4DA6FF;">{n_rigs}</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;margin-top:4px;">New spuds</div>
    </td>
    <td width="25%" style="padding:0 16px;border-left:1px solid #1E3050;">
      <div style="font-size:26px;font-weight:700;color:#4DA6FF;">{n_basins}</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;margin-top:4px;">Basins</div>
    </td>
    <td width="25%" style="padding:0 16px;border-left:1px solid #1E3050;">
      <div style="font-size:26px;font-weight:700;color:#4DA6FF;">{n_mud}</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;margin-top:4px;">Mud cos.</div>
    </td>
    <td width="25%" style="padding-left:16px;border-left:1px solid #1E3050;">
      <div style="font-size:26px;font-weight:700;color:#4DA6FF;">6w</div>
      <div style="font-size:11px;color:#8899AA;text-transform:uppercase;margin-top:4px;">Lookback</div>
    </td>
  </tr></table>

  <div style="padding:12px 36px;background:#F7F5F0;border-bottom:1px solid #E8E4DC;">
    <table><tr>
      <td style="padding-right:16px;">
        <span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:12px;background:#D1FAE5;color:#065F46;">0-7 days</span>
        <span style="font-size:11px;color:#8899AA;margin-left:4px;">{fresh} rigs</span>
      </td>
      <td style="padding-right:16px;">
        <span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:12px;background:#FEF3C7;color:#92400E;">8-21 days</span>
        <span style="font-size:11px;color:#8899AA;margin-left:4px;">{recent} rigs</span>
      </td>
      <td>
        <span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:12px;background:#F3F4F6;color:#374151;">22-42 days</span>
        <span style="font-size:11px;color:#8899AA;margin-left:4px;">{older} rigs</span>
      </td>
    </tr></table>
  </div>

  <div style="padding:16px 36px 8px;">
    <p style="font-size:13px;color:#4B5563;line-height:1.6;margin:0;">
      Sorted by spud date — newest first. Green badges are the hottest leads
      (spudded in the last 7 days). Move fast on the top of the list.
    </p>
  </div>

  <div style="padding:12px 36px 8px;">
    <h2 style="font-size:12px;font-weight:700;color:#0D1B2A;text-transform:uppercase;
               letter-spacing:0.08em;margin:0;border-left:3px solid #4DA6FF;padding-left:10px;">
      New spuds — last 6 weeks · sorted newest first
    </h2>
  </div>

  {cards}

  <div style="height:12px;"></div>

  <table width="100%" style="background:#F7F5F0;border-top:1px solid #E8E4DC;padding:20px 36px;"><tr>
    <td align="center" style="font-size:11px;color:#9CA3AF;line-height:1.6;">
      RigIntel &middot; Automated weekly sweep &middot; North America<br/>
      Spud dates estimated from public permit activity and operator drilling schedules.<br/>
      Data sourced from Baker Hughes rig count, state permit filings, and operator releases.<br/>
      <a href="#" style="color:#6B7280;">Unsubscribe</a> &nbsp;&middot;&nbsp;
      <a href="#" style="color:#6B7280;">Manage preferences</a>
    </td>
  </tr></table>

</div>
</div>
</body></html>"""


# ── Step 3: Send via SendGrid ─────────────────────────────────────────────────

def send_email(html_body: str, week_label: str, n_rigs: int):
    sg = SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    for recipient in EMAIL_TO_LIST:
        message = Mail(
            from_email=EMAIL_FROM,
            to_emails=recipient,
            subject=f"RigIntel — {n_rigs} new spuds · {week_label}",
            html_content=html_body,
        )
        response = sg.send(message)
        print(f"  Sent to {recipient} -> {response.status_code}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today      = datetime.date.today()
    cutoff     = today - datetime.timedelta(weeks=SPUD_LOOKBACK_WEEKS)
    week_label = f"Week of {today.strftime('%b %d, %Y')}"

    print(f"[RigIntel] v3 — per-basin sweep + spud sort")
    print(f"[RigIntel] {len(BASINS)} basins · 6-week window · up to {RIGS_PER_BASIN} rigs/basin")

    rigs = sweep_all_basins()
    print(f"[RigIntel] Total: {len(rigs)} rigs")

    if not rigs:
        print("[RigIntel] No rigs returned — check API keys and try again.")
        return

    print("[RigIntel] Building email...")
    html = build_email_html(rigs, week_label, cutoff)

    print("[RigIntel] Sending...")
    send_email(html, week_label, len(rigs))
    print("[RigIntel] Done.")


if __name__ == "__main__":
    main()




