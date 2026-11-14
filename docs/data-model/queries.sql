-- Example queries on the Aimo order-process model (run against schema.sql).
-- Each query is tagged with who uses it: @agent (makes ordering more precise)
-- or @insight (buyer / Valio Aimo dashboards).

-- Q1 @insight  Event report: ordered vs used vs kept vs wasted per product, with value
SELECT e.name AS event, p.name AS product,
       ROUND(SUM(u.qty_ordered_base),1) AS ordered, ROUND(SUM(u.qty_used),1) AS used,
       ROUND(SUM(u.qty_kept + u.qty_redistributed),1) AS reused,
       ROUND(SUM(u.qty_wasted),1) AS wasted, ROUND(SUM(u.waste_value_eur),2) AS waste_eur,
       ROUND(SUM(u.qty_used) / SUM(u.qty_ordered_base), 3) AS utilisation,
       MAX(u.shortage_qty) > 0 AS ran_short
FROM v_usage_fact u
JOIN event e   ON e.event_id = u.event_id
JOIN product p ON p.product_id = u.product_id
WHERE u.event_id = :event_id
GROUP BY e.name, p.name
ORDER BY waste_eur DESC;

-- Q2 @agent  Right-size the next event: learned use per guest for this org, event type and need
SELECT need_group_id, n_events, used_per_guest, ordered_per_guest, waste_rate, first_event, last_event
FROM sig_per_guest_consumption
WHERE org_id = :org_id AND event_type = :event_type AND service_style = :service_style
  AND n_events >= 3;                                  -- only act on enough evidence

-- Q3 @agent  Leftovers to net before ordering (still usable on the need-by date)
SELECT l.lot_id, l.product_id, p.need_group_id, l.qty_base, l.best_before
FROM leftover_lot l JOIN product p ON p.product_id = l.product_id
WHERE l.site_id = :site_id AND l.status = 'available' AND l.best_before >= :need_by
ORDER BY l.best_before;                               -- use oldest first

-- Q4 @agent  Substitution evidence for ranking (bonus/penalty with its n)
SELECT from_product_id, to_product_id, n, accepted, acceptance_rate
FROM sig_substitution_acceptance
WHERE org_id = :org_id AND from_product_id = :requested_product_id;

-- Q5 @agent  Experienced supplier reliability vs what offers claim
SELECT r.supplier_id, r.n_lines, r.on_time_rate AS experienced_on_time,
       (SELECT AVG(o.claimed_on_time_rate) FROM offer o JOIN product p ON p.product_id = o.product_id
         WHERE p.supplier_id = r.supplier_id) AS claimed_on_time,
       r.fill_rate, r.quality_issue_rate
FROM sig_supplier_reliability r
WHERE r.org_id = :org_id;

-- Q6 @insight  Monthly scorecard: autonomy, manual corrections, exceptions, spend
SELECT substr(created_at,1,7) AS month,
       COUNT(*) AS processes,
       AVG(final_outcome IN ('AUTO','NOTIFY')) AS autonomous_rate,
       AVG(corrections > 0)                    AS manual_correction_rate,
       AVG(chosen_rank = 1)                    AS top_option_chosen_rate,
       SUM(order_value_eur)                    AS spend_eur,
       AVG(exceptions)                         AS exceptions_per_process
FROM v_process_fact
WHERE org_id = :org_id
GROUP BY month ORDER BY month;

-- Q7 @insight  Mandate tuning: rules humans nearly always approve (candidate to relax)
SELECT rule_id, n, approve_rate, ROUND(avg_latency_min,1) AS avg_latency_min
FROM sig_approval_pattern
WHERE org_id = :org_id AND n >= 5 AND approve_rate >= 0.9
ORDER BY n DESC;

-- Q8 @insight  Price check: today's offer vs this buyer's 8-week average for the product
SELECT o.offer_id, o.unit_price_eur / (p.pack_size * un.to_base_factor) AS price_now,
       (SELECT AVG(h.avg_price) FROM sig_price_history h
         WHERE h.org_id = :org_id AND h.product_id = o.product_id
           AND h.month >= substr(date(:today,'-56 days'),1,7)) AS avg_price_8w
FROM offer o JOIN product p ON p.product_id = o.product_id JOIN unit un ON un.unit_code = p.pack_unit_code
WHERE o.process_id = :process_id;

-- Q9 @insight  Waste trend by category and reason (Valio Aimo ops: aggregate only)
SELECT substr(c.recorded_at,1,7) AS month, u.category_id, c.waste_reason_code,
       SUM(u.qty_wasted) AS wasted_base, SUM(u.waste_value_eur) AS waste_eur
FROM v_usage_fact u JOIN consumption c ON c.order_line_id = u.order_line_id
WHERE u.qty_wasted > 0
GROUP BY month, u.category_id, c.waste_reason_code
ORDER BY month, waste_eur DESC;

-- Q10 @insight  Why-not report for a process: every excluded candidate and the reason
SELECT p.name, er.label AS excluded_because
FROM candidate_exclusion ce
JOIN product p ON p.product_id = ce.product_id
JOIN exclusion_reason er ON er.reason_code = ce.reason_code
WHERE ce.process_id = :process_id;
