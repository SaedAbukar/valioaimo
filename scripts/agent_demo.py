"""An external purchasing agent that talks ONLY to the gateway over HTTP (stdlib only).

    make run                                   # gateway on :8000 (live mock API if .env has the key)
    python scripts/agent_demo.py               # the brief's milk request -> order (within authority)
    python scripts/agent_demo.py --over-limit  # 3,000 L -> needs OK -> Laura approves -> order
    python scripts/agent_demo.py --suggestions # pull Valio Aimo's seller suggestions, verify each signature

It does what any agent would: read the discovery documents, look up products,
then follow the playbook by obeying `next_allowed_tools`, cite the signed offers
when ordering, and verify the signed confirmation against the published JWKS.
The approval step uses the approver's OWN credential, as a human would.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import sys
import time
import urllib.error
import urllib.request

BRIEF = ("I need 1,000 litres of lactose-free milk by Monday. "
         "Find an option that meets our requirements based on price and availability.")
OVER = "I need 3,000 litres of lactose-free milk by Monday. Best price and availability, please."


class Gateway:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token or self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def say(step: str, text: str):
    print(f"\033[1m{step:<12}\033[0m {text}")


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_es256(jws: str, jwks: dict) -> bool:
    """Verify a compact JWS with the gateway's published key (needs `cryptography`; any JOSE library works)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    h, p, sig = jws.split(".")
    kid = json.loads(_b64(h))["kid"]
    k = next(k for k in jwks["keys"] if k["kid"] == kid)
    pub = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64(k["x"]), "big"), int.from_bytes(_b64(k["y"]), "big"), ec.SECP256R1()).public_key()
    raw = _b64(sig)
    try:
        pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                   f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:  # noqa: BLE001
        return False


def run(base: str, token: str, text: str, approver: str | None) -> dict:
    t0 = time.perf_counter()
    gw = Gateway(base, token)
    _, ucp = gw.call("GET", "/.well-known/ucp")
    _, jwks = gw.call("GET", "/.well-known/jwks.json")
    _, rules = gw.call("GET", "/v1/rules")
    say("discover", f"{ucp['business']['name']}: playbook v{ucp['playbook']['version']}, "
                    f"{len(ucp['ucp']['capabilities'])} capabilities, {len(jwks['keys'])} signing key(s)")
    _, me = gw.call("GET", "/v1/mandate")
    lim = me["mandate"]["limits"]
    say("authority", f"{me['mandate']['buyerId']} mandate signed by {me['mandate']['issuedBy']['name']}: "
                     f"€{lim['perOrderEUR']:,} per order, valid={me['valid']}")
    say("rules", f"needs a human: {', '.join(r['title'] for r in rules['autonomy']['needsNamedHumanOk'][:4])}, …")

    # 1. structured lookup (read-only)
    today = datetime.date.today()
    monday = today + datetime.timedelta(days=(7 - today.weekday()) % 7 or 7)
    st, found = gw.call("POST", "/v1/products/search", {"query": "lactose-free milk", "qty": 1000, "needBy": monday.isoformat(), "limit": 5})
    say("lookup", f"{found['count']} products, prices from {'the Valio Aimo mock API' if found['live'] else 'demo values'}:")
    for p in found["products"][:3]:
        a = p["availability"]
        print(f"{'':13}{p['name'][:46]:<47} €{p['price']['perUnit']:.2f}/{p['price']['unit']}  "
              f"{a['status']} {a['earliestDelivery']}  reliability {p['deliveryReliability']}  {p.get('tag', '')}")

    # 2. the playbook, driven only by next_allowed_tools
    st, r = gw.call("POST", "/v1/sessions", {})
    sid = r["sessionId"]
    say("session", f"{sid} (agent {r['output']['agentId']})")
    st, bad = gw.call("POST", f"/v1/sessions/{sid}/tools/place_order", {})
    say("rails", f"place_order now -> {st} {bad.get('error')}; allowed: {bad.get('next_allowed_tools')[:2]}")

    plan, order = None, None
    nxt = ["parse_request"]
    prefer = ["parse_request", "recall", "request_offers", "plan_basket", "check_basket", "render_cards",
              "place_order", "request_approval"]
    done: set[str] = set()
    while True:
        tool = next((t for t in prefer if t in nxt and t not in done), None)
        if tool is None:
            break
        args = {"text": text} if tool == "parse_request" else {"offerIds": [o["offerId"] for o in plan["offers"]]} if tool == "place_order" else {}
        st, r = gw.call("POST", f"/v1/sessions/{sid}/tools/{tool}", args)
        if st != 200:
            say(tool, f"{st} {r.get('error')}: {r.get('message')}")
            break
        out, nxt = r["output"], r["next_allowed_tools"]
        done.add(tool)
        if tool == "parse_request":
            say("understand", f"{', '.join(f'{l['qty']:g} {l['unit']} {l['text']}' for l in out.get('lines', []))} by {out['when']['value']}")
        elif tool == "recall":
            say("recall", f"{len(out['matched'])} from memory, gaps: {out['gaps'] or 'none'}")
        elif tool == "request_offers":
            say("discover", f"{sum(len(g['candidates']) for g in out['gaps'])} signed offers for the gaps")
        elif tool == "plan_basket":
            plan = out
            for l in out["lines"]:
                say("plan", f"{l['qty']:g} {l['unit']} {l['name']} @ €{l['unitPrice']:.2f} -> {l['deliveryDate']} ({l['source']})")
            say("offers", ", ".join(f"{o['offerId']} €{o['unitPrice']}/{o['unit']} until {o['validUntil'][11:16]} ({o['priceSource']})"
                                    for o in out["offers"]))
        elif tool == "check_basket":
            say("check", f"gateway decided: {out['decision'].upper()} (limit €{out['limit']:,}, total €{plan['total']:,.2f})"
                         + (f" - {'; '.join(out['reasons'])}" if out["reasons"] else ""))
        elif tool == "request_approval":
            ap = out["approval"]
            say("approval", f"sent to {ap['approver']['name']} ({ap['approver']['role']}), id {ap['approvalId']}")
            st, mine = gw.call("POST", f"/v1/approvals/{ap['approvalId']}", {"ok": True}, token=token)
            say("rails", f"agent tries to approve itself -> {st} {mine.get('error')}")
            if not approver:
                break
            _, inbox = gw.call("GET", "/v1/approvals", token=approver)
            say("inbox", f"{inbox['for']} has {len(inbox['pending'])} pending")
            st, dec = gw.call("POST", f"/v1/approvals/{ap['approvalId']}", {"ok": True, "note": "Big week, fine."}, token=approver)
            say("human", f"{dec['approval']['decidedBy']} -> {dec['approval']['status']}")
            _, r = gw.call("GET", f"/v1/sessions/{sid}")
            nxt = r["next_allowed_tools"]
        elif tool == "place_order":
            order = out
            say("act", f"ordered {order['orderId']} ({order['backendOrderRef']}), €{order['total']:,.2f}"
                       + (f", approved by {order['approvedBy']}" if order["approvedBy"] else ""))
            break

    if order:
        _, o = gw.call("GET", f"/v1/orders/{order['orderId']}")
        ok = verify_es256(o["confirmation"]["jws"], jwks)
        say("verify", f"signed confirmation checked with /.well-known/jwks.json by the agent itself: {'valid' if ok else 'INVALID'}")
    _, log = gw.call("GET", f"/v1/sessions/{sid}/log")
    say("log", f"{len(log['audit'])} audit events; last: {log['audit'][-1]['who']} {log['audit'][-1]['what']}")
    secs = time.perf_counter() - t0
    say("time", f"{secs:.1f} s end to end")
    return {"order": order, "seconds": secs, "sessionId": sid}


