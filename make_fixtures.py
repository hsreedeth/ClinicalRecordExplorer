"""Generate synthetic FHIR R4-shaped resources. Not a full FHIR validator."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
SYSTEM = 'https://example.org/clinical-record-explorer/codes'

def concept(system, code, display=None):
    return {'coding': [{'system': system, 'code': code, **({'display': display} if display else {})}]}

def build():
    resources, current = [], {}
    def add(r):
        resources.append(r)
        current[r['resourceType']+'/'+r['id']] = r['meta']['versionId']
    for p in 'ABCDEFGH':
        add({'resourceType':'Patient','id':p,'meta':{'versionId':'original'},'birthDate':'1980-06-12'})
        add({'resourceType':'Encounter','id':'visit-'+p,'meta':{'versionId':'original'},
             'status':'finished','class':{'system':'http://terminology.hl7.org/CodeSystem/v3-ActCode','code':'AMB'},
             'subject':{'reference':'Patient/'+p},'period':{'start':'2025-01-01','end':'2025-01-01'}})
        c={'resourceType':'Condition','id':'diabetes-'+p,'meta':{'versionId':'original'},
           'subject':{'reference':'Patient/'+p},'encounter':{'reference':'Encounter/visit-'+p},
           'code':concept(SYSTEM,'diabetes','Diabetes mellitus (teaching code)'),
           'verificationStatus':concept('http://terminology.hl7.org/CodeSystem/condition-ver-status','refuted' if p=='C' else 'confirmed'),
           'recordedDate':'2025-01-01','onsetDateTime':'2024-11-15'}
        if p!='C':
            c['clinicalStatus']=concept('http://terminology.hl7.org/CodeSystem/condition-clinical','active')
        add(c)
    def obs(p, value, day, status='final', version='original', unit='%'):
        r={'resourceType':'Observation','id':'hba1c-'+p,'meta':{'versionId':version},
           'subject':{'reference':'Patient/'+p},'status':status,'code':concept(SYSTEM,'hba1c','HbA1c (teaching code)'),
           'effectiveDateTime':day}
        if value is not None:
            r['valueQuantity']={'value':value,'unit':unit,'system':'http://unitsofmeasure.org','code':unit}
        add(r)
    obs('A',8.4,'2025-03-01')
    resources.append(json.loads(json.dumps(resources[-1])))
    obs('B',9.1,'2025-03-02'); obs('B',6.8,'2025-03-02','corrected','corrected-release')
    obs('C',8.7,'2025-03-01')
    obs('D',9.2,'2025-03-03'); obs('D',None,'2025-03-03','entered-in-error','withdrawn-release')
    obs('E',64,'2025-03-01',unit='mmol/mol')
    obs('F',8.9,'2025-07-01')
    obs('H',8.2,'2025-06-30')
    manifest={'source_namespace':'synthetic-clinic','fhir_version':'4.0.1',
              'current_versions':current,'coverage':{'start':'2025-01-01','end':'2025-12-31'},
              'coverage_basis':'Explicit synthetic assumption; not inferred from visits',
              'mapping_version':'teaching-1','default_threshold':8.0,'default_window_days':180}
    return resources,manifest

if __name__=='__main__':
    resources,manifest=build()
    for name,data in [('source.json',resources),('manifest.json',manifest)]:
        (ROOT/'fixtures'/name).write_text(json.dumps(data,indent=2)+'\n')
