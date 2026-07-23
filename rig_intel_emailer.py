"""
RigIntel Weekly Email Bot — v6 (dashboard edition)
- Sweeps 8 basins via Claude
- Saves data to public/data/rigs.json (powers the Vercel dashboard)
- Sends a slim luxury email with top leads + link to full dashboard

SETUP:  pip install anthropic sendgrid
ENV:    ANTHROPIC_API_KEY, SENDGRID_API_KEY, EMAIL_FROM, EMAIL_TO, DASHBOARD_URL
"""

import os, json, time, datetime
import anthropic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ── Config ────────────────────────────────────────────────────────────────────

BASINS = [
    "Permian Basin","Midland Basin","Anadarko Basin","Williston Basin",
    "Eagle Ford","D-J Basin","Wyoming / Green River Basin","Haynesville Shale",
]
RIGS_PER_BASIN       = 8
LOOKAHEAD_PER_BASIN  = 5
SPUD_LOOKBACK_WEEKS  = 6
LOOKAHEAD_WEEKS      = 8
ANTHROPIC_MODEL      = "claude-sonnet-4-6"
DELAY                = 1

EMAIL_FROM     = os.environ.get("EMAIL_FROM",     "mattmalouf81@gmail.com")
EMAIL_TO_LIST  = [e.strip() for e in os.environ.get("EMAIL_TO","mattmalouf81@gmail.com").split(",")]
DASHBOARD_URL  = os.environ.get("DASHBOARD_URL",  "https://rigintel-bot.vercel.app")
DATA_FILE      = os.path.join(os.path.dirname(__file__), "public", "data", "rigs.json")

# ── Claude calls ──────────────────────────────────────────────────────────────

def _claude(client, prompt):
    msg  = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=2000,
                                  messages=[{"role":"user","content":prompt}])
    raw  = "".join(b.text for b in msg.content if hasattr(b,"text"))
    return raw.replace("```json","").replace("```","").strip()

def sweep_active(client, basin, today_s, cutoff_s):
    prompt = f"""Drilling data research agent. Today: {today_s}. Basin: {basin}.
Return JSON array of up to {RIGS_PER_BASIN} rigs spudded between {cutoff_s} and {today_s}.
Each object EXACTLY: id, name (contractor+rig number), operator, mud (company),
temp (int F), footage (int ft drilled so far), basin: "{basin}",
spud_date (YYYY-MM-DD in window),
priority (int 1-10, 10=best sales opportunity),
tip (1-2 sentences: current mud vendor + specific angle to win business)
Vary contractors/operators/mud companies. Return ONLY valid JSON array."""
    try:
        rigs = json.loads(_claude(client, prompt))
        print(f"  v {basin} [active]: {len(rigs)}")
        return _clamp(rigs, "spud_date",
                      datetime.date.fromisoformat(cutoff_s), datetime.date.today())
    except Exception as e:
        print(f"  x {basin} [active]: {e}"); return []

def sweep_lookahead(client, basin, today_s, end_s):
    prompt = f"""Drilling data research agent. Today: {today_s}. Basin: {basin}.
Return JSON array of up to {LOOKAHEAD_PER_BASIN} permitted-but-not-yet-spudded wells
expected to spud in {basin} between {today_s} and {end_s}.
Each object EXACTLY: id, permit_date (YYYY-MM-DD), operator, basin: "{basin}",
formation, est_spud_date (YYYY-MM-DD between {today_s} and {end_s}),
est_depth (int ft), est_temp (int F), likely_mud (company name),
priority (int 1-10, 10=most urgent pre-spud opportunity),
tip (1-2 sentences: why call NOW before mud contract awarded, name likely vendor)
Sort by est_spud_date ascending. Return ONLY valid JSON array."""
    try:
        rigs = json.loads(_claude(client, prompt))
        print(f"  v {basin} [ahead]: {len(rigs)}")
        return _clamp_ahead(rigs, datetime.date.today(),
                            datetime.date.today()+datetime.timedelta(weeks=LOOKAHEAD_WEEKS))
    except Exception as e:
        print(f"  x {basin} [ahead]: {e}"); return []

