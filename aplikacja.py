import streamlit as st, pandas as pd, json, io
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

st.set_page_config(page_title="FEA COACH APP", page_icon="⚽", layout="wide")
ROOT=Path(__file__).parent
DATA=ROOT
STATE=DATA/'state.json'
ASSETS=ROOT

def load_json(name):
    with open(DATA/name,encoding='utf-8') as f: return json.load(f)

def save_library(name, data):
    with open(DATA/name,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)

def next_id(items, prefix, key):
    nums=[]
    for x in items:
        v=str(x.get(key,''))
        if v.startswith(prefix):
            try: nums.append(int(v.split('-')[1]))
            except: pass
    return f"{prefix}{max(nums or [0])+1:02d}"

def effectiveness(ident):
    rows=[]
    for h in st.session_state.get('history',[]):
        s=h.get('score')
        if not s: continue
        if ident in s.get('blocks',{}):
            rows.append({'day':h.get('day',''),'rating':s['blocks'][ident],'decision':s.get('decision',''),'weak':s.get('weak',''),'time':h.get('time','')})
    if not rows: return {'uses':0,'avg':0,'good':0,'rows':[]}
    avg=sum(r['rating'] for r in rows)/len(rows)
    return {'uses':len(rows),'avg':avg,'good':sum(1 for r in rows if r['rating']>=4),'rows':rows}

def load_state():
    if STATE.exists():
        with open(STATE,encoding='utf-8') as f: return json.load(f)
    return {'match':{},'plans':{},'scores':{},'history':[],'pending':{},'microcycle_memory':{},'problem_history':[],'microcycle_id':1}

def save_state(s):
    with open(STATE,'w',encoding='utf-8') as f: json.dump(s,f,ensure_ascii=False,indent=2)

fea=load_json('fea.json'); motor=load_json('silnik.json'); db=load_state()
for k,v in db.items():
    if k not in st.session_state: st.session_state[k]=v
if 'pending' not in st.session_state: st.session_state.pending={}
if 'microcycle_memory' not in st.session_state: st.session_state.microcycle_memory={}
if 'problem_history' not in st.session_state: st.session_state.problem_history=[]
if 'microcycle_id' not in st.session_state: st.session_state.microcycle_id=1

def persist():
    save_state({k:st.session_state[k] for k in ['match','plans','scores','history','pending','microcycle_memory','problem_history','microcycle_id']})

DAY_ORDER=['Poniedziałek','Środa','Piątek']
NEXT={'Poniedziałek':'Środa','Środa':'Piątek'}
WEAK_LABEL={'R':'rozumienie zasady i percepcja','W':'wykonanie zachowania','P':'utrzymanie zachowania pod presją','G':'spontaniczny transfer do gry'}

def tokens(text):
    clean=str(text).lower()
    for ch in '/–—,.;:()[]+': clean=clean.replace(ch,' ')
    stop={'oraz','przez','jest','gra','gry','zawodnik','zawodnicy','trening','pod','nad','bez','dla','się','nie','lub','przy','po','do','na','w','i','z'}
    return {w for w in clean.split() if len(w)>3 and w not in stop}

def drill_text(x): return ' '.join(str(v) for v in x.values()).lower()

def classify_problem(problem, observation='', area='MIX'):
    text=(str(problem)+' '+str(observation)+' '+str(area)).lower()
    axes=[]
    rules={
      'PER':['skan','widzi','zobacz','przestrze','ustawienie','partner','przeciwnik','woln'],
      'DEC':['decyz','moment','kiedy','wybór','wybor','przenie','zmiana centrum','utrzymać','atakować'],
      'EXE':['wykon','podanie','przyję','strzał','final','techn','dokład','prowadzenie'],
      'PRESSURE':['pres','press','nacisk','tempo','pod presją','chaos'],
      'TRANSFER':['mecz','transfer','swobod','znika','nie pojawia','bez pomocy'],
      'MENTAL':['odwaga','pewność','zaangaż','reakcja po błędzie','mental']}
    for k,words in rules.items():
        if any(w in text for w in words): axes.append(k)
    if not axes: axes=['DEC']
    return axes

def stage_score(x, axes, weak='R'):
    text=drill_text(x)
    cues={
      'PER':['percepc','skan','woln','przestrze','partner'],
      'DEC':['decyz','moment','przewag','zmiana centrum','kierunk'],
      'EXE':['wykon','final','podanie','przyję','strzał','techn'],
      'PRESSURE':['press','presją','4v4','5v5','6v6','8v8','obrońc'],
      'TRANSFER':['transfer','swobod','8v8','gra właściwa','mecz'],
      'MENTAL':['reakcj','kryzys','błąd','zaangaż']}
    s=0
    for a in axes: s+=sum(2 for q in cues.get(a,[]) if q in text)
    weakmap={'R':'PER','W':'EXE','P':'PRESSURE','G':'TRANSFER'}
    s+=sum(2 for q in cues.get(weakmap.get(weak,''),[]) if q in text)
    return s

def relevance(x, problem, weak='', observation='', area='MIX'):
    text=drill_text(x); s=sum(3 for w in tokens(problem) if w in text)
    return s+stage_score(x,classify_problem(problem,observation,area),weak)

def decide(R,W,P,G):
    vals={'R':R,'W':W,'P':P,'G':G}; weak=min(vals,key=vals.get); avg=sum(vals.values())/4
    if min(vals.values())<=1: dec='CHANGE'
    elif avg>=4.25 and min(vals.values())>=4: dec='PROGRESS'
    elif weak in ('P','G') and vals[weak]<=2: dec='CONTINUE'
    elif avg>=3.15: dec='CONTINUE'
    elif avg>=2.25: dec='REGRESS'
    else: dec='CHANGE'
    return dec,weak,avg

def analysis_profile(R,W,P,G,problem,obs='',area='MIX'):
    dec,weak,avg=decide(R,W,P,G); axes=classify_problem(problem,obs,area)
    vals={'R':R,'W':W,'P':P,'G':G}
    if weak=='R': cause='Zawodnicy nie rozpoznają jeszcze wystarczająco wcześnie informacji potrzebnej do działania.'
    elif weak=='W': cause='Zawodnicy rozpoznają rozwiązanie, ale jakość wykonania ogranicza skuteczność.'
    elif weak=='P': cause='Zachowanie działa w łatwiejszym środowisku, ale zanika przy presji czasu lub przeciwnika.'
    else: cause='Zachowanie nie przenosi się jeszcze spontanicznie do gry właściwej.'
    action={'PROGRESS':'zwiększyć presję, tempo lub złożoność bez zmiany głównej zasady',
            'CONTINUE':'utrzymać priorytet, ale mocniej trafić w najsłabsze ogniwo',
            'REGRESS':'uprościć środowisko i zwiększyć liczbę czytelnych powtórzeń',
            'CHANGE':'zmienić bodziec/środek, zachowując problem jako punkt odniesienia'}[dec]
    return {'decision':dec,'weak':weak,'average':avg,'axes':axes,'cause':cause,'action':action,
            'text':f"Diagnoza: {cause} Zalecenie: {action}. Profil R/W/P/G: {R}/{W}/{P}/{G}; średnia {avg:.2f}/5. Obszary: {', '.join(axes)}."}

