"""Anteprime nominali X/Z e sezionatura CAD, compatibili con la punta parametrica."""
import copy
import json
import math
import os
import tempfile
import threading
import uuid
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from core import *

from mesh_checks import final_mesh_checks,inherit_sections
from joiners import JOINER_DEFAULTS,joiner_parameters,apply_joiners,validate_joiner_layout,require_joiner_dependencies,check_profile_boundaries

COMPONENTS={'ala':'Ala','alettone':'Alettone','raccordo':'Raccordo centrale'}


def clip_polygon(points, distance):
    """Ritaglio di una faccia con un semispazio distance >= 0."""
    if not points:return []
    result=[];previous=points[-1];dp=distance(previous)
    for current in points:
        dc=distance(current)
        if (dp>=0)!=(dc>=0):
            t=dp/(dp-dc)
            result.append(tuple(a+(b-a)*t for a,b in zip(previous,current)))
        if dc>=0:result.append(current)
        previous,dp=current,dc
    return result


def ring_faces(rings):
    faces=[rings[0],rings[-1]]
    for a,b in zip(rings,rings[1:]):
        for i in range(len(a)):
            j=(i+1)%len(a);faces.append([a[i],a[j],b[j],b[i]])
    return faces


def section_preview(params,component):
    """Proiezione delle facce dell'involucro nominale; nessuna mesh CAD interna."""
    p=dict(params)
    if component!='raccordo' and tip_parameters(p)[0]:p['points']=max(80,p['points'])
    points=p['points'];rings=[];origin=0.
    if component=='raccordo':
        settings=connector_parameters(p);spars,_=parse_spars(p.get('spars',[]),0.,p['span'])
        if not spars and connector_ribs_enabled(p):raise ValueError('Con nervature attive, configura almeno un longherone e attiva il raccordo.')
        angle=math.radians(settings['diedro_semiala']);sn,cs=math.sin(angle),math.cos(angle)
        chord=p['root_chord'];profile=naca_profile(p['airfoil'],points,max(.9,2*p['line_width'])/chord)
        directions=[]
        for spar in spars:
            root_values,delta_values=spar_axis(p,spar)
            x,y,z=delta_values
            norm=math.sqrt(x*x+y*y+z*z);directions.append((-y*sn+z*cs)/norm)
        half=connector_half_span(p,settings,profile,directions)
        raw=[[(x*chord,y*chord*cs,-half+y*chord*sn) for x,y in profile],
             [(x*chord,y*chord,0.) for x,y in profile],
             [(x*chord,y*chord*cs,half-y*chord*sn) for x,y in profile]]
        roll=math.pi+angle
        rings=[[(x,y*math.cos(roll)-z*math.sin(roll),y*math.sin(roll)+z*math.cos(roll)) for x,y,z in ring] for ring in raw]
        shift=-min(v[2] for ring in rings for v in ring)
        rings=[[(x,y,z+shift) for x,y,z in ring] for ring in rings]
        faces=ring_faces(rings)
    else:
        v=vase_parameters(p);te=max(.9,2*v['larghezza_linea_vaso'])
        zs=planform_stations(p)
        washout=washout_parameters(p)
        if washout['washout_deg']:
            start=washout['washout_start']
            zs.extend(start+(p['span']-start)*i/16 for i in range(17))
        for z in sorted(set(zs)):
            chord,lead,_=planform_section(p,z)
            rings.append([(lead+x*chord,y*chord,z) for x,y in section_profile(p,z,te/chord)])
        tip,tip_length=tip_parameters(dict(p,skin=v['legamento']/2))
        if tip:
            scale_end=2*v['larghezza_linea_vaso']/(p['tip_chord']*int(airfoil_tip_code(p)[2:])/100)
            if scale_end>=.9:raise ValueError('Punta incompatibile con il profilo e la larghezza linea.')
            for fraction,scale in smooth_tip_sections()[1:]:
                rings.append([(x,y,p['span']+tip_length*fraction) for x,y in smooth_tip_profile(p,fraction,points)])
        faces=ring_faces(rings);a=aileron_parameters(p)
        if component=='alettone' and not a:raise ValueError('Attiva l’alettone nel relativo passo.')
        if a:
            start=a['inizio_alettone'];end=start+a['lunghezza_alettone'];gap=a['gioco_alettone'];axial=aileron_axial_bounds(a)
            hinge=[]
            for z,width in ((start,a['larghezza_alettone_radice']),(end,a['larghezza_alettone_estremita'])):
                chord,lead,_=wing_section_at(p,z)
                if width+2*p['skin']+gap>=chord:raise ValueError('Alettone troppo largo rispetto alla corda locale.')
                x=lead+chord-width
                hinge.append((x,upper_surface_at(p,z,x)))
            def hx(z):return hinge[0][0]+(hinge[1][0]-hinge[0][0])*(z-start)/(end-start)
            def hy(z):return hinge[0][1]+(hinge[1][1]-hinge[0][1])*(z-start)/(end-start)
            clipped=[]
            for face in faces:
                if component=='alettone':
                    q=clip_polygon(face,lambda v:v[2]-(axial['part_start']))
                    q=clip_polygon(q,lambda v:axial['part_end']-v[2])
                    q=clip_polygon(q,lambda v:v[0]-hx(v[2])-gap/2)
                    bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
                    q=clip_polygon(q,lambda v:v[0]-hx(v[2])-gap/2-bevel*(hy(v[2])-v[1]))
                    if len(q)>=3:clipped.append(q)
                else:
                    lo=axial['cut_start'];hi=axial['cut_end']
                    below=clip_polygon(face,lambda v:lo-v[2]);above=clip_polygon(face,lambda v:v[2]-hi)
                    middle=clip_polygon(clip_polygon(face,lambda v:v[2]-lo),lambda v:hi-v[2])
                    middle=clip_polygon(middle,lambda v:hx(v[2])-gap/2-v[0])
                    clipped.extend(q for q in (below,middle,above) if len(q)>=3)
            faces=clipped
            if component=='alettone':origin=axial['part_start']
    if component!='raccordo':faces=[[washout_point(p,v) for v in face] for face in faces]
    polygons=[[(x,z-origin) for x,y,z in face] for face in faces]
    vertices=[v for poly in polygons for v in poly]
    if not vertices:raise ValueError('Sagoma vuota: controlla le dimensioni del componente.')
    servo_outlines=[]
    layout=servo_layout(p) if component=='ala' else None
    if layout:
        for key in ('outer_bounds','inner_bounds'):
            xmin,xmax,zmin,zmax=layout[key];outline=[]
            for x,z in servo_footprint(layout,key,closed=True):
                xx,yy,zz=washout_point(p,(x,servo_surface(p,z,x),z));outline.append((xx,zz))
            servo_outlines.append(outline)
    return dict(polygons=polygons,xmin=min(x for x,z in vertices),xmax=max(x for x,z in vertices),
                height=max(z for x,z in vertices),origin=origin,servo_outlines=servo_outlines)


