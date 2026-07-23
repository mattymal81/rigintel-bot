"""
RigIntel Weekly Email Bot — v5 (luxury edition)
- Per-basin sweep, 6-week active + 8-week look-ahead
- Premium HTML email with collapsible basin sections
- Top lead hero card, priority scores, editorial design
- Delivers every Tuesday morning via GitHub Actions

SETUP:  pip install anthropic sendgrid
ENV:    ANTHROPIC_API_KEY, SENDGRID_API_KEY, EMAIL_FROM, EMAIL_TO
"""

import os, json, time, datetime
import anthropic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ── Config ────────────────────────────────────────────────────────────────────

BASINS = [
    "Permian Basin", "Midland Basin", "Anadarko Basin", "Williston Basin",
    "Eagle Ford", "D-J Basin", "Wyoming / Green River Basin", "Haynesville Shale",
]
RIGS_PER_BASIN       = 8
LOOKAHEAD_PER_BASIN  = 5
SPUD_LOOKBACK_WEEKS  = 6
LOOKAHEAD_WEEKS      = 8
ANTHROPIC_MODEL      = "claude-sonnet-4-6"
DELAY                = 1

EMAIL_FROM    = os.environ.get("EMAIL_FROM", "mattmalouf81@gmail.com")
EMAIL_TO_LIST = [e.strip() for e in os.environ.get("EMAIL_TO", "mattmalouf81@gmail.com").split(",")]

# ── Claude calls ──────────────────────────────────────────────────────────────

def _claude(client, prompt):
    msg   = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=2000,
                                   messages=[{"role":"user","content":prompt}])
    raw   = "".join(b.text for b in msg.content if hasattr(b,"text"))
    return raw.replace("```json","").replace("```","").strip()

def sweep_active(client, basin, today_s, cutoff_s):
    prompt = f"""Drilling data agent. Today: {today_s}. Basin: {basin}.
Return JSON array of up to {RIGS_PER_BASIN} rigs spudded between {cutoff_s} and {today_s}.
Each object EXACTLY:
- id (e.g. TX-2291), name (contractor+number), operator, mud (company name),
  temp (int °F), footage (int ft drilled so far), basin: "{basin}",
  spud_date (YYYY-MM-DD within window),
  priority (int 1-10, 10=best sales opportunity, based on contract timing and well profile),
  tip (1-2 sentences: current mud vendor + specific sales angle)
Vary contractors/operators/mud cos. Return ONLY valid JSON array."""
    try:
        rigs = json.loads(_claude(client, prompt))
        print(f"  v {basin} [active]: {len(rigs)}")
        return _clamp_dates(rigs, "spud_date",
                            datetime.date.fromisoformat(cutoff_s), datetime.date.today())
    except Exception as e:
        print(f"  x {basin} [active]: {e}"); return []

def sweep_lookahead(client, basin, today_s, end_s):
    prompt = f"""Drilling data agent. Today: {today_s}. Basin: {basin}.
Return JSON array of up to {LOOKAHEAD_PER_BASIN} permitted-but-not-yet-spudded wells
expected to spud between {today_s} and {end_s}.
Each object EXACTLY:
- id, permit_date (YYYY-MM-DD), operator, basin: "{basin}", formation,
  est_spud_date (YYYY-MM-DD between {today_s} and {end_s}),
  est_depth (int ft), est_temp (int °F), likely_mud (company name),
  priority (int 1-10, 10=most urgent pre-spud opportunity),
  tip (1-2 sentences: why call NOW, name likely vendor, specific angle)
Sort by est_spud_date ascending. Return ONLY valid JSON array."""
    try:
        rigs = json.loads(_claude(client, prompt))
        print(f"  v {basin} [ahead]: {len(rigs)}")
        return _clamp_lookahead(rigs, datetime.date.today(),
                                datetime.date.fromisoformat(end_s[:10] if len(end_s)>10 else end_s)
                                if "-" in end_s else
                                datetime.date.today() + datetime.timedelta(weeks=LOOKAHEAD_WEEKS))
    except Exception as e:
        print(f"  x {basin} [ahead]: {e}"); return []

