"""Optional caregiver dashboard — today's windows, order log, and per-agent
reasoning replay. Read-only over app.db plus a kill-switch / autonomy toggle.

Run:  uvicorn sentinel.dashboard:app --reload
"""
from __future__ import annotations

import os
from datetime import date

from .models import Profile, Store

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
except Exception:  # fastapi optional
    FastAPI = None

CFG = "config.yaml" if os.path.exists("config.yaml") else "config.example.yaml"

if FastAPI:
    app = FastAPI(title="Sustenance Sentinel")

    @app.get("/", response_class=HTMLResponse)
    def home():
        profile = Profile.from_yaml(CFG)
        store = Store()
        day = date.today().isoformat()
        rows = store.traces_for(profile.person_id, day)
        spent = store.spent_today(profile.person_id, day)
        killed = store.is_killed(profile.person_id)
        items = "".join(
            f"<tr><td>{r['window']}</td><td><b>{r['agent']}</b></td>"
            f"<td>{r['message']}</td></tr>" for r in rows
        ) or "<tr><td colspan=3>No activity yet today.</td></tr>"
        store.close()
        return f"""
        <h2>Sustenance Sentinel — {profile.name}</h2>
        <p>Day: {day} | Spent: ₹{spent}/{profile.spend_cap_per_day} |
           Autonomy: {profile.autonomy} | Kill switch: {'ON' if killed else 'off'}</p>
        <p><a href="/kill?on=1">Stop all ordering</a> ·
           <a href="/kill?on=0">Resume</a></p>
        <h3>Reasoning replay (who decided what)</h3>
        <table border=1 cellpadding=6>{items}</table>
        """

    @app.get("/kill")
    def kill(on: int = 1):
        profile = Profile.from_yaml(CFG)
        store = Store()
        store.set_killed(profile.person_id, bool(on))
        store.close()
        return {"killed": bool(on)}
