import copy
import json
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline import ROOT,build_database,build_report,load_resources

class PipelineTests(unittest.TestCase):
    def setUp(self): self.resources,self.manifest=load_resources()
    def report(self):
        db,run=build_database(self.resources,self.manifest)
        try: return build_report(db,run)
        finally: db.close()
    def resource(self,kind,id,version=None):
        return next(r for r in self.resources if r['resourceType']==kind and r['id']==id and (version is None or r['meta']['versionId']==version))
    def patient(self,p): return next(r for r in self.report()['patients'] if r['person_id']==p)
    def test_independent_oracle(self):
        expected=json.loads((ROOT/'fixtures/expected.json').read_text())
        for r in self.report()['patients']:
            self.assertEqual({'outcome':r['outcome'],'value':r['value']},expected[r['person_id']])
        self.assertEqual(self.report()['counts'],{'imported':8,'qualifying':7,'measured':3,'meets_threshold':2,'below_threshold':1,'no_eligible_result':4,'outside_cohort':1,'naive':7})
    def test_shuffle_does_not_change_decisions(self):
        baseline=self.report()['patients']; random.Random(27).shuffle(self.resources)
        self.assertEqual(self.report()['patients'],baseline)
    def test_duplicate_idempotence(self):
        baseline=self.report()['patients']; self.resources+=copy.deepcopy(self.resources)
        self.assertEqual(self.report()['patients'],baseline)
    def test_conflicting_same_revision_fails(self):
        altered=copy.deepcopy(self.resource('Patient','A')); altered['birthDate']='1990-01-01'; self.resources.append(altered)
        with self.assertRaisesRegex(ValueError,'conflicting payloads'): self.report()
    def test_manifest_selection_not_numeric_version_order(self):
        r=self.resource('Observation','hba1c-B','original');r['meta']['versionId']='9999'
        self.assertEqual(self.patient('B')['value'],6.8)
    def test_withdrawal_does_not_resurrect_prior_result(self):
        self.assertEqual(self.patient('D')['outcome'],'no_eligible_result')
        db,run=build_database(self.resources,self.manifest)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM measurement WHERE person_id='D'").fetchone()[0],0);db.close()
    def test_window_boundaries(self):
        self.assertEqual(self.patient('H')['outcome'],'meets_threshold')
        self.assertEqual(self.patient('F')['outcome'],'no_eligible_result')
        db,run=build_database(self.resources,self.manifest)
        expanded=build_report(db,run,window_days=181)
        self.assertEqual(next(r for r in expanded['patients'] if r['person_id']=='F')['outcome'],'meets_threshold'); db.close()
    def test_unsupported_unit_retained(self):
        self.assertEqual(self.patient('E')['value'],None)
        rows=self.report()['tables']['measurement']; self.assertEqual(next(r for r in rows if r['person_id']=='E')['value'],64)
    def test_missing_is_not_zero(self): self.assertIsNone(self.patient('G')['value'])
    def test_missing_patient_quarantined_and_audit_survives(self):
        self.resource('Observation','hba1c-B','corrected-release')['subject']['reference']='Patient/missing'
        self.resource('Observation','hba1c-C')['subject']['reference']='Patient/missing'
        r=self.report();self.assertEqual(r['dispositions']['quarantined'],2)
        self.assertEqual(self.patient('B')['outcome'],'no_eligible_result')
    def test_optional_visit_not_invented(self):
        r=self.report();self.assertTrue(all(m['visit_id'] is None for m in r['tables']['measurement']))
    def test_cross_patient_visit_quarantined(self):
        self.resource('Observation','hba1c-B','corrected-release')['encounter']={'reference':'Encounter/visit-A'}
        p=self.patient('B');self.assertEqual(p['outcome'],'no_eligible_result');self.assertIn('cross-patient',p['reason'])
    def test_wrong_code_system_not_accepted(self):
        self.resource('Condition','diabetes-A')['code']['coding'][0]['system']='https://wrong.example'
        self.assertEqual(self.patient('A')['outcome'],'outside_cohort')
    def test_unsupported_modifier_stops_resource(self):
        self.resource('Observation','hba1c-H')['modifierExtension']=[{'url':'https://example.org/unknown','valueBoolean':True}]
        self.assertEqual(self.patient('H')['outcome'],'no_eligible_result')
    def test_latest_eligible_not_latest_any(self):
        extra=copy.deepcopy(self.resource('Observation','hba1c-A'));extra['id']='later-A';extra['status']='preliminary';extra['effectiveDateTime']='2025-04-01';extra['valueQuantity']['value']=12
        self.resources.append(extra);self.manifest['current_versions']['Observation/later-A']='original'
        self.assertEqual(self.patient('A')['value'],8.4)
    def test_disposition_reconciliation_and_foreign_keys(self):
        report=self.report();self.assertEqual(sum(report['dispositions'].values()),report['run']['unique_revisions'])
        self.assertEqual(report['run']['supplied_payloads'],report['run']['unique_revisions']+report['run']['duplicate_copies'])
        db,run=build_database();self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[]);db.close()
    def test_rerun_stable(self): self.assertEqual(self.report(),self.report())
    def test_tie_is_stable_and_flagged(self):
        extra=copy.deepcopy(self.resource('Observation','hba1c-A'));extra['id']='aaa-tie-A';extra['valueQuantity']['value']=7
        self.resources.append(extra);self.manifest['current_versions']['Observation/aaa-tie-A']='original'
        p=self.patient('A');self.assertEqual(p['value'],7);self.assertTrue(p['warnings'])
    def test_underage_excluded(self):
        self.resource('Patient','A')['birthDate']='2010-06-12'
        self.assertEqual(self.patient('A')['outcome'],'outside_cohort')

if __name__=='__main__': unittest.main()