def drill_profile(x):
    text=drill_text(x)
    axes=[]
    axis_cues={
      'PER':['percepc','skan','zobacz','woln','przestrze','partner','przeciwnik'],
      'DEC':['decyz','przewag','moment','kierunk','zmiana','przenie','wybór','wybor'],
      'EXE':['podanie','przyję','strzał','final','techn','prowadzenie','wykon'],
    }
    for a,qs in axis_cues.items():
        if any(q in text for q in qs): axes.append(a)
    pressure=sum(1 for q in ['press','presją','obrońc','4v4','5v5','6v6','8v8','czas','kontakt'] if q in text)
    transfer=sum(1 for q in ['transfer','gra właściwa','mecz','8v8','swobod','br+','bramk'] if q in text)
    complexity=sum(1 for q in ['neutral','sektor','przewag','4v4','5v5','6v6','8v8','br+'] if q in text)
    return {'axes':axes or ['DEC'],'pressure':min(5,1+pressure),'transfer':min(5,1+transfer),'complexity':min(5,1+complexity)}

def target_profile(weak, decision):
    # R/W/P/G determines the learning environment, while decision controls difficulty.
    base={
      'R':{'axis':'PER','pressure':1,'transfer':1},
      'W':{'axis':'EXE','pressure':2,'transfer':2},
      'P':{'axis':'DEC','pressure':4,'transfer':3},
      'G':{'axis':'DEC','pressure':4,'transfer':5},
    }.get(weak,{'axis':'DEC','pressure':3,'transfer':3})
    shift={'REGRESS':-1,'CONTINUE':0,'PROGRESS':1,'CHANGE':0}.get(decision,0)
    return {**base,'pressure':max(1,min(5,base['pressure']+shift)),'transfer':max(1,min(5,base['transfer']+shift))}

def semantic_fit(x, problem, decision, weak, observation='', area='MIX'):
    prof=drill_profile(x); target=target_profile(weak,decision)
    problem_axes=classify_problem(problem,observation,area)
    axis_score=5 if target['axis'] in prof['axes'] else (3 if any(a in prof['axes'] for a in problem_axes) else 1)
    pressure_score=max(0,5-abs(prof['pressure']-target['pressure']))
    transfer_score=max(0,5-abs(prof['transfer']-target['transfer']))
    lexical=min(5,relevance(x,problem,weak,observation,area)/3)
    total=axis_score*3+pressure_score*2+transfer_score*2+lexical
    return total,prof,target

def selection_reason(x, problem, decision, weak, observation='', area='MIX'):
    score,prof,target=semantic_fit(x,problem,decision,weak,observation,area)
    axis=', '.join(prof['axes'])
    return (f"{x.get('ID') or x.get('Kod')} pasuje do etapu {weak}: profil {axis}, "
            f"presja {prof['pressure']}/5 (cel {target['pressure']}/5), transfer {prof['transfer']}/5 "
            f"(cel {target['transfer']}/5). Decyzja: {decision}. Dopasowanie {score:.1f} pkt.")

def choose_fea(problem, decision='CONTINUE', weak='R', used=None, n=4, observation='', area='MIX'):
    used=set(used or [])
    active=[x for x in fea if x.get('Status','AKTYWNY')=='AKTYWNY']
    ranked=sorted(active,key=lambda x:(semantic_fit(x,problem,decision,weak,observation,area)[0], effectiveness(x.get('ID',''))['avg'] if effectiveness(x.get('ID',''))['uses']>=2 else 0),reverse=True)
    picks=[]
    for x in ranked:
        ident=x.get('ID','')
        if decision in ('CHANGE','PROGRESS') and ident in used: continue
        if ident not in [p.get('ID') for p in picks]: picks.append(x)
        if len(picks)>=n: break
    if len(picks)<n:
        for x in ranked:
            if x not in picks: picks.append(x)
            if len(picks)>=n: break
    return picks

def choose_motor(problem, weak='P', observation='', area='MIX'):
    active=[x for x in motor if x.get('Status','AKTYWNY')=='AKTYWNY']
    ranked=sorted(active,key=lambda x:relevance(x,problem,weak,observation,area),reverse=True)
    return ranked[0] if ranked else {}

def build_plan(day, problem, decision='CONTINUE', weak='R', previous=None, observation='', area='MIX'):
    used=[b['ID'] for b in (previous or {}).get('blocks',[]) if b.get('ID','').startswith('FEA-')]
    picks=choose_fea(problem,decision,weak,used,4,observation,area)
    mot=choose_motor(problem,weak,observation,area)
    mins={'Poniedziałek':[12,10,20,18,22],'Środa':[12,10,20,18,22],'Piątek':[10,7,13,15,20]}[day]
    roles=['Aktywacja','Motoryka','Główna I','Główna II','Gra / transfer']
    blocks=[]
    # activation, 2 main drills, transfer; motor separate
    selected=[picks[0],mot,picks[1],picks[2],next((x for x in fea if x.get('ID')=='FEA-20'),picks[3])]
    for role,item,t in zip(roles,selected,mins):
        ident=item.get('ID') or item.get('Kod','')
        blocks.append({'role':role,'ID':ident,'name':item.get('Nazwa',''),'time':t,
                       'field':item.get('Pole') or item.get('Organizacja',''),
                       'goal':item.get('Cel/percepcja') or item.get('Akcent',''),
                       'organization':item.get('Organizacja',''),
                       'course':item.get('Przebieg i zasady') or item.get('Coaching / bezpieczeństwo',''),
                       'questions':item.get('Pytania') or item.get('Coaching / bezpieczeństwo',''),
                       'progression':item.get('Progresja') or item.get('Objętość',''),
                       'selection_reason': selection_reason(item,problem,decision,weak,observation,area) if ident.startswith('FEA-') else f"Motoryka dobrana do obszaru {weak} i problemu treningowego."})
    return {'day':day,'problem':problem,'decision_in':decision,'weak_in':weak,'analysis_axes':classify_problem(problem,observation,area),'blocks':blocks,'created':datetime.now().isoformat(timespec='seconds')}


def find_item(ident):
    if ident.startswith('M-'):
        return next((x for x in motor if x.get('Kod')==ident),{})
    return next((x for x in fea if x.get('ID')==ident),{})

def block_from_item(role,item,t):
    ident=item.get('ID') or item.get('Kod','')
    return {'role':role,'ID':ident,'name':item.get('Nazwa',''),'time':t,
            'field':item.get('Pole') or item.get('Organizacja',''),
            'goal':item.get('Cel / percepcja') or item.get('Cel/percepcja') or item.get('Akcent',''),
            'organization':item.get('Organizacja',''),
            'course':item.get('Przebieg i zasady') or item.get('Coaching / bezpieczeństwo',''),
            'questions':item.get('Pytania') or item.get('Coaching / bezpieczeństwo',''),
            'progression':item.get('Progresja') or item.get('Objętość','')}

def graphic_path(ident):
    folder='motor' if ident.startswith('M-') else 'fea'
    p=ASSETS/f'{ident}.png'
    return p if p.exists() else None