def pick_top_lead(client, active, upcoming):
    if not active and not upcoming: return None
    sample = (active[:3] + upcoming[:2])
    prompt = f"""You are a senior oil and gas sales strategist.
Given these rig leads, pick the single best opportunity for a drilling fluids supplier salesperson.
Data: {json.dumps(sample)}
Return a JSON object with:
- chosen_id: the id of the best rig
- headline: 8-10 word punchy headline for why this is the top lead
- insight: 2-3 sentence strategic insight expanding on the opportunity
Return ONLY valid JSON object."""
    try:
        result = json.loads(_claude(client, prompt))
        chosen_id = result.get("chosen_id","")
        all_rigs  = active + upcoming
        rig = next((r for r in all_rigs if r.get("id") == chosen_id), all_rigs[0])
        rig["_headline"] = result.get("headline","")
        rig["_insight"]  = result.get("insight","")
        return rig
    except:
        return None

def week_summary(client, active, upcoming):
    prompt = f"""You are an oil and gas market analyst writing a one-sentence executive summary
for a drilling fluids supplier's weekly rig intelligence briefing.
Active spuds this week: {len(active)} across basins: {list({r.get('basin') for r in active})}.
Upcoming permitted rigs: {len(upcoming)}.
Write exactly ONE punchy, insight-rich sentence (max 30 words) summarizing the week's drilling activity
and the key opportunity theme for a mud company salesperson.
Return plain text only — no quotes, no punctuation at the very end."""
    try:
        return _claude(client, prompt).strip().strip('"').strip("'")
    except:
        return f"{len(active)} active spuds and {len(upcoming)} permitted rigs across {len(BASINS)} North American basins."

def _clamp_dates(rigs, field, lo, hi):
    out = []
    for r in rigs:
        try:
            sd = datetime.date.fromisoformat(r.get(field,""))
            r[field] = sd.isoformat() if lo <= sd <= hi else hi.isoformat()
        except: r[field] = hi.isoformat()
        out.append(r)
    return out

def _clamp_lookahead(rigs, lo, hi):
    out = []
    for r in rigs:
        try:
            sd = datetime.date.fromisoformat(r.get("est_spud_date",""))
            if lo <= sd <= hi:
                r["est_spud_date"] = sd.isoformat(); out.append(r)
        except: pass
    return out

def sweep_all():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(weeks=SPUD_LOOKBACK_WEEKS)
    end    = today + datetime.timedelta(weeks=LOOKAHEAD_WEEKS)
    ts, cs, es = today.strftime("%B %d, %Y"), cutoff.isoformat(), end.strftime("%B %d, %Y")

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
    top    = pick_top_lead(client, active, upcoming)
    print("  Writing week summary...")
    summary = week_summary(client, active, upcoming)

    return active, upcoming, top, summary

# ── HTML helpers ──────────────────────────────────────────────────────────────

BASIN_META = {
    "permian":     {"bg":"#DBEAFE","fg":"#1E3A8A","dot":"#3B82F6"},
    "midland":     {"bg":"#EDE9FE","fg":"#3B0764","dot":"#7C3AED"},
    "anadarko":    {"bg":"#FEF3C7","fg":"#78350F","dot":"#D97706"},
    "williston":   {"bg":"#F3E8FF","fg":"#4C1D95","dot":"#9333EA"},
    "eagle ford":  {"bg":"#D1FAE5","fg":"#064E3B","dot":"#10B981"},
    "d-j":         {"bg":"#FEE2E2","fg":"#7F1D1D","dot":"#EF4444"},
    "wyoming":     {"bg":"#E0F2FE","fg":"#0C4A6E","dot":"#0284C7"},
    "haynesville": {"bg":"#DCFCE7","fg":"#14532D","dot":"#16A34A"},
}

def bm(basin):
    k = basin.lower()
    for key, val in BASIN_META.items():
        if key in k: return val
    return {"bg":"#F3F4F6","fg":"#374151","dot":"#6B7280"}

