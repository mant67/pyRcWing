"""Horizontal tip preview and geometric starting values; no change to CAD rules."""
# File revision: 5
import math
import tkinter as tk
from tkinter import ttk
from core import (airfoil_tip_code, elliptical_planform, planform_parameters,
    planform_section, planform_outline, smooth_tip_sections, smooth_tip_profile, base_smooth_tip_profile,
    tip_center_percentage, washout_point, profile_thickness_ratio)


def tip_planform_edges(p,edited=True,fractions=None):
    """Project the tip onto the nominal planform with matching join tangents."""
    length=p['tip_length']
    def bounds(profile):
        xs=[x for x,_ in profile]
        return min(xs),max(xs)

    span=p['span']
    h=min(.001,span/100000)
    chord,lead,_=planform_section(p,span)
    prev_chord,prev_lead,_=planform_section(p,span-h)
    nominal=(lead,lead+chord)
    incoming=((lead-prev_lead)/h,(lead+chord-prev_lead-prev_chord)/h)
    actual=bounds(base_smooth_tip_profile(p,0.,points=80))
    step=1e-6
    next_bounds=bounds(base_smooth_tip_profile(p,step,points=80))
    profile=smooth_tip_profile if edited else base_smooth_tip_profile
    join=.125
    if fractions is None:
        fractions={f for f,_ in smooth_tip_sections(p)}
        fractions.update(join*i/8 for i in range(1,9))
        fractions.update(join/2**i for i in range(4,10))
    edges=[[],[]]
    for f in sorted(fractions):
        x_values=bounds(profile(p,f,points=80))
        t=min(1.,f/join)
        for side,x in enumerate(x_values):
            shift=nominal[side]-actual[side]
            slope=incoming[side]-(next_bounds[side]-actual[side])/(step*length)
            correction=(1-t)**2*((1+2*t)*shift+t*join*length*slope)
            edges[side].append((f,x+correction,span+f*length))
    return edges


def tip_suggestion(values):
    p=dict(values)
    for key in ('span','root_chord','tip_chord','sweep','line_width'):
        p[key]=float(str(p[key]).replace(',','.'))
        if not math.isfinite(p[key]) or (key!='sweep' and p[key]<=0):
            raise ValueError('Completa le dimensioni positive della geometria.')
    p['points']=80;code=airfoil_tip_code(p);planform_parameters(p)
    width=float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.'))
    if not math.isfinite(width) or width<=0:raise ValueError('Larghezza linea non valida.')
    span,root,chord=p['span'],p['root_chord'],p['tip_chord']
    if chord*profile_thickness_ratio(p,'tip')<=2*width/.9:
        raise ValueError('Profilo terminale troppo sottile per la punta con questa larghezza linea.')
    lower=max(2*p['line_width'],1.3*width)+.1
    upper=max(lower,min(chord,.5*span))
    if elliptical_planform(p):
        ratio=chord/root;factor=math.sqrt(1-ratio*ratio)
        raw=span*ratio*ratio/(factor*(1+factor))
        length=round(max(lower,min(upper,raw)),2)
        center=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))/100
        center+=p['sweep']*length/(span*chord)
        basis='prolungamento della pianta ellittica'
    else:
        taper=max(0.,(root-chord)/span)
        raw=min(.5*chord,.35*chord/taper) if taper else .5*chord
        length=round(max(lower,min(upper,raw)),2)
        center=.5+length*(p['sweep']/span+(chord-root)/(2*span))/chord
        basis='corda terminale e direzione della mezzeria'
    return dict(tip_length=length,wing_center_line_perc=round(max(0.,min(1.,center))*100,2),
                basis=basis,limited=abs(length-raw)>.01)