def pdf_conspect(plan):
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=22,leftMargin=22,topMargin=20,bottomMargin=20)
    styles=getSampleStyleSheet(); body=ParagraphStyle('body',parent=styles['BodyText'],fontSize=8.2,leading=10.2)
    small=ParagraphStyle('small',parent=body,fontSize=7.5,leading=9)
    head=ParagraphStyle('head',parent=styles['Heading1'],fontSize=15,leading=17,alignment=TA_CENTER,spaceAfter=5)
    story=[Paragraph('FEA COACH SYSTEM - KONSPEKT TRENINGOWY',head),Paragraph(f"<b>{plan['day']}</b> | Priorytet: {plan['problem']} | Decyzja wejściowa: {plan['decision_in']} | Obszar: {plan['weak_in']}",body),Spacer(1,7)]
    for i,b in enumerate(plan['blocks']):
        gp=graphic_path(b['ID'])
        left=[]
        if gp: left.append(RLImage(str(gp),width=210,height=125,kind='proportional'))
        else: left.append(Paragraph('<b>Grafika:</b> brak pliku dla '+b['ID'],body))
        left.append(Paragraph('<b>Pole:</b> '+str(b.get('field','')),small))
        right=[Paragraph(f"<b>{b['role']} | {b['ID']} | {b['name']} | {b['time']} min</b>",body),
               Paragraph('<b>Cel / percepcja:</b> '+str(b.get('goal','')),small),
               Paragraph('<b>Organizacja:</b> '+str(b.get('organization','')),small),
               Paragraph('<b>Przebieg:</b> '+str(b.get('course','')),small),
               Paragraph('<b>Coaching / pytania:</b> '+str(b.get('questions','')),small),
               Paragraph('<b>Progresja / obciążenie:</b> '+str(b.get('progression','')),small)]
        t=Table([[left,right]],colWidths=[240,540],hAlign='CENTER')
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOX',(0,0),(-1,-1),0.6,colors.grey),('INNERGRID',(0,0),(-1,-1),0.25,colors.lightgrey),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        story += [t,Spacer(1,6)]
        if i==2: story.append(PageBreak())
    doc.build(story); buf.seek(0); return buf.getvalue()

def used_ids(day):
    return [b['ID'] for b in st.session_state.plans.get(day,{}).get('blocks',[])]


def expected_kpi_for_block(block, weak):
    base={
      'R':'zawodnik wcześniej rozpoznaje informację i potrafi wyjaśnić swoją decyzję',
      'W':'zachowanie jest wykonane jakościowo i powtarzalnie w tempie zadania',
      'P':'zachowanie utrzymuje się mimo presji przeciwnika i ograniczonego czasu',
      'G':'zachowanie pojawia się spontanicznie w grze bez podpowiedzi trenera'
    }[weak]
    if block.get('role')=='Motoryka':
        return 'jakość ruchu i pierwszego kroku nie spada w kolejnych powtórzeniach; zawodnicy reagują bez kolejek i zbędnych przerw'
    if block.get('role')=='Gra / transfer':
        return 'minimum kilka spontanicznych zachowań zgodnych z priorytetem bez zatrzymywania gry i bez komendy trenera'
    return base

def block_pressure(block):
    txt=(' '.join(str(block.get(k,'')) for k in ['name','organization','course','progression'])).lower()
    if block.get('role')=='Gra / transfer' or any(x in txt for x in ['8v8','gra właściwa','swobodna']): return 'wysoka / meczowa'
    if any(x in txt for x in ['6v6','5v5','4v4','press','obrońc']): return 'średnia–wysoka'
    if any(x in txt for x in ['3v2','2v1','3v3']): return 'średnia'
    return 'niska–średnia'

def detailed_rationale(block, score, problem):
    weak=score['weak']; dec=score['decision']; axes=score.get('diagnosis',{}).get('axes',[])
    weak_reason={
      'R':'najniższa ocena dotyczy rozumienia/percepcji, więc środek powinien zwiększać czytelność informacji przed działaniem',
      'W':'najniższa ocena dotyczy wykonania, więc potrzebujemy powtarzalnych działań z zachowaniem kontekstu gry',
      'P':'zachowanie zanika pod presją, dlatego kolejny bodziec musi zachować przeciwnika, czas i konieczność szybkiej decyzji',
      'G':'problemem jest transfer, dlatego środek powinien zbliżać środowisko do gry właściwej i ograniczać sterowanie trenera'
    }[weak]
    axis=' / '.join(axes) if axes else 'DEC'
    pressure=block_pressure(block)
    transfer='bezpośredni do gry' if block.get('role')=='Gra / transfer' else ('wysoki' if pressure in ['wysoka / meczowa','średnia–wysoka'] else 'pośredni')
    return {
      'ID':block['ID'],'role':block['role'],'name':block['name'],
      'problem':problem or 'aktualny priorytet mikrocyklu',
      'diagnostic_fit':f"{axis}: {weak_reason}",
      'decision_fit':f"Decyzja {dec}: "+{
        'PROGRESS':'zwiększamy trudność bez zmiany głównej zasady.',
        'CONTINUE':'utrzymujemy priorytet, ale kierujemy coaching w najsłabsze ogniwo.',
        'REGRESS':'upraszczamy środowisko, aby odzyskać czytelność i jakość.',
        'CHANGE':'zmieniamy bodziec, bo poprzednie środowisko nie dało oczekiwanej odpowiedzi.'}[dec],
      'pressure':pressure,'transfer':transfer,
      'expected':expected_kpi_for_block(block,weak),
      'next_score':f"W następnym Training Score oczekujemy wzrostu {weak} oraz oceny tego środka ≥4/5; jeśli {weak} pozostanie ≤2, system powinien ponownie zmienić/regresować bodziec."
    }

def microcycle_trend(day, current_score):
    idx=DAY_ORDER.index(day)
    previous_day=DAY_ORDER[idx-1] if idx>0 else None
    previous=st.session_state.scores.get(previous_day) if previous_day else None
    metrics=['R','W','P','G']
    delta={m:(current_score[m]-previous[m]) if previous else None for m in metrics}
    weak=current_score.get('weak','R')
    weak_delta=delta.get(weak)
    if previous is None:
        status='BASELINE'; verdict='Pierwszy pomiar mikrocyklu — zapisujemy punkt odniesienia.'
    elif weak_delta is not None and weak_delta>=1:
        status='IMPROVING'; verdict=f"Obszar {weak} poprawił się o {weak_delta:+d} pkt względem {previous_day}. Adaptacja daje pozytywny sygnał."
    elif weak_delta is not None and weak_delta<=-1:
        status='DECLINING'; verdict=f"Obszar {weak} spadł o {weak_delta:+d} pkt względem {previous_day}. Bodziec wymaga korekty."
    else:
        status='STABLE'; verdict=f"Obszar {weak} pozostaje bez wyraźnej zmiany względem {previous_day}. Potrzebna jest ocena transferu i jakości środka."
    block_effect=[]
    if previous:
        prev_plan=st.session_state.plans.get(previous_day,{})
        for b in prev_plan.get('blocks',[]):
            rating=previous.get('blocks',{}).get(b['ID'])
            block_effect.append({'ID':b['ID'],'Nazwa':b['name'],'Ocena':rating,'Sygnał':'POZYTYWNY' if rating and rating>=4 else ('SŁABY' if rating and rating<=2 else 'NEUTRALNY')})
    return {'day':day,'previous_day':previous_day,'delta':delta,'status':status,'verdict':verdict,'block_effect':block_effect}

def adaptive_decision(score, trend):
    dec=score['decision']
    if trend['status']=='IMPROVING' and score['G']>=3 and score['P']>=3:
        return 'PROGRESS', 'Trend jest dodatni, a zachowanie utrzymuje się pod presją/transferem — można zwiększyć trudność.'
    if trend['status']=='DECLINING':
        return ('CHANGE' if score[score['weak']]<=2 else 'REGRESS'), 'Trend pogorszył się — nie powtarzamy automatycznie tego samego bodźca.'
    if trend['status']=='STABLE' and score[score['weak']]<=2:
        return 'CHANGE', 'Brak poprawy w najsłabszym obszarze przy niskiej ocenie — potrzebna zmiana bodźca.'
    return dec, 'Utrzymano decyzję wynikającą z aktualnego profilu R/W/P/G.'