def validate_cut_positions(cuts,height):
    values=sorted(float(str(v).replace(',','.')) for v in cuts)
    if not math.isfinite(height) or height<=0:raise ValueError('Altezza del componente non valida.')
    if any(not math.isfinite(v) or v<=1e-4 or v>=height-1e-4 for v in values):
        raise ValueError(f'I piani devono essere interni al componente: 0 < Z < {height:.3f} mm.')
    if any(b-a<1e-4 for a,b in zip(values,values[1:])):raise ValueError('Due piani di taglio coincidono.')
    return values


def split_solid_z(solid,cuts,progress=None):
    import cadquery as cq
    bb=solid.BoundingBox();origin=0. if abs(bb.zmin)<1e-5 else bb.zmin;height=bb.zmax-origin
    limits=[0.]+validate_cut_positions(cuts,height)+[height];parts=[]
    pad=max(bb.xlen,bb.ylen,height,1.)+1
    for i,(start,end) in enumerate(zip(limits,limits[1:])):
        if len(limits)==2:part=solid
        else:
            low=origin+start-(pad if i==0 else 0.)
            high=origin+end+(pad if i==len(limits)-2 else 0.)
            box=cq.Workplane('XY').box(bb.xlen+2*pad,bb.ylen+2*pad,high-low).translate(((bb.xmin+bb.xmax)/2,(bb.ymin+bb.ymax)/2,(low+high)/2)).val()
            part=solid.intersect(box)
        if not part.isValid():part=part.fix()
        if not part.isValid() or len(part.Solids())!=1 or part.Volume()<1e-9:
            raise RuntimeError(f'Pezzo {i+1} non valido o disconnesso: modifica la quota del taglio.')
        part=part.translate((0,0,-(origin+start)))
        if hasattr(solid,'_oval_params'):part._oval_params=solid._oval_params
        if hasattr(solid,'_washout_params'):
            part._washout_params=solid._washout_params
            part._washout_origin=getattr(solid,'_washout_origin',0.)+origin+start
        inherit_sections(solid,part,origin+start,end-start)
        sections=validate_vase_sections(cq,part,end-start,samples=9)
        parts.append(dict(solid=part,start=start,end=end,sections=sections))
        if progress:progress(i+1,len(limits)-1)
    return parts


