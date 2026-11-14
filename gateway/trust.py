"""Offer Attestations (W3C VC 2.0 data model secured as compact JWS ES256) and the
six-check trust protocol an agent must pass before acting on a claim."""
from __future__ import annotations

from datetime import timedelta

from . import catalog
from .crypto import verify_jws
from .util import iso, new_id, parse_dt, s2d

PRICE_TTL_MIN = 15
STOCK_TTL_MIN = 5
ISSUER = "did:web:gateway.aimo.example"
VC_CONTEXT = ["https://www.w3.org/ns/credentials/v2", "https://gateway.aimo.example/ns/offer/v1"]
BOUND_FIELDS = ["offerId", "gtin", "aimoSku", "unit", "packSize", "unitsPerCase", "unitPrice", "currency"]

CHECKS = [
    ("signature", "Signature valid (ES256 vs JWKS)"),
    ("validity", "Offer within validity window (price 15 min)"),
    ("freshness", "Availability fresh (≤ 5 min) & confident"),
    ("binding", "GTIN / SKU / unit / price match signed claim"),
    ("status", "Offer not revoked (status list)"),
    ("reverify", "Live re-check: price & stock still hold"),
]


def issue_offer(gw, gtin: str, need_by=None, buyer_id: str | None = None) -> dict:
    p = catalog.by_gtin(gtin)
    be = gw.backend
    now = gw.clock.now()
    sched = be.schedule(gtin)
    stock_now = be.stock[gtin]
    by = need_by or s2d(sched[0]["date"]) if sched else need_by
    qty_by = be.available_by(gtin, by) if by else stock_now
    inbound_part = max(0.0, qty_by - stock_now)
    conf = 0.0 if qty_by <= 0 else round((min(stock_now, qty_by) * 0.97 + inbound_part * 0.8) / qty_by, 2)
    today = gw.clock.today().isoformat()
    certs = [dict(c, valid=c["validUntil"] >= today) for c in p["certificates"]]
    subject = {
        "offerId": new_id("OF"),
        "gtin": p["gtin"], "aimoSku": p["aimoSku"], "name": p["name"], "brand": p["brand"],
        "category": p["category"], "kind": p["kind"],
        "unit": p["unit"], "packSize": p["packSize"], "unitsPerCase": p["unitsPerCase"], "caseQty": p["caseQty"],
        "unitPrice": be.price(gtin), "currency": "EUR", "priceBasis": p["priceBasis"],
        "availability": {"qtyAvailable": qty_by, "byDate": by.isoformat() if by else None, "asOf": iso(now),
                         "confidence": conf, "schedule": sched},
        "delivery": {"earliestDate": be.earliest(gtin).isoformat(), "cutoff": "14:00 EET, day before delivery",
                     "onTimeRate": p["onTimeRate"]},
        "origin": p["origin"],
        "attributes": {"allergens": p["allergens"], "mayContain": p["mayContain"], "diet": p["diet"]},
        "certificates": certs,
        "validFrom": iso(now),
        "validUntil": iso(now + timedelta(minutes=PRICE_TTL_MIN)),
        "digitalLink": catalog.digital_link(p),
        "priceSource": "valio-aimo-mock-api" if (gtin in be.live or p.get("livePrice")) else "demo-values",
        "aimoProductId": (be.live.get(gtin) or {}).get("aimoProductId") or p.get("aimoProductId"),
        "trustLevel": "L2" if certs and all(c["valid"] for c in certs) else "L1",
    }
    vc = {
        "@context": VC_CONTEXT,
        "id": f"urn:aimo:offer:{subject['offerId']}",
        "type": ["VerifiableCredential", "OfferAttestation"],
        "issuer": ISSUER,
        "validFrom": subject["validFrom"],
        "validUntil": subject["validUntil"],
        "credentialSubject": subject,
        "credentialStatus": {"id": f"https://gateway.aimo.example/v1/offers/status#{subject['offerId']}",
                             "type": "BitstringStatusListEntry", "statusPurpose": "revocation"},
    }
    jws = gw.gateway_key.sign(vc, typ="vc+jwt")
    offer = dict(subject)
    offer["buyerId"] = buyer_id
    offer["proof"] = {"type": "JsonWebSignature", "format": "vc+jwt", "alg": "ES256", "kid": gw.gateway_key.kid, "jws": jws}
    gw.store.put("offer", offer["offerId"], offer, buyer_id, subject["validFrom"])
    return offer


def verify_offer(gw, offer: dict, qty: float | None = None, live: bool = True) -> dict:
    now = gw.clock.now()
    res = {}
    ok, payload, detail = verify_jws(offer.get("proof", {}).get("jws", ""), gw.jwks()["keys"])
    res["signature"] = (ok, detail)
    subj = (payload or {}).get("credentialSubject", {})
    if ok:
        vu = parse_dt(subj["validUntil"])
        left = (vu - now).total_seconds()
        res["validity"] = (left > 0, f"valid for {int(left // 60)} min {int(left % 60)} s" if left > 0
                           else f"expired {int(-left // 60)} min ago (validUntil {subj['validUntil']})")
        age = (now - parse_dt(subj["availability"]["asOf"])).total_seconds()
        conf = subj["availability"]["confidence"]
        res["freshness"] = (age <= STOCK_TTL_MIN * 60 and conf >= 0.8,
                            f"stock read {int(age // 60)} min ago, confidence {conf:.2f}"
                            + ("" if age <= STOCK_TTL_MIN * 60 else " — stale, live re-check required"))
        mism = [f for f in BOUND_FIELDS if subj.get(f) != offer.get(f)]
        res["binding"] = (not mism, "presented fields match signed payload" if not mism else
                          f"presented {', '.join(mism)} differ from the signed claim")
    else:
        for k in ("validity", "freshness", "binding"):
            res[k] = (False, "not evaluated: signature failed")
    revoked = gw.store.get("revocation", offer.get("offerId", ""))
    res["status"] = (not revoked, "not revoked" if not revoked else f"revoked: {revoked.get('reason')}")
    if live and ok:
        cur = gw.backend.price(subj["gtin"])
        need = qty if qty is not None else 0
        by = s2d(subj["availability"]["byDate"]) if subj["availability"].get("byDate") else gw.clock.today()
        avail = gw.backend.available_by(subj["gtin"], by)
        issues, short = [], []
        if abs(cur - subj["unitPrice"]) > 1e-9:
            issues.append(f"price now €{cur:.2f} (offer €{subj['unitPrice']:.2f})")
        if need and avail + 1e-9 < need:
            short.append(f"{subj['name']}: only {avail:g} {subj['unit']} available by {by.isoformat()}, order needs {need:g}")
            issues.append(f"only {avail:g} {subj['unit']} available by {by.isoformat()}")
        res["reverify"] = (not issues, "price and stock confirmed live" if not issues else "; ".join(issues))
    else:
        res["reverify"] = (False, "not evaluated")
        short = []
    checks = [{"id": cid, "label": label, "ok": res[cid][0], "detail": res[cid][1]} for cid, label in CHECKS]
    # freshness is advisory: stale stock is re-read live by check 6
    hard = [c for c in checks if c["id"] != "freshness"]
    return {"offerId": offer.get("offerId"), "verified": all(c["ok"] for c in hard), "checks": checks,
            "trustLevel": subj.get("trustLevel", "L0") if ok else "L0", "shortfall": short}