def build_analysis_card(day, score):
    nxt=NEXT.get(day)
    if not nxt: return None
    current=st.session_state.plans.get(day,{})
    problem=score.get('problem','') or st.session_state.match.get('problem','')
    trend=microcycle_trend(day,score)
    adaptive_dec, adaptive_reason=adaptive_decision(score,trend)
    proposed=build_plan(nxt, problem, adaptive_dec, score['weak'], current, score.get('observation',''), st.session_state.match.get('area','MIX'))
    current_ids=[b['ID'] for b in current.get('blocks',[])]
    proposed_ids=[b['ID'] for b in proposed.get('blocks',[])]
    stays=[x for x in proposed_ids if x in current_ids]
    changes=[]
    for i,b in enumerate(proposed.get('blocks',[])):
        old=current.get('blocks',[{}]*5)[i] if i < len(current.get('blocks',[])) else {}
        if old.get('ID') != b.get('ID'):
            changes.append({'role':b.get('role',''),'from':old.get('ID','—'),'to':b.get('ID',''),'name':b.get('name','')})
    rationale=[]
    for b in proposed.get('blocks',[]):
        r=detailed_rationale(b,score,problem)
        e=effectiveness(b['ID'])
        r['history']=f"{e['uses']} użyć • średnia {e['avg']:.2f}/5" if e['uses'] else 'brak wcześniejszych ocen'
        rationale.append(r)
    success={
      'R':'zawodnicy wcześniej skanują/rozpoznają sytuację i potrafią uzasadnić wybór',
      'W':'rośnie jakość i powtarzalność wykonania bez utraty intencji taktycznej',
      'P':'zachowanie utrzymuje się pod aktywną presją i w wyższym tempie',
      'G':'zachowanie pojawia się samo w grze właściwej bez komendy trenera'
    }[score['weak']]
    return {'source_day':day,'next_day':nxt,'score':score,'profile':score.get('diagnosis',{}),'trend':trend,'adaptive_decision':adaptive_dec,'adaptive_reason':adaptive_reason,'proposed_plan':proposed,'stays':stays,'changes':changes,'rationale':rationale,'success_criterion':success,'created':datetime.now().isoformat(timespec='seconds')}

def approve_pending(day):
    card=st.session_state.pending.get(day)
    if not card: return False
    st.session_state.plans[card['next_day']]=card['proposed_plan']
    st.session_state.microcycle_memory[day]={'trend':card.get('trend',{}),'adaptive_decision':card.get('adaptive_decision'),'approved_next':card['next_day'],'time':datetime.now().isoformat(timespec='seconds')}
    st.session_state.history.append({'day':day,'approved_analysis':{'next_day':card['next_day'],'decision':card.get('adaptive_decision',card['score']['decision']),'weak':card['score']['weak'],'trend':card.get('trend',{}).get('status')},'time':datetime.now().isoformat(timespec='seconds')})
    del st.session_state.pending[day]
    persist(); return True

def regenerate_next(day, score):
    nxt=NEXT.get(day)
    if not nxt: return
    base_problem=score.get('problem') or st.session_state.match.get('problem','')
    st.session_state.plans[nxt]=build_plan(nxt,base_problem,score['decision'],score['weak'],st.session_state.plans.get(day),score.get('observation',''),st.session_state.match.get('area','MIX'))


def problem_similarity(a,b):
    A=tokens(a); B=tokens(b)
    if not A or not B: return 0.0
    return len(A&B)/max(1,len(A|B))

def archive_microcycle():
    m=st.session_state.get('match',{})
    if not m.get('problem'): return
    scores=st.session_state.get('scores',{})
    if not scores and not st.session_state.get('plans'): return
    first=next((scores[d] for d in DAY_ORDER if d in scores),None)
    last=next((scores[d] for d in reversed(DAY_ORDER) if d in scores),None)
    delta={k:(last[k]-first[k]) if first and last else None for k in ['R','W','P','G']}
    status='BRAK DANYCH'
    if first and last:
        avg_delta=sum(delta.values())/4
        if last.get('G',0)>=4 and last.get('P',0)>=4: status='ROZWIĄZANY TRENINGOWO'
        elif avg_delta>=0.75: status='WYRAŹNA POPRAWA'
        elif avg_delta>0: status='CZĘŚCIOWA POPRAWA'
        elif avg_delta<0: status='POGORSZENIE'
        else: status='BEZ ZMIANY'
    st.session_state.problem_history.append({
        'microcycle_id':st.session_state.microcycle_id,'date':datetime.now().strftime('%Y-%m-%d'),
        'opponent':m.get('opponent',''),'result':m.get('result',''),'problem':m.get('problem',''),
        'observation':m.get('observation',''),'area':m.get('area',''),'first_score':first,'last_score':last,
        'delta':delta,'status':status,'plans':{d:[b['ID'] for b in st.session_state.plans.get(d,{}).get('blocks',[])] for d in DAY_ORDER}
    })
    st.session_state.microcycle_id += 1

def prior_problem_context(problem):
    matches=[]
    for h in st.session_state.get('problem_history',[]):
        sim=problem_similarity(problem,h.get('problem',''))
        if sim>=0.18: matches.append((sim,h))
    matches.sort(key=lambda x:(x[0],x[1].get('microcycle_id',0)),reverse=True)
    if not matches: return {'status':'NOWY PROBLEM','matches':[],'message':'Brak podobnego problemu w zapisanej historii.'}
    best=matches[0][1]; last=best.get('last_score') or {}
    if best.get('status')=='ROZWIĄZANY TRENINGOWO':
        msg='Podobny problem wcześniej osiągnął dobre parametry treningowe. Jeśli wrócił w meczu, traktuj go jako problem transferu/utrzymania pod presją meczową, a nie jako naukę od zera.'
        status='NAWRÓT / TRANSFER MECZOWY'
    elif best.get('status') in ('WYRAŹNA POPRAWA','CZĘŚCIOWA POPRAWA'):
        msg='Podobny problem wcześniej poprawiał się w treningu, ale nie został zamknięty. Warto kontynuować od wyższego poziomu reprezentatywności zamiast wracać do początku.'
        status='PROBLEM CZĘŚCIOWO ROZWIĄZANY'
    else:
        msg='Podobny problem nie dawał wcześniej wystarczającej poprawy. System powinien unikać prostego powtórzenia identycznego zestawu środków.'
        status='PROBLEM UTRWALONY'
    return {'status':status,'matches':[x[1] for x in matches[:3]],'message':msg,'last_score':last}



def workflow_state():
    plans=st.session_state.get('plans',{})
    scores=st.session_state.get('scores',{})
    pending=st.session_state.get('pending',{})
    if not st.session_state.get('match',{}).get('problem'):
        return {'step':'MECZ','title':'Wprowadź analizę meczu','detail':'Zdefiniuj problem meczowy i priorytet. System utworzy poniedziałek.','page':'Analiza meczu','progress':0}
    if 'Poniedziałek' in plans and 'Poniedziałek' not in scores:
        return {'step':'PON','title':'Wykonaj Training Score poniedziałku','detail':'Oceń R/W/P/G oraz każdy zastosowany środek.','page':'Training Score','progress':20}
    if 'Poniedziałek' in pending:
        return {'step':'ANALIZA PON','title':'Podejmij decyzję po poniedziałku','detail':'Sprawdź diagnozę i propozycję środy. Zatwierdź albo analizuj ponownie.','page':'Karta analizy','progress':35}
    if 'Środa' in plans and 'Środa' not in scores:
        return {'step':'ŚR','title':'Wykonaj Training Score środy','detail':'Sprawdź, czy poniedziałkowa adaptacja dała poprawę.','page':'Training Score','progress':50}
    if 'Środa' in pending:
        return {'step':'ANALIZA ŚR','title':'Podejmij decyzję po środzie','detail':'Porównaj trend PON → ŚR i zatwierdź plan piątkowy.','page':'Karta analizy','progress':65}
    if 'Piątek' in plans and 'Piątek' not in scores:
        return {'step':'PT','title':'Wykonaj Training Score piątku','detail':'Oceń gotowość i transfer przed meczem.','page':'Training Score','progress':80}
    if 'Piątek' in scores:
        return {'step':'MECZ / TRANSFER','title':'Mikrocykl gotowy do weryfikacji meczowej','detail':'Po kolejnym meczu rozpocznij nową analizę. Poprzedni mikrocykl zostanie zarchiwizowany i porównany z nowym problemem.','page':'Analiza meczu','progress':100}
    return {'step':'MIKROCYKL','title':'Sprawdź aktualny mikrocykl','detail':'System oczekuje na kolejną decyzję trenera.','page':'Mikrocykl','progress':10}

