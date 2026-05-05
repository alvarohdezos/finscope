"""
FINscope — Watchlist Subscribe endpoint
POST /api/watchlist-subscribe
Body: { email, tickers: [str, ...], lang: "en"|"es" }

Dependencies (all stdlib, no pip install needed):
  - Upstash Redis REST API  → UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN
  - Resend transactional email → RESEND_API_KEY
  - FROM_EMAIL  → e.g. "FINscope <no-reply@yourdomain.com>"
  - SITE_URL    → e.g. "https://finscope.vercel.app"

Graceful degradation: if env vars are missing, returns ok=True so the UX never
shows a hard error.  The subscription logic is best-effort.
"""
from http.server import BaseHTTPRequestHandler
import json, os, re, secrets, time, urllib.request

# ── Env ────────────────────────────────────────────────────────────────────────
RESEND_KEY    = os.environ.get('RESEND_API_KEY', '')
UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '').rstrip('/')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
FROM_EMAIL    = os.environ.get('FROM_EMAIL', 'FINscope <onboarding@resend.dev>')
SITE_URL      = os.environ.get('SITE_URL', 'https://finscope.vercel.app')

TTL_SECS = 60 * 60 * 24 * 90   # 90-day subscription TTL in Redis
EMAIL_RE  = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
TICKER_RE = re.compile(r'^[A-Z.\-]{1,10}$')


# ── Upstash Redis REST ─────────────────────────────────────────────────────────

def _redis(command: list):
    """Execute a Redis command via Upstash REST API.  Returns parsed JSON or None."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    req = urllib.request.Request(
        UPSTASH_URL,
        data=json.dumps(command).encode(),
        headers={
            'Authorization': f'Bearer {UPSTASH_TOKEN}',
            'Content-Type':  'application/json',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── Resend email ───────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, html: str) -> bool:
    """Send via Resend REST API.  Returns True if accepted (200/201)."""
    if not RESEND_KEY:
        return False
    payload = {
        'from':    FROM_EMAIL,
        'to':      [to],
        'subject': subject,
        'html':    html,
    }
    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=json.dumps(payload).encode(),
        headers={
            'Authorization': f'Bearer {RESEND_KEY}',
            'Content-Type':  'application/json',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status in (200, 201)
    except Exception:
        return False


# ── Core subscribe logic ───────────────────────────────────────────────────────

def subscribe(email: str, tickers: list, lang: str) -> dict:
    token = secrets.token_urlsafe(32)
    record = {
        'email':      email,
        'tickers':    tickers,
        'lang':       lang,
        'token':      token,
        'created_at': int(time.time()),
        'active':     True,
    }

    # Persist: wl:{email} = full record | tok:{token} = email (for unsubscribe lookup)
    r1 = _redis(['SET', f'wl:{email}',  json.dumps(record), 'EX', TTL_SECS])
    r2 = _redis(['SET', f'tok:{token}', email,              'EX', TTL_SECS])

    # Build unsubscribe URL
    unsub_url = f'{SITE_URL}/api/watchlist-unsubscribe?token={token}'
    tickers_str = ', '.join(tickers)

    if lang == 'es':
        subject = '✓ Suscripción a FINscope confirmada'
        html = _html_es(email, tickers_str, unsub_url)
    else:
        subject = '✓ FINscope watchlist subscription confirmed'
        html = _html_en(email, tickers_str, unsub_url)

    email_ok = _send_email(email, subject, html)

    return {
        'ok':         True,
        'email_sent': email_ok,
        'redis_ok':   r1 is not None,
    }


# ── Email templates ────────────────────────────────────────────────────────────

def _css():
    return """
