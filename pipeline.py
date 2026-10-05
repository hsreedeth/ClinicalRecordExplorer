"""Deterministic, deliberately bounded teaching pipeline; standard library only."""
import csv
import hashlib
import json
import math
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
REPORT_SCHEMA_VERSION = 2
LINEAGE_SCHEMA_VERSION = 1
VER = 'http://terminology.hl7.org/CodeSystem/condition-ver-status'
CLIN = 'http://terminology.hl7.org/CodeSystem/condition-clinical'

def load_resources():
    return json.loads((ROOT/'fixtures/source.json').read_text()), json.loads((ROOT/'fixtures/manifest.json').read_text())

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)

def parse_date(value):
    # This subset accepts full calendar dates only. Other date/time forms are quarantined.
    if not isinstance(value,str) or len(value)!=10:
        raise ValueError('unsupported date: expected YYYY-MM-DD')
    return date.fromisoformat(value).isoformat()

def codes(obj):
    return {(c.get('system'),c.get('code')) for c in obj.get('coding',[]) if c.get('code')}

def status_code(obj,system):
    pairs=codes(obj)
    if len(pairs)!=1 or next(iter(pairs))[0]!=system:
        raise ValueError('missing, conflicting or unsupported status coding')
    return next(iter(pairs))[1]

def select_current_versions(resources,manifest):
    revisions, duplicate_count = {},0
    for r in resources:
        key=r['resourceType']+'/'+r['id']; version=r.get('meta',{}).get('versionId')
        if not isinstance(version,str) or not version:
            raise ValueError('every source revision needs an opaque versionId')
        pair=(key,version)
        if pair in revisions:
            if canonical(revisions[pair])!=canonical(r):
                raise ValueError('conflicting payloads for the same resource revision: '+key)
            duplicate_count+=1
        revisions[pair]=r
    current={}
    for key in sorted({key for key,_ in revisions}):
        version=manifest['current_versions'].get(key)
        if (key,version) not in revisions:
            raise ValueError('manifest does not select a supplied revision: '+key)
        current[key]=revisions[(key,version)]
    return revisions,current,duplicate_count

def resolve_reference(obj,kind,current):
    ref=obj.get('reference')
    if not isinstance(ref,str) or not ref.startswith(kind+'/') or ref.count('/')!=1:
        raise ValueError('unsupported '+kind+' reference')
    if ref not in current:
        raise ValueError('unresolved '+kind+' reference')
    return ref

def lookup_mapping(obj,mappings,domain):
    pairs=codes(obj)
    if not pairs or any(pair not in mappings for pair in pairs):
        raise ValueError('unsupported source coding; retain for mapping review')
    targets={mappings[pair]['local_concept'] for pair in pairs}
    if len(targets)!=1 or any(mappings[pair]['domain']!=domain for pair in pairs):
        raise ValueError('conflicting targets or wrong mapping domain')
    pair=sorted(pairs)[0]
    return pair[0],pair[1],next(iter(targets))

def nested_modifier(value):
    if isinstance(value,dict):
        return bool(value.get('modifierExtension')) or any(nested_modifier(v) for v in value.values())
    if isinstance(value,list):
        return any(nested_modifier(v) for v in value)
    return False