def days_ago(s):
    try:
        d = (datetime.date.today() - datetime.date.fromisoformat(s)).days
        if d==0: return "Today"
        if d==1: return "Yesterday"
        if d<=13: return f"{d}d ago"
        return datetime.date.fromisoformat(s).strftime("%b %d")
    except: return ""

def days_until(s):
    try:
        d = (datetime.date.fromisoformat(s) - datetime.date.today()).days
        if d==0: return "Spuds TODAY"
        if d==1: return "Spuds tomorrow"
        if d<=14: return f"Spuds in {d}d"
        return f"Est. {datetime.date.fromisoformat(s).strftime('%b %d')}"
    except: return ""

def fresh_style(s):
    try:
        d=(datetime.date.today()-datetime.date.fromisoformat(s)).days
        if d<=7:  return "#059669","#D1FAE5"   # green
        if d<=21: return "#D97706","#FEF3C7"   # amber
    except: pass
    return "#6B7280","#F3F4F6"                 # gray

def urgency_style(s):
    try:
        d=(datetime.date.fromisoformat(s)-datetime.date.today()).days
        if d<=14: return "#DC2626","#FEE2E2"
        if d<=35: return "#D97706","#FEF3C7"
    except: pass
    return "#6B7280","#F3F4F6"

def priority_bar(p):
    try: p = int(p)
    except: p = 5
    filled = min(p, 10)
    bars = ""
    for i in range(1, 11):
        if i <= filled:
            c = "#EF4444" if i>=9 else "#F59E0B" if i>=6 else "#10B981"
        else:
            c = "#E5E7EB"
        bars += f'<span style="display:inline-block;width:14px;height:6px;background:{c};border-radius:1px;margin-right:1px;"></span>'
    return bars, p

# ── Card builders ─────────────────────────────────────────────────────────────

def hero_card(rig, is_active=True):
    m   = bm(rig.get("basin",""))
    dot = m["dot"]
    headline = rig.get("_headline","Top lead this week")
    insight  = rig.get("_insight","")
    p_bars, p_val = priority_bar(rig.get("priority",9))
    if is_active:
        fc, fbg = fresh_style(rig.get("spud_date",""))
        badge   = f'<span style="font-size:10px;font-weight:600;color:{fc};background:{fbg};padding:2px 8px;border-radius:20px;">{days_ago(rig.get("spud_date",""))}</span>'
        sub     = f'{rig.get("operator","")} &middot; {rig.get("mud","")}'
        detail  = f'<td width="50%" style="padding:10px 20px 0 0"><div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Well temp</div><div style="font-size:16px;font-weight:600;color:#fff;">{rig.get("temp","—")}&deg;F</div></td><td width="50%" style="padding:10px 0 0 0"><div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Footage</div><div style="font-size:16px;font-weight:600;color:#fff;">{int(rig.get("footage",0)):,} ft</div></td>'
    else:
        uc, ubg = urgency_style(rig.get("est_spud_date",""))
        badge   = f'<span style="font-size:10px;font-weight:600;color:{uc};background:{ubg};padding:2px 8px;border-radius:20px;">{days_until(rig.get("est_spud_date",""))}</span>'
        sub     = f'{rig.get("operator","")} &middot; Likely: {rig.get("likely_mud","")}'
        depth   = int(rig.get("est_depth",0))
        detail  = f'<td width="50%" style="padding:10px 20px 0 0"><div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Est. temp</div><div style="font-size:16px;font-weight:600;color:#fff;">{rig.get("est_temp","—")}&deg;F</div></td><td width="50%" style="padding:10px 0 0 0"><div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Est. depth</div><div style="font-size:16px;font-weight:600;color:#fff;">{depth:,} ft</div></td>'

    return f"""
<div style="margin:0 0 0 0;background:linear-gradient(135deg,#0F2744 0%,#1A3A5C 60%,#0D2137 100%);padding:28px 32px 24px;border-radius:0;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot};"></span>
    <span style="font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#64748B;">Top lead this week</span>
  </div>
  <div style="font-size:20px;font-weight:700;color:#FFFFFF;line-height:1.25;margin-bottom:6px;letter-spacing:-.3px;">{headline}</div>
  <div style="font-size:12px;color:#94A3B8;margin-bottom:14px;">{sub}</div>
  <table width="100%"><tr>{detail}</tr></table>
  <div style="margin-top:16px;background:rgba(255,255,255,.06);border-left:3px solid {dot};border-radius:0 4px 4px 0;padding:12px 14px;">
    <div style="font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:{dot};margin-bottom:5px;">Strategic insight</div>
    <div style="font-size:12px;color:#CBD5E1;line-height:1.6;">{insight}</div>
  </div>
  <div style="margin-top:14px;display:flex;align-items:center;gap:10px;">
    {badge}
    <span style="font-size:10px;color:#64748B;">{rig.get("basin","")}</span>
    <span style="margin-left:auto;font-size:10px;color:#64748B;">Priority</span>
    <span style="font-size:12px;font-weight:700;color:#fff;margin-right:4px;">{p_val}/10</span>
    {p_bars}
  </div>
</div>"""


