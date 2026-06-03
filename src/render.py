"""Stage 7a — Rendering. Briefing -> Markdown (for the repo) and HTML (for email)."""
from __future__ import annotations

import html
from .config import SourceConfig
from .models import Briefing

_FLAG = {"US": "🇺🇸", "CN": "🇨🇳", "INTL": "🌐"}


# --------------------------- Markdown ---------------------------
def render_markdown(b: Briefing, sources: SourceConfig) -> str:
    L: list[str] = []
    L.append(f"# Orbital Brief — {b.week_start} → {b.week_end}\n")
    L.append("## Executive Summary\n")
    L.append(b.exec_summary + "\n")

    if b.ledger_movements:
        L.append("## Asymmetry Ledger — Movements This Week\n")
        for m in b.ledger_movements:
            L.append(f"- {m}")
        L.append("")

    for pillar in sources.pillars:
        pid = pillar["id"]
        items = b.pillars.get(pid, [])
        if not items:
            continue
        L.append(f"## {pillar['name']}\n")
        for a in items:
            flag = _FLAG.get(a.country, "")
            L.append(f"### {flag} {a.headline}  ·  sig {a.significance}/5")
            L.append(a.analysis)
            if a.dual_use_read:
                L.append(f"\n> **Defense read:** {a.dual_use_read}")
            srcs = "  ·  ".join(f"[{n}]({u})" for n, u in a.sources)
            L.append(f"\n_Sources: {srcs}_\n")

    lc = b.launch_context
    L.append("## Access & Constellations (context)\n")
    L.append(f"Launch cadence in window — US: **{lc.us_count}**, China: **{lc.cn_count}**. {lc.note}\n")
    if lc.launches:
        L.append("| Date (NET) | Vehicle / Mission | Provider | Country |")
        L.append("|---|---|---|---|")
        for x in lc.launches[:25]:
            date = (x.net or "")[:10]
            L.append(f"| {date} | {x.name} | {x.provider} | {x.country} |")
        L.append("")

    L.append(f"\n---\n_Generated {b.generated_at} · automated brief; verify before acting on any item._")
    return "\n".join(L)


# --------------------------- HTML (email) ---------------------------
def render_html(b: Briefing, sources: SourceConfig) -> str:
    def esc(s: str) -> str:
        return html.escape(s or "")

    P = ['<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
         'max-width:680px;margin:0 auto;color:#1a1a1a;line-height:1.5;">']
    P.append(f'<h1 style="font-size:22px;border-bottom:2px solid #0b3d91;padding-bottom:8px;">'
             f'Orbital Brief <span style="color:#666;font-weight:400;">{b.week_start} → {b.week_end}</span></h1>')

    P.append('<h2 style="font-size:16px;color:#0b3d91;">Executive Summary</h2>')
    P.append(f'<p>{esc(b.exec_summary)}</p>')

    if b.ledger_movements:
        P.append('<h2 style="font-size:16px;color:#0b3d91;">Asymmetry Ledger — Movements This Week</h2>')
        P.append('<ul style="padding-left:18px;">' +
                 "".join(f"<li>{esc(m)}</li>" for m in b.ledger_movements) + "</ul>")

    for pillar in sources.pillars:
        items = b.pillars.get(pillar["id"], [])
        if not items:
            continue
        P.append(f'<h2 style="font-size:16px;color:#0b3d91;margin-top:24px;">{esc(pillar["name"])}</h2>')
        for a in items:
            flag = _FLAG.get(a.country, "")
            P.append('<div style="margin:0 0 16px;padding:12px 14px;background:#f6f8fc;'
                     'border-left:3px solid #0b3d91;border-radius:4px;">')
            P.append(f'<div style="font-weight:600;">{flag} {esc(a.headline)} '
                     f'<span style="color:#888;font-weight:400;font-size:12px;">· sig {a.significance}/5</span></div>')
            P.append(f'<p style="margin:6px 0;">{esc(a.analysis)}</p>')
            if a.dual_use_read:
                P.append(f'<p style="margin:6px 0;padding:8px;background:#fff4e5;border-radius:4px;'
                         f'font-size:14px;"><strong>Defense read:</strong> {esc(a.dual_use_read)}</p>')
            srcs = " · ".join(f'<a href="{esc(u)}" style="color:#0b3d91;">{esc(n)}</a>' for n, u in a.sources)
            P.append(f'<div style="font-size:12px;color:#666;">Sources: {srcs}</div>')
            P.append('</div>')

    lc = b.launch_context
    P.append('<h2 style="font-size:16px;color:#0b3d91;margin-top:24px;">Access & Constellations</h2>')
    P.append(f'<p>Launch cadence in window — US: <strong>{lc.us_count}</strong>, '
             f'China: <strong>{lc.cn_count}</strong>. {esc(lc.note)}</p>')

    P.append('<hr style="margin-top:28px;border:none;border-top:1px solid #ddd;">')
    P.append(f'<p style="font-size:11px;color:#999;">Generated {esc(b.generated_at)} · '
             'automated brief — verify before acting on any item.</p>')
    P.append('</div>')
    return "".join(P)
