"""Freeze and grade prospective model-stability cohorts from frozen V1/V2/V3 selections.

This never edits prospective/selections.csv.  A game's first investigation classification is
written once to prospective/investigation_cohort.csv and preserved on later runs.
"""
import csv, json, math
from pathlib import Path

SELECTIONS = Path('prospective/selections.csv')
GRADED = Path('prospective/graded_selections.csv')
OUT = Path('prospective')
COHORT = OUT / 'investigation_cohort.csv'
SUMMARY = OUT / 'investigation_summary.json'

FIELDS = [
    'season','game_id','kickoff_utc','home_team','away_team','classified_at_utc',
    'v1_margin','v2_margin','v3_margin','v1_v2_disagreement','same_projected_winner',
    'investigation_status','investigation_reason'
]


def f(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def game_key(r):
    return (str(r.get('season','')), str(r.get('game_id','')))


def classify(v1, v2):
    disagreement=abs(v1-v2)
    same=(v1>=0)==(v2>=0)
    if not same:
        return disagreement, False, 'UNSTABLE', 'models disagree on projected winner'
    if disagreement>=10:
        return disagreement, True, 'UNSTABLE', 'large V1/V2 disagreement (10+ pts)'
    if disagreement>=5:
        return disagreement, True, 'CAUTION', 'moderate V1/V2 disagreement (5-9.9 pts)'
    return disagreement, True, 'PASS', 'V1/V2 agreement under 5 pts'


def load_rows(path):
    if not path.exists(): return []
    with path.open(newline='',encoding='utf-8') as h:
        return list(csv.DictReader(h))


def build_new_cohorts(selections, existing):
    frozen={game_key(r):dict(r) for r in existing}
    grouped={}
    for r in selections:
        k=game_key(r); version=str(r.get('model_version','')).lower()
        if not k[0] or not k[1] or version not in ('v1','v2','v3'): continue
        grouped.setdefault(k,{})[version]=r
    for k, models in grouped.items():
        if k in frozen or 'v1' not in models or 'v2' not in models: continue
        v1=f(models['v1'].get('projected_home_margin'))
        v2=f(models['v2'].get('projected_home_margin'))
        if v1 is None or v2 is None: continue
        disagreement,same,status,reason=classify(v1,v2)
        base=models.get('v3') or models['v2']
        classified=max(str(models['v1'].get('captured_at_utc','')),str(models['v2'].get('captured_at_utc','')))
        frozen[k]={
            'season':k[0],'game_id':k[1],'kickoff_utc':base.get('kickoff_utc',''),
            'home_team':base.get('home_team',''),'away_team':base.get('away_team',''),
            'classified_at_utc':classified,'v1_margin':v1,'v2_margin':v2,
            'v3_margin':f(models.get('v3',{}).get('projected_home_margin')) if 'v3' in models else '',
            'v1_v2_disagreement':round(disagreement,3),'same_projected_winner':str(same).lower(),
            'investigation_status':status,'investigation_reason':reason,
        }
    return sorted(frozen.values(),key=lambda r:(r.get('kickoff_utc',''),r.get('game_id','')))


def summarize(cohort, graded):
    # Use the frozen V3/final projection when a settled V3 row exists; one game = one observation.
    settled_v3={game_key(r):r for r in graded if str(r.get('model_version','')).lower()=='v3' and r.get('grading_status')=='settled'}
    groups={s:{'classified_games':0,'settled_games':0,'winner_correct':0,'within_7':0,'abs_errors':[]} for s in ('PASS','CAUTION','UNSTABLE')}
    for c in cohort:
        s=c.get('investigation_status')
        if s not in groups: continue
        g=groups[s]; g['classified_games']+=1
        r=settled_v3.get(game_key(c))
        pred=f(c.get('v3_margin')); actual=f(r.get('actual_home_margin')) if r else None
        if pred is None or actual is None: continue
        g['settled_games']+=1
        if (pred>0 and actual>0) or (pred<0 and actual<0): g['winner_correct']+=1
        err=abs(pred-actual); g['abs_errors'].append(err)
        if err<=7: g['within_7']+=1
    out={}
    for s,g in groups.items():
        n=g['settled_games']; errs=g.pop('abs_errors')
        g['winner_accuracy']=round(g['winner_correct']/n,6) if n else None
        g['margin_mae']=round(sum(errs)/n,3) if n else None
        g['within_7_rate']=round(g['within_7']/n,6) if n else None
        out[s]=g
    return {
        'method':'prospective frozen investigation cohorts; status uses only frozen V1/V2 projections; performance uses frozen V3/final margin after settlement',
        'thresholds':{'PASS':'same projected winner and disagreement <5','CAUTION':'same projected winner and disagreement 5-9.9','UNSTABLE':'different projected winner or disagreement >=10'},
        'groups':out
    }


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    selections=load_rows(SELECTIONS)
    existing=load_rows(COHORT)
    cohort=build_new_cohorts(selections,existing)
    with COHORT.open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=FIELDS,extrasaction='ignore'); w.writeheader(); w.writerows(cohort)
    summary=summarize(cohort,load_rows(GRADED))
    SUMMARY.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
