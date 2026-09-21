from copy import deepcopy
from datetime import date, timedelta
import unittest

from demo import demo
from engine import Invalid, fingerprint, plan, simulate, validate

TODAY = date(2026, 9, 21)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.data = demo(TODAY)

    def amx(self, data=None):
        return next(l for l in plan(data or self.data)['lines'] if l['sku'] == 'AMX-500')

    def test_known_order_and_cost(self):
        r = self.amx()
        self.assertEqual((r['selected']['quantity'], r['selected']['cost_idr']), (200, 3000000))
        self.assertEqual(r['selected']['supplier'], 'Supplier A · standard')
        self.assertEqual(r['selected']['projection']['unmet_units'], 0)

    def test_no_input_mutation_and_determinism(self):
        before = deepcopy(self.data)
        self.assertEqual(plan(self.data), plan(self.data))
        self.assertEqual(self.data, before)

    def test_suppliers_are_sized_to_same_comparison_horizon(self):
        options = self.amx()['options']
        self.assertEqual([o['quantity'] for o in options], [200, 200])
        self.assertEqual([len(o['projection']['trace']) for o in options], [14, 14])

    def test_reserved_and_quarantine_are_unavailable(self):
        self.assertEqual(self.amx()['usable_now'], 200)
        self.data['lots'][2]['quantity'] += 500
        self.assertEqual(self.amx()['usable_now'], 200)

    def test_near_expiry_consumed_first(self):
        result = simulate(self.data, self.data['products'][0], 20, 2)
        self.assertEqual(result['excluded_units'], 100)
        self.assertEqual(result['end_units'], 60)

    def test_expiry_exclusive_boundary(self):
        self.data['lots'] = [{'lot_id':'boundary','sku':'AMX-500','quantity':100,'reserved':0,'expiry':(TODAY+timedelta(days=90)).isoformat(),'status':'released'}]
        result = simulate(self.data, self.data['products'][0], 20, 1)
        self.assertEqual(result['unmet_units'], 20)
        self.assertEqual(result['excluded_units'], 100)

    def test_late_receipt_cannot_erase_earlier_shortage(self):
        self.data['lots'] = []
        self.data['inbound'][0]['arrival'] = (TODAY+timedelta(days=3)).isoformat()
        result = simulate(self.data, self.data['products'][0], 20, 4)
        self.assertEqual(result['unmet_units'], 60)
        self.assertEqual(result['first_shortage'], TODAY.isoformat())

    def test_unconfirmed_receipts_ignored(self):
        old = self.amx()['baseline']['unmet_units']
        self.data['inbound'][0]['status'] = 'unconfirmed'
        self.assertGreater(self.amx()['baseline']['unmet_units'], old)
        self.assertIn('Unconfirmed inbound is excluded.', self.amx()['warnings'])

    def test_cold_product_blocked(self):
        self.assertEqual(next(l for l in plan(self.data)['lines'] if l['sku']=='VAX-01')['status'], 'BLOCKED')

    def test_censored_demand_blocked(self):
        self.data['demand'][0]['stockout'] = True
        self.assertEqual(self.amx()['status'], 'BLOCKED')

    def test_missing_and_duplicate_demand_rejected(self):
        for mode in ['missing','duplicate']:
            d = deepcopy(self.data)
            if mode == 'missing': d['demand'].pop()
            else: d['demand'].append(d['demand'][0])
            with self.assertRaises(Invalid): plan(d)

    def test_future_demand_rejected(self):
        self.data['demand'][0]['date'] = TODAY.isoformat()
        with self.assertRaises(Invalid): plan(self.data)

    def test_nan_boolean_negative_and_unknown_field_rejected(self):
        for value in [float('nan'), True, -1, 1.5]:
            d = deepcopy(self.data)
            d['budget_idr'] = value
            with self.assertRaises(Invalid): plan(d)
        self.data['unexpected'] = 1
        with self.assertRaises(Invalid): plan(self.data)

    def test_overdue_inbound_rejected(self):
        self.data['inbound'][0]['arrival'] = (TODAY-timedelta(days=1)).isoformat()
        with self.assertRaises(Invalid): plan(self.data)

    def test_budget_is_hard_limit(self):
        self.data['budget_idr'] = 100
        r = plan(self.data)
        self.assertLessEqual(r['total_cost_idr'], 100)
        self.assertEqual(self.amx()['status'], 'BLOCKED')

    def test_shared_budget_not_per_sku(self):
        self.data['lots'] = [r for r in self.data['lots'] if r['sku']!='PAR-500']
        self.data['budget_idr'] = 3500000
        r = plan(self.data)
        self.assertLessEqual(r['total_cost_idr'], 3500000)
        self.assertEqual(next(l for l in r['lines'] if l['sku']=='PAR-500')['status'],'BLOCKED')

    def test_supplier_eligibility_capacity_and_shelf_life(self):
        for field, value in [('approved',False),('capacity_units',1),('shelf_life_days',95),('valid_until','2026-01-01')]:
            d = deepcopy(self.data)
            for o in d['offers']: o[field] = value
            self.assertEqual(self.amx(d)['status'], 'BLOCKED')

    def test_moq_and_pack_round_up(self):
        self.data['offers'][0].update(moq=251, pack_size=12)
        option = self.amx()['options'][0]
        self.assertEqual(option['quantity'], 252)

    def test_stock_cap(self):
        self.data['products'][0]['max_stock_units'] = 450
        self.assertEqual(self.amx()['status'], 'BLOCKED')

    def test_zero_demand(self):
        for r in self.data['demand']: r['units'] = 0
        self.assertEqual(self.amx()['status'], 'NO_ORDER')

    def test_no_suppliers(self):
        self.data['offers'] = []
        self.assertEqual(self.amx()['status'], 'BLOCKED')

    def test_high_stock_does_not_force_moq(self):
        self.data['lots'][0]['quantity'] = 1500
        self.assertEqual(self.amx()['status'], 'NO_ORDER')

    def test_expired_lots_do_not_add_available_stock(self):
        self.data['lots'][0]['expiry'] = '2025-01-01'
        self.assertEqual(self.amx()['usable_now'], 120)

    def test_unknown_sku_and_reserved_overflow(self):
        for field, value in [('sku','UNKNOWN'),('reserved',101)]:
            d = deepcopy(self.data)
            d['lots'][0][field] = value
            with self.assertRaises(Invalid): validate(d)


if __name__ == '__main__': unittest.main()