def write_piece_sidecars(params,path,piece,height,component):
    p=copy.deepcopy(params);original=copy.deepcopy(p.get('_verifica_vaso',{}));start,end=piece['start'],piece['end']
    caps=aileron_cap_parameters(p) if component=='alettone' else None
    layer=vase_parameters(p)['altezza_strato_vaso']
    bottom=max(0.,min(end,caps['spessore'])-start) if caps else 0.
    top=max(0.,end-max(start,height-caps['spessore'])) if caps else 0.
    if caps and not (bottom>1e-6 or top>1e-6):p['chiudi_estremita_alettone']=False
    p['_componente_esportazione']=component
    p['_verifica_vaso']=dict(componente=component,apertura_totale=piece.get('print_height',end-start),campioni_sezione=original.get('campioni_mesh_finale',piece['sections']),
        quota_radice_originale=original.get('quota_radice_originale',0.)+start,
        sezionatura=dict(inizio_z_locale=start,fine_z_locale=end,traslazione_stampa_z=-start,
                        chiusura_inferiore_residua=bottom,chiusura_superiore_residua=top,giunzioni=piece.get('joiners',[])),
        verifica_componente_originale=original,
        verifica_ovali_gcode=original.get('verifica_ovali_gcode'),verifica_slicer=original.get('verifica_slicer','NON ESEGUITA'),
        nota=('Giunzioni Spiral Vase: rimuovere il supporto femmina se presente; verificare l’accoppiamento con un provino.' if piece.get('joiners') else 'Taglio puro: non sono stati aggiunti tappi. Stampare ogni pezzo separatamente.'))
    settings,report=write_vase_sidecars(p,path)
    if caps and (bottom>1e-6 or top>1e-6):
        lines=settings.read_text(encoding='utf-8').splitlines()
        count_bottom=int(math.ceil(bottom/layer-1e-8)) if bottom>1e-6 else 3
        count_top=int(math.ceil(top/layer-1e-8)) if top>1e-6 else 0
        lines=[f'bottom_solid_layers = {count_bottom}' if line.startswith('bottom_solid_layers =') else
               f'top_solid_layers = {count_top}' if line.startswith('top_solid_layers =') else line for line in lines]
        settings.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        data=json.loads(report.read_text(encoding='utf-8'));data['strati_pieni_pezzo']=dict(inferiori=count_bottom,superiori=count_top)
        report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    data=json.loads(report.read_text(encoding='utf-8'))
    data['parametri_generazione']={k:v for k,v in params.items() if not k.startswith('_')}
    data['riferimento_parametri']='Componente originale, seguito dai tagli Z specificati in sezionatura.'
    report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return settings,report


class SectioningPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.pack(fill='both',expand=True)
        self.cut_cache=None
        self.cuts={c:[] for c in COMPONENTS};self.preview={};self.selected=None;self.dragging=False;self.cache={};self.canvases={};self.transforms={};self.controls=[];self.export_buttons={}
        ttk.Label(self,text='Sezionatura 2D',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(self,text='Vista X/Z della sagoma nominale, senza strutture interne. Click: aggiungi un piano; trascina una linea per spostarlo; tasto destro: elimina. Quote Z locali dalla base di ogni componente nella posizione di stampa.',wraplength=800).pack(anchor='w',pady=6)
        previews=ttk.Frame(self);previews.pack(fill='x')
        for column,(component,name) in enumerate(COMPONENTS.items()):
            previews.columnconfigure(column,weight=1,uniform='preview')
            frame=ttk.LabelFrame(previews,text=name,padding=4);frame.grid(row=0,column=column,sticky='nsew',padx=3)
            canvas=tk.Canvas(frame,height=300,width=250,background='#ffffff',highlightthickness=1,highlightbackground='#cbd5e1')
            canvas.pack(fill='both',expand=True);self.canvases[component]=canvas
            canvas.bind('<Configure>',lambda event,c=component:self.draw_shape(c))
            canvas.bind('<Button-1>',lambda event,c=component:self.click(c,event))
            canvas.bind('<B1-Motion>',lambda event,c=component:self.drag(c,event))
            canvas.bind('<ButtonRelease-1>',lambda event:setattr(self,'dragging',False))
            canvas.bind('<Button-3>',lambda event,c=component:self.delete_near(c,event))
        row=ttk.Frame(self);row.pack(fill='x',pady=8)
        self.target=tk.StringVar(value='ala')
        self.target_display=tk.StringVar(value=COMPONENTS['ala'])
        target=ttk.Combobox(row,values=list(COMPONENTS.values()),textvariable=self.target_display,state='readonly',width=20);target.pack(side='left');self.controls.append((target,'readonly'));self.component_picker=target
        self.target.trace_add('write',lambda *_:self.sync_component_picker())
        ttk.Label(row,text='Z locale (mm)').pack(side='left',padx=6)
        target.bind('<<ComboboxSelected>>',self.choose_component)
        self.position=tk.StringVar();entry=ttk.Entry(row,textvariable=self.position,width=10);entry.pack(side='left');self.controls.append((entry,'normal'));entry.bind('<Return>',lambda event:self.add_numeric())
        for label,command in [('Aggiungi',self.add_numeric),('Modifica',self.edit_numeric),('Elimina',self.delete_selected)]:
            button=ttk.Button(row,text=label,command=command);button.pack(side='left',padx=3);self.controls.append((button,'normal'))
        utilities=ttk.Frame(self);utilities.pack(fill='x',pady=(0,6))
        for label,command in [('Svuota elemento',self.clear_target),('Aggiorna anteprime',self.refresh),('Taglio a fine scasso',self.cut_at_aileron_end)]:
            button=ttk.Button(utilities,text=label,command=command);button.pack(side='left',padx=3);self.controls.append((button,'normal'))
        table_frame=ttk.Frame(self);table_frame.pack(fill='x')
        self.table=ttk.Treeview(table_frame,columns=('element','z'),show='headings',height=4,selectmode='browse')
        self.table.heading('element',text='Elemento');self.table.heading('z',text='Piano Z locale (mm)');self.table.pack(side='left',fill='x',expand=True)
        scrollbar=ttk.Scrollbar(table_frame,orient='vertical',command=self.table.yview);scrollbar.pack(side='right',fill='y');self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind('<<TreeviewSelect>>',self.select_table)
        self.joiner_vars={k:tk.StringVar(value=v) for k,v in JOINER_DEFAULTS.items()}
        group=ttk.LabelFrame(self,text='Giunzioni di allineamento e incollaggio',padding=8);group.pack(fill='x',pady=6)
        self.joiner_controls=[]
        switch=ttk.Checkbutton(group,text='Giunzioni maschio/femmina a ogni taglio (tutti i componenti)',variable=self.joiner_vars['JoinerEnabled'],onvalue='1',offvalue='0',command=self.toggle_joiners)
        switch.grid(row=0,column=0,columnspan=4,sticky='w');self.controls.append((switch,'normal'))
        fields=(('JoinerLength','Lunghezza linguetta (mm)'),('JoinerClearance','Gioco minimo assemblaggio (mm)'),('JoinerLeadInOffset','Gioco aggiuntivo sulla linea (mm)'),('FemaleSupportGap','Gap supporto removibile (mm)'),('FemaleRibMargin','Riserva oltre la linguetta (mm)'))
        for i,(key,label) in enumerate(fields):
            row=1+i//2;column=(i%2)*2
            ttk.Label(group,text=label).grid(row=row,column=column,sticky='w',padx=(0,8),pady=2)
            entry=ttk.Entry(group,textvariable=self.joiner_vars[key],width=12);entry.grid(row=row,column=column+1,sticky='w',padx=(0,18))
            self.joiner_controls.append((entry,key))
        support=ttk.Checkbutton(group,text='Supporti femmina verticali e removibili',variable=self.joiner_vars['FemaleSupportEnabled'],onvalue='1',offvalue='0',command=self.toggle_joiners)
        support.grid(row=4,column=0,columnspan=4,sticky='w');self.joiner_controls.append((support,'FemaleSupportEnabled'))
        ttk.Label(group,text='Maschio ancorato sotto il taglio sul pezzo inferiore, femmina sul successivo. Distacco locale uniforme: linea effettiva + gioco aggiuntivo. Il profilo viene verificato durante l’inserimento. I supporti crescono verticali fino alle nervature interrotte e vanno rimossi prima dell’incollaggio. La verifica PrusaSlicer è opzionale e si attiva nel primo pannello.',wraplength=920).grid(row=5,column=0,columnspan=4,sticky='w',pady=(5,0))
        self.joiner_note=tk.StringVar()
        ttk.Label(group,textvariable=self.joiner_note,wraplength=920,foreground='#6d28d9').grid(row=6,column=0,columnspan=4,sticky='w',pady=(4,0))
        for variable in self.joiner_vars.values():variable.trace_add('write',lambda *_:self.joiner_changed())
        self.app.vars['diametro_ugello'].trace_add('write',lambda *_:self.joiner_changed())
        self.app.vars['larghezza_linea_vaso'].trace_add('write',lambda *_:self.joiner_changed())
        self.toggle_joiners()
        self.update_joiner_note()
        self.details=tk.StringVar(value='Apri il pannello o aggiorna le anteprime per leggere la configurazione corrente.')
        ttk.Label(self,textvariable=self.details,wraplength=800).pack(anchor='w',pady=7)
        ttk.Label(self,text='Senza giunzioni i tagli conservano fori e cavità. Con giunzioni la zona femmina è libera da nervature e sedi interne; servo e cerniere non possono intersecare l’innesto. Ogni pezzo è appoggiato su Z=0.',wraplength=800).pack(anchor='w',pady=4)
        buttons=ttk.Frame(self);buttons.pack(fill='x',pady=6)
        for component,name in COMPONENTS.items():
            button=ttk.Button(buttons,text='Esporta '+name.lower()+' sezionato…',command=lambda c=component:self.export(c));button.pack(side='left',padx=4);self.export_buttons[component]=button

    def joiner_changed(self):
        self.toggle_joiners()
        self.update_joiner_note()
        if hasattr(self,'details'):
            for component in COMPONENTS:self.draw_cuts(component)

    def update_joiner_note(self):
        try:
            settings=joiner_parameters(dict({k:v.get() for k,v in self.joiner_vars.items()},larghezza_linea_vaso=self.app.vars['larghezza_linea_vaso'].get(),diametro_ugello=self.app.vars['diametro_ugello'].get()))
            text=(f"Distacco uniforme: {settings['ShrinkOffset']:g} mm = linea effettiva {settings['PrintWidth']:g} + gioco aggiuntivo {settings['JoinerLeadInOffset']:g}. Riserva femmina: {max(settings['PrintWidth'],settings['FemaleRibMargin']):g} mm." if settings else 'Giunzioni disattivate: esportazione sezionata originale.')
        except ValueError as exc:text=str(exc)
        self.joiner_note.set(text)

    def toggle_joiners(self):
        busy=self.app.generating;active=self.joiner_vars['JoinerEnabled'].get()=='1'
        for widget,key in self.joiner_controls:
            available=active and (key!='FemaleSupportGap' or self.joiner_vars['FemaleSupportEnabled'].get()=='1')
            widget.configure(state='normal' if available and not busy else 'disabled')

    def parameters(self,component):
        if component=='raccordo':return self.app.connector_inputs()
        p=params_from_ui(self.app.vars);p.update(self.app.spar_params());p['_componente_esportazione']=component
        if component=='alettone' and not aileron_parameters(p):raise ValueError('Attiva l’alettone nel passo dedicato.')
        return p

    def refresh(self):
        if self.app.generating:return
        self.preview={}
        for component in COMPONENTS:
            try:
                p=self.parameters(component);data=section_preview(p,component);data['params']=p;self.preview[component]=data
            except (ValueError,TypeError,KeyError,ZeroDivisionError) as exc:self.preview[component]=dict(error=str(exc))
            self.draw_shape(component)
        self.update_table();self.set_busy(False)

    def set_busy(self,busy):
        for widget,state in self.controls:widget.configure(state='disabled' if busy else state)
        self.toggle_joiners()
        for component,button in self.export_buttons.items():
            button.configure(state='disabled' if busy or not self.preview.get(component) or 'error' in self.preview[component] else 'normal')

    def draw_shape(self,component):
        canvas=self.canvases[component];canvas.delete('all');data=self.preview.get(component,{})
        width=max(250,canvas.winfo_width());height=300
        if not data or 'error' in data:
            canvas.create_text(width/2,height/2,text=data.get('error','Anteprima da aggiornare'),width=width-30,fill='#64748b');return
        scale=min((width-85)/max(1.,data['xmax']-data['xmin']),(height-55)/data['height'])
        left=35;bottom=height-28
        self.transforms[component]=(left,bottom,scale,data['xmin'])
        def xy(x,z):return (left+(x-data['xmin'])*scale,bottom-z*scale)
        canvas.create_line(left-8,bottom,left-8,20,arrow='last',fill='#64748b')
        canvas.create_text(left-8,10,text='Z',fill='#64748b')
        canvas.create_text(left-15,bottom,text='0',fill='#64748b')
        for poly in data['polygons']:
            if len(poly)>=3:canvas.create_polygon(*[value for point in poly for value in xy(*point)],fill='#bfdbfe',outline='')
        if component=='ala' and tip_parameters(data['params'])[0]:
            p=data['params'];q=tip_center_percentage(p);axis=planform_section(p,p['span'])[1]+p['tip_chord']*q/100
            axis=washout_point(p,(axis,0,p['span']))[0]
            x1,y1=xy(axis,p['span']);x2,y2=xy(axis,data['height'])
            canvas.create_line(x1,y1,x2,y2,fill='#7c3aed',dash=(4,3),width=1.5)
            canvas.create_text(x1+5,(y1+y2)/2,text=f'{q:g}%',anchor='w',fill='#6d28d9',font=('Segoe UI',8))
        for outline,color in zip(data.get('servo_outlines',[]),('#d97706','#b91c1c')):
            canvas.create_line(*[v for point in outline for v in xy(*point)],fill=color,width=2,tags='servo')
        canvas.create_text(width/2,11,text=f"{data['height']:.2f} mm",fill='#334155')
        base=f"Base a Z ala {data['origin']:.2f} mm" if component=='alettone' else ('Base: radice ala' if component=='ala' else 'Base: piano di stampa')
        canvas.create_text(width/2,height-10,text=base,fill='#64748b',font=('Segoe UI',8))
        self.draw_cuts(component)

    def draw_cuts(self,component):
        canvas=self.canvases[component];canvas.delete('cuts');data=self.preview.get(component,{})
        if 'height' not in data or component not in self.transforms:return
        left,bottom,scale,xmin=self.transforms[component];width=max(250,canvas.winfo_width())
        valid=[z for z in self.cuts[component] if 0<z<data['height']]
        for z in valid:
            y=bottom-z*scale;selected=self.selected==(component,z)
            canvas.create_line(18,y,width-12,y,fill='#dc2626',width=3 if selected else 1.5,tags='cuts')
            canvas.create_text(width-13,y-8,text=f'{z:.2f}',anchor='e',fill='#b91c1c',tags='cuts')
        limits=[0.]+sorted(valid)+[data['height']]
        if self.joiner_vars['JoinerEnabled'].get()=='1':
            try:length=float(self.joiner_vars['JoinerLength'].get().replace(',','.'))
            except ValueError:length=0.
            if math.isfinite(length) and length>0:
                for z in self.cuts[component]:
                    top=bottom-min(z+length,data['height'])*scale;yy=bottom-z*scale
                    canvas.create_rectangle(left,top,width-28,yy,fill='#ede9fe',stipple='gray50',outline='#7c3aed',dash=(3,3),tags='cuts')
                    canvas.create_text(left+4,(top+yy)/2,text='M → F',anchor='w',fill='#6d28d9',font=('Segoe UI',8,'bold'),tags='cuts')
        for index,(a,b) in enumerate(zip(limits,limits[1:]),1):
            y=bottom-(a+b)/2*scale
            canvas.create_text(width-12,y,text=f'P{index}',anchor='e',fill='#334155',tags='cuts')

    def event_z(self,component,event):
        if component not in self.transforms:return None
        left,bottom,scale,xmin=self.transforms[component]
        return round((bottom-event.y)/scale,2)

    def nearest(self,component,event):
        z=self.event_z(component,event)
        if z is None or not self.cuts[component]:return None
        nearest=min(self.cuts[component],key=lambda v:abs(v-z))
        return nearest if abs(nearest-z)*self.transforms[component][2]<=8 else None

    def click(self,component,event):
        if self.app.generating or 'height' not in self.preview.get(component,{}):return
        self.target.set(component);near=self.nearest(component,event)
        if near is None:
            z=self.event_z(component,event)
            try:self.insert(component,z)
            except ValueError:return
        else:self.selected=(component,near);self.position.set(f'{near:.2f}');self.update_table()
        self.dragging=True

    def drag(self,component,event):
        if self.app.generating or not self.dragging or not self.selected or self.selected[0]!=component:return
        z=self.event_z(component,event)
        try:self.replace_selected(z)
        except ValueError:return

    def insert(self,component,z):
        data=self.preview.get(component,{})
        if 'height' not in data:raise ValueError(data.get('error','Aggiorna le anteprime.'))
        values=validate_cut_positions(self.cuts[component]+[z],data['height'])
        self.cuts[component]=values;self.selected=(component,float(z));self.position.set(f'{float(z):.2f}');self.update_table()

    def replace_selected(self,z):
        if not self.selected:raise ValueError('Seleziona un piano da modificare.')
        component,old=self.selected;data=self.preview[component]
        values=list(self.cuts[component]);values.remove(old);values.append(z)
        self.cuts[component]=validate_cut_positions(values,data['height']);self.selected=(component,float(z));self.position.set(f'{float(z):.2f}');self.update_table()

    def add_numeric(self):
        if self.app.generating:return
        try:self.insert(self.target.get(),float(self.position.get().replace(',','.')))
        except (ValueError,TypeError) as exc:messagebox.showerror('Piano di taglio',str(exc))

    def edit_numeric(self):
        if self.app.generating:return
        try:self.replace_selected(float(self.position.get().replace(',','.')))
        except (ValueError,TypeError) as exc:messagebox.showerror('Piano di taglio',str(exc))

    def delete_selected(self):
        if self.app.generating or not self.selected:return
        component,z=self.selected
        if z in self.cuts[component]:self.cuts[component].remove(z)
        self.selected=None;self.update_table()

    def delete_near(self,component,event):
        if self.app.generating:return
        near=self.nearest(component,event)
        if near is not None:self.selected=(component,near);self.delete_selected()

    def clear_target(self):
        if self.app.generating:return
        self.cuts[self.target.get()]=[];self.selected=None;self.update_table()

    def cut_at_aileron_end(self):
        if self.app.generating:return
        try:
            p=self.parameters('ala');a=aileron_parameters(p)
            if not a:raise ValueError('Attiva l’alettone per aggiungere il taglio alla fine dello scasso.')
            end=aileron_axial_bounds(a)['cut_end']
            self.target.set('ala')
            existing=next((z for z in self.cuts['ala'] if abs(z-end)<1e-5),None)
            if existing is not None:
                self.selected=('ala',existing);self.position.set(f'{existing:.2f}');self.update_table()
            elif self.selected and self.selected[0]=='ala':self.replace_selected(end)
            else:self.insert('ala',end)
            self.app.status.set(f'Taglio alla fine effettiva dello scasso: Z={end:g} mm, incluso il gioco terminale.')
        except ValueError as exc:messagebox.showerror('Piano di taglio',str(exc))

    def sync_component_picker(self):
        labels=[self.app.tr(name) if hasattr(self.app,'language') else name for name in COMPONENTS.values()]
        if tuple(self.component_picker['values'])!=tuple(labels):self.component_picker.configure(values=labels)
        index=list(COMPONENTS).index(self.target.get())
        if self.component_picker.current()!=index:self.component_picker.current(index)

    def choose_component(self,event=None):
        index=self.component_picker.current()
        if index>=0:self.target.set(list(COMPONENTS)[index]);self.change_target()

    def change_target(self):
        self.selected=None
        self.position.set('')
        self.table.selection_remove(*self.table.selection())
        for component in COMPONENTS:self.draw_cuts(component)

    def select_table(self,event=None):
        if self.app.generating:return
        selected=self.table.selection()
        if not selected:return
        component,index=selected[0].split(':');index=int(index)
        if index>=len(self.cuts[component]):return
        z=self.cuts[component][index];self.selected=(component,z);self.target.set(component);self.position.set(f'{z:.2f}')
        for c in COMPONENTS:self.draw_cuts(c)

    def update_table(self):
        self.table.delete(*self.table.get_children());summaries=[]
        for component,name in COMPONENTS.items():
            for i,z in enumerate(self.cuts[component]):
                self.table.insert('',tk.END,iid=f'{component}:{i}',values=(name,f'{z:.2f}'))
                if self.selected==(component,z):self.table.selection_set(f'{component}:{i}')
            data=self.preview.get(component,{})
            if 'height' in data:
                try:
                    cuts=validate_cut_positions(self.cuts[component],data['height']);limits=[0.]+cuts+[data['height']]
                    summaries.append(name+': '+str(len(limits)-1)+' pezzi ('+' / '.join(f'{b-a:.2f}' for a,b in zip(limits,limits[1:]))+' mm)')
                except ValueError:summaries.append(name+': quote fuori intervallo, correggere i tagli.')
            self.draw_cuts(component)
        self.details.set(' | '.join(summaries) or 'Nessun componente configurato.')

    def export(self,component):
        if self.app.generating:return
        self.refresh()
        try:
            data=self.preview[component]
            if 'error' in data:raise ValueError(data['error'])
            cuts=validate_cut_positions(self.cuts[component],data['height']);params=copy.deepcopy(data['params'])
            params.update({k:v.get() for k,v in self.joiner_vars.items()})
            settings=joiner_parameters(params)
            params['_joiners_active']=bool(settings)
            validate_joiner_layout(cuts,data['height'],settings,vase_parameters(params)['larghezza_linea_vaso'])
            check_profile_boundaries(params,cuts)
        except (ValueError,KeyError) as exc:messagebox.showerror('Sezionatura',str(exc));return
        directory=filedialog.askdirectory(title='Cartella per i pezzi: '+COMPONENTS[component])
        if not directory:return
        self.app.begin_operation('Esportazione '+COMPONENTS[component].lower()+' sezionato')
        def worker():
            try:
                result=self.export_files(component,params,cuts,Path(directory))
                self.app.events.put(('sections_done',result))
            except Exception as exc:self.app.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start();self.app.after(100,self.app.poll_generation)

    def notify(self,phase,done=0,total=1,index=0,count=1,stage=''):
        self.app.events.put(('sections_progress',dict(phase=phase,done=done,total=total,index=index,count=count,stage=stage)))

    def update_progress(self,data):
        phase=data['phase'];ratio=data['done']/max(1,data['total'])
        if phase=='split':value=20+15*ratio;text=f"Sezionatura e controllo pezzi: {data['done']}/{data['total']}"
        elif phase=='joiners':value=35+10*ratio;text=f"Giunzioni e controllo contorni: {data['done']}/{data['total']}"
        elif phase=='piece':
            stages={'triangulation':(0,.2,'triangolazione'),
                    'vertices':(.2,.5,'verifica vertici'),
                    'mesh_check':(.5,.6,'controllo mesh'),
                    'mesh_sections':(.73,.75,'verifica sezioni sulla mesh finale'),
                    'washout':(.6,.75,'applicazione washout'),
                    'write':(.75,.85,'scrittura STL'),
                    'slicer':(.85,.95,'verifica zero retrazioni'),
                    'reports':(.95,1.,'impostazioni e rapporti')}
            lo,hi,label=stages.get(data['stage'],(0,0,'elaborazione del pezzo'))
            fraction=lo+(hi-lo)*ratio
            value=45+50*(data['index']+fraction)/max(1,data['count'])
            text=f"Pezzo {data['index']+1}/{data['count']}: {label}"
        else:value=95;text='Salvataggio piano di taglio e completamento cartella'
        self.app.progress_value=max(self.app.progress_value,min(99.,value));self.app.progress_stage='sections'
        self.app.progress_bar.configure(mode='determinate',value=self.app.progress_value)
        self.app.progress_text.set(f'{self.app.operation_name} — {text} — {self.app.progress_value:.0f}% (avanzamento fasi)')
        self.app.status.set(text)

    def export_files(self,component,params,cuts,directory):
        enabled=not (component=="alettone" and aileron_cap_parameters(params))
        with final_mesh_checks(enabled):
            return self._export_files(component,params,cuts,directory)

    def _export_files(self,component,params,cuts,directory):
        settings_joiner=joiner_parameters(params)
        if settings_joiner:require_joiner_dependencies();check_profile_boundaries(dict(params,_componente_esportazione=component),cuts)
        params=dict(params,_joiners_active=bool(settings_joiner))
        if settings_joiner and not cuts:raise ValueError('Le giunzioni richiedono almeno un taglio.')
        key=json.dumps({k:v for k,v in params.items() if not k.startswith('_') and k!='verifica_prusaslicer' and (k not in JOINER_DEFAULTS or k=='JoinerEnabled')},sort_keys=True)
        cached=self.cache.get(component)
        if cached and cached[0]==key:solid,p=cached[1],copy.deepcopy(cached[2])
        else:
            p=copy.deepcopy(params)
            p['_componente_esportazione']=component
            callback=lambda msg:self.app.events.put(('progress',msg))
            solid,_=build_central_connector(p,callback) if component=='raccordo' else build_solid(p,callback)
            self.cache[component]=(key,solid,copy.deepcopy(p))
        for k in JOINER_DEFAULTS:
            if k in params:p[k]=params[k]
        p['verifica_prusaslicer']=params.get('verifica_prusaslicer','0')
        p['_joiners_active']=bool(settings_joiner)
        assembly_key=json.dumps(dict(base=key,cuts=cuts,joiners={k:p.get(k) for k in JOINER_DEFAULTS}),sort_keys=True)
        if self.cut_cache and self.cut_cache['key']==assembly_key:
            pieces=self.cut_cache['pieces'];volume_original=self.cut_cache['volume_original'];volume_parts=self.cut_cache['volume_parts']
            self.app.events.put(('progress','Tagli e giunzioni invariati: riuso dei pezzi già calcolati'))
            self.notify('joiners',1,1)
        else:
            self.notify('split',0,len(cuts)+1)
            pieces=split_solid_z(solid,cuts,lambda done,total:self.notify('split',done,total))
            # Le superfici spline richiedono integrazione adattiva: il calcolo
            # predefinito può simulare una perdita di volume dopo un taglio valido.
            volume_original=solid.Volume(tol=1e-8);volume_parts=sum(piece['solid'].Volume(tol=1e-8) for piece in pieces)
            if abs(volume_parts-volume_original)>max(1e-5,volume_original*1e-6):raise RuntimeError('La sezionatura non conserva il volume del componente.')
            if settings_joiner:
                self.notify('joiners',0,len(cuts)+len(pieces))
                pieces=apply_joiners(solid,p,pieces,cuts,lambda done,total:self.notify('joiners',done,total))
            self.cut_cache=dict(key=assembly_key,pieces=pieces,volume_original=volume_original,volume_parts=volume_parts)
        height=pieces[-1]['end'];tolerance=min(vase_parameters(p)['fessura_vaso']/10,.005)
        directory=directory.resolve()
        final=directory/(component+'_sezionato_v91_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
        if final.parent.resolve()!=directory or final.exists():raise ValueError('Cartella di destinazione non valida.')
        files=[];manifest=dict(versione=VERSION,componente=component,quote_z_locali=cuts,altezza_originale=height,volume_originale=volume_original,volume_pezzi=volume_parts,
                               parametri={k:v for k,v in p.items() if not k.startswith('_')},giunzioni=settings_joiner,volume_pezzi_con_giunzioni=sum(piece['solid'].Volume(tol=1e-8) for piece in pieces),pezzi=[])
        with tempfile.TemporaryDirectory(prefix='.wing_v91_',dir=directory) as temp:
            staging=Path(temp)
            for i,piece in enumerate(pieces):
                path=staging/f'{component}_{i+1:02d}.stl'
                callback=lambda stage,done,total,i=i:self.notify('piece',done or 0,total or 1,i,len(pieces),stage)
                piece_params=copy.deepcopy(p)
                piece_params['_female_joiner']=any(j.get('lato')=='femmina' for j in piece.get('joiners',[]))
                piece_params['_verifica_vaso'].pop('verifica_ovali_gcode',None)
                export_verified_stl(piece['solid'],path,tolerance,progress=callback,params=piece_params)
                self.notify('piece',0,1,i,len(pieces),'reports')
                settings,report=write_piece_sidecars(piece_params,path,piece,height,component)
                files.append(path.name);manifest['pezzi'].append(dict(file=path.name,inizio_z_locale=piece['start'],fine_z_locale=piece['end'],altezza=piece.get('print_height',piece['end']-piece['start']),giunzioni=piece.get('joiners',[]),impostazioni=settings.name,rapporto=report.name))
                self.notify('piece',1,1,i,len(pieces),'reports')
            self.notify('manifest')
            (staging/'piano_tagli.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            if staging.resolve().parent!=directory or final.resolve().parent!=directory:raise ValueError('Percorso fuori dalla cartella di esportazione.')
            staging.rename(final)
        return dict(directory=str(final),component=COMPONENTS[component],files=files)