class TipEditor:
    def __init__(self,owner,canvas=None):
        self.owner=owner;self.app=owner.app;self.canvas=canvas if canvas is not None else owner.canvases['tip']
        self.handles={};self.view=None;self.drag=None
        if canvas is not None:return
        box=ttk.LabelFrame(self.app.pages[3],text='Proposta dalla geometria dell’ala',padding=8)
        box.pack(fill='x',pady=(4,0),before=self.canvas)
        self.proposal_text=tk.StringVar()
        ttk.Label(box,textvariable=self.proposal_text,wraplength=800).pack(anchor='w')
        self.proposal_button=ttk.Button(box,text='Applica proposta',command=self.apply_suggestion)
        self.proposal_button.pack(anchor='w',pady=(6,0))
        ttk.Label(box,text='Valori geometrici di partenza, modificabili con i campi o le maniglie. La proposta non modifica automaticamente la configurazione.',wraplength=800).pack(anchor='w',pady=(6,0))
        for key in ('span','root_chord','tip_chord','sweep','airfoil','airfoil_tip','planform',
                    'ellipse_center_perc','line_width','larghezza_linea_vaso','elliptical_tip'):
            self.app.vars[key].trace_add('write',self.update_suggestion)
        self.update_suggestion()

    def update_suggestion(self,*_):
        if getattr(self.app,'loading_configuration',False):return
        try:
            proposal=tip_suggestion({k:v.get() for k,v in self.app.vars.items()})
            extra=' · contenuta entro le dimensioni della semiala' if proposal['limited'] else ''
            self.proposal_text.set(f"Lunghezza {proposal['tip_length']:g} mm · Linea centrale {proposal['wing_center_line_perc']:g}% dal bordo d’attacco\nCalcolo: {proposal['basis']}{extra}.")
            state='normal' if self.app.vars['elliptical_tip'].get()=='1' else 'disabled'
        except (ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError) as exc:
            self.proposal_text.set('Proposta non disponibile: '+str(exc));state='disabled'
        self.proposal_button.configure(state=state)

    def apply_suggestion(self):
        if self.app.generating or self.app.vars['elliptical_tip'].get()!='1':return
        try:proposal=tip_suggestion({k:v.get() for k,v in self.app.vars.items()})
        except (ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError):self.update_suggestion();return
        self.app.vars['tip_length'].set(f"{proposal['tip_length']:g}")
        self.app.vars['wing_center_line_perc'].set(f"{proposal['wing_center_line_perc']:g}")
        self.owner.draw('tip')

    def draw(self,c,p,w,h,trace_view=None):
        self.handles={}
        tracing=trace_view is not None
        if not tracing:self.update_suggestion()
        body=planform_outline(p);high=dict(p,points=80);tip=[]
        chord,lead,_=planform_section(p,p['span'])
        if p['elliptical_tip']:
            leading,trailing=tip_planform_edges(high)
            tip=[(z,x) for _,x,z in leading]+[(z,x) for _,x,z in reversed(trailing)]
            middle=len(body)//2
            span=p['span']
            start=body[middle-2][0]
            join_rows=[]
            for i in range(1,10):
                z=span-(span-start)/2**i
                c_at_z,le_at_z,_=planform_section(p,z)
                join_rows.append((z,le_at_z,le_at_z+c_at_z))
            body=(body[:middle-1]+[(z,le) for z,le,_ in join_rows]+body[middle-1:middle+1]
                  +[(z,te) for z,_,te in reversed(join_rows)]+body[middle+1:])
        outline=body+tip;xs=[x for z,x in outline];height_span=max(xs)-min(xs)
        total=p['span']+(p['tip_length'] if p['elliptical_tip'] else 0.)
        if tracing:
            self.view=(trace_view.ox,trace_view.oy,trace_view.scale)
        elif self.drag is None:
            left,top,right,bottom=30.,70.,w*.59-24,h-62.
            scale=min((right-left)/total,(bottom-top)/max(1.,height_span))
            self.view=(left+(right-left-total*scale)/2,top+(bottom-top-height_span*scale)/2-min(xs)*scale,scale)
        ox,oy,scale=self.view
        def xy(z,x):return ox+z*scale,oy+x*scale
        def coords(points):return [v for point in points for v in xy(*point)]
        c.create_polygon(coords(body),fill='' if tracing else '#dbeafe',outline='#2563eb',width=2,tags='tip_wing')
        c.create_text(16,12,anchor='nw',text='Pianta nominale · Radice a sinistra, estremità a destra',fill='#475569')
        if not tracing:self.owner.note(c,w*.61,12,'Sezioni della punta',w*.37)
        if not p['elliptical_tip']:
            self.owner.note(c,16 if tracing else w*.61,40 if tracing else 55,'Punta disattivata.\nAttivala per usare le maniglie e applicare la proposta geometrica.',w*.36)
            c.create_text(16,h-24,anchor='w',text='Ala orizzontale, nella stessa scala sui due assi · Vista senza washout.',fill='#64748b')
            return
        c.create_polygon(coords(tip),fill='' if tracing else '#fed7aa',outline='#ea580c',width=2,tags='tip_shape')
        c.create_line(*coords([(p['span'],lead),(p['span'],lead+chord)]),fill='#64748b',dash=(3,3),tags='tip_joint')
        axis=lead+chord*tip_center_percentage(p)/100
        vertex=(p['span']+p['tip_length'],axis)
        c.create_line(*coords([(p['span'],axis),vertex]),fill='#7c3aed',dash=(4,3),tags='tip_axis')
        # The dimension follows the vertex while the vertex is dragged.
        dimension_y=min(xs)-24/scale
        a,b=xy(p['span'],dimension_y),xy(vertex[0],dimension_y)
        c.create_line(*a,*b,arrow='both',fill='#059669',width=2,tags='tip_length_dimension')
        c.create_line(*xy(vertex[0],dimension_y),*xy(*vertex),fill='#94a3b8',dash=(3,3))
        if tracing:self.handles={'wing_center_line_perc':xy(*vertex)}
        for key,(x,y) in self.handles.items():
            c.create_oval(x-6,y-6,x+6,y+6,fill='#ea580c',outline='white',width=2,tags=('tip_handle',key))
        c.create_text(b[0]-8,b[1]-11,anchor='se',text=f"L {p['tip_length']:g} mm",fill='#059669')
        vx,vy=xy(*vertex)
        c.create_text(vx-8,vy+12,anchor='ne',text=f"Centro {tip_center_percentage(p):g}%",fill='#7c3aed')
        if tracing:
            c.create_text(16,h-23,anchor='w',text=self.app.tr('Trascina l’apice: in orizzontale per la lunghezza, in verticale per il centro.'),fill='#475569')
            return
        self.owner.note(c,w*.61,48,f"Lunghezza aggiuntiva: {p['tip_length']:g} mm\nLinea centrale: {tip_center_percentage(p):g}% dal bordo d’attacco",w*.36)
        sections=[]
        for f in (0.,.6,.9):
            z=p['span']+p['tip_length']*f
            sections.append([(xx,yy) for x,y in smooth_tip_profile(p,f) for xx,yy,_ in [washout_point(p,(x,y,z))]])
        pv=self.owner.profile_view(c,sections[0],(w*.61,120,w-20,h-45))
        for points,color in zip(sections[1:],('#f97316','#7c3aed')):pv.line(points+[points[0]],fill=color,width=2,tags='feature')
        self.owner.note(c,w*.61,h-35,'Sezioni alla base, al 60% e al 90% della punta',w*.36)
        c.create_text(16,h-23,anchor='w',text='Pianta senza washout · Le sezioni a destra mantengono il washout.',fill='#64748b')

    def press(self,event):
        if self.app.generating or self.view is None or not self.handles:return
        key=min(self.handles,key=lambda k:math.hypot(event.x-self.handles[k][0],event.y-self.handles[k][1]))
        x,y=self.handles[key]
        if math.hypot(event.x-x,event.y-y)<=13:self.drag=(key,self.owner.params(),event.x,event.y,self.view)

    def motion(self,event):
        if self.drag is None or self.app.generating:return
        _,p,x,y,view=self.drag
        scale=view[2]
        width=float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.'))
        lower=max(2*p['line_width'],1.3*width)+.01
        length=max(lower,p['tip_length']+(event.x-x)/scale)
        center=max(0.,min(100.,tip_center_percentage(p)+(event.y-y)/scale/p['tip_chord']*100))
        self.app.vars['tip_length'].set(f'{length:.2f}')
        self.app.vars['wing_center_line_perc'].set(f'{center:.2f}')
        self.owner.draw('tip')

    def release(self,event):
        if self.drag is None:return
        self.drag=None;self.owner.draw('tip')
