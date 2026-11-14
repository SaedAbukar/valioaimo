-- Governed catalogue: outcome labels and metrics (load after schema.sql).
-- Labels are computed by versioned rules when a process, line or event closes;
-- humans can override (source = 'human'). Metrics are the only definitions
-- dashboards may use, so every number means the same thing everywhere.

INSERT INTO label_definition (label_code, level, definition, rule_version) VALUES
 ('perfect_order',   'event',      'utilisation >= 0.95 on every line and no shortage', 'v1'),
 ('right_sized',     'order_line', 'utilisation between 0.90 and 1.00 and shortage_qty = 0', 'v1'),
 ('over_ordered',    'order_line', 'qty_wasted + qty_kept > 10% of ordered base qty', 'v1'),
 ('under_ordered',   'order_line', 'shortage_qty > 0 or emergency_purchase = 1', 'v1'),
 ('good_substitute', 'order_line', 'is_substitute and substitute_accepted = 1 and rating >= 4', 'v1'),
 ('bad_substitute',  'order_line', 'is_substitute and (substitute_accepted = 0 or rating <= 2)', 'v1'),
 ('price_good',      'order_line', 'price_per_base_unit <= 8-week org average for the product', 'v1'),
 ('late_delivery',   'order_line', 'delivered_at > need_by', 'v1'),
 ('autonomous',      'process',    'final policy outcome AUTO or NOTIFY', 'v1'),
 ('corrected',       'process',    'at least one manual_change with change_kind = error_correction', 'v1'),
 ('top_choice',      'process',    'ordered plan had rank 1', 'v1'),
 ('exception_free',  'process',    'no process_exception rows', 'v1');

INSERT INTO metric_definition (metric_code, name, formula, source_view, grain, unit, better_when, audience) VALUES
 ('autonomous_rate',        'Autonomous rate',          'AVG(final_outcome IN (''AUTO'',''NOTIFY''))', 'v_process_fact', 'process', '%', 'higher', 'both'),
 ('manual_correction_rate', 'Manual-correction rate',   'AVG(corrections > 0)', 'v_process_fact', 'process', '%', 'lower', 'both'),
 ('top_choice_rate',        'Top option chosen',        'AVG(chosen_rank = 1)', 'v_process_fact', 'process', '%', 'higher', 'buyer'),
 ('utilisation',            'Utilisation',              'SUM(qty_used) / SUM(qty_ordered_base)', 'v_usage_fact', 'order_line', '%', 'target', 'both'),
 ('waste_eur',              'Waste value',              'SUM(waste_value_eur)', 'v_usage_fact', 'order_line', 'EUR', 'lower', 'both'),
 ('waste_rate',             'Waste rate',               'SUM(qty_wasted) / SUM(qty_ordered_base)', 'v_usage_fact', 'order_line', '%', 'lower', 'both'),
 ('coverage',               'Coverage',                 'AVG(coverage)', 'v_request_fulfilment', 'request_line', '%', 'target', 'buyer'),
 ('rounding_overage',       'Case-rounding overage',    'SUM(overage_base)', 'v_request_fulfilment', 'request_line', 'base unit', 'lower', 'both'),
 ('need_by_hit_rate',       'Need-by hit rate',         'AVG(on_time_rate)', 'sig_supplier_reliability', 'org x supplier', '%', 'higher', 'both'),
 ('fill_rate',              'Fill rate',                'AVG(fill_rate)', 'sig_supplier_reliability', 'org x supplier', '%', 'higher', 'both'),
 ('approval_latency',       'Approval latency',         'AVG(avg_latency_min)', 'sig_approval_pattern', 'org x rule', 'min', 'lower', 'buyer'),
 ('substitute_acceptance',  'Substitute acceptance',    'SUM(accepted) / SUM(n)', 'sig_substitution_acceptance', 'org x swap', '%', 'higher', 'both'),
 ('spend_eur',              'Spend',                    'SUM(order_value_eur)', 'v_process_fact', 'process', 'EUR', 'target', 'buyer'),
 ('exceptions_per_process', 'Exceptions per process',   'AVG(exceptions)', 'v_process_fact', 'process', 'count', 'lower', 'aimo_ops');