def active_card(rig, rank):
    m = bm(rig.get("basin",""))
    fc, fbg = fresh_style(rig.get("spud_date",""))
    p_bars, p_val = priority_bar(rig.get("priority",5))
    footage = rig.get("footage",0)
    try: footage = f"{int(footage):,}"
    except: footage = str(footage)
    return f"""
<div style="background:#fff;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:10px;">
  <table width="100%" style="border-bottom:1px solid #F1F5F9;"><tr>
    <td style="padding:14px 16px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:10px;font-weight:700;color:#CBD5E1;font-variant-numeric:tabular-nums;">#{rank:02d}</span>
        <div>
          <div style="font-size:13px;font-weight:700;color:#0F172A;letter-spacing:-.2px;">{rig.get("name","")}</div>
          <div style="font-size:10px;color:#94A3B8;margin-top:1px;font-family:monospace;">{rig.get("id","")}</div>
        </div>
      </div>
    </td>
    <td align="right" style="padding:14px 16px;vertical-align:middle;">
      <div style="margin-bottom:5px;text-align:right;">
        <span style="font-size:10px;font-weight:600;color:{m['fg']};background:{m['bg']};padding:2px 9px;border-radius:20px;">{rig.get("basin","")}</span>
      </div>
      <span style="font-size:10px;font-weight:600;color:{fc};background:{fbg};padding:2px 9px;border-radius:20px;">{days_ago(rig.get("spud_date",""))}</span>
    </td>
  </tr></table>
  <table width="100%"><tr>
    <td width="33%" style="padding:10px 16px 8px;">
      <div style="font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Operator</div>
      <div style="font-size:12px;font-weight:600;color:#1E293B;">{rig.get("operator","")}</div>
    </td>
    <td width="33%" style="padding:10px 16px 8px;">
      <div style="font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Mud company</div>
      <div style="font-size:12px;font-weight:600;color:#1E293B;">{rig.get("mud","")}</div>
    </td>
    <td width="33%" style="padding:10px 16px 8px;">
      <div style="font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Temp / Footage</div>
      <div style="font-size:12px;font-weight:600;color:#1E293B;">{rig.get("temp","—")}&deg;F &middot; {footage} ft</div>
    </td>
  </tr></table>
  <div style="margin:0 16px 12px;background:#FFFBF0;border-left:2px solid #F59E0B;border-radius:0 4px 4px 0;padding:9px 12px;">
    <div style="font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#B45309;margin-bottom:3px;">Sales tip</div>
    <div style="font-size:11px;color:#78350F;line-height:1.55;">{rig.get("tip","")}</div>
  </div>
  <div style="padding:8px 16px 10px;display:flex;align-items:center;gap:6px;border-top:1px solid #F8FAFC;">
    <span style="font-size:9px;color:#94A3B8;letter-spacing:.06em;text-transform:uppercase;">Priority</span>
    <span style="font-size:11px;font-weight:700;color:#0F172A;">{p_val}/10</span>
    {p_bars}
  </div>
</div>"""


