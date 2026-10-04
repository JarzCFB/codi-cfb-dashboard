"""Settle frozen prospective selections; never modify prospective/selections.csv."""
import csv
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from grade_snapshots import fetch_results, index_results, school, utc

INPUT = Path('prospective/selections.csv')
OUTPUT = Path('prospective')
FIELDS = ['rule_version','model_version','season','game_id','kickoff_utc','captured_at_utc','home_team','away_team','division_status','selection','sportsbook_key','sportsbook','spread','american_odds','projected_home_margin','edge_points','market_last_update_utc','actual_home_margin','selection_result','one_unit_profit','cfbd_game_id','grading_status']

def grade_selections(rows, games):
    idx=index_results(games)
    out=[]; seen=set()
    for r in rows:
        x={k:r.get(k,'') for k in FIELDS}
        x.update(actual_home_margin='',selection_result='',one_unit_profit='',cfbd_game_id='',grading_status='pending')
        key=(r.get('season'),r.get('game_id'),r.get('model_version'))
        try:
            kick=utc(r['kickoff_utc']); captured=utc(r['captured_at_utc']); market=utc(r['market_last_update_utc'])
            price=float(r['american_odds']); spread=float(r['spread'])
            if key in seen or not all((kick,captured,market)) or captured>kick-timedelta(hours=6) or market>captured or market>=kick or not (-200<=price<=200) or price==0 or r['division_status']!='FBS vs FBS' or r['selection'] not in (r['home_team'],r['away_team']):
                x['grading_status']='invalid_selection';out.append(x);continue
            seen.add(key)
            matches=[g for dt,g in idx.get((school(r['home_team']),school(r['away_team'])),[]) if abs(dt-kick)<=timedelta(hours=36)]
            if len(matches)!=1:
                x['grading_status']='pending' if not matches else 'ambiguous_result'
                out.append(x);continue
            g=matches[0]; actual=float(g['homePoints'])-float(g['awayPoints'])
            selection_margin=actual if r['selection']==r['home_team'] else -actual
            diff=selection_margin+spread
            result='win' if diff>0 else 'loss' if diff<0 else 'push'
            profit=(price/100 if price>0 else 100/abs(price)) if result=='win' else -1 if result=='loss' else 0
            x.update(actual_home_margin=actual,selection_result=result,one_unit_profit=round(profit,6),cfbd_game_id=g.get('id',''),grading_status='settled')
        except (ValueError,TypeError,KeyError):
            x['grading_status']='invalid_selection'
        out.append(x)
    return out

def _edge_bucket(value):
    try:
        edge=float(value)
    except (TypeError, ValueError):
        return 'missing'
    if edge < 5: return '3_to_lt5'
    if edge < 7: return '5_to_lt7'
    if edge < 10: return '7_to_lt10'
    return '10_plus'

def _performance(rows):
    counts=Counter(r['selection_result'] for r in rows)
    net=round(sum(float(r['one_unit_profit']) for r in rows),6)
    return {'settled':len(rows),'wins':counts['win'],'losses':counts['loss'],'pushes':counts['push'],
            'net_units':net,'roi_per_settled_selection':round(net/len(rows),6) if rows else None}

def summarize(rows):
    result={}
    for version in ('v1','v2','v3'):
        subset=[r for r in rows if r['model_version']==version]
        settled=[r for r in subset if r['grading_status']=='settled']
        perf=_performance(settled)
        result[version]={'selections':len(subset),**perf,
            'pending':sum(r['grading_status']=='pending' for r in subset),
            'invalid_or_ambiguous':sum(r['grading_status'] in ('invalid_selection','ambiguous_result') for r in subset)}
    v3_settled=[r for r in rows if r['model_version']=='v3' and r['grading_status']=='settled']
    buckets={}
    for label in ('3_to_lt5','5_to_lt7','7_to_lt10','10_plus','missing'):
        bucket=[r for r in v3_settled if _edge_bucket(r.get('edge_points'))==label]
        if bucket or label != 'missing': buckets[label]=_performance(bucket)
    status_counts=Counter(r.get('grading_status','') for r in rows)
    health={
        'total_frozen_selections':len(rows),
        'settled':status_counts['settled'],
        'pending':status_counts['pending'],
        'invalid_selection':status_counts['invalid_selection'],
        'ambiguous_result':status_counts['ambiguous_result'],
        'missing_price':sum(not str(r.get('american_odds','')).strip() for r in rows),
        'missing_market_timestamp':sum(not str(r.get('market_last_update_utc','')).strip() for r in rows),
        'non_fbs_matchup':sum(r.get('division_status')!='FBS vs FBS' for r in rows),
    }
    return {'method':'frozen first qualifying prospective selection per game and model; hypothetical one-unit flat stake',
            'models':result,'v3_edge_buckets':buckets,'pipeline_health':health}

def main():
    if not INPUT.exists():
        print('No prospective selections yet; nothing to grade.');return
    with INPUT.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    seasons=sorted({int(r['season']) for r in rows if r.get('season','').isdigit()})
    games=[g for season in seasons for g in fetch_results(season)]
    graded=grade_selections(rows,games)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with (OUTPUT/'graded_selections.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');w.writeheader();w.writerows(graded)
    summary=summarize(graded)
    (OUTPUT/'results_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