def workflow_rows():
    plans=st.session_state.get('plans',{}); scores=st.session_state.get('scores',{}); pending=st.session_state.get('pending',{})
    rows=[]
    for d in DAY_ORDER:
        if d not in plans: status='OCZEKUJE'
        elif d not in scores: status='DO OCENY'
        elif d in pending: status='DECYZJA TRENERA'
        else: status='ZAMKNIĘTY'
        sc=scores.get(d,{})
        rows.append({'Etap':d,'Status':status,'R':sc.get('R'),'W':sc.get('W'),'P':sc.get('P'),'G':sc.get('G'),'Decyzja':sc.get('decision','')})
    return rows

def microcycle_summary():
    scores=st.session_state.get('scores',{})
    if not scores: return None
    first=next((scores[d] for d in DAY_ORDER if d in scores),None)
    last=next((scores[d] for d in reversed(DAY_ORDER) if d in scores),None)
    if not first or not last: return None
    delta={k:last[k]-first[k] for k in ['R','W','P','G']}
    if len(scores)==1: verdict='PUNKT ODNIESIENIA'
    elif last.get('G',0)>=4 and last.get('P',0)>=4: verdict='GOTOWY DO WERYFIKACJI MECZOWEJ'
    elif sum(delta.values())>0: verdict='TREND DODATNI — WERYFIKUJ W MECZU'
    elif sum(delta.values())<0: verdict='WYMAGA DALSZEJ KOREKTY'
    else: verdict='BEZ WYRAŹNEJ ZMIANY'
    return {'first':first,'last':last,'delta':delta,'verdict':verdict}

st.sidebar.title('FEA COACH APP')
st.sidebar.caption('v1.1 • pełny workflow trenera')
page=st.sidebar.radio('Moduł',['Dashboard','Analiza meczu','Mikrocykl','Training Score','Karta analizy','Trend mikrocyklu','Pamięć problemów','Edycja treningu','Konspekt','Biblioteka','Skuteczność środków','Historia'])

if page=='Dashboard':
    st.title('⚽ FEA COACH APP v1.1')
    action=workflow_state(); summary=microcycle_summary()
    st.subheader('Co teraz wymaga decyzji trenera?')
    st.info(f"**{action['step']} — {action['title']}**\n\n{action['detail']}")
    st.progress(action['progress']/100, text=f"Postęp mikrocyklu: {action['progress']}%")
    if st.session_state.match.get('problem'):
        st.success('Aktualny priorytet: '+st.session_state.match['problem'])
        ctx=st.session_state.match.get('prior_context',{})
        if ctx: st.caption('Pamięć problemu: '+ctx.get('status','')+' — '+ctx.get('message',''))
    st.markdown('### Status workflow')
    st.dataframe(pd.DataFrame(workflow_rows()),use_container_width=True,hide_index=True)
    if summary:
        st.markdown('### Sygnał z mikrocyklu')
        c1,c2,c3,c4=st.columns(4)
        for c,m in zip([c1,c2,c3,c4],['R','W','P','G']): c.metric(m,summary['last'][m],delta=summary['delta'][m])
        st.write('**'+summary['verdict']+'**')
        st.caption('Wynik treningowy nie zamyka problemu. Ostateczna weryfikacja następuje w kolejnym meczu.')
    st.markdown('### Baza systemu')
    c1,c2,c3,c4=st.columns(4); c1.metric('Środki FEA',len(fea)); c2.metric('Motoryka',len(motor)); c3.metric('Treningi',len(st.session_state.plans)); c4.metric('Oceny',len(st.session_state.scores))
    st.caption('Docelowy obieg: MECZ → DIAGNOZA → PRIORYTET → PON → SCORE → ANALIZA → ŚR → SCORE → ANALIZA → PT → SCORE → MECZ → WERYFIKACJA TRANSFERU.')

elif page=='Analiza meczu':
    st.title('Analiza pomeczowa → priorytet mikrocyklu')
    m=st.session_state.match
    c1,c2=st.columns(2)
    opp=c1.text_input('Przeciwnik',m.get('opponent','')); result=c2.text_input('Wynik',m.get('result',''))
    problem=st.text_area('Najważniejszy problem meczowy',m.get('problem',''),height=110)
    observation=st.text_area('Opis sytuacji / kiedy problem występował',m.get('observation',''),height=100)
    area=st.selectbox('Dominujący obszar',['PER – percepcja','DEC – decyzja','EXE – wykonanie','MENTAL','MIX'])
    if st.button('Analizuj i rozpocznij mikrocykl',type='primary'):
        archive_microcycle()
        prior=prior_problem_context(problem)
        start_dec='CONTINUE'; start_weak='R'
        if prior['status']=='NAWRÓT / TRANSFER MECZOWY': start_dec='PROGRESS'; start_weak='G'
        elif prior['status']=='PROBLEM CZĘŚCIOWO ROZWIĄZANY': start_dec='CONTINUE'; start_weak=(prior.get('last_score') or {}).get('weak','P')
        elif prior['status']=='PROBLEM UTRWALONY': start_dec='CHANGE'; start_weak=(prior.get('last_score') or {}).get('weak','R')
        st.session_state.match={'opponent':opp,'result':result,'problem':problem,'observation':observation,'area':area,'prior_context':prior}
        st.session_state.plans={'Poniedziałek':build_plan('Poniedziałek',problem,start_dec,start_weak,None,observation,area)}
        st.session_state.scores={}; st.session_state.pending={}; st.session_state.microcycle_memory={}; persist()
        st.success('Utworzono priorytet i trening poniedziałkowy. Kolejne jednostki powstaną dopiero po analizie Score.')

elif page=='Pamięć problemów':
    st.title('Pamięć problemu między mikrocyklami')
    st.caption('System porównuje nowe problemy meczowe z wcześniejszymi mikrocyklami. Nie uznaje wyniku treningowego za dowód rozwiązania problemu w meczu — sprawdza, czy zachowanie wraca w kolejnym spotkaniu.')
    current=st.session_state.match.get('problem','')
    if current:
        ctx=prior_problem_context(current)
        st.subheader('Aktualny problem')
        st.write('**'+current+'**')
        st.info(ctx['status']+' — '+ctx['message'])
        if ctx['matches']:
            rows=[]
            for h in ctx['matches']:
                rows.append({'Mikrocykl':h.get('microcycle_id'),'Przeciwnik':h.get('opponent'),'Problem':h.get('problem'),'Status końcowy':h.get('status'),'ΔR':h.get('delta',{}).get('R'),'ΔW':h.get('delta',{}).get('W'),'ΔP':h.get('delta',{}).get('P'),'ΔG':h.get('delta',{}).get('G')})
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    if st.session_state.problem_history:
        st.subheader('Archiwum mikrocykli')
        rows=[]
        for h in reversed(st.session_state.problem_history):
            rows.append({'Mikrocykl':h.get('microcycle_id'),'Data':h.get('date'),'Przeciwnik':h.get('opponent'),'Wynik':h.get('result'),'Problem':h.get('problem'),'Status':h.get('status'),'ΔR':h.get('delta',{}).get('R'),'ΔW':h.get('delta',{}).get('W'),'ΔP':h.get('delta',{}).get('P'),'ΔG':h.get('delta',{}).get('G')})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else: st.info('Archiwum powstanie przy rozpoczęciu kolejnego mikrocyklu.')