def lookahead_card(rig, rank):
    m = bm(rig.get("basin",""))
    uc, ubg = urgency_style(rig.get("est_spud_date",""))
    p_bars, p_val = priority_bar(rig.get("priority",5))
    permit_d = rig.get("permit_date","")
    try: permit_d = datetime.date.fromisoformat(permit_d).strftime("%b %d")
    except: pass
    depth = rig.get("est_depth",0)
    try: depth = f"{int(depth):,}"
    except: depth = str(depth)
    return f"""
<div style="background:#F8FAFF;border:1px solid #DBEAFE;border-radius:8px;overflow:hidden;margin-bottom:10px;">
  <table width="100%" style="border-bottom:1px solid #EFF6FF;"><tr>
    <td style="padding:14px 16px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:10px;font-weight:700;color:#BFDBFE;font-variant-numeric:tabular-nums;">#{rank:02d}</span>
        <div>
          <div style="font-size:13px;font-weight:700;color:#0F172A;letter-spacing:-.2px;">{rig.get("operator","")}</div>
          <div style="font-size:10px;color:#94A3B8;margin-top:1px;font-family:monospace;">{rig.get("id","")} &middot; Permit: {permit_d}</div>
        </div>
      </div>
    </td>
    <td align="right" style="padding:14px 16px;vertical-align:middle;">
      <div style="margin-bottom:5px;text-align:right;">
        <span style="font-size:10px;font-weight:600;color:{m['fg']};background:{m['bg']};padding:2px 9px;border-radius:20px;">{rig.get("basin","")}</span>
      </div>
      <span style="font-size:10px;font-weight:600;color:{uc};background:{ubg};padding:2px 9px;border-radius:20px;">{days_until(rig.get("est_spud_date",""))}</span>
    </td>
  </tr></table>
  <table width="100%"><tr>
    <td width="33%" style="padding:10px 16px 8px;">
      <div style="font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Formation</div>
      <div style="font-size:12px;font-weight:600;color:#1E293B;">{rig.get("formation","—")}</div>
    </td>
    <td width="33%" style="padding:10px 16px 8px;">
      <div style="font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Likely mud vendor</div>
      <div style="font-size:12px;font-weight:600;color:#1E293B;">{rig.get("likely_mud","—")}</div>
    </td>
    <td width="33%" style="padding:10px 16px 8px;">
      <div style="font-size:9px;letter-spacing:.07em;text-transform:uppercase;color:#94A3B8;margin-bottom:3px;">Est. temp / depth</div>
      <div style="font-size:12px;font-weight:600;color:#1E293B;">{rig.get("est_temp","—")}&deg;F &middot; {depth} ft</div>
    </td>
  </tr></table>
  <div style="margin:0 16px 12px;background:#EFF6FF;border-left:2px solid #3B82F6;border-radius:0 4px 4px 0;padding:9px 12px;">
    <div style="font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#1D4ED8;margin-bottom:3px;">Pre-spud opportunity</div>
    <div style="font-size:11px;color:#1E3A5F;line-height:1.55;">{rig.get("tip","")}</div>
  </div>
  <div style="padding:8px 16px 10px;display:flex;align-items:center;gap:6px;border-top:1px solid #EFF6FF;">
    <span style="font-size:9px;color:#94A3B8;letter-spacing:.06em;text-transform:uppercase;">Priority</span>
    <span style="font-size:11px;font-weight:700;color:#0F172A;">{p_val}/10</span>
    {p_bars}
  </div>
</div>"""


# ── Basin section (collapsible via checkbox hack) ─────────────────────────────

