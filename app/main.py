
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

import os
from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from io import StringIO
import csv
from datetime import datetime, date
from .storage import SessionLocal, init_db, Order, Payment, Event

app = FastAPI(title="Order Intake Cloud API")

FRONTEND_ORIGINS = os.getenv('FRONTEND_ORIGINS', 'http://localhost:3000').split(',')
origins = [o.strip() for o in FRONTEND_ORIGINS]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class ParseIn(BaseModel):
    text: str
    matcher: str = "hybrid"
    lang: Literal["en","ms"] = "en"

class PaymentIn(BaseModel):
    amount: float = Field(gt=0)

class EventIn(BaseModel):
    event: Literal["RETURN","COLLECT","INSTALMENT_CANCEL","BUYBACK"]

@app.on_event("startup")
def on_startup(): init_db()

@app.get("/health")
def health(): return {"ok": True}

@app.post("/parse")
def parse(body: ParseIn):
    import re
    m = re.search(r'\b([A-Z]{2,5}-\d{3,6})\b', body.text.upper())
    code = m.group(1) if m else None
    parsed = {"raw_preview": body.text[:160], "matcher": body.matcher, "lang": body.lang}
    match = {"order_code": code, "reason": "regex-match"} if code else None
    return {"parsed": parsed, "match": match}

@app.post("/orders/{code}/payments")
def payment(code: str, body: PaymentIn):
    with SessionLocal() as s:
        order = s.get(Order, code)
        if not order:
            order = Order(code=code, created_at=datetime.utcnow()); s.add(order)
        pay = Payment(order_code=code, amount=body.amount, created_at=datetime.utcnow())
        s.add(pay); s.commit()
    return {"ok": True, "code": code, "amount": body.amount}

@app.post("/orders/{code}/event")
def event(code: str, body: EventIn):
    with SessionLocal() as s:
        order = s.get(Order, code)
        if not order:
            order = Order(code=code, created_at=datetime.utcnow()); s.add(order)
        ev = Event(order_code=code, kind=body.event, created_at=datetime.utcnow())
        s.add(ev); s.commit()
    return {"ok": True, "code": code, "event": body.event}

@app.get("/export/csv")
def export_csv(start: Optional[date] = None, end: Optional[date] = None, children: bool = True, adjustments: bool = True, unsettled: bool = False):
    with SessionLocal() as s:
        pays: List[Payment] = s.query(Payment).all()
        evs: List[Event] = s.query(Event).all()
    buf = StringIO(); w = csv.writer(buf)
    w.writerow(["type","order_code","date","amount_or_event","unsettled"])
    for p in pays:
        d = p.created_at.date().isoformat()
        if start and d < start.isoformat(): pass
        if end and d > end.isoformat(): pass
        w.writerow(["payment", p.order_code, d, f"{p.amount:.2f}", "false"])
    for e in evs:
        d = e.created_at.date().isoformat()
        if start and d < start.isoformat(): pass
        if end and d > end.isoformat(): pass
        w.writerow(["event", e.order_code, d, e.kind, "false"])
    return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="export.csv"'})

