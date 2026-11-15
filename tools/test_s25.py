"""Operator-run planner contracts. No Django, database, Docker or network use."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from legacy_plan import afm, build_plan, cents, day, digest, positive_id, read_json

FIXTURES = Path(__file__).resolve().parents[1]/'docs/implementation/fixtures'


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.source = read_json(FIXTURES/'s25-source.json')
        self.review = read_json(FIXTURES/'s25-review.json')

    def plan(self):
        self.review['source_sha256'] = digest(self.source)
        return build_plan(self.source,self.review)

    def state(self, plan, key):
        return next(e for e in plan['entries'] if e['key'] == key)

    def test_every_identity_has_a_disposition(self):
        plan = self.plan()
        self.assertTrue(plan['all_source_identities_covered'])
        self.assertEqual(plan['unresolved'],[])
        self.assertEqual(len(plan['entries']),32)
        self.assertFalse(plan['live_cutover_approved'])

    def test_exact_cash_opening_and_transfer_totals(self):
        expected = self.plan()['expected']['accounts']
        self.assertEqual(expected['cash_accounts:1'],dict(opening='120.00',balance='335.00',income='375.00',expense='120.00',transfer_in='0.00',transfer_out='40.00'))
        self.assertEqual(expected['cash_accounts:2']['balance'],'40.00')
        self.assertEqual(expected['cash_accounts:3']['balance'],'95.00')
        self.assertEqual(expected['cash_accounts:4']['balance'],'0.00')

    def test_zero_and_negative_cash_are_quarantined_without_abs_or_round(self):
        plan = self.plan()
        for key in ('transactions:8','transactions:9'):
            self.assertEqual(self.state(plan,key)['action'],'quarantine')
            self.assertNotIn(key,plan['expected']['cash'])
        self.assertEqual(self.source['transactions'][8]['amount'],'-5.00')

    def test_uuid_default_singleton_is_ordinary(self):
        plan = self.plan()
        self.assertFalse(plan['expected']['cash']['transactions:17']['transfer'])
        self.assertEqual(plan['transfers'],[['transactions:6','transactions:7']])

    def test_ambiguous_group_keeps_all_three_legs_in_quarantine(self):
        plan = self.plan()
        for key in ('transactions:11','transactions:12','transactions:13'):
            self.assertIn('ambiguous-transfer',self.state(plan,key)['issues'])

    def test_pair_requires_independent_supporting_reference(self):
        self.review['transfers'] = {}
        plan = self.plan()
        self.assertEqual(plan['transfers'],[])
        self.assertIn('transactions:6',plan['unresolved'])
        self.assertNotIn('transactions:7',plan['expected']['cash'])

    def test_pair_with_only_one_preopening_leg_is_not_half_imported(self):
        self.review['records']['cash_accounts:2']['opening']['date']='2026-01-07'
        plan = self.plan()
        self.assertEqual(plan['transfers'],[])
        self.assertEqual(self.state(plan,'transactions:6')['action'],'quarantine')
        self.assertEqual(self.state(plan,'transactions:7')['action'],'quarantine')

    def test_invalid_settlement_link_keeps_real_cash_without_allocation(self):
        plan = self.plan()
        self.assertEqual(self.state(plan,'transactions:10')['action'],'hold-unallocated')
        self.assertEqual(plan['expected']['cash']['transactions:10']['unallocated'],'25.00')

    def test_old_completed_status_does_not_settle_debt(self):
        plan = self.plan()
        self.assertEqual(self.source['agreements'][1]['status'],'COMPLETED')
        self.assertEqual(plan['expected']['charges']['agreements:2/0']['outstanding'],'20.00')
        self.assertEqual(plan['obligation_reconciliation']['agreements:2']['derived_state'],'OPEN')

    def test_raw_source_difference_is_explained_by_excluded_cash(self):
        plan=self.plan()
        for row in plan['raw_account_reconciliation'].values():
            self.assertEqual(row['unexplained_difference'],'0.00')
            self.assertEqual(row['unpriced_source_rows'],[])
        self.assertEqual(plan['raw_account_reconciliation']['cash_accounts:3']['raw_balance'],'110.00')
        self.assertEqual(plan['raw_account_reconciliation']['cash_accounts:3']['excluded_signed_cash'],'15.00')

    def test_credit_and_supplier_advance_are_source_bound(self):
        cash = self.plan()['expected']['cash']
        self.assertEqual(cash['transactions:3']['unallocated'],'50.00')
        self.assertEqual(cash['transactions:5']['unallocated'],'20.00')

    def test_unmapped_user_is_never_given_a_default_office(self):
        plan = self.plan()
        self.assertEqual(self.state(plan,'users:3')['action'],'quarantine')
        self.assertIn('unmapped-user',self.state(plan,'transactions:15')['issues'])
        self.assertNotIn('transactions:15',plan['expected']['cash'])

    def test_foreign_party_reference_denied(self):
        plan = self.plan()
        self.assertIn('foreign-or-missing-reference',self.state(plan,'transactions:14')['issues'])

    def test_opening_contains_precutoff_cash_once(self):
        plan = self.plan()
        self.assertEqual(self.state(plan,'transactions:1')['action'],'opening-component')
        self.assertNotIn('transactions:1',plan['expected']['cash'])
        self.assertEqual(plan['expected']['accounts']['cash_accounts:1']['opening'],'120.00')

    def test_wrong_opening_amount_is_unresolved(self):
        self.review['records']['cash_accounts:1']['opening']['amount']='100.00'
        self.assertIn('cash_accounts:1:opening-mismatch',self.plan()['unresolved'])

    def test_stale_source_hash_rejected(self):
        self.source['cash_accounts'][0]['name']='Άλλαξε μετά την ανασκόπηση'
        with self.assertRaises(ValueError):
            build_plan(self.source,self.review)

    def test_duplicate_identity_rejected(self):
        self.source['transactions'].append(copy.deepcopy(self.source['transactions'][0]))
        with self.assertRaises(ValueError):
            self.plan()

    def test_unknown_review_identity_rejected(self):
        self.review['records']['transactions:999']={}
        with self.assertRaises(ValueError):
            self.plan()

    def test_changed_lineage_rejected(self):
        self.review['lineage']='another-source'
        with self.assertRaises(ValueError):
            self.plan()

    def test_overallocation_rejected(self):
        self.review['records']['transactions:3']['allocations'][0]['amount']='150.00'
        with self.assertRaises(ValueError):
            self.plan()

    def test_cross_office_allocation_rejected(self):
        self.review['records']['transactions:3']['allocations'][0]['agreement']=3
        with self.assertRaises(ValueError):
            self.plan()

    def test_backdated_allocation_rejected(self):
        self.review['records']['transactions:3']['allocations'][0]['date']='2026-01-01'
        with self.assertRaises(ValueError):
            self.plan()

    def test_held_cash_cannot_be_settled(self):
        self.review['records']['transactions:10']['allocations']=[{'agreement':1,'charge':0,'amount':'1.00','date':'2026-01-10','reference':'SYNTHETIC'}]
        with self.assertRaises(ValueError):
            self.plan()

    def test_review_reference_required(self):
        self.review['records']['cash_accounts:1']['reference']=''
        plan = self.plan()
        self.assertIn('cash_accounts:1',plan['unresolved'])

    def test_quarantine_needs_recorded_reason(self):
        self.review['records']['transactions:8']['reason']=''
        self.assertIn('transactions:8',self.plan()['unresolved'])

    def test_no_implicit_import_of_blocked_master(self):
        self.review['records']['entities:1']['action']='quarantine'
        plan = self.plan()
        self.assertIn('blocked-master',self.state(plan,'transactions:2')['issues'])

    def test_category_cycle_quarantines_descendants(self):
        self.source['categories'][0]['parent_id']=2
        plan = self.plan()
        self.assertIn('category-cycle',self.state(plan,'categories:1')['issues'])
        self.assertEqual(self.state(plan,'categories:2')['action'],'quarantine')

    def test_named_human_approval_is_not_inferred(self):
        plan = self.plan()
        self.assertEqual(plan['financial_acceptance'],'Pending')
        self.assertEqual(plan['mode'],'synthetic')
        self.assertNotIn('reviewer_name',self.review)

    def test_money_denies_float_boolean_precision_nan_and_overflow(self):
        for value in (1.2,True,'1','1.2','1.230','NaN','Infinity','-0.01','0.00','10000000000.00'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                cents(value)
        self.assertEqual(str(cents('-10.00',signed=True)),'-10.00')

    def test_identifier_and_date_are_strict(self):
        for value in (True,1.5,'1',0,-1):
            with self.subTest(value=value),self.assertRaises(ValueError):
                positive_id(value)
        with self.assertRaises(ValueError):
            day('2026-2-01')

    def test_duplicate_json_keys_and_float_literals_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'review.json'
            for text in ('{"amount":"1.00","amount":"2.00"}','{"amount":1.1}','{"amount":NaN}'):
                path.write_text(text)
                with self.subTest(text=text),self.assertRaises(ValueError):
                    read_json(path)

    def test_afm_matches_s15_syntax_without_new_checksum_policy(self):
        self.assertEqual(afm(' EL １２３-４５６７８９ '),'123456789')
        self.assertEqual(afm(''),'')
        self.assertEqual(afm('000000000'),'000000000')
        with self.assertRaises(ValueError):
            afm('1234')

    def test_reviewed_finite_monthly_schedule(self):
        agreement = self.source['agreements'][0]
        agreement['start_date']='2026-01-15'; agreement['total_amount']='300.00'
        choice = self.review['records']['agreements:1']
        choice['billing_mode']='MONTHLY'
        choice['charges']=[{'amount':'150.00','date':'2026-01-15','due':'2026-01-31','period':'2026-01-01'},
            {'amount':'300.00','date':'2026-02-01','due':'2026-02-28','period':'2026-02-01'}]
        # Review cash as credit; the old references never automatically allocate.
        for key in ('transactions:2','transactions:3'):
            self.review['records'][key].pop('allocations')
        plan = self.plan()
        self.assertEqual(plan['expected']['charges']['agreements:1/0']['amount'],'150.00')
        self.assertEqual(plan['expected']['charges']['agreements:1/1']['amount'],'300.00')

    def test_partial_full_month_needs_review_instead_of_automatic_proration(self):
        choice=self.review['records']['agreements:1'];choice['billing_mode']='MONTHLY'
        choice['charges'][0].update(amount='10.00',period='2026-01-01')
        self.review['records']['transactions:2'].pop('allocations')
        self.review['records']['transactions:3'].pop('allocations')
        plan=self.plan()
        self.assertEqual(self.state(plan,'agreements:1')['action'],'quarantine')


if __name__ == '__main__':
    unittest.main()