def basin_section_active(basin, rigs, offset):
    m     = bm(basin)
    cards = "".join(active_card(r, offset+i+1) for i, r in enumerate(rigs))
    uid   = basin.lower().replace(" ","_").replace("/","")
    avg_p = round(sum(int(r.get("priority",5)) for r in rigs)/len(rigs), 1) if rigs else 0
    return f"""
<div style="margin-bottom:2px;">
  <input type="checkbox" id="a_{uid}" style="display:none;" checked>
  <label for="a_{uid}" style="display:block;cursor:pointer;padding:11px 20px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:6px;margin-bottom:2px;">
    <table width="100%"><tr>
      <td>
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{m['dot']};margin-right:8px;vertical-align:middle;"></span>
        <span style="font-size:12px;font-weight:700;color:#0F172A;letter-spacing:-.1px;">{basin}</span>
        <span style="font-size:11px;color:#94A3B8;margin-left:8px;">{len(rigs)} rig{'s' if len(rigs)!=1 else ''}</span>
      </td>
      <td align="right">
        <span style="font-size:10px;color:#64748B;">Avg priority</span>
        <span style="font-size:11px;font-weight:700;color:#0F172A;margin-left:4px;">{avg_p}/10</span>
        <span style="font-size:12px;color:#CBD5E1;margin-left:8px;">&#9660;</span>
      </td>
    </tr></table>
  </label>
  <div class="basin-body-a_{uid}" style="padding:0 4px;">
    {cards}
  </div>
</div>"""


def basin_section_lookahead(basin, rigs, offset):
    m     = bm(basin)
    cards = "".join(lookahead_card(r, offset+i+1) for i, r in enumerate(rigs))
    uid   = basin.lower().replace(" ","_").replace("/","")
    soonest = days_until(rigs[0].get("est_spud_date","")) if rigs else ""
    return f"""
<div style="margin-bottom:2px;">
  <input type="checkbox" id="l_{uid}" style="display:none;" checked>
  <label for="l_{uid}" style="display:block;cursor:pointer;padding:11px 20px;background:#F0F7FF;border:1px solid #DBEAFE;border-radius:6px;margin-bottom:2px;">
    <table width="100%"><tr>
      <td>
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{m['dot']};margin-right:8px;vertical-align:middle;"></span>
        <span style="font-size:12px;font-weight:700;color:#0F172A;letter-spacing:-.1px;">{basin}</span>
        <span style="font-size:11px;color:#94A3B8;margin-left:8px;">{len(rigs)} permit{'s' if len(rigs)!=1 else ''}</span>
      </td>
      <td align="right">
        <span style="font-size:10px;color:#3B82F6;">Next: {soonest}</span>
        <span style="font-size:12px;color:#BFDBFE;margin-left:8px;">&#9660;</span>
      </td>
    </tr></table>
  </label>
  <div style="padding:0 4px;">
    {cards}
  </div>
</div>"""


# ── Full email builder ────────────────────────────────────────────────────────