def build_database(resources=None,manifest=None):
    if resources is None:
        resources,manifest=load_resources()
    revisions,current,duplicates=select_current_versions(resources,manifest)
    db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
    db.executescript((ROOT/'schema.sql').read_text())
    with (ROOT/'mapping.csv').open() as f:
        mappings={(r['source_system'],r['source_code']):r for r in csv.DictReader(f)}
    # Source namespace is part of every persisted resource key.
    namespace=manifest['source_namespace']
    full=lambda key: namespace+'|'+key
    def audit(key,disposition,reason):
        db.execute('INSERT OR REPLACE INTO transformation_audit VALUES(?,?,?,?)',
                   (full(key),current[key]['meta']['versionId'],disposition,reason))
    for (key,version),r in sorted(revisions.items()):
        ref=r.get('subject',{}).get('reference','')
        patient=r['id'] if r['resourceType']=='Patient' else ref.removeprefix('Patient/')
        is_current=current[key]['meta']['versionId']==version
        db.execute('INSERT INTO source_revision VALUES(?,?,?,?,?,?)',
                   (full(key),version,r['resourceType'],patient,int(is_current),canonical(r)))
        if not is_current:
            db.execute('INSERT INTO transformation_audit VALUES(?,?,?,?)',
                       (full(key),version,'superseded','Preserved in source history; not transformed as current'))
    db.commit()
    def subject(r):
        ref=resolve_reference(r.get('subject',{}),'Patient',current)
        p=current[ref]['id']
        if not db.execute('SELECT 1 FROM person WHERE person_id=?',(p,)).fetchone():
            raise ValueError('patient failed supported-subset checks')
        return p
    def visit(r,p):
        if not r.get('encounter'):
            return None
        ref=resolve_reference(r['encounter'],'Encounter',current)
        linked=current[ref]
        if subject(linked)!=p:
            raise ValueError('cross-patient encounter link')
        vid=full(ref)
        if not db.execute('SELECT 1 FROM visit_occurrence WHERE visit_id=?',(vid,)).fetchone():
            raise ValueError('encounter failed supported-subset checks')
        return vid
    for kind in ('Patient','Encounter','Condition','Observation'):
        for key,r in sorted(current.items()):
            if r['resourceType']!=kind:
                continue
            try:
                if nested_modifier(r):
                    raise ValueError('unsupported modifier extension')
                with db:
                    if kind=='Patient':
                        birth=parse_date(r.get('birthDate'))
                        db.execute('INSERT INTO person VALUES(?,?)',(r['id'],birth))
                        coverage=manifest['coverage']; start=parse_date(coverage['start']); end=parse_date(coverage['end'])
                        if start>end: raise ValueError('coverage end precedes start')
                        db.execute('INSERT INTO observation_period VALUES(?,?,?)',(r['id'],start,end))
                    elif kind=='Encounter':
                        p=subject(r); start=parse_date(r.get('period',{}).get('start')); end=parse_date(r.get('period',{}).get('end'))
                        if end<start: raise ValueError('encounter end precedes start')
                        if r.get('status')!='finished' or r.get('class',{}).get('code')!='AMB' or r.get('class',{}).get('system')!='http://terminology.hl7.org/CodeSystem/v3-ActCode':
                            raise ValueError('unsupported encounter status or class')
                        db.execute('INSERT INTO visit_occurrence VALUES(?,?,?,?)',(full(key),p,start,end))
                    elif kind=='Condition':
                        p=subject(r); vid=visit(r,p); system,code,target=lookup_mapping(r.get('code',{}),mappings,'Condition')
                        verification=status_code(r.get('verificationStatus',{}),VER)
                        clinical=status_code(r['clinicalStatus'],CLIN) if r.get('clinicalStatus') else None
                        if verification not in {'unconfirmed','provisional','differential','confirmed','refuted','entered-in-error'}:
                            raise ValueError('unsupported verification status')
                        if clinical not in {None,'active','recurrence','relapse','inactive','remission','resolved'}:
                            raise ValueError('unsupported clinical status')
                        recorded=parse_date(r.get('recordedDate')); onset=parse_date(r['onsetDateTime']) if r.get('onsetDateTime') else None
                        if recorded<db.execute('SELECT birth_date FROM person WHERE person_id=?',(p,)).fetchone()[0]:
                            raise ValueError('diagnosis record precedes birth')
                        if verification=='entered-in-error':
                            audit(key,'withdrawn','Current diagnosis entered-in-error; no clinical event emitted'); continue
                        db.execute('INSERT INTO condition_occurrence VALUES(?,?,?,?,?,?,?,?)',(full(key),p,vid,system,code,target,recorded,onset))
                        db.execute('INSERT INTO condition_detail VALUES(?,?,?)',(full(key),verification,clinical))
                    else:
                        p=subject(r); vid=visit(r,p); system,code,target=lookup_mapping(r.get('code',{}),mappings,'Measurement')
                        status=r.get('status')
                        if status not in {'registered','preliminary','final','amended','corrected','cancelled','entered-in-error','unknown'}:
                            raise ValueError('unsupported measurement status')
                        day=parse_date(r.get('effectiveDateTime'))
                        if day<db.execute('SELECT birth_date FROM person WHERE person_id=?',(p,)).fetchone()[0]:
                            raise ValueError('measurement precedes birth')
                        if status=='entered-in-error':
                            audit(key,'withdrawn','Current measurement entered-in-error; previous value cannot reappear'); continue
                        q=r.get('valueQuantity',{}); value=q.get('value')
                        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
                            raise ValueError('unsupported or absent numeric valueQuantity')
                        supported=int(q.get('system')=='http://unitsofmeasure.org' and q.get('code')=='%')
                        db.execute('INSERT INTO measurement VALUES(?,?,?,?,?,?,?,?,?,?)',(full(key),p,vid,system,code,target,day,value,q.get('system'),q.get('code')))
                        db.execute('INSERT INTO measurement_detail VALUES(?,?,?)',(full(key),status,supported))
                    audit(key,'transformed','Current resource retained in teaching relational subset')
            except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                audit(key,'quarantined',str(exc))
                db.commit()
    for key,r in current.items():
        if r['resourceType'] not in {'Patient','Encounter','Condition','Observation'}:
            audit(key,'quarantined','Unsupported resource type')
    db.commit()
    run={'source_sha256':hashlib.sha256(canonical(resources).encode()).hexdigest(),
         'manifest_sha256':hashlib.sha256(canonical(manifest).encode()).hexdigest(),
         'mapping_sha256':hashlib.sha256((ROOT/'mapping.csv').read_bytes()).hexdigest(),
         'supplied_payloads':len(resources),'unique_revisions':len(revisions),
         'current_resources':len(current),'duplicate_copies':duplicates,
         'source_namespace':namespace,'mapping_version':manifest['mapping_version']}
    return db,run