body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;margin:0;padding:0;background:#f8f9fb;color:#0d0f14}
.wrap{max-width:560px;margin:40px auto;background:#fff;border:1px solid #e2e6ef;border-radius:8px;overflow:hidden}
.hdr{background:#0f2d6b;padding:22px 32px;display:flex;align-items:center;gap:4px}
.logo-fin{font-size:20px;font-weight:800;color:#fff;letter-spacing:-.01em}
.logo-sc{font-size:20px;font-weight:300;color:rgba(255,255,255,.55);letter-spacing:-.01em}
.body{padding:32px}
.h1{font-size:22px;font-weight:800;color:#0d0f14;margin:0 0 10px;letter-spacing:-.02em}
.intro{font-size:14px;color:#3d4f70;line-height:1.75;margin:0 0 22px}
.tickers{background:#f2f4f8;border:1px solid #e2e6ef;border-radius:6px;padding:15px 20px;font-size:15px;font-weight:700;color:#0f2d6b;letter-spacing:.05em;margin-bottom:22px}
.info{font-size:12.5px;color:#6b7a99;line-height:1.75;padding:13px 16px;background:rgba(37,99,235,.04);border-left:3px solid #2563eb;border-radius:0 4px 4px 0;margin-bottom:20px}
.info strong{color:#1a2744}
.fine{font-size:12px;color:#6b7a99;margin:0}
.foot{padding:18px 32px;background:#f8f9fb;border-top:1px solid #e2e6ef;font-size:11px;color:#a0aec0;line-height:2}
.foot a{color:#6b7a99;text-decoration:none}
"""


def _html_en(email: str, tickers_str: str, unsub_url: str) -> str:
    css = _css()
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FINscope — Watchlist confirmed</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="hdr"><span class="logo-fin">FIN</span><span class="logo-sc">scope</span></div>
  <div class="body">
    <div class="h1">Your watchlist is confirmed.</div>
    <p class="intro">
      Every Monday at 09:00 UTC you'll receive a concise brief covering material news,
      upcoming earnings dates, composite score changes, and sector events for each ticker
      in your watchlist — all filtered by AI to remove noise.
    </p>
    <div class="tickers">📌 {tickers_str}</div>
    <div class="info">
      <strong>What's in each digest:</strong><br>
      · AI-filtered news — only items with direct P&amp;L impact<br>
      · Earnings calendar for the next 30 days<br>
      · Composite score delta vs prior week<br>
      · Macro overlay (yield curve, VIX, credit spreads)
    </div>
    <p class="fine">
      You're receiving this because <strong>{email}</strong> subscribed at FINscope.
      Your first digest will arrive on the next Monday at 09:00 UTC.
    </p>
  </div>
  <div class="foot">
    FINscope · Institutional equity research tool · Educational use only · Not investment advice<br>
    <a href="{unsub_url}">Unsubscribe</a> &nbsp;·&nbsp;
    <a href="https://github.com/alvarohdezos/finscope">GitHub</a>
  </div>
</div>
</body></html>"""


def _html_es(email: str, tickers_str: str, unsub_url: str) -> str:
    css = _css()
    return f"""<!DOCTYPE html><html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FINscope — Suscripción confirmada</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="hdr"><span class="logo-fin">FIN</span><span class="logo-sc">scope</span></div>
  <div class="body">
    <div class="h1">Tu lista de seguimiento está confirmada.</div>
    <p class="intro">
      Cada lunes a las 09:00 UTC recibirás un informe conciso con noticias materiales filtradas
      por IA, próximas fechas de presentación de resultados, variación de la puntuación compuesta
      y eventos del sector que puedan afectar a cada valor de tu lista — sin ruido.
    </p>
    <div class="tickers">📌 {tickers_str}</div>
    <div class="info">
      <strong>Contenido de cada informe:</strong><br>
      · Noticias filtradas por IA — solo impacto directo en cuenta de resultados<br>
      · Calendario de resultados para los próximos 30 días<br>
      · Variación de la puntuación compuesta respecto a la semana anterior<br>
      · Variables macroeconómicas clave (curva de tipos, VIX, spreads de crédito)
    </div>
    <p class="fine">
      Recibes este mensaje porque <strong>{email}</strong> se suscribió en FINscope.
      Tu primer informe llegará el próximo lunes a las 09:00 UTC.
    </p>
  </div>
  <div class="foot">
    FINscope · Herramienta de análisis institucional de renta variable ·
    Solo informativo · No constituye asesoramiento de inversión<br>
    <a href="{unsub_url}">Cancelar suscripción</a> &nbsp;·&nbsp;
    <a href="https://github.com/alvarohdezos/finscope">GitHub</a>
  </div>
</div>
</body></html>"""


# ── Vercel handler ─────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length  = int(self.headers.get('Content-Length', 0))
            body    = json.loads(self.rfile.read(length).decode('utf-8'))
            email   = (body.get('email') or '').strip().lower()
            tickers = body.get('tickers') or []
            lang    = (body.get('lang', 'en') or 'en').lower()
            if lang not in ('en', 'es'):
                lang = 'en'

            # ── Validation ──────────────────────────────────────────────────
            if not email or not EMAIL_RE.match(email):
                raise ValueError('Invalid email address')
            if not isinstance(tickers, list) or len(tickers) == 0:
                raise ValueError('At least 1 ticker is required')
            clean = [str(t).upper().strip()[:10] for t in tickers[:5]]
            clean = [t for t in clean if TICKER_RE.match(t)]
            if not clean:
                raise ValueError('No valid tickers provided')

            result = subscribe(email, clean, lang)
            self._respond(200, result)

        except ValueError as e:
            self._respond(400, {'ok': False, 'error': str(e)})
        except Exception:
            self._respond(500, {'ok': False, 'error': 'Internal server error'})

    def _respond(self, status: int, data: dict):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type',   'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass
