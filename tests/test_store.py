from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from demo import demo
from engine import Invalid
from store import Store, Conflict

TODAY = date(2026, 9, 21)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'test.sqlite')
        self.run = self.store.create(demo(TODAY))

    def tearDown(self): self.temp.cleanup()

    def decide(self, action='APPROVED', **kwargs):
        return self.store.decide(self.run['id'], action, 'Reviewer', 'Checked supplier and quantity', self.run['result']['snapshot_hash'], today=kwargs.get('today',TODAY))

    def test_export_requires_approval(self):
        with self.assertRaises(Conflict): self.store.export(self.run['id'], TODAY)

    def test_approved_export_is_idempotent_and_survives_restart(self):
        self.decide()
        first = self.store.export(self.run['id'], TODAY)
        reopened = Store(self.store.path)
        self.assertEqual(first,reopened.export(self.run['id'], TODAY))
        self.assertEqual(first['status'],'DRAFT_NOT_SENT')
        self.assertEqual(len(first['lines']),1)
        self.assertEqual(first['unresolved_skus'],['VAX-01'])
        self.assertEqual(len(reopened.get(self.run['id'])['events']),3)

    def test_rejection_and_double_decision(self):
        self.decide('REJECTED')
        with self.assertRaises(Conflict): self.decide()
        with self.assertRaises(Conflict): self.store.export(self.run['id'], TODAY)

    def test_new_snapshot_invalidates_approval_and_export(self):
        self.decide()
        d = demo(TODAY); d['budget_idr'] += 1
        self.store.create(d)
        with self.assertRaises(Conflict): self.store.export(self.run['id'], TODAY)
        self.assertFalse(self.store.get(self.run['id'])['is_current'])

    def test_new_snapshot_invalidates_pending_decision(self):
        d = demo(TODAY); d['budget_idr'] += 1
        self.store.create(d)
        with self.assertRaises(Conflict): self.decide()

    def test_old_date_blocked(self):
        with self.assertRaises(Conflict): self.decide(today=TODAY+timedelta(days=1))

    def test_wrong_review_hash(self):
        with self.assertRaises(Conflict):
            self.store.decide(self.run['id'],'APPROVED','Reviewer','Reason','wrong',TODAY)

    def test_reason_required(self):
        with self.assertRaises(Invalid):
            self.store.decide(self.run['id'],'APPROVED','Reviewer',' ',self.run['result']['snapshot_hash'],TODAY)

    def test_concurrent_approval_exactly_once(self):
        def attempt(_):
            try: self.decide(); return 'success'
            except Conflict: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt,range(2))),['conflict','success'])

    def test_empty_order_cannot_be_approved(self):
        d = demo(TODAY); d['budget_idr'] = 0
        self.run = self.store.create(d)
        with self.assertRaises(Conflict): self.decide()

    def test_identical_reimport_cannot_export_duplicate_order(self):
        self.decide()
        self.store.export(self.run['id'], TODAY)
        self.run = self.store.create(demo(TODAY))
        self.decide()
        with self.assertRaises(Conflict): self.store.export(self.run['id'], TODAY)


if __name__ == '__main__': unittest.main()