def measurement_decision(r,index,window_days,threshold):
    from datetime import timedelta
    q=r.get('valueQuantity',{})
    if r.get('status')=='entered-in-error': return 'Withdrawn current revision; original value is not usable'
    if r.get('status') not in {'final','corrected'}: return 'Result status is outside this study policy'
    if q.get('system')!='http://unitsofmeasure.org' or q.get('code')!='%': return 'Unsupported unit: '+str(q.get('code','missing'))
    if index is None: return 'Patient outside diagnosis cohort'
    try:
        day=date.fromisoformat(parse_date(r.get('effectiveDateTime')))
        first=date.fromisoformat(index); last=first+timedelta(days=window_days)
        if not first<=day<=last: return 'Outside study window (day '+str((day-first).days)+')'
    except (ValueError,TypeError): return 'Unsupported measurement date'
    return 'Eligible candidate; latest-result selection follows'

def build_report(db,run,threshold=8.0,window_days=180):
    if not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=30:
        raise ValueError('threshold must be between 0 and 30')
    if not isinstance(window_days,int) or not 0<=window_days<=730:
        raise ValueError('window must be an integer between 0 and 730 days')
    results=[dict(r) for r in db.execute((ROOT/'cohort.sql').read_text(),{'threshold':threshold,'window_days':window_days})]
    revisions=[dict(r) for r in db.execute('SELECT s.*,a.disposition,a.reason FROM source_revision s JOIN transformation_audit a USING(source_key,version) ORDER BY source_key,version')]
    for r in revisions: r['payload']=json.loads(r['payload'])
    naive=set(); coded=set()
    teaching_system='https://example.org/clinical-record-explorer/codes'
    for r in revisions:
        p=r['payload']
        if p['resourceType']=='Condition' and (teaching_system,'diabetes') in codes(p.get('code',{})):
            coded.add(r['patient_id'])
    for r in revisions:
        p=r['payload']; value=p.get('valueQuantity',{}).get('value')
        if p['resourceType']=='Observation' and (teaching_system,'hba1c') in codes(p.get('code',{})) and isinstance(value,(int,float)) and not isinstance(value,bool) and value>=threshold and r['patient_id'] in coded:
            naive.add(r['patient_id'])
    for row in results:
        trace=[dict(r) for r in revisions if r['patient_id']==row['person_id']]
        reasons=[]
        for r in trace:
            p=r['payload']
            if r['resource_type']=='Observation':
                if not r['is_current']: decision='Superseded revision; retained only as source history'
                elif r['disposition']=='quarantined': decision='Quarantined: '+r['reason']
                else: decision=measurement_decision(p,row['index_date'],window_days,threshold)
                r['study_decision']=decision
                r['selected']=bool(r['is_current'] and r['source_key']==row['measurement_id'])
                if r['selected']: r['study_decision']='Selected latest eligible result'
                if r['is_current']: reasons.append(decision)
        if row['outcome']=='outside_cohort':
            row['reason']='No supported confirmed active adult diabetes record'
        elif row['outcome']=='no_eligible_result':
            row['reason']='; '.join(dict.fromkeys(reasons)) if reasons else 'No HbA1c measurement recorded'
        else:
            row['reason']='Latest eligible result '+str(row['value'])+'% '+('meets' if row['outcome']=='meets_threshold' else 'is below')+' '+str(threshold)+'%'
        conflicts=[dict(r) for r in db.execute('SELECT effective_date,COUNT(DISTINCT value) n FROM measurement WHERE person_id=? GROUP BY effective_date HAVING COUNT(DISTINCT value)>1',(row['person_id'],))]
        row['warnings']=['Conflicting same-day measurements; stable source-key tie rule applied'] if conflicts else []
        row['trace']=trace
    counts={k:sum(r['outcome']==k for r in results) for k in ('meets_threshold','below_threshold','no_eligible_result','outside_cohort')}
    counts.update(imported=len(results),qualifying=len(results)-counts['outside_cohort'],measured=counts['meets_threshold']+counts['below_threshold'],naive=len(naive))
    disposition={r['disposition']:r['n'] for r in db.execute('SELECT disposition,COUNT(*) n FROM transformation_audit GROUP BY disposition')}
    return {'schema_version':REPORT_SCHEMA_VERSION,'patients':results,'counts':counts,'naive_patients':sorted(naive),'run':run,'dispositions':disposition,
            'parameters':{'threshold':threshold,'window_days':window_days},
            'tables':{name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in ('person','observation_period','visit_occurrence','condition_occurrence','condition_detail','measurement','measurement_detail')},
            'sql':(ROOT/'cohort.sql').read_text(),
            'lineage':build_lineage(db,results,run,threshold,window_days)}