elif page=='Mikrocykl':
    st.title('Dynamiczny mikrocykl')
    st.write('**Priorytet:**',st.session_state.match.get('problem','Brak analizy meczu'))
    cols=st.columns(3)
    for col,day in zip(cols,DAY_ORDER):
        with col:
            st.subheader(day)
            plan=st.session_state.plans.get(day)
            if not plan:
                prev=DAY_ORDER[DAY_ORDER.index(day)-1] if day!='Poniedziałek' else None
                st.warning('Oczekuje na analizę '+prev if prev else 'Najpierw wykonaj analizę meczu')
                continue
            st.caption(f"Wejście: {plan['decision_in']} • słaby obszar: {plan['weak_in']} • diagnoza: {', '.join(plan.get('analysis_axes',[]))}")
            for b in plan['blocks']: st.write(f"**{b['role']}** — {b['ID']} {b['name']} ({b['time']} min)")
            if day in st.session_state.scores:
                s=st.session_state.scores[day]; st.success(f"Score → {s['decision']} | {s['weak']}")
    st.divider(); st.caption('Środa nie jest generowana przed oceną poniedziałku. Piątek nie jest generowany przed oceną środy.')

elif page=='Trend mikrocyklu':
    st.title('Pamięć mikrocyklu → trend R/W/P/G')
    scored=[d for d in DAY_ORDER if d in st.session_state.scores]
    if not scored:
        st.info('Trend pojawi się po pierwszym Training Score.'); st.stop()
    rows=[]
    for d in scored:
        sc=st.session_state.scores[d]
        tr=microcycle_trend(d,sc)
        rows.append({'Dzień':d,'R':sc['R'],'W':sc['W'],'P':sc['P'],'G':sc['G'],'Średnia':round(sc['average'],2),'Najsłabszy':sc['weak'],'Trend':tr['status']})
    df=pd.DataFrame(rows)
    st.dataframe(df,use_container_width=True,hide_index=True)
    if len(rows)>=2:
        chart=df.set_index('Dzień')[['R','W','P','G']]
        st.line_chart(chart)
    day=st.selectbox('Szczegóły adaptacji',scored,index=len(scored)-1)
    sc=st.session_state.scores[day]; tr=microcycle_trend(day,sc); adec,reason=adaptive_decision(sc,tr)
    st.subheader(tr['verdict'])
    if tr['previous_day']:
        cols=st.columns(4)
        for c,m in zip(cols,['R','W','P','G']):
            c.metric(m,sc[m],delta=tr['delta'][m])
    st.write('**Decyzja adaptacyjna na kolejną jednostkę:**',adec)
    st.caption(reason)
    if tr['block_effect']:
        st.markdown('#### Jak zadziałały środki poprzedniej jednostki')
        st.dataframe(pd.DataFrame(tr['block_effect']),use_container_width=True,hide_index=True)
    st.info('System nie traktuje pojedynczej oceny jako dowodu skuteczności. Trend wspiera decyzję trenera i jest porównywany z obserwacją oraz transferem do gry.')

elif page=='Training Score':
    st.title('Training Score → analiza i przebudowa kolejnej jednostki')
    available=[d for d in DAY_ORDER if d in st.session_state.plans]
    if not available: st.warning('Najpierw utwórz analizę meczu.'); st.stop()
    day=st.selectbox('Jednostka',available)
    plan=st.session_state.plans[day]
    st.caption('Oceniasz: '+', '.join(used_ids(day)))
    c1,c2,c3,c4=st.columns(4)
    R=c1.slider('R – Rozumienie',1,5,3,key='R'+day); W=c2.slider('W – Wykonanie',1,5,3,key='W'+day); P=c3.slider('P – Presja',1,5,3,key='P'+day); G=c4.slider('G – Transfer',1,5,3,key='G'+day)
    block_scores={}
    st.markdown('#### Ocena środków')
    for b in plan['blocks']:
        block_scores[b['ID']]=st.slider(f"{b['ID']} • {b['name']}",1,5,3,key='blk'+day+b['ID'])
    problem=st.text_input('Największy problem po treningu',value=st.session_state.match.get('problem',''))
    obs=st.text_area('Obserwacja trenera – co działało, co znikało pod presją?')
    if st.button('Przeanalizuj i zbuduj kolejny trening',type='primary'):
        prof=analysis_profile(R,W,P,G,problem,obs,st.session_state.match.get('area','MIX')); dec,weak,avg=prof['decision'],prof['weak'],prof['average']; analysis=prof['text']
        score={'R':R,'W':W,'P':P,'G':G,'decision':dec,'weak':weak,'average':avg,'analysis':analysis,'diagnosis':prof,'problem':problem,'blocks':block_scores,'observation':obs}
        st.session_state.scores[day]=score
        st.session_state.history.append({'day':day,'score':score,'plan_ids':used_ids(day),'time':datetime.now().isoformat(timespec='seconds')})
        if day in NEXT:
            st.session_state.pending[day]=build_analysis_card(day,score)
        persist()
        st.metric('Decyzja',dec); st.write(analysis)
        if day in NEXT: st.success(f"Analiza gotowa. {NEXT[day]} NIE został jeszcze zmieniony — przejdź do „Karta analizy” i zatwierdź propozycję.")
    if day in st.session_state.scores:
        s=st.session_state.scores[day]
        st.info(s['analysis'])
        if day in NEXT and st.button('Analizuj ponownie z aktualną biblioteką'):
            st.session_state.pending[day]=build_analysis_card(day,s); persist(); st.success('Odświeżono propozycję. Sprawdź ją w module „Karta analizy”.')

