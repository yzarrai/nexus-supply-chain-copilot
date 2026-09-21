from datetime import date, timedelta


def demo(today=None):
    today = today or date.today()
    products = [
        {'sku': 'AMX-500', 'name': 'Amoxicillin 500 mg · demo', 'unit': 'box', 'storage': 'ambient', 'priority': 1, 'min_remaining_days': 90, 'max_stock_units': 2000},
        {'sku': 'PAR-500', 'name': 'Paracetamol 500 mg · demo', 'unit': 'box', 'storage': 'ambient', 'priority': 2, 'min_remaining_days': 90, 'max_stock_units': 3000},
        {'sku': 'VAX-01', 'name': 'Vaccine · out of scope', 'unit': 'vial', 'storage': 'cold', 'priority': 1, 'min_remaining_days': 90, 'max_stock_units': 1000},
    ]
    iso = lambda delta: (today + timedelta(days=delta)).isoformat()
    return {
        'schema_version': '1.0', 'as_of': iso(0), 'warehouse': 'Surabaya demo DC', 'currency': 'IDR', 'budget_idr': 5000000, 'review_days': 7, 'safety_days': 3,
        'products': products,
        'lots': [
            {'lot_id': 'AMX-A', 'sku': 'AMX-500', 'quantity': 100, 'reserved': 20, 'expiry': iso(365), 'status': 'released'},
            {'lot_id': 'AMX-NEAR', 'sku': 'AMX-500', 'quantity': 120, 'reserved': 0, 'expiry': iso(91), 'status': 'released'},
            {'lot_id': 'AMX-Q', 'sku': 'AMX-500', 'quantity': 200, 'reserved': 0, 'expiry': iso(400), 'status': 'quarantine'},
            {'lot_id': 'PAR-A', 'sku': 'PAR-500', 'quantity': 900, 'reserved': 0, 'expiry': iso(365), 'status': 'released'},
        ],
        'demand': [{'date': iso(-i), 'sku': p['sku'], 'units': {'AMX-500': 20, 'PAR-500': 30, 'VAX-01': 5}[p['sku']], 'stockout': False} for p in products for i in range(28, 0, -1)],
        'offers': [
            {'offer_id': 'AMX-STANDARD', 'sku': 'AMX-500', 'supplier': 'Supplier A · standard', 'approved': True, 'lead_days': 7, 'pack_size': 10, 'moq': 50, 'unit_cost_idr': 15000, 'capacity_units': 1000, 'shelf_life_days': 365, 'valid_until': iso(30)},
            {'offer_id': 'AMX-FAST', 'sku': 'AMX-500', 'supplier': 'Supplier B · fast', 'approved': True, 'lead_days': 3, 'pack_size': 10, 'moq': 50, 'unit_cost_idr': 16500, 'capacity_units': 1000, 'shelf_life_days': 365, 'valid_until': iso(30)},
            {'offer_id': 'PAR-STANDARD', 'sku': 'PAR-500', 'supplier': 'Supplier A · standard', 'approved': True, 'lead_days': 5, 'pack_size': 20, 'moq': 100, 'unit_cost_idr': 8000, 'capacity_units': 2000, 'shelf_life_days': 365, 'valid_until': iso(30)},
        ],
        'inbound': [{'po_line_id': 'PO-001-1', 'sku': 'AMX-500', 'quantity': 40, 'arrival': iso(4), 'expiry': iso(365), 'status': 'confirmed'}],
    }