def build_lineage(db, patients, run, threshold, window_days):
    """Expose checks over the transformed SQL inputs, never infer clinical fields in UI."""
    nodes, edges = [], []
    def add(patient, rule, title, decision, reason, evidence, parents=(), source=None):
        nid = patient + ':' + rule
        node = dict(id=nid, patient_id=patient, rule_id=rule, title=title,
                    decision=decision, reason=reason, evidence=evidence,
                    explanation=reason, information='derived')
        if source:
            node.update(source_key=source['source_key'], version=source['version'],
                        disposition=source['disposition'], source_json=source['payload'])
        nodes.append(node)
        edges.extend(dict(source=parent,target=nid,patient_id=patient) for parent in parents)
        return nid
    for row in patients:
        pid=row['person_id']; trace=row['trace']
        person=next(r for r in trace if r['resource_type']=='Patient' and r['is_current'])
        root=add(pid,'patient','Patient '+pid,'pass','Current patient in relational output',
                 {'birth_date':person['payload'].get('birthDate')},source=person)
        nodes[-1]['information']='source'
        branches={'Condition':[], 'Observation':[]}
        for i,r in enumerate(trace):
            if r['resource_type']=='Patient': continue
            payload=r['payload']; kind=r['resource_type']; base='record-'+str(i)
            src=add(pid,base,kind+' / '+payload['id'],'pass','Original source revision retained',
                    {'version':r['version'],'current':bool(r['is_current']),'disposition':r['disposition']},[root],r)
            nodes[-1]['information']='source'
            rev=add(pid,base+'-revision','Revision selection', 'pass' if r['is_current'] else 'fail',
                    r['reason'] if not r['is_current'] else 'Explicit manifest selects this opaque version; identical payload copies collapse',
                    {'is_current':bool(r['is_current']),'version':r['version']},[src],r)
            if not r['is_current']: continue
            retained=add(pid,base+'-transform','Transformation / audit', 'pass' if r['disposition']=='transformed' else 'fail',
                         r['reason'],{'disposition':r['disposition']},[rev],r)
            if kind not in branches: continue
            prior=retained; ready=r['disposition']=='transformed'
            if kind=='Condition':
                c=db.execute('SELECT c.*,d.*,p.birth_date FROM condition_occurrence c JOIN condition_detail d USING(condition_id) JOIN person p USING(person_id) WHERE condition_id=?',(r['source_key'],)).fetchone()
                checks=[('mapping','Diagnosis code mapping',bool(c and c['local_concept']=='LOCAL_DIABETES'),{'coding':payload.get('code'), 'local_concept':c['local_concept'] if c else None},'Mapped diagnosis must be LOCAL_DIABETES'),
                        ('verification','Diagnosis verification',bool(c and c['verification_status']=='confirmed'),{'verificationStatus':payload.get('verificationStatus')},'Study requires confirmed verification'),
                        ('clinical','Clinical status',bool(c and c['clinical_status']=='active'),{'clinicalStatus':payload.get('clinicalStatus')},'Study requires active clinical status'),
                        ('adult','Adult at recorded index',bool(c and db.execute("SELECT ? >= date(?,'+18 years')",(c['recorded_date'],c['birth_date'])).fetchone()[0]),{'birth_date':person['payload'].get('birthDate'),'recorded_date':payload.get('recordedDate')},'Recorded diagnosis date must be on or after the eighteenth birthday')]
            else:
                m=db.execute('SELECT m.*,d.* FROM measurement m JOIN measurement_detail d USING(measurement_id) WHERE measurement_id=?',(r['source_key'],)).fetchone()
                checks=[('status','Result status',bool(m and m['status'] in ('final','corrected')),{'status':payload.get('status')},'Only final or corrected results qualify'),
                        ('mapping','Measurement code mapping',bool(m and m['local_concept']=='LOCAL_HBA1C'),{'coding':payload.get('code'),'local_concept':m['local_concept'] if m else None},'Mapped measurement must be LOCAL_HBA1C'),
                        ('unit','Supported unit',bool(m and m['supported_unit']),{'valueQuantity':payload.get('valueQuantity')},'Only UCUM % is supported; other units remain retained without conversion'),
                        ('window','Inclusive study window',bool(m and row['index_date'] and db.execute("SELECT ? BETWEEN ? AND date(?,'+' || ? || ' days')",(m['effective_date'],row['index_date'],row['index_date'],window_days)).fetchone()[0]),{'effective_date':payload.get('effectiveDateTime'),'index_date':row['index_date'],'window_days':window_days,'day_from_index':int(db.execute('SELECT julianday(?) - julianday(?)',(m['effective_date'],row['index_date'])).fetchone()[0]) if m and row['index_date'] else None},'Measurement date must be within day 0 through the inclusive final day')]
            for rule,title,passed,evidence,reason in checks:
                decision=('pass' if passed else 'fail') if ready else 'not evaluated'
                if rule=='window' and not row['index_date']: decision='not applicable'
                prior=add(pid,base+'-'+rule,title,decision,reason if ready else 'Not evaluated after failed prerequisite. '+reason,evidence,[prior],r)
                ready=ready and passed
            branches[kind].append(prior)
        # All revision identities of one resource feed its current-selection decision.
        for n in nodes:
            if n['patient_id']==pid and n['rule_id'].endswith('-revision') and n['evidence']['is_current']:
                for old in nodes:
                    if old['patient_id']==pid and old['rule_id'].endswith('-revision') and not old['evidence']['is_current'] and old.get('source_key')==n.get('source_key'):
                        edges.append(dict(source=old['id'],target=n['id'],patient_id=pid))
        index=add(pid,'index','Qualifying recorded index','pass' if row['index_date'] else 'fail',
                  'Earliest recorded date among confirmed, active adult mapped diagnoses',{'index_date':row['index_date']},branches['Condition'] or [root])
        # Window eligibility depends explicitly on the diagnosis branch.
        for n in nodes:
            if n['patient_id']==pid and n['rule_id'].endswith('-window'):
                edges.append(dict(source=index,target=n['id'],patient_id=pid))
        latest=add(pid,'latest','Latest eligible measurement','pass' if row['measurement_id'] else ('not applicable' if not row['index_date'] else 'fail'),
                   'Latest eligible date; same-date ties use ascending source key. '+row['reason'],
                   {'measurement_id':row['measurement_id'],'effective_date':row['effective_date'],'value':row['value']},[index]+branches['Observation'])
        compare=add(pid,'threshold','Threshold comparison','not evaluated' if row['value'] is None else ('pass' if row['value']>=threshold else 'fail'),
                    'Compare selected eligible value to the illustrative threshold',{'value':row['value'],'threshold':threshold},[latest])
        add(pid,'outcome','Final patient outcome','pass' if row['outcome']=='meets_threshold' else ('fail' if row['outcome']=='below_threshold' else 'not applicable'),
            row['reason'],{'outcome':row['outcome']},[compare,index])
    lineage = {'schema_version':LINEAGE_SCHEMA_VERSION,'nodes':nodes,'edges':edges,
               'duplicate_handling':{'duplicate_copies':run['duplicate_copies'],'policy':'Identical resource/version payloads collapse; conflicting payloads stop the run'}}
    lineage['groups']=build_lineage_groups(patients,nodes)
    validate_lineage(lineage, {p['person_id'] for p in patients})
    return lineage

