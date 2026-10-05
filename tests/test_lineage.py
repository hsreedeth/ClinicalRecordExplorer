"""Lineage must explain SQL results without resurrecting source history."""
import unittest
from pipeline import build_database,build_report

class LineageTests(unittest.TestCase):
    def setUp(self): self.db,self.run=build_database()
    def tearDown(self): self.db.close()
    def nodes(self,patient,days=180):
        return [n for n in build_report(self.db,self.run,window_days=days)['lineage']['nodes'] if n['patient_id']==patient]
    def test_correction_and_withdrawal(self):
        b=self.nodes('B')
        self.assertTrue(any(n.get('disposition')=='superseded' and n.get('source_json',{}).get('valueQuantity',{}).get('value')==9.1 for n in b))
        self.assertEqual(next(n for n in b if n['rule_id']=='threshold')['evidence']['value'],6.8)
        d=self.nodes('D')
        self.assertTrue(any(n['title']=='Transformation / audit' and n['decision']=='fail' and n.get('disposition')=='withdrawn' for n in d))
        self.assertEqual(next(n for n in d if n['rule_id']=='threshold')['decision'],'not evaluated')
    def test_window_boundary_and_dependency(self):
        f=next(n for n in self.nodes('F') if n['rule_id'].endswith('-window'))
        self.assertEqual(f['decision'],'fail')
        self.assertEqual(next(n for n in self.nodes('F',181) if n['rule_id'].endswith('-window'))['decision'],'pass')
        self.assertEqual(next(n for n in self.nodes('H') if n['rule_id'].endswith('-window'))['decision'],'pass')
        report=build_report(self.db,self.run)
        self.assertIn({'source':'F:index','target':f['id'],'patient_id':'F'},report['lineage']['edges'])
    def test_missing_measurement_and_blocked_checks(self):
        self.assertFalse(any(n.get('source_json',{}).get('resourceType')=='Observation' for n in self.nodes('G')))
        c=self.nodes('C')
        self.assertEqual(next(n for n in c if n['title']=='Diagnosis verification')['decision'],'fail')
        self.assertEqual(next(n for n in c if n['title']=='Clinical status')['decision'],'not evaluated')
    def test_integrity(self):
        report=build_report(self.db,self.run);nodes=report['lineage']['nodes'];ids={n['id'] for n in nodes}
        self.assertEqual(len(ids),len(nodes))
        for n in nodes:
            self.assertIn(n['decision'],('pass','fail','not applicable','not evaluated'))
            self.assertTrue(n['evidence']);self.assertTrue(n['reason'])
        for e in report['lineage']['edges']:
            self.assertIn(e['source'],ids);self.assertIn(e['target'],ids)

    def test_stage_partition_and_summaries(self):
        report=build_report(self.db,self.run);lineage=report['lineage']
        self.assertEqual(report['schema_version'],2)
        self.assertEqual(lineage['schema_version'],1)
        self.assertEqual(len(lineage['groups']),40)
        def group(patient,stage): return next(g for g in lineage['groups'] if g['patient_id']==patient and g['stage_id']==stage)
        self.assertEqual(group('B','source')['summary'],'9.1% → corrected 6.8%')
        self.assertEqual(group('C','diagnosis')['summary'],'Refuted diagnosis')
        self.assertEqual(group('D','source')['summary'],'Current result withdrawn')
        self.assertEqual(group('D','measurement')['decision'],'not evaluated')
        self.assertEqual(group('E','measurement')['summary'],'Unsupported unit: mmol/mol')
        self.assertEqual(group('F','measurement')['summary'],'Day 181: outside window')
        self.assertEqual(group('G','measurement')['summary'],'No measurement recorded')
        self.assertEqual(group('G','measurement')['member_ids'],[])
        self.assertEqual(group('H','measurement')['summary'],'Day 180: included')
        assigned=[id for g in lineage['groups'] for id in g['member_ids']]
        self.assertEqual(sorted(assigned),sorted(n['id'] for n in lineage['nodes']))

    def test_stage_summaries_update_from_computed_evidence(self):
        report=build_report(self.db,self.run,threshold=9,window_days=181)
        f=next(g for g in report['lineage']['groups'] if g['patient_id']=='F' and g['stage_id']=='measurement')
        self.assertEqual(f['summary'],'Day 181: included');self.assertEqual(f['decision'],'pass')
        a=next(g for g in report['lineage']['groups'] if g['patient_id']=='A' and g['stage_id']=='outcome')
        self.assertEqual(a['summary'],'Below threshold')

    def test_contract_rejects_broken_dependencies(self):
        from pipeline import validate_lineage
        report=build_report(self.db,self.run)
        report['lineage']['edges'][0]['target']='missing-node'
        with self.assertRaisesRegex(ValueError,'Invalid lineage edge'):
            validate_lineage(report['lineage'],{r['person_id'] for r in report['patients']})

    def test_snapshot_uses_identical_report_contract(self):
        import json
        from generate_preview import generate
        report=generate()
        html=(__import__('pipeline').ROOT/'Preview.html').read_text()
        payload=html.split('<script id="snapshot-report" type="application/json">',1)[1].split('</script>',1)[0]
        self.assertEqual(json.loads(payload),report)
        self.assertEqual(report,build_report(self.db,self.run))
