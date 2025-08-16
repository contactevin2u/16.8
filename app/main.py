from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from io import StringIO
import os, re, csv, json
from datetime import datetime, date

from .storage import SessionLocal, init_db, Order, Payment, Event

app = FastAPI(title="Order Intake Cloud API")

# --- CORS (env-driven) ---
FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
FRONTEND_ORIGIN_REGEX = os.getenv("FRONTEND_ORIGIN_REGEX", "").strip() or None
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in FRONTEND_ORIGINS if o.strip()],
    allow_origin_regex=FRONTEND_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Optional OpenAI client for AI parsing ---
try:
    from openai import OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    openai_client = None

# --------- Models ---------
class ParseIn(BaseModel):
    text: str
    matcher: str = "ai"
    lang: Literal["en","ms"] = "en"

class PaymentIn(BaseModel):
    amount: float = Field(gt=0)

class EventIn(BaseModel):
    event: Literal["RETURN","COLLECT","INSTALMENT_CANCEL","BUYBACK"]

class OrderCreate(BaseModel):
    code: str

# --------- Lifecycle ---------
@app.on_event("startup")
def on_startup() -> None:
    init_db()

# --------- Routes ---------
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/orders")
def create_order(body: OrderCreate):
    with SessionLocal() as s:
        existing = s.get(Order, body.code)
        if existing:
            return {"ok": True, "code": body.code, "created": False}
        s.add(Order(code=body.code, created_at=datetime.utcnow()))
        s.commit()
        return {"ok": True, "code": body.code, "created": True}

@app.post("/parse")
def parse(body: ParseIn):
    # If matcher = "ai" and key exists -> use OpenAI (gpt-4o-mini)
    if body.matcher == "ai" and openai_client is not None:
        prompt = f\"\"\"Extract an order summary as JSON with keys:
- order_code (string or null)
- customer_name (string or null)
- phone (string or null)

Text:
{body.text}
\"\"\"
        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You extract structured order data as JSON."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            code = data.get("order_code") or None
            parsed = {"ai": data, "matcher": body.matcher, "lang": body.lang}
            match = {"order_code": code, "reason": "ai-extract"} if code else None
            return {"parsed": parsed, "match": match}
        except Exception:
            # fallback to regex below
            pass

    # Else -> regex fallback for codes like OS-1234
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
            s.add(Order(code=code, created_at=datetime.utcnow()))
        s.add(Payment(order_code=code, amount=body.amount, created_at=datetime.utcnow()))
        s.commit()
    return {"ok": True, "code": code, "amount": body.amount}

@app.post("/orders/{code}/event")
def event(code: str, body: EventIn):
    with SessionLocal() as s:
        order = s.get(Order, code)
        if not order:
            s.add(Order(code=code, created_at=datetime.utcnow()))
        s.add(Event(order_code=code, kind=body.event, created_at=datetime.utcnow()))
        s.commit()
    return {"ok": True, "code": code, "event": body.event}

@app.get("/export/csv")
def export_csv(start: Optional[date] = None, end: Optional[date] = None, children: bool = True, adjustments: bool = True, unsettled: bool = False):
    with SessionLocal() as s:
        pays: List[Payment] = s.query(Payment).all()
        evs: List[Event] = s.query(Event).all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["type","order_code","date","amount_or_event","unsettled"])
    for p in pays:
        d = p.created_at.date().isoformat()
        w.writerow(["payment", p.order_code, d, f"{p.amount:.2f}", "false"])
    for e in evs:
        d = e.created_at.date().isoformat()
        w.writerow(["event", e.order_code, d, e.kind, "false"])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="export.csv"'})