STAGE_TITLES = {
    'source':'Source/history', 'diagnosis':'Diagnosis eligibility',
    'measurement':'Measurement eligibility', 'selected':'Selected result', 'outcome':'Outcome'
}
OUTCOME_LABELS = {'meets_threshold':'Meets threshold','below_threshold':'Below threshold',
                  'no_eligible_result':'No eligible result','outside_cohort':'Outside diagnosis cohort'}

def lineage_stage(node):
    rule=node['rule_id']
    if rule=='index': return 'diagnosis'
    if rule=='latest': return 'selected'
    if rule in ('threshold','outcome'): return 'outcome'
    if rule=='patient' or node['information']=='source' or rule.endswith(('-revision','-transform')):
        return 'source'
    return 'diagnosis' if node.get('source_json',{}).get('resourceType')=='Condition' else 'measurement'

def build_lineage_groups(patients, nodes):
    """Presentation summaries of computed evidence; no second eligibility engine."""
    groups=[]
    for row in patients:
        pid=row['person_id']; own=[n for n in nodes if n['patient_id']==pid]
        by_rule={n['rule_id']:n for n in own}
        obs=[r for r in row['trace'] if r['resource_type']=='Observation']
        current=[r for r in obs if r['is_current']]
        current_resources=[r for r in row['trace'] if r['is_current']]
        for stage,title in STAGE_TITLES.items():
            members=[n for n in own if lineage_stage(n)==stage]
            decisive=next((n for n in members if n['decision']=='fail'),members[-1] if members else by_rule['latest'])
            evidence={}; summary=''; decision=decisive['decision']
            if stage=='source':
                problematic=next((r for r in current_resources if r['disposition']=='quarantined'),None)
                withdrawn=next((r for r in current if r['disposition']=='withdrawn'),None)
                corrected=next((r for r in current if r['payload'].get('status')=='corrected' and any(old['source_key']==r['source_key'] and not old['is_current'] for old in obs)),None)
                evidence={'current_resources':len(current_resources),'superseded_revisions':sum(not r['is_current'] for r in row['trace']),
                          'source_references':[{'source_key':r['source_key'],'version':r['version'],'disposition':r['disposition']} for r in row['trace']]}
                decision='pass'
                if problematic or withdrawn:
                    r=problematic or withdrawn
                    decisive=next(n for n in members if n['rule_id'].endswith('-transform') and n.get('source_key')==r['source_key'])
                    summary='Current resource quarantined' if problematic else 'Current result withdrawn';decision='fail'
                elif corrected:
                    old=next(r for r in obs if r['source_key']==corrected['source_key'] and not r['is_current'])
                    oldq=old['payload'].get('valueQuantity',{});newq=corrected['payload'].get('valueQuantity',{})
                    summary=f"{oldq.get('value','no value')}{oldq.get('code','')} → corrected {newq.get('value','no value')}{newq.get('code','')}"
                    decisive=next(n for n in members if n['information']=='source' and n.get('source_key')==corrected['source_key'] and n.get('version')==corrected['version'])
                else: summary=f"{len(current_resources)} current records · {evidence['superseded_revisions']} prior revisions"
            elif stage=='diagnosis':
                decisive=by_rule['index'];decision=decisive['decision'];evidence=decisive['evidence']
                summary='Index: '+row['index_date'] if row['index_date'] else 'No qualifying diagnosis'
                if not row['index_date']:
                    failed=next((n for n in members if n['decision']=='fail' and n['rule_id']!='index'),None)
                    if failed:
                        decisive=failed
                        if failed['rule_id'].endswith('-verification'):
                            values=[c.get('code','unknown') for c in failed['evidence']['verificationStatus'].get('coding',[])]
                            summary=', '.join(values).capitalize()+' diagnosis'
                        elif failed['rule_id'].endswith('-clinical'):
                            values=[c.get('code','unknown') for c in failed['evidence']['clinicalStatus'].get('coding',[])]
                            summary='Clinical status: '+', '.join(values)
                        elif failed['rule_id'].endswith('-adult'): summary='Under 18 at recorded diagnosis'
                        else: summary=failed['reason']
            elif stage=='measurement':
                evidence={'measurement_records':len(current),'index_date':row['index_date']}
                if not current:
                    summary='No measurement recorded';decision='not applicable'
                elif not row['index_date']:
                    summary='No qualifying index date';decision='not applicable'
                else:
                    blocked=next((r for r in current if r['disposition']!='transformed'),None)
                    # Prefer an eligible branch when other current measurements failed.
                    windows=[n for n in members if n['rule_id'].endswith('-window')]
                    eligible=next((n for n in windows if n['decision']=='pass' and n.get('source_key')==row['measurement_id']),None)
                    failed=next((n for n in members if n['decision']=='fail'),None)
                    if eligible:
                        decisive=eligible;decision='pass';summary=f"Day {eligible['evidence']['day_from_index']}: included"
                    elif failed:
                        decisive=failed;decision='fail'
                        if failed['rule_id'].endswith('-unit'):
                            summary='Unsupported unit: '+str(failed['evidence']['valueQuantity'].get('code','missing'))
                        elif failed['rule_id'].endswith('-window'):
                            summary=f"Day {failed['evidence']['day_from_index']}: outside window"
                        elif failed['rule_id'].endswith('-status'): summary='Result status: '+str(failed['evidence']['status'])
                        else: summary=failed['reason']
                    elif blocked:
                        decisive=next(n for n in own if n['rule_id'].endswith('-transform') and n.get('source_key')==blocked['source_key'])
                        decision='not evaluated';summary='Current result withdrawn' if blocked['disposition']=='withdrawn' else 'Measurement quarantined'
                    else:
                        decision='not evaluated';summary='Eligibility not evaluated'
            elif stage=='selected':
                decisive=by_rule['latest'];decision=decisive['decision'];evidence=decisive['evidence']
                summary=f"{row['value']}% · {row['effective_date']}" if row['value'] is not None else 'No eligible result selected'
            else:
                decisive=by_rule['outcome'];decision=decisive['decision'];evidence=decisive['evidence'];summary=OUTCOME_LABELS[row['outcome']]
            evidence={'stage_inputs':evidence,'decisive_check':{'node_id':decisive['id'], 'decision':decisive['decision'], 'inputs':decisive['evidence']}}
            groups.append({'id':pid+':stage:'+stage,'patient_id':pid,'stage_id':stage,'title':title,
                           'decision':decision,'summary':summary,'reason':decisive['reason'],
                           'evidence':evidence,'member_ids':[n['id'] for n in members],
                           'decisive_node_id':decisive['id'],'outcome':row['outcome']})
    return groups