elif page=='Karta analizy':
    st.title('Karta analizy → decyzja przed kolejnym treningiem')
    pending_days=[d for d in ['Poniedziałek','Środa'] if d in st.session_state.pending]
    if not pending_days:
        st.info('Brak analizy oczekującej na decyzję. Najpierw zapisz Training Score poniedziałku lub środy.')
        st.stop()
    day=st.selectbox('Analiza po jednostce',pending_days)
    card=st.session_state.pending[day]; s=card['score']; prof=card.get('profile',{})
    st.subheader(f"{day} → {card['next_day']}")
    c1,c2,c3,c4=st.columns(4)
    c1.metric('R',s['R']); c2.metric('W',s['W']); c3.metric('P',s['P']); c4.metric('G',s['G'])
    st.markdown('### 1. Co wykryto')
    st.write(f"**Najsłabszy obszar:** {s['weak']} – {WEAK_LABEL.get(s['weak'],'')}  |  **Decyzja:** {s['decision']}  |  **Średnia:** {s['average']:.2f}/5")
    st.write('**Obszary diagnozy:**', ', '.join(prof.get('axes',[])))
    st.markdown('### 2. Dlaczego')
    st.write(prof.get('cause',s.get('analysis',''))); st.caption('Obserwacja trenera: '+(s.get('observation') or 'brak'))
    st.markdown('### 3. Pamięć mikrocyklu — czy poprzednia adaptacja zadziałała')
    tr=card.get('trend',{})
    st.write(tr.get('verdict','Brak wcześniejszego punktu odniesienia.'))
    if tr.get('previous_day'):
        cc=st.columns(4)
        for c,m in zip(cc,['R','W','P','G']): c.metric(m,s[m],delta=tr.get('delta',{}).get(m))
    st.write('**Decyzja adaptacyjna:**',card.get('adaptive_decision',s['decision']))
    st.caption(card.get('adaptive_reason',''))
    st.markdown('### 4. Co zostaje')
    st.write(', '.join(card['stays']) if card['stays'] else 'Brak środka zachowanego automatycznie.')
    st.markdown('### 5. Co zmieniamy')
    if card['changes']:
        st.dataframe(pd.DataFrame(card['changes']),use_container_width=True,hide_index=True)
    else: st.info('System proponuje utrzymanie układu środków; zmienia się kierunek coachingu/progresji.')
    st.markdown('### 6. Proponowany kolejny trening i uzasadnienie')
    for r in card['rationale']:
        with st.expander(f"{r['role']} — {r['ID']} {r['name']}", expanded=True):
            st.write('**Problem, który adresuje:**',r['problem'])
            st.write('**Dopasowanie PER/DEC/EXE + R/W/P/G:**',r['diagnostic_fit'])
            st.write('**Dlaczego przy tej decyzji:**',r['decision_fit'])
            c1,c2,c3=st.columns(3)
            c1.metric('Presja',r['pressure']); c2.metric('Transfer',r['transfer']); c3.metric('Historia',r['history'])
            st.write('**Oczekiwany efekt:**',r['expected'])
            st.info(r['next_score'])
    st.markdown('### 7. Po czym poznamy, że adaptacja zadziałała')
    st.success(card.get('success_criterion','Wzrost najsłabszego obszaru i transfer zachowania do gry.'))
    st.caption(f"Warunek kontrolny: {s['weak']} powinno wzrosnąć w kolejnym Training Score. Ocena proponowanych środków docelowo ≥4/5.")
    st.markdown('### 8. Decyzja trenera')
    a,b=st.columns(2)
    if a.button(f"ZATWIERDŹ → utwórz {card['next_day']}",type='primary',use_container_width=True):
        approve_pending(day); st.success(f"Zatwierdzono. {card['next_day']} został utworzony, a konspekt korzysta z tego planu."); st.rerun()
    if b.button('ANALIZUJ PONOWNIE z aktualną biblioteką',use_container_width=True):
        st.session_state.pending[day]=build_analysis_card(day,s); persist(); st.success('Propozycja została przeliczona z aktualną Biblioteką FEA i Motoryki.'); st.rerun()
    st.caption('Jeśli chcesz podmienić pojedynczy środek po zatwierdzeniu, użyj modułu „Edycja treningu”. Każda ręczna zmiana zapisuje się w historii.')

elif page=='Edycja treningu':
    st.title('Ręczna podmiana środka')
    available=[d for d in DAY_ORDER if d in st.session_state.plans]
    if not available: st.warning('Brak planów.'); st.stop()
    day=st.selectbox('Dzień',available); plan=st.session_state.plans[day]
    idx=st.selectbox('Blok',range(len(plan['blocks'])),format_func=lambda i:f"{plan['blocks'][i]['role']} | {plan['blocks'][i]['ID']} | {plan['blocks'][i]['name']}")
    old=plan['blocks'][idx]; is_motor=old['role']=='Motoryka'
    source=motor if is_motor else fea
    key='Kod' if is_motor else 'ID'
    options=[x.get(key,'') for x in source if x.get('Status','AKTYWNY')=='AKTYWNY']
    new_id=st.selectbox('Nowy środek',options,index=options.index(old['ID']) if old['ID'] in options else 0,format_func=lambda ident: ident+' | '+find_item(ident).get('Nazwa',''))
    item=find_item(new_id); gp=graphic_path(new_id)
    c1,c2=st.columns([1,2])
    with c1:
        if gp: st.image(str(gp),caption=new_id,use_container_width=True)
        else: st.info('Brak zatwierdzonej grafiki dla tego środka.')
    with c2:
        st.write('**Cel:**',item.get('Cel / percepcja') or item.get('Cel/percepcja') or item.get('Akcent',''))
        st.write('**Organizacja:**',item.get('Organizacja',''))
        st.write('**Progresja:**',item.get('Progresja') or item.get('Objętość',''))
    reason=st.text_input('Powód podmiany','Lepsze dopasowanie do aktualnego problemu')
    if st.button('Zatwierdź podmianę',type='primary'):
        plan['blocks'][idx]=block_from_item(old['role'],item,old['time'])
        st.session_state.history.append({'day':day,'manual_change':{'from':old['ID'],'to':new_id,'reason':reason},'time':datetime.now().isoformat(timespec='seconds')})
        persist(); st.success(f"Podmieniono {old['ID']} → {new_id}. Konspekt korzysta od razu z nowego środka.")

elif page=='Konspekt':
    st.title('Konspekt z aktualnego planu')
    available=[d for d in DAY_ORDER if d in st.session_state.plans]
    if not available: st.warning('Brak planów.'); st.stop()
    day=st.selectbox('Dzień',available); p=st.session_state.plans[day]
    st.header(f"{day} • {p['problem']}")
    st.caption(f"Decyzja wejściowa: {p['decision_in']} • obszar: {p['weak_in']}")
    for b in p['blocks']:
        with st.expander(f"{b['role']} | {b['ID']} | {b['name']} | {b['time']} min",expanded=True):
            c1,c2=st.columns([1,2]); gp=graphic_path(b['ID'])
            with c1:
                if gp: st.image(str(gp),caption=b['ID'],use_container_width=True)
                else: st.info('Brak zatwierdzonej grafiki.')
            with c2:
                st.write('**Pole / organizacja:**',b['field']); st.write('**Cel:**',b['goal']); st.write('**Organizacja:**',b['organization']); st.write('**Przebieg:**',b.get('course','')); st.write('**Coaching:**',b.get('questions','')); st.write('**Progresja:**',b['progression']); st.write('**Dlaczego ten środek:**',b.get('selection_reason','Dobór zgodny z aktualną diagnozą.'))
    pdf=pdf_conspect(p)
    st.download_button('Pobierz konspekt PDF 2×A4',pdf,file_name=f"FEA_Konspekt_{day}.pdf",mime='application/pdf',type='primary')
    st.caption('Konspekt jest generowany z aktualnego planu. Ręczna podmiana środka natychmiast zmienia konspekt i grafikę.')

