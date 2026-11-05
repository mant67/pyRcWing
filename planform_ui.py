"""Horizontal editable planform shared with manual geometry fields."""
import math
import tkinter as tk
from tkinter import ttk
from planform import *

class PlanformEditor:
    def __init__(self,app,parent,controls):
        self.app=app;self.drag=None;self.handles={};self.transform=None
        app.vars['planform']=tk.StringVar(value='trapezoidal')
        app.vars['ellipse_center_perc']=tk.StringVar(value='50')
        box=ttk.LabelFrame(controls,text='Pianta alare',padding=6);box.pack(fill='x',pady=6)
        for label,value in (('Trapezoidale','trapezoidal'),('Ellittica','elliptical')):
            ttk.Radiobutton(box,text=label,value=value,variable=app.vars['planform']).pack(side='top',anchor='w')
        row=ttk.Frame(box);row.pack(fill='x',pady=4)
        ttk.Label(row,text='Linea centrale ellisse (% corda)').pack(side='left')
        self.center_entry=ttk.Entry(row,textvariable=app.vars['ellipse_center_perc'],width=7);self.center_entry.pack(side='right')
        self.note=ttk.Label(box,wraplength=360);self.note.pack(fill='x')
        self.canvas=tk.Canvas(parent,height=300,background='white',highlightthickness=1,highlightbackground='#cbd5e1')
        self.canvas.pack(fill='x',pady=(0,10))
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        for key in ('planform','ellipse_center_perc','root_chord','tip_chord','span','sweep','airfoil_tip','create_ribs','nervature_specchiate_ala','rib_pitch','rib_angle'):
            app.vars[key].trace_add('write',self.changed)
        self.changed()

    def parameters(self):
        p={k:v.get().strip() for k,v in self.app.vars.items()}
        for key in ('span','root_chord','tip_chord','sweep'):
            p[key]=float(p[key].replace(',','.'))
            if not math.isfinite(p[key]):raise ValueError('Completa le dimensioni della pianta.')
        if min(p[k] for k in ('span','root_chord','tip_chord'))<=0:raise ValueError('Le dimensioni devono essere positive.')
        planform_parameters(p)
        return p

    def changed(self,*_):
        if getattr(self.app,"loading_configuration",False):return
        elliptical=elliptical_planform({'planform':self.app.vars['planform'].get()})
        self.center_entry.configure(state='normal' if elliptical else 'disabled')
        self.app.geometry_labels['sweep'].configure(text='Freccia linea centrale (mm)' if elliptical else 'Freccia bordo attacco (mm)')
        self.app.geometry_labels['tip_chord'].configure(text='Corda terminale ellisse (mm)' if elliptical else 'Corda estremità (mm)')
        self.note.configure(text=('Ellisse con corda terminale finita per la stampa. Le maniglie sui due bordi si spostano indipendentemente. Punta aggiuntiva disponibile.' if elliptical else 'Bordi rettilinei. La punta separata è disponibile nel pannello Punta.'))
        if hasattr(self.app,'tip_check'):
            self.app.tip_check.configure(state='normal')
            enabled=self.app.vars['elliptical_tip'].get()=='1'
            for entry in self.app.tip_entries:entry.configure(state='normal' if enabled else 'disabled')
        self.draw();self.app.draw_profile_preview()

    def draw(self):
        c=self.canvas;c.delete('all');self.handles={}
        w=max(320,c.winfo_width());h=300
        try:p=self.parameters()
        except (ValueError,TypeError,IndexError) as exc:
            self.transform=None;c.create_text(18,25,text=str(exc),anchor='nw',width=w-36,fill='#b91c1c',tags='planform_error');return
        outline=planform_outline(p);ys=[y for z,y in outline]
        if self.drag is None:
            scale=min((w-170)/p['span'],(h-110)/max(1,max(ys)-min(ys)))
            self.transform=(80,52-min(ys)*scale,scale)
        ox,oy,scale=self.transform
        def xy(z,y):return ox+z*scale,oy+y*scale
        coords=[v for point in outline for v in xy(*point)]
        c.create_polygon(coords,fill='#dbeafe',outline='#2563eb',width=2,tags='planform_outline')
        if str(p.get('nervature_specchiate_ala','0')).lower() in ('1','true','yes','on'):
            if str(p.get('create_ribs','1')).lower() in ('1','true','yes','on'):
                c.create_text(12,18,anchor='w',text='Nervature schematiche: viola = originali · verde = specchiate',fill='#475569',tags='rib_legend')
            try:
                for family,points in planform_rib_segments(p):
                    c.create_line(*[v for point in points for v in xy(*point)],fill=('#7c3aed' if family=='original' else '#059669'),width=1,tags=('rib_trace',family))
            except (ValueError,TypeError,ZeroDivisionError):pass
        ch,le,_=planform_section(p,p['span']);q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))/100 if elliptical_planform(p) else 0
        axis=p['sweep']+p['root_chord']*q
        if elliptical_planform(p):c.create_line(*xy(0,p['root_chord']*q),*xy(p['span'],axis),dash=(4,3),fill='#94a3b8')
        items=[('root_chord',0,p['root_chord'],'Corda radice'),('tip_chord',p['span'],le+ch,'Bordo uscita'),('span',p['span']+28/scale,le+ch/2,'Apertura'),('sweep',p['span'],le,'Bordo attacco')]
        if elliptical_planform(p):items.append(('ellipse_center_perc',-28/scale,p['root_chord']*q,'Centro ellisse'))
        for key,z,y,label in items:
            x,yy=xy(z,y);self.handles[key]=(x,yy)
            if key=='span':c.create_line(*xy(p['span'],le+ch/2),x,yy,fill='#ea580c',dash=(2,2))
            if key=='ellipse_center_perc':c.create_line(*xy(0,p['root_chord']*q),x,yy,fill='#ea580c',dash=(2,2))
            c.create_oval(x-6,yy-6,x+6,yy+6,fill='#ea580c',outline='white',width=2,tags=('handle',key))
            c.create_text(x+(10 if z==0 else -10),yy-10,text=label,anchor='sw' if z==0 else 'se',fill='#9a3412',font=('Segoe UI',8))
        c.create_text(12,h-40,anchor='w',text=f"Radice a sinistra · estremità a destra · semiala {p['span']:g} mm · corde {p['root_chord']:g} / {p['tip_chord']:g} mm",fill='#334155')
        c.create_text(12,h-19,anchor='w',text='Trascina le maniglie arancioni oppure modifica i campi. Vista nominale, senza washout.',fill='#64748b')

    def press(self,event):
        if getattr(self.app,'generating',False) or self.transform is None:return
        nearest=min(self.handles,key=lambda k:math.hypot(event.x-self.handles[k][0],event.y-self.handles[k][1]),default=None)
        if nearest and math.hypot(event.x-self.handles[nearest][0],event.y-self.handles[nearest][1])<=13:
            self.drag=(nearest,self.parameters(),event.x,event.y)

    def motion(self,event):
        if self.drag is None:return
        key,p,x0,y0=self.drag;scale=self.transform[2];dx=(event.x-x0)/scale;dy=(event.y-y0)/scale
        value=p[key] if key!='ellipse_center_perc' else float(str(p[key]).replace(',','.'))
        if key=='span':value=max(10,value+dx)
        elif key in ('sweep','tip_chord'):
            # Move one endpoint, preserving the absolute position of the other.
            elliptical=elliptical_planform(p)
            q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))/100 if elliptical else 0.
            width=float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.'))
            thick=int(str(p.get('airfoil_tip','2412'))[2:])/100
            minimum=4*width/max(.01,thick)+.1 if elliptical else 5.
            target=p['tip_chord']+(-dy if key=='sweep' else dy)
            chord=max(minimum,min(p['root_chord']-.1,target)) if elliptical else max(minimum,target)
            delta=chord-p['tip_chord']
            sweep=p['sweep']-(1-q)*delta if key=='sweep' else p['sweep']+q*delta
            self.app.vars['tip_chord'].set(f'{chord:.6f}')
            self.app.vars['sweep'].set(f'{sweep:.6f}')
            return
        elif key=='ellipse_center_perc':value=max(0,min(100,value+dy/p['root_chord']*100))
        elif key=='root_chord':value=max(p['tip_chord']+.1 if elliptical_planform(p) else 5,value+dy)
        self.app.vars[key].set(f'{value:.2f}')

    def release(self,event):
        self.drag=None;self.draw()