def validate_lineage(lineage, patient_ids):
    """Contract shared by HTTP reports and offline snapshot generation."""
    if lineage['schema_version']!=LINEAGE_SCHEMA_VERSION: raise ValueError('Unsupported lineage schema')
    if not isinstance(lineage['duplicate_handling']['duplicate_copies'],int):
        raise ValueError('Invalid duplicate handling evidence')
    nodes=lineage['nodes'];ids={n['id'] for n in nodes}
    if len(ids)!=len(nodes): raise ValueError('Duplicate lineage node ID')
    decisions={'pass','fail','not applicable','not evaluated'}
    for n in nodes:
        if n['patient_id'] not in patient_ids or n['decision'] not in decisions or not isinstance(n['evidence'],dict):
            raise ValueError('Invalid lineage node')
    for e in lineage['edges']:
        if e['source'] not in ids or e['target'] not in ids or e['patient_id'] not in patient_ids:
            raise ValueError('Invalid lineage edge')
    membership=[]
    for g in lineage['groups']:
        if g['patient_id'] not in patient_ids or g['decision'] not in decisions or g['decisive_node_id'] not in ids:
            raise ValueError('Invalid lineage group')
        membership.extend(g['member_ids'])
    if sorted(membership)!=sorted(ids): raise ValueError('Lineage groups must partition the evidence nodes')
    for pid in patient_ids:
        if {g['stage_id'] for g in lineage['groups'] if g['patient_id']==pid}!=set(STAGE_TITLES):
            raise ValueError('Missing lineage stage')

if __name__=='__main__':
    db,run=build_database(); report=build_report(db,run)
    print(json.dumps({'counts':report['counts'],'run':run},indent=2))