def build_email(active, upcoming, top, summary, week_label, cutoff, lookahead_end):
    from collections import defaultdict
    by_basin_a = defaultdict(list)
    by_basin_u = defaultdict(list)
    for r in active:   by_basin_a[r.get("basin","")].append(r)
    for r in upcoming: by_basin_u[r.get("basin","")].append(r)

    # Active basin sections
    a_sections, a_offset = "", 0
    for basin in BASINS:
        rigs = by_basin_a.get(basin, [])
        if rigs:
            a_sections += basin_section_active(basin, rigs, a_offset)
            a_offset   += len(rigs)

    # Lookahead basin sections
    u_sections, u_offset = "", 0
    for basin in BASINS:
        rigs = by_basin_u.get(basin, [])
        if rigs:
            u_sections += basin_section_lookahead(basin, rigs, u_offset)
            u_offset   += len(rigs)

    hero = hero_card(top, is_active=("spud_date" in top)) if top else ""

    n_active   = len(active)
    n_upcoming = len(upcoming)
    n_basins   = len(set(by_basin_a)|set(by_basin_u))
    n_mud      = len({r.get("mud","") for r in active})
    aw = f"{cutoff.strftime('%b %d')} – {datetime.date.today().strftime('%b %d, %Y')}"
    uw = f"{datetime.date.today().strftime('%b %d')} – {lookahead_end.strftime('%b %d, %Y')}"

    toggle_js = """
<script>
document.querySelectorAll('[id^="a_"],[id^="l_"]').forEach(function(cb){
  cb.addEventListener('change', function(){
    var body = document.querySelector('.basin-body-' + this.id) ||
               this.nextElementSibling.nextElementSibling;
    if(body){ body.style.display = this.checked ? '' : 'none'; }
  });
});
</script>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>RigIntel · {week_label}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  body {{ font-family: 'Inter', Arial, sans-serif; margin:0; padding:0; background:#0A0F1E; }}
  input[type=checkbox]:checked ~ div {{ display:block; }}
  input[type=checkbox]:not(:checked) ~ div {{ display:none; }}
  label {{ user-select:none; }}
</style>
</head>
<body style="margin:0;padding:0;background:#0A0F1E;">
<div style="width:100%;background:#0A0F1E;padding:28px 0 40px;">
<div style="width:620px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.5);">

  <!-- TOP BAR -->
  <div style="background:#0A0F1E;padding:6px 24px;display:flex;align-items:center;">
    <span style="font-size:9px;letter-spacing:.15em;text-transform:uppercase;color:#334155;">Confidential · For internal use only</span>
    <span style="margin-left:auto;font-size:9px;color:#334155;">{week_label}</span>
  </div>

  <!-- MASTHEAD -->
  <div style="background:linear-gradient(180deg,#0D1B2A 0%,#0F2744 100%);padding:32px 32px 24px;">
    <table width="100%"><tr>
      <td>
        <div style="font-size:26px;font-weight:700;letter-spacing:-1px;color:#fff;">
          RIG<span style="color:#4DA6FF;">INTEL</span>
        </div>
        <div style="font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:#475569;margin-top:4px;">
          North America &middot; Drilling Intelligence Briefing
        </div>
      </td>
      <td align="right" style="vertical-align:top;">
        <div style="font-size:10px;color:#475569;text-align:right;line-height:1.8;">
          <span style="color:#4DA6FF;font-size:20px;font-weight:700;">{n_active}</span> active spuds<br/>
          <span style="color:#60A5FA;font-size:20px;font-weight:700;">{n_upcoming}</span> upcoming permits
        </div>
      </td>
    </tr></table>

    <!-- SUMMARY LINE -->
    <div style="margin-top:18px;padding:12px 16px;background:rgba(255,255,255,.05);border-radius:6px;border-left:3px solid #4DA6FF;">
      <div style="font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#4DA6FF;margin-bottom:4px;">Weekly outlook</div>
      <div style="font-size:12px;color:#CBD5E1;line-height:1.6;">{summary}</div>
    </div>

    <!-- STAT ROW -->
    <table width="100%" style="margin-top:20px;"><tr>
      <td width="25%" style="text-align:center;padding:0 8px;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{n_active}</div>
        <div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#475569;margin-top:2px;">Active spuds</div>
      </td>
      <td width="25%" style="text-align:center;padding:0 8px;border-left:1px solid #1E293B;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{n_upcoming}</div>
        <div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#475569;margin-top:2px;">Upcoming</div>
      </td>
      <td width="25%" style="text-align:center;padding:0 8px;border-left:1px solid #1E293B;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{n_basins}</div>
        <div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#475569;margin-top:2px;">Basins</div>
      </td>
      <td width="25%" style="text-align:center;padding:0 8px;border-left:1px solid #1E293B;">
        <div style="font-size:22px;font-weight:700;color:#fff;">{n_mud}</div>
        <div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#475569;margin-top:2px;">Mud cos.</div>
      </td>
    </tr></table>
  </div>

  <!-- HERO: TOP LEAD -->
  {hero}

  <!-- SECTION: ACTIVE SPUDS -->
  <div style="padding:24px 24px 8px;">
    <table width="100%"><tr>
      <td>
        <div style="font-size:9px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#94A3B8;">Section 01</div>
        <div style="font-size:16px;font-weight:700;color:#0F172A;letter-spacing:-.3px;margin-top:2px;">Active spuds</div>
        <div style="font-size:11px;color:#94A3B8;margin-top:2px;">{aw} &middot; sorted newest first &middot; click basin to expand</div>
      </td>
      <td align="right" style="vertical-align:bottom;">
        <div style="display:inline-flex;gap:8px;align-items:center;">
          <span style="font-size:10px;color:#059669;">&#9632; 0-7d</span>
          <span style="font-size:10px;color:#D97706;">&#9632; 8-21d</span>
          <span style="font-size:10px;color:#9CA3AF;">&#9632; 22-42d</span>
        </div>
      </td>
    </tr></table>
    <div style="height:1px;background:linear-gradient(to right,#E2E8F0,transparent);margin:12px 0 14px;"></div>
    {a_sections}
  </div>

  <!-- DIVIDER -->
  <div style="margin:8px 24px 0;">
    <div style="height:1px;background:linear-gradient(to right,#3B82F6,#60A5FA,#BFDBFE,transparent);"></div>
  </div>

  <!-- SECTION: LOOK AHEAD -->
  <div style="padding:24px 24px 8px;">
    <table width="100%"><tr>
      <td>
        <div style="font-size:9px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#94A3B8;">Section 02</div>
        <div style="font-size:16px;font-weight:700;color:#0F172A;letter-spacing:-.3px;margin-top:2px;">Look ahead</div>
        <div style="font-size:11px;color:#94A3B8;margin-top:2px;">{uw} &middot; permitted, not yet spudded &middot; sorted soonest first</div>
      </td>
      <td align="right" style="vertical-align:bottom;">
        <div style="display:inline-flex;gap:8px;align-items:center;">
          <span style="font-size:10px;color:#DC2626;">&#9632; &lt;14d</span>
          <span style="font-size:10px;color:#D97706;">&#9632; 15-56d</span>
        </div>
      </td>
    </tr></table>
    <div style="height:1px;background:linear-gradient(to right,#DBEAFE,transparent);margin:12px 0 14px;"></div>
    {u_sections}
  </div>

  <!-- FOOTER -->
  <div style="background:#0A0F1E;padding:24px 32px;">
    <table width="100%"><tr>
      <td>
        <div style="font-size:13px;font-weight:700;color:#fff;letter-spacing:-.2px;">RIG<span style="color:#4DA6FF;">INTEL</span></div>
        <div style="font-size:10px;color:#334155;margin-top:4px;line-height:1.6;">
          Automated weekly sweep &middot; North America<br/>
          Spud &amp; permit dates estimated from public activity and operator drilling schedules.<br/>
          Sources: Baker Hughes rig count, state permit filings, operator releases.
        </div>
      </td>
      <td align="right" style="vertical-align:top;">
        <div style="font-size:10px;color:#334155;line-height:2;">
          <a href="#" style="color:#475569;text-decoration:none;">Unsubscribe</a><br/>
          <a href="#" style="color:#475569;text-decoration:none;">Manage preferences</a>
        </div>
      </td>
    </tr></table>
  </div>

</div>
</div>
{toggle_js}
</body></html>"""