def pick_top(client, active, upcoming):
    if not active and not upcoming: return None
    sample = (active[:3]+upcoming[:2])
    prompt = f"""Senior oil and gas sales strategist.
Pick the single best opportunity for a drilling fluids supplier from: {json.dumps(sample)}
Return JSON object: chosen_id, headline (8-10 word punchy reason this is top lead),
insight (2-3 sentence strategic expansion on the opportunity)
Return ONLY valid JSON object."""
    try:
        result = json.loads(_claude(client, prompt))
        cid    = result.get("chosen_id","")
        rig    = next((r for r in active+upcoming if r.get("id")==cid), (active+upcoming)[0])
        rig["_headline"] = result.get("headline","")
        rig["_insight"]  = result.get("insight","")
        return rig
    except: return None

def week_summary(client, active, upcoming):
    prompt = f"""Oil and gas market analyst. Write ONE punchy insight-rich sentence (max 30 words)
summarizing this week's North America drilling activity for a mud company salesperson.
Active spuds: {len(active)} across {list({r.get("basin") for r in active})}.
Upcoming permits: {len(upcoming)}. Return plain text only."""
    try: return _claude(client, prompt).strip().strip('"').strip("'")
    except: return f"{len(active)} active spuds and {len(upcoming)} permitted rigs across North America."

def _clamp(rigs, field, lo, hi):
    out = []
    for r in rigs:
        try:
            sd=datetime.date.fromisoformat(r.get(field,""))
            r[field]=sd.isoformat() if lo<=sd<=hi else hi.isoformat()
        except: r[field]=hi.isoformat()
        out.append(r)
    return out

def _clamp_ahead(rigs, lo, hi):
    out = []
    for r in rigs:
        try:
            sd=datetime.date.fromisoformat(r.get("est_spud_date",""))
            if lo<=sd<=hi:
                r["est_spud_date"]=sd.isoformat(); out.append(r)
        except: pass
    return out

def sweep_all():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(weeks=SPUD_LOOKBACK_WEEKS)
    end    = today + datetime.timedelta(weeks=LOOKAHEAD_WEEKS)
    ts,cs  = today.strftime("%B %d, %Y"), cutoff.isoformat()
    es     = end.strftime("%B %d, %Y")

    active, upcoming = [], []
    for i, basin in enumerate(BASINS):
        print(f"  [{i+1}/{len(BASINS)}] {basin}")
        active.extend(sweep_active(client, basin, ts, cs))
        time.sleep(DELAY)
        upcoming.extend(sweep_lookahead(client, basin, ts, es))
        if i < len(BASINS)-1: time.sleep(DELAY)

    active.sort(key=lambda r: r.get("spud_date","1900-01-01"), reverse=True)
    upcoming.sort(key=lambda r: r.get("est_spud_date","9999-12-31"))

    print("  Selecting top lead...")
    top = pick_top(client, active, upcoming)
    print("  Writing week summary...")
    summary = week_summary(client, active, upcoming)
    return active, upcoming, top, summary

# ── Save JSON for dashboard ───────────────────────────────────────────────────