elif page=='Biblioteka':
    st.title('Biblioteka FEA / Motoryka')
    st.caption('Biblioteka jest aktywna: nowe środki są od razu dostępne dla analizy, ręcznej podmiany i ponownego generowania kolejnego treningu.')
    t1,t2,t3=st.tabs(['FEA','Motoryka','Dodaj nowy środek'])
    with t1:
        q=st.text_input('Szukaj w FEA',key='qfea')
        view=[x for x in fea if not q or q.lower() in drill_text(x)]
        enriched=[]
        for x in view:
            row=dict(x); pr=drill_profile(x); row['PER/DEC/EXE']=', '.join(pr['axes']); row['Presja 1-5']=pr['pressure']; row['Transfer 1-5']=pr['transfer']; enriched.append(row)
        st.dataframe(pd.DataFrame(enriched),use_container_width=True,hide_index=True)
        ids=[x.get('ID') for x in fea]
        ident=st.selectbox('Edytuj kartę FEA',ids)
        item=find_item(ident); eff=effectiveness(ident)
        c1,c2,c3=st.columns(3); c1.metric('Użycia ocenione',eff['uses']); c2.metric('Śr. ocena',f"{eff['avg']:.2f}" if eff['uses'] else '—'); c3.metric('Oceny 4–5',eff['good'])
        with st.form('edit_fea'):
            name=st.text_input('Nazwa',item.get('Nazwa','')); area=st.text_input('Obszar',item.get('Obszar','')); field=st.text_input('Pole',item.get('Pole',''))
            goal=st.text_area('Cel / percepcja',item.get('Cel / percepcja','')); org=st.text_area('Organizacja',item.get('Organizacja','')); course=st.text_area('Przebieg i zasady',item.get('Przebieg i zasady',''))
            questions=st.text_area('Pytania / coaching',item.get('Pytania','')); prog=st.text_area('Progresja',item.get('Progresja','')); reg=st.text_area('Regresja',item.get('Regresja',''))
            status=st.selectbox('Status',['AKTYWNY','ARCHIWALNY'],index=0 if item.get('Status','AKTYWNY')=='AKTYWNY' else 1)
            if st.form_submit_button('Zapisz kartę FEA',type='primary'):
                item.update({'Nazwa':name,'Obszar':area,'Pole':field,'Cel / percepcja':goal,'Organizacja':org,'Przebieg i zasady':course,'Pytania':questions,'Progresja':prog,'Regresja':reg,'Status':status})
                save_library('fea.json',fea); st.success('Zapisano. Zmiana jest od razu dostępna dla silnika.')
    with t2:
        q=st.text_input('Szukaj w Motoryce',key='qmot')
        view=[x for x in motor if not q or q.lower() in drill_text(x)]
        st.dataframe(pd.DataFrame(view),use_container_width=True,hide_index=True)
        ids=[x.get('Kod') for x in motor]; ident=st.selectbox('Edytuj kartę Motoryki',ids)
        item=find_item(ident); eff=effectiveness(ident)
        c1,c2=st.columns(2); c1.metric('Użycia ocenione',eff['uses']); c2.metric('Śr. ocena',f"{eff['avg']:.2f}" if eff['uses'] else '—')
        with st.form('edit_motor'):
            name=st.text_input('Nazwa',item.get('Nazwa','')); accent=st.text_input('Akcent',item.get('Akcent','')); volume=st.text_input('Objętość',item.get('Objętość','')); rest=st.text_input('Przerwa',item.get('Przerwa',''))
            org=st.text_area('Organizacja',item.get('Organizacja','')); coach=st.text_area('Coaching / bezpieczeństwo',item.get('Coaching / bezpieczeństwo','')); link=st.text_input('Powiązanie',item.get('Powiązanie',''))
            status=st.selectbox('Status',['AKTYWNY','ARCHIWALNY'],index=0 if item.get('Status','AKTYWNY')=='AKTYWNY' else 1,key='motstatus')
            if st.form_submit_button('Zapisz kartę Motoryki',type='primary'):
                item.update({'Nazwa':name,'Akcent':accent,'Objętość':volume,'Przerwa':rest,'Organizacja':org,'Coaching / bezpieczeństwo':coach,'Powiązanie':link,'Status':status})
                save_library('motor.json',motor); st.success('Zapisano. Motoryka jest od razu dostępna dla silnika.')
    with t3:
        kind=st.radio('Typ',['FEA','MOTORYKA'],horizontal=True)
        if kind=='FEA':
            newident=next_id(fea,'FEA-','ID'); st.info('Nowy ID: '+newident)
            with st.form('new_fea'):
                name=st.text_input('Nazwa'); area=st.text_input('Obszar'); players=st.text_input('Zawodnicy','18'); field=st.text_input('Pole'); goal=st.text_area('Cel / percepcja'); org=st.text_area('Organizacja'); course=st.text_area('Przebieg i zasady'); questions=st.text_area('Pytania / coaching'); prog=st.text_area('Progresja'); reg=st.text_area('Regresja'); reason=st.text_input('Powód utworzenia','Nowy środek trenera')
                if st.form_submit_button('Dodaj do Biblioteki FEA',type='primary'):
                    fea.append({'ID':newident,'Nazwa':name,'Obszar':area,'Zawodnicy':players,'Pole':field,'Cel / percepcja':goal,'Organizacja':org,'Przebieg i zasady':course,'Pytania':questions,'Progresja':prog,'Regresja':reg,'Typ':'WŁASNY','Wersja':'1.0','Status':'AKTYWNY','Powód utworzenia':reason,'Data dodania':datetime.now().strftime('%d.%m.%Y'),'Liczba użyć':0,'Grafika':newident+'.png','Status grafiki':'BRAK'})
                    save_library('fea.json',fea); st.success(newident+' dodany. Możesz od razu użyć „Analizuj ponownie”.')
        else:
            newident=next_id(motor,'M-','Kod'); st.info('Nowy ID: '+newident)
            with st.form('new_motor'):
                name=st.text_input('Nazwa'); accent=st.text_input('Akcent'); volume=st.text_input('Objętość'); rest=st.text_input('Przerwa'); org=st.text_area('Organizacja'); coach=st.text_area('Coaching / bezpieczeństwo'); link=st.text_input('Powiązanie z problemem'); reason=st.text_input('Powód utworzenia','Nowy środek motoryczny')
                if st.form_submit_button('Dodaj do Biblioteki Motoryki',type='primary'):
                    motor.append({'Kod':newident,'Nazwa':name,'Akcent':accent,'Objętość':volume,'Przerwa':rest,'Organizacja':org,'Coaching / bezpieczeństwo':coach,'Powiązanie':link,'Typ':'WŁASNY','Wersja':'1.0','Status':'AKTYWNY','Powód utworzenia':reason,'Data dodania':datetime.now().strftime('%d.%m.%Y'),'Liczba użyć':0,'Grafika':newident+'.png','Status grafiki':'BRAK'})
                    save_library('motor.json',motor); st.success(newident+' dodany do Motoryki.')

elif page=='Skuteczność środków':
    st.title('Historia skuteczności środków')
    st.caption('Ocena pochodzi z Training Score. To nie jest ranking „najlepszych ćwiczeń” — pokazuje, jak dany środek działał w konkretnych mikrocyklach i problemach.')
    rows=[]
    for item in fea+motor:
        ident=item.get('ID') or item.get('Kod'); e=effectiveness(ident)
        rows.append({'ID':ident,'Nazwa':item.get('Nazwa',''),'Użycia ocenione':e['uses'],'Średnia ocena':round(e['avg'],2) if e['uses'] else None,'Oceny 4–5':e['good']})
    df=pd.DataFrame(rows)
    st.dataframe(df,use_container_width=True,hide_index=True)
    ident=st.selectbox('Pokaż historię środka',df['ID'].tolist())
    e=effectiveness(ident); item=find_item(ident)
    st.subheader(ident+' | '+item.get('Nazwa',''))
    if e['rows']: st.dataframe(pd.DataFrame(e['rows']),use_container_width=True,hide_index=True)
    else: st.info('Ten środek nie ma jeszcze ocen z Training Score.')

elif page=='Historia':
    st.title('Historia decyzji mikrocyklu')
    if not st.session_state.history: st.info('Historia pojawi się po pierwszym Training Score.')
    for h in reversed(st.session_state.history):
        if h.get('score'):
            s=h['score']; st.write(f"**{h['day']}** → {s['decision']} | słaby obszar {s['weak']} | średnia {s['average']:.2f}")
            st.caption(s['analysis'])
        elif h.get('manual_change'):
            c=h['manual_change']; st.write(f"**{h['day']} – podmiana ręczna:** {c['from']} → {c['to']}")
            st.caption(c.get('reason',''))
