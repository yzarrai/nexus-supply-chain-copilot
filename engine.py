"""Pure, deterministic decision functions. No network, LLM, or database access."""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import math

VERSION = 'baseline-fefo-1.0'


class Invalid(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


def integer(value, label, minimum=0, maximum=10**9):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Invalid(f'{label}: expected integer {minimum}..{maximum}')


def day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise Invalid(f'Invalid ISO date: {value}') from None


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise Invalid(f'{label}: nonempty text of at most 160 characters required')


def keys(obj, required, label):
    if not isinstance(obj, dict) or set(obj) != set(required.split()):
        raise Invalid(f'{label}: expected exactly these fields: {required}')


def validate(data):
    keys(data, 'schema_version as_of warehouse currency budget_idr review_days safety_days products lots demand offers inbound', 'snapshot')
    if data['schema_version'] != '1.0' or data['currency'] != 'IDR':
        raise Invalid('Only schema 1.0 and IDR are supported')
    today = day(data['as_of'])
    text(data['warehouse'], 'warehouse')
    integer(data['budget_idr'], 'budget_idr', maximum=10**12)
    integer(data['review_days'], 'review_days', 1, 28)
    integer(data['safety_days'], 'safety_days', 0, 14)
    for name in ['products', 'lots', 'demand', 'offers', 'inbound']:
        if not isinstance(data[name], list) or len(data[name]) > 10000:
            raise Invalid(f'{name}: expected array with at most 10000 entries')
    if not 1 <= len(data['products']) <= 100:
        raise Invalid('Provide 1..100 products')
    products = {}
    for p in data['products']:
        keys(p, 'sku name unit storage priority min_remaining_days max_stock_units', 'product')
        for k in ['sku', 'name', 'unit']:
            text(p[k], k)
        if p['sku'] in products:
            raise Invalid('Duplicate SKU')
        if p['storage'] not in ['ambient', 'cold']:
            raise Invalid('storage must be ambient or cold')
        integer(p['priority'], 'priority', 1, 5)
        integer(p['min_remaining_days'], 'min_remaining_days', 1, 730)
        integer(p['max_stock_units'], 'max_stock_units', 1, 10**7)
        products[p['sku']] = p
    seen = set()
    for kind in ['lots', 'demand', 'offers', 'inbound']:
        for row in data[kind]:
            if not isinstance(row, dict) or row.get('sku') not in products:
                raise Invalid(f'{kind}: unknown SKU')
            if kind == 'lots':
                keys(row, 'lot_id sku quantity reserved expiry status', kind)
                text(row['lot_id'], 'lot_id')
                unique = (kind, row['lot_id'])
                integer(row['quantity'], 'quantity')
                integer(row['reserved'], 'reserved', 0, row['quantity'])
                day(row['expiry'])
                if row['status'] not in ['released', 'quarantine', 'recalled']:
                    raise Invalid('Unknown lot status')
            elif kind == 'demand':
                keys(row, 'date sku units stockout', kind)
                d = day(row['date'])
                if not today - timedelta(days=28) <= d < today:
                    raise Invalid('Demand must be exactly the 28 days preceding as_of')
                integer(row['units'], 'units', 0, 10**7)
                if type(row['stockout']) is not bool:
                    raise Invalid('stockout must be a boolean')
                unique = (kind, row['sku'], row['date'])
            elif kind == 'offers':
                keys(row, 'offer_id sku supplier approved lead_days pack_size moq unit_cost_idr capacity_units shelf_life_days valid_until', kind)
                for k in ['offer_id', 'supplier']:
                    text(row[k], k)
                if type(row['approved']) is not bool:
                    raise Invalid('approved must be a boolean')
                for k, low, high in [('lead_days', 1, 60), ('pack_size', 1, 10**6), ('moq', 1, 10**7), ('unit_cost_idr', 1, 10**9), ('capacity_units', 0, 10**7), ('shelf_life_days', 1, 730)]:
                    integer(row[k], k, low, high)
                day(row['valid_until'])
                unique = (kind, row['offer_id'])
            else:
                keys(row, 'po_line_id sku quantity arrival expiry status', kind)
                text(row['po_line_id'], 'po_line_id')
                integer(row['quantity'], 'quantity', 1)
                arrival, expiry = day(row['arrival']), day(row['expiry'])
                if row['status'] not in ['confirmed', 'unconfirmed']:
                    raise Invalid('Unknown inbound status')
                if row['status'] == 'confirmed' and arrival < today:
                    raise Invalid('Overdue confirmed inbound requires an updated ETA')
                if expiry <= arrival:
                    raise Invalid('Inbound expiry must follow arrival')
                unique = (kind, row['po_line_id'])
            if unique in seen:
                raise Invalid(f'Duplicate record: {unique}')
            seen.add(unique)
    for sku in products:
        if sum(r['sku'] == sku for r in data['demand']) != 28:
            raise Invalid(f'{sku}: 28 complete daily demand rows required; missing is not zero')
    return data


def simulate(data, product, daily, horizon, proposed=None):
    """Daily FEFO: receipts, eligibility expiry, consumption. Unmet demand is lost.

    Expiry minus customer minimum remaining life is the exclusive use-by date.
    Reserved stock is already unavailable; demand means future unreserved demand.
    """
    today = day(data['as_of'])
    buffer_days = timedelta(days=product['min_remaining_days'])
    batches = []
    inbound = []
    for r in data['lots']:
        if r['sku'] == product['sku'] and r['status'] == 'released':
            batches.append([day(r['expiry']) - buffer_days, float(r['quantity'] - r['reserved'])])
    for r in data['inbound']:
        if r['sku'] == product['sku'] and r['status'] == 'confirmed':
            inbound.append((day(r['arrival']), day(r['expiry']) - buffer_days, r['quantity']))
    if proposed:
        offer, qty = proposed
        arrival = today + timedelta(days=offer['lead_days'])
        inbound.append((arrival, arrival + timedelta(days=offer['shelf_life_days']) - buffer_days, qty))
    missed, excluded, first_shortage = 0.0, 0.0, None
    trace = []
    for offset in range(horizon):
        current = today + timedelta(days=offset)
        batches.extend([[expiry, float(qty)] for arrival, expiry, qty in inbound if arrival == current])
        for b in batches:
            if b[0] <= current:
                excluded += b[1]
                b[1] = 0
        need = daily
        for b in sorted(batches, key=lambda x: x[0]):
            take = min(need, b[1])
            b[1] -= take
            need -= take
        if need > 1e-8 and first_shortage is None:
            first_shortage = current.isoformat()
        missed += need
        trace.append({'date': current.isoformat(), 'available_end': round(sum(b[1] for b in batches), 3), 'unmet': round(need, 3)})
    return {'unmet_units': round(missed, 3), 'end_units': round(sum(b[1] for b in batches), 3), 'excluded_units': round(excluded, 3), 'first_shortage': first_shortage, 'trace': trace}


def plan(data):
    validate(data)
    today = day(data['as_of'])
    remaining = data['budget_idr']
    lines = []
    # Explicit deterministic priority heuristic; never claim a global optimum.
    for p in sorted(data['products'], key=lambda p: (p['priority'], p['sku'])):
        sku = p['sku']
        history = [r for r in data['demand'] if r['sku'] == sku]
        daily = sum(r['units'] for r in history) / 28
        line = {'sku': sku, 'name': p['name'], 'unit': p['unit'], 'priority': p['priority'], 'daily_demand': round(daily, 4), 'status': 'REVIEW', 'warnings': [], 'options': [], 'selected': None}
        lines.append(line)
        if p['storage'] != 'ambient':
            line.update(status='BLOCKED', warnings=['Cold-chain products require qualified storage and transport constraints; unsupported in this slice.'])
            continue
        if any(r['stockout'] for r in history):
            line.update(status='BLOCKED', warnings=['Stockout-censored sales are not an adequate demand estimate. Planner input required.'])
            continue
        if daily == 0:
            line.update(status='NO_ORDER', warnings=['Zero observed demand; no automatic replenishment.'])
            continue
        raw_offers = [o for o in data['offers'] if o['sku'] == sku]
        # Common evaluation horizon makes supplier comparisons comparable.
        horizon = max([o['lead_days'] for o in raw_offers] or [7]) + data['review_days']
        baseline = simulate(data, p, daily, horizon)
        line['horizon_days'] = horizon
        line['baseline'] = baseline
        eligible_now = sum(r['quantity'] - r['reserved'] for r in data['lots'] if r['sku'] == sku and r['status'] == 'released' and day(r['expiry']) - timedelta(days=p['min_remaining_days']) > today)
        line['usable_now'] = eligible_now
        if baseline['excluded_units']:
            line['warnings'].append('Some stock becomes ineligible before use; see expiry exclusion in the projection.')
        if any(r['sku'] == sku and r['status'] == 'unconfirmed' for r in data['inbound']):
            line['warnings'].append('Unconfirmed inbound is excluded.')
        need_any = False
        for offer in raw_offers:
            base = baseline
            # Lost demand BEFORE arrival cannot be recovered by a new order.
            before = simulate(data, p, daily, offer['lead_days'])['unmet_units']
            requirement = max(0, base['unmet_units'] - before + daily * data['safety_days'] - base['end_units'])
            qty = math.ceil(max(requirement, offer['moq']) / offer['pack_size']) * offer['pack_size'] if requirement > 1e-6 else 0
            need_any = need_any or qty > 0
            reasons = []
            if not offer['approved']:
                reasons.append('Supplier not approved')
            if day(offer['valid_until']) < today:
                reasons.append('Offer expired')
            if offer['shelf_life_days'] <= p['min_remaining_days'] + horizon - offer['lead_days'] + data['safety_days']:
                reasons.append('Insufficient remaining shelf life')
            if qty > offer['capacity_units']:
                reasons.append('Supplier capacity exceeded')
            # Conservative stock cap: all physical stock + confirmed inbound + new order.
            physical = sum(r['quantity'] for r in data['lots'] if r['sku'] == sku)
            incoming = sum(r['quantity'] for r in data['inbound'] if r['sku'] == sku and r['status'] == 'confirmed')
            if physical + incoming + qty > p['max_stock_units']:
                reasons.append('Conservative SKU storage cap exceeded')
            cost = qty * offer['unit_cost_idr']
            if cost > remaining:
                reasons.append('Remaining shared budget exceeded')
            result = simulate(data, p, daily, horizon, (offer, qty))
            option = {'offer_id': offer['offer_id'], 'supplier': offer['supplier'], 'quantity': qty, 'unit_cost_idr': offer['unit_cost_idr'], 'cost_idr': cost, 'lead_days': offer['lead_days'], 'arrival': (today + timedelta(days=offer['lead_days'])).isoformat(), 'reasons': reasons, 'feasible': not reasons, 'projection': result}
            line['options'].append(option)
        feasible = [o for o in line['options'] if o['feasible']]
        if feasible:
            chosen = min(feasible, key=lambda o: (o['projection']['unmet_units'], o['cost_idr'], o['lead_days'], o['offer_id']))
            line['selected'] = deepcopy(chosen)
            remaining -= chosen['cost_idr']
            line['status'] = 'RECOMMEND' if chosen['quantity'] else 'NO_ORDER'
            if chosen['projection']['unmet_units']:
                line['warnings'].append('Shortage remains in the projection. Procurement alone does not resolve all demand; escalate for expediting or transfer review.')
        elif raw_offers and not need_any and not baseline['unmet_units']:
            line['status'] = 'NO_ORDER'
        else:
            line['status'] = 'BLOCKED'
            line['warnings'].append('No feasible supplier option within constraints.')
    return {'engine_version': VERSION, 'snapshot_hash': fingerprint(data), 'as_of': data['as_of'], 'warehouse': data['warehouse'], 'currency': 'IDR', 'method': '28-day mean + daily FEFO + priority-first supplier heuristic', 'budget_idr': data['budget_idr'], 'total_cost_idr': data['budget_idr'] - remaining, 'remaining_budget_idr': remaining, 'lines': lines, 'disclaimer': 'Deterministic projection, not a calibrated stockout probability. Synthetic demonstration; approval exports a draft requisition only.'}