def save_dashboard_data(active, upcoming, top, summary, week_label):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    payload = {
        "week":     week_label,
        "summary":  summary,
        "top":      top,
        "active":   active,
        "upcoming": upcoming,
        "generated": datetime.datetime.utcnow().isoformat()+"Z"
    }
    with open(DATA_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  Saved {len(active)} active + {len(upcoming)} upcoming to {DATA_FILE}")

# ── Build slim email ──────────────────────────────────────────────────────────

BASIN_COLORS = {
    "permian":("DBEAFE","1E40AF"),"midland":("EDE9FE","4C1D95"),
    "anadarko":("FEF3C7","78350F"),"williston":("F3E8FF","4C1D95"),
    "eagle ford":("D1FAE5","064E3B"),"d-j":("FEE2E2","7F1D1D"),
    "wyoming":("E0F2FE","0C4A6E"),"haynesville":("DCFCE7","14532D"),
}
def bcol(basin):
    k=basin.lower()
    for key,v in BASIN_COLORS.items():
        if key in k: return v
    return ("F3F4F6","374151")

def top5_cards(active, upcoming):
    top5 = (active[:3]+upcoming[:2])
    cards = ""
    for i, r in enumerate(top5):
        is_a = "spud_date" in r
        bg,fg = bcol(r.get("basin",""))
        name  = r.get("name","") if is_a else r.get("operator","")
        mud   = r.get("mud","—") if is_a else r.get("likely_mud","—")
        date  = r.get("spud_date","") if is_a else r.get("est_spud_date","")
        try:
            dt   = datetime.date.fromisoformat(date)
            diff = (datetime.date.today()-dt).days if is_a else (dt-datetime.date.today()).days
            dlabel = f"{diff}d ago" if is_a else f"in {diff}d"
        except: dlabel = "—"
        tip_bg = "FFFBEB" if is_a else "EFF6FF"
        tip_border = "F59E0B" if is_a else "3B82F6"
        tip_color = "78350F" if is_a else "1E3A5F"
        cards += f"""
    <div style="margin:0 24px 10px;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;">
      <table width="100%" style="background:#F8FAFC;border-bottom:1px solid #E2E8F0;"><tr>
        <td style="padding:10px 14px;">
          <span style="font-size:10px;color:#8899AA;font-weight:700;">#{i+1}</span>
          &nbsp;<span style="font-size:13px;font-weight:700;color:#0F172A;">{name}</span>
          <div style="font-size:10px;color:#94A3B8;margin-top:1px;">{r.get("id","")}</div>
        </td>
        <td align="right" style="padding:10px 14px;">
          <span style="font-size:10px;padding:2px 8px;border-radius:20px;font-weight:600;background:#{bg};color:#{fg};">{r.get("basin","")}</span>
          <div style="font-size:10px;color:#94A3B8;margin-top:3px;">{dlabel}</div>
        </td>
      </tr></table>
      <table width="100%"><tr>
        <td width="50%" style="padding:8px 14px;">
          <div style="font-size:9px;color:#94A3B8;text-transform:uppercase;letter-spacing:.06em;">Operator</div>
          <div style="font-size:12px;color:#1E293B;font-weight:500;margin-top:1px;">{r.get("operator","—")}</div>
        </td>
        <td width="50%" style="padding:8px 14px;">
          <div style="font-size:9px;color:#94A3B8;text-transform:uppercase;letter-spacing:.06em;">Mud company</div>
          <div style="font-size:12px;color:#1E293B;font-weight:500;margin-top:1px;">{mud}</div>
        </td>
      </tr></table>
      <div style="margin:0 14px 10px;background:#{tip_bg};border-left:2px solid #{tip_border};padding:7px 10px;border-radius:0 3px 3px 0;">
        <div style="font-size:11px;color:#{tip_color};line-height:1.5;">{r.get("tip","")}</div>
      </div>
    </div>"""
    return cards

def build_email(active, upcoming, top, summary, week_label):
    n_a, n_u = len(active), len(upcoming)
    cards    = top5_cards(active, upcoming)
    top_hl   = (top or {}).get("_headline","") if top else ""
    top_ins  = (top or {}).get("_insight","")  if top else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>RigIntel · {week_label}</title></head>
<body style="margin:0;padding:0;background:#0A0F1E;font-family:Arial,Helvetica,sans-serif;">
<div style="width:100%;background:#0A0F1E;padding:28px 0 40px;">
<div style="width:600px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.5);">

  <div style="background:#0A0F1E;padding:5px 24px;">
    <span style="font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#334155;">Confidential · For internal use only</span>
  </div>

  <div style="background:#0D1B2A;padding:28px 32px 22px;">
    <table width="100%"><tr>
      <td>
        <div style="font-size:24px;font-weight:700;letter-spacing:-1px;color:#fff;">RIG<span style="color:#4DA6FF;">INTEL</span></div>
        <div style="font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#475569;margin-top:3px;">North America · Weekly Briefing</div>
      </td>
      <td align="right">
        <div style="font-size:10px;color:#475569;">{week_label}</div>
        <div style="margin-top:6px;">
          <span style="font-size:18px;font-weight:700;color:#34D399;">{n_a}</span>
          <span style="font-size:10px;color:#475569;margin-left:3px;">active</span>
          &nbsp;&nbsp;
          <span style="font-size:18px;font-weight:700;color:#60A5FA;">{n_u}</span>
          <span style="font-size:10px;color:#475569;margin-left:3px;">upcoming</span>
        </div>
      </td>
    </tr></table>
    <div style="margin-top:14px;background:rgba(255,255,255,.05);border-left:3px solid #4DA6FF;padding:10px 14px;border-radius:0 5px 5px 0;">
      <div style="font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#4DA6FF;margin-bottom:3px;">Weekly outlook</div>
      <div style="font-size:12px;color:#CBD5E1;line-height:1.6;">{summary}</div>
    </div>
  </div>

  {'<div style="background:#0F2744;padding:20px 32px;border-bottom:3px solid #1E3A5C;"><div style="font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#3B82F6;margin-bottom:8px;">Top lead this week</div><div style="font-size:18px;font-weight:700;color:#fff;letter-spacing:-.3px;margin-bottom:6px;">'+top_hl+'</div><div style="font-size:12px;color:#93C5FD;line-height:1.6;">'+top_ins+'</div></div>' if top_hl else ""}

  <div style="padding:20px 36px 8px;">
    <h2 style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#0F172A;margin:0 0 4px;border-left:3px solid #4DA6FF;padding-left:10px;">
      This week's top 5 leads
    </h2>
    <p style="font-size:12px;color:#6B7280;margin:0 0 14px;padding-left:13px;">Active spuds first, then upcoming permits. Full list on the dashboard.</p>
  </div>

  {cards}

  <div style="margin:8px 24px 20px;text-align:center;">
    <a href="{DASHBOARD_URL}" style="display:inline-block;background:#1D4ED8;color:#fff;font-size:14px;font-weight:700;padding:14px 32px;border-radius:8px;text-decoration:none;letter-spacing:-.1px;">
      Open full briefing &rarr;
    </a>
    <div style="font-size:11px;color:#94A3B8;margin-top:10px;">
      {n_a + n_u} total leads &middot; filter by basin &middot; search by operator or mud company
    </div>
  </div>

  <div style="background:#F7F5F0;border-top:1px solid #E8E4DC;padding:16px 32px;text-align:center;">
    <div style="font-size:11px;color:#9CA3AF;line-height:1.6;">
      RigIntel &middot; Automated weekly sweep &middot; North America<br/>
      Data estimated from public permit filings, Baker Hughes rig count, and operator releases.<br/>
      <a href="#" style="color:#6B7280;">Unsubscribe</a> &nbsp;&middot;&nbsp; <a href="#" style="color:#6B7280;">Manage preferences</a>
    </div>
  </div>

</div>
</div>
</body></html>"""

# ── Send email ────────────────────────────────────────────────────────────────

def send_email(html, week_label, n_a, n_u):
    sg = SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    subject = f"RigIntel — {n_a} spuds · {n_u} upcoming · {week_label}"
    for to in EMAIL_TO_LIST:
        r = sg.send(Mail(from_email=EMAIL_FROM, to_emails=to,
                         subject=subject, html_content=html))
        print(f"  Sent to {to} -> {r.status_code}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today         = datetime.date.today()
    week_label    = f"Week of {today.strftime('%b %d, %Y')}"

    print("[RigIntel] v6 — dashboard edition")
    print(f"[RigIntel] {len(BASINS)} basins · {RIGS_PER_BASIN} active + {LOOKAHEAD_PER_BASIN} upcoming per basin")

    active, upcoming, top, summary = sweep_all()
    print(f"[RigIntel] Active: {len(active)} | Upcoming: {len(upcoming)}")

    if not active and not upcoming:
        print("[RigIntel] No data returned — check API keys."); return

    print("[RigIntel] Saving dashboard data...")
    save_dashboard_data(active, upcoming, top, summary, week_label)

    print("[RigIntel] Building email...")
    html = build_email(active, upcoming, top, summary, week_label)

    print("[RigIntel] Sending email...")
    send_email(html, week_label, len(active), len(upcoming))
    print("[RigIntel] Done.")

if __name__ == "__main__":
    main()