def suggestions(base: str, token: str) -> int:
    """The buyer's agent pulls the seller agent's suggestions and checks each one is signed by the gateway and promotional."""
    gw = Gateway(base, token)
    _, jwks = gw.call("GET", "/.well-known/jwks.json")
    st, r = gw.call("GET", "/v1/suggestions")
    if st != 200:
        say("suggestions", f"HTTP {st}: {r}")
        return 1
    if r["optedOut"]:
        say("suggestions", "this buyer opted out of seller suggestions")
        return 0
    for sg in r["suggestions"]:
        ok = verify_es256(sg["proof"]["jws"], jwks)
        typ = json.loads(_b64(sg["proof"]["jws"].split(".")[0]))["typ"]
        say(sg["type"], f"{sg['name']} · €{sg['price']['perUnit']:.2f}/{sg['price']['unit']} ({sg['price']['source']})")
        say("", f"why: {sg['reason']}")
        say("", f"trade-off: {sg['tradeOff']}")
        say("", f"{typ} from '{sg['issuer']}', promotional={sg['promotional']}, signature {'valid' if ok else 'INVALID'}, "
                f"valid until {sg['validUntil']}")
    say("use", "nothing was added to any order; to use one: plan_basket {acceptSuggestion: <id>} (re-planned and re-checked)")
    return 0 if all(verify_es256(x["proof"]["jws"], jwks) for x in r["suggestions"]) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--token", default="demo-key-pohjola", help="the agent's credential (bound to one buyer)")
    ap.add_argument("--approver", default="demo-human-usr-lvirtanen", help="the named approver's credential")
    ap.add_argument("--over-limit", action="store_true", help="order 3,000 L so a human must approve")
    ap.add_argument("--text", help="your own request")
    ap.add_argument("--suggestions", action="store_true", help="pull and verify Valio Aimo seller suggestions")
    a = ap.parse_args()
    if a.suggestions:
        sys.exit(suggestions(a.base, a.token))
    res = run(a.base, a.token, a.text or (OVER if a.over_limit else BRIEF), a.approver)
    sys.exit(0 if res["order"] and res["seconds"] < 60 else 1)


if __name__ == "__main__":
    main()