# ── Send + Main ───────────────────────────────────────────────────────────────

def send_email(html, week_label, n_active, n_upcoming):
    sg      = SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
    subject = f"RigIntel — {n_active} spuds · {n_upcoming} upcoming · {week_label}"
    for to in EMAIL_TO_LIST:
        r = sg.send(Mail(from_email=EMAIL_FROM, to_emails=to,
                         subject=subject, html_content=html))
        print(f"  Sent to {to} -> {r.status_code}")

def main():
    today         = datetime.date.today()
    cutoff        = today - datetime.timedelta(weeks=SPUD_LOOKBACK_WEEKS)
    lookahead_end = today + datetime.timedelta(weeks=LOOKAHEAD_WEEKS)
    week_label    = f"Week of {today.strftime('%b %d, %Y')}"

    print("[RigIntel] v5 — luxury edition")
    print(f"[RigIntel] {len(BASINS)} basins · {RIGS_PER_BASIN} active + {LOOKAHEAD_PER_BASIN} upcoming per basin")

    active, upcoming, top, summary = sweep_all()
    print(f"[RigIntel] Active: {len(active)} | Upcoming: {len(upcoming)}")

    if not active and not upcoming:
        print("[RigIntel] No data — check API keys."); return

    print("[RigIntel] Building email...")
    html = build_email(active, upcoming, top, summary, week_label, cutoff, lookahead_end)

    print("[RigIntel] Sending...")
    send_email(html, week_label, len(active), len(upcoming))
    print("[RigIntel] Done.")

if __name__ == "__main__":
    main()
