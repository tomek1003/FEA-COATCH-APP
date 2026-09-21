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
DATA=ROOT/'data'
STATE=DATA/'state.json'
ASSETS=ROOT/'assets'

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
    return {'match':{},'plans':{},'scores':{},'history':[]}

def save_state(s):
    with open(STATE,'w',encoding='utf-8') as f: json.dump(s,f,ensure_ascii=False,indent=2)

fea=load_json('fea.json'); motor=load_json('motor.json'); db=load_state()
for k,v in db.items():
    if k not in st.session_state: st.session_state[k]=v

def persist():
    save_state({k:st.session_state[k] for k in ['match','plans','scores','history']})

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

def choose_fea(problem, decision='CONTINUE', weak='R', used=None, n=4, observation='', area='MIX'):
    used=set(used or [])
    active=[x for x in fea if x.get('Status','AKTYWNY')=='AKTYWNY']
    ranked=sorted(active,key=lambda x:(relevance(x,problem,weak,observation,area), effectiveness(x.get('ID',''))['avg'] if effectiveness(x.get('ID',''))['uses']>=2 else 0),reverse=True)
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
                       'progression':item.get('Progresja') or item.get('Objętość','')})
    return {'day':day,'problem':problem,'decision_in':decision,'weak_in':weak,'analysis_axes':classify_problem(problem,observation,area),'blocks':blocks,'created':datetime.now().isoformat(timespec='seconds')}


def find_item(ident):
    if ident.startswith('M-'):
        return next((x for x in motor if x.get('Kod')==ident),{})
    return next((x for x in fea if x.get('ID')==ident),{})

def block_from_item(role,item,t):
    ident=item.get('ID') or item.get('Kod','')
    return {'role':role,'ID':ident,'name':item.get('Nazwa',''),'time':t,
            'field':item.get('Pole') or item.get('Organizacja',''),
            'goal':item.get('Cel / percepcja') or item.get('Akcent',''),
            'organization':item.get('Organizacja',''),
            'course':item.get('Przebieg i zasady') or item.get('Coaching / bezpieczeństwo',''),
            'questions':item.get('Pytania') or item.get('Coaching / bezpieczeństwo',''),
            'progression':item.get('Progresja') or item.get('Objętość','')}

def graphic_path(ident):
    folder='motor' if ident.startswith('M-') else 'fea'
    p=ASSETS/folder/f'{ident}.png'
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

def regenerate_next(day, score):
    nxt=NEXT.get(day)
    if not nxt: return
    base_problem=score.get('problem') or st.session_state.match.get('problem','')
    st.session_state.plans[nxt]=build_plan(nxt,base_problem,score['decision'],score['weak'],st.session_state.plans.get(day),score.get('observation',''),st.session_state.match.get('area','MIX'))

st.sidebar.title('FEA COACH APP')
st.sidebar.caption('v0.5 • diagnoza PER/DEC/EXE + R/W/P/G + adaptacja')
page=st.sidebar.radio('Moduł',['Dashboard','Analiza meczu','Mikrocykl','Training Score','Edycja treningu','Konspekt','Biblioteka','Skuteczność środków','Historia'])

if page=='Dashboard':
    st.title('⚽ FEA COACH APP v0.5')
    c1,c2,c3,c4=st.columns(4); c1.metric('Środki FEA',len(fea)); c2.metric('Motoryka',len(motor)); c3.metric('Treningi',len(st.session_state.plans)); c4.metric('Oceny',len(st.session_state.scores))
    st.info('Mecz → priorytet → Poniedziałek → Score → analiza → Środa → Score → analiza → Piątek.')
    if st.session_state.match.get('problem'): st.success('Aktualny priorytet: '+st.session_state.match['problem'])

elif page=='Analiza meczu':
    st.title('Analiza pomeczowa → priorytet mikrocyklu')
    m=st.session_state.match
    c1,c2=st.columns(2)
    opp=c1.text_input('Przeciwnik',m.get('opponent','')); result=c2.text_input('Wynik',m.get('result',''))
    problem=st.text_area('Najważniejszy problem meczowy',m.get('problem',''),height=110)
    observation=st.text_area('Opis sytuacji / kiedy problem występował',m.get('observation',''),height=100)
    area=st.selectbox('Dominujący obszar',['PER – percepcja','DEC – decyzja','EXE – wykonanie','MENTAL','MIX'])
    if st.button('Analizuj i rozpocznij mikrocykl',type='primary'):
        st.session_state.match={'opponent':opp,'result':result,'problem':problem,'observation':observation,'area':area}
        st.session_state.plans={'Poniedziałek':build_plan('Poniedziałek',problem,'CONTINUE','R',None,observation,area)}
        st.session_state.scores={}; st.session_state.history=[]; persist()
        st.success('Utworzono priorytet i trening poniedziałkowy. Kolejne jednostki powstaną dopiero po analizie Score.')

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
        regenerate_next(day,score); persist()
        st.metric('Decyzja',dec); st.write(analysis)
        if day in NEXT: st.success(f"Przebudowano {NEXT[day]} na podstawie tej analizy.")
    if day in st.session_state.scores:
        s=st.session_state.scores[day]
        st.info(s['analysis'])
        if day in NEXT and st.button('Analizuj ponownie z aktualną biblioteką'):
            regenerate_next(day,s); persist(); st.success(f"{NEXT[day]} wygenerowano ponownie z aktualnej biblioteki.")

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
        st.write('**Cel:**',item.get('Cel / percepcja') or item.get('Akcent',''))
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
                st.write('**Pole / organizacja:**',b['field']); st.write('**Cel:**',b['goal']); st.write('**Organizacja:**',b['organization']); st.write('**Przebieg:**',b.get('course','')); st.write('**Coaching:**',b.get('questions','')); st.write('**Progresja:**',b['progression'])
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
        st.dataframe(pd.DataFrame(view),use_container_width=True,hide_index=True)
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
