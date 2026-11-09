"""Horizontal editable planform shared with manual geometry fields."""
# File revision: 6
import json
import math
import tkinter as tk
from tkinter import messagebox, ttk
from airfoil_editor import AirfoilEditor, LIBRARY_PATH, profile_from_controls
from planform import *

DIMENSIONS=('span','root_chord','tip_chord','sweep','ellipse_center_perc')


def local_slope(edge,fraction):
    a=max(0.,fraction-.0001)
    b=min(1.,fraction+.0001)
    return (edge(b)-edge(a))/(b-a)


def draw_node_tangent(canvas,center,slope,span,scale,lengths):
    x,y=center
    grips={direction:(x+direction*span*scale*length,y+direction*slope*scale*length)
           for direction,length in zip((-1,1),lengths)}
    canvas.create_line(*grips[-1],*grips[1],fill='#7c3aed',width=2)
    for gx,gy in grips.values():
        canvas.create_oval(gx-5,gy-5,gx+5,gy+5,fill='#7c3aed',outline='white',width=2)
    return grips


def move_tangent_handle(nodes,index,center,event,direction,span,scale,base_slope,trailing_end=None):
    points=curve_controls(nodes,trailing_end)
    current=points[index+1]
    dx=max(1e-6,direction*(event.x-center[0]))
    dy=direction*(event.y-center[1])
    slope=span*max(-12.,min(12.,dy/dx))-base_slope
    lengths=list(node_handle_lengths(nodes,index,trailing_end))
    if direction<0:
        previous=points[index]
        width=current[0]-previous[0]
        other=segment_handles(previous,current)[0]
        handle_index=0
    else:
        following=points[index+2]
        width=following[0]-current[0]
        other=segment_handles(current,following)[1]
        handle_index=1
    limit=max(.001*width,.999*width-other)
    lengths[handle_index]=max(.001*width,min(limit,dx/(span*scale)))
    node=nodes[index]
    return (*current[:2],slope,*lengths,*node[5:])


def planform_base_edge(p,side,fraction):
    chord,lead,_=base_planform_section(p,fraction*p['span'])
    return lead+side*chord


def read_dimensions(values):
    p=dict(values)
    for key in ('span','root_chord','tip_chord','sweep'):
        p[key]=float(str(p[key]).replace(',','.'))
        if not math.isfinite(p[key]):raise ValueError('Completa le dimensioni della pianta.')
    if min(p[k] for k in ('span','root_chord','tip_chord'))<=0:raise ValueError('Le dimensioni devono essere positive.')
    planform_parameters(p)
    return p


def handle_changes(p,key,dx,dy):
    elliptical=elliptical_planform(p)
    value=float(str(p[key]).replace(',','.'))
    if key=='span':value=max(10,value+dx)
    elif key in ('sweep','tip_chord'):
        # Move one endpoint while holding the other fixed.
        q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))/100 if elliptical else 0.
        minimum=5.
        if elliptical:
            width=float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.'))
            custom=profile_from_controls(p.get('custom_airfoil_tip',''),80)
            thick=(max(y for _,y in custom)-min(y for _,y in custom)) if custom else int(str(p['airfoil_tip'])[2:])/100
            minimum=min(p['tip_chord'],4*width/max(1e-8,thick)+.001)
        target=p['tip_chord']+(-dy if key=='sweep' else dy)
        chord=max(minimum,min(p['root_chord']-.001,target)) if elliptical else max(minimum,target)
        delta=chord-p['tip_chord']
        sweep=p['sweep']-(1-q)*delta if key=='sweep' else p['sweep']+q*delta
        return {'tip_chord':f'{chord:.6f}','sweep':f'{sweep:.6f}'}
    elif key=='ellipse_center_perc':value=max(0,min(100,value+dy/p['root_chord']*100))
    elif key=='root_chord':value=max(p['tip_chord']+.1 if elliptical else 5,value+dy)
    return {key:f'{value:.2f}'}


class PlanformEditor:
    def __init__(self,app,parent,controls):
        self.app=app;self.drag=None;self.handles={};self.transform=None
        app.vars['planform']=tk.StringVar(value='trapezoidal')
        app.vars['ellipse_center_perc']=tk.StringVar(value='50')
        app.vars['planform_notes']=tk.StringVar()
        app.vars['planform_name']=tk.StringVar()
        app.vars['planform_nodes']=tk.StringVar()
        box=ttk.LabelFrame(controls,text='Pianta alare',padding=6);box.pack(fill='x',pady=6)
        for label,value in (('Trapezoidale','trapezoidal'),('Ellittica','elliptical')):
            ttk.Radiobutton(box,text=label,value=value,variable=app.vars['planform']).pack(side='top',anchor='w')
        row=ttk.Frame(box);row.pack(fill='x',pady=4)
        ttk.Label(row,text='Linea centrale ellisse (% corda)').pack(side='left')
        self.center_entry=ttk.Entry(row,textvariable=app.vars['ellipse_center_perc'],width=7);self.center_entry.pack(side='right')
        self.note=ttk.Label(box,wraplength=360);self.note.pack(fill='x')
        self.tracing_editor=PlanformTracingEditor(app,self)
        ttk.Button(box,text='Editor pianta…',command=self.tracing_editor.open).pack(anchor='w',pady=(6,0))
        self.canvas=tk.Canvas(parent,height=300,background='white',highlightthickness=1,highlightbackground='#cbd5e1')
        self.canvas.pack(fill='x',pady=(0,10))
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        for key in ('planform','ellipse_center_perc','root_chord','tip_chord','span','sweep','airfoil_tip','create_ribs','nervature_specchiate_ala','rib_pitch','rib_angle','planform_nodes'):
            app.vars[key].trace_add('write',self.changed)
        self.changed()

    def parameters(self):
        return read_dimensions({k:v.get().strip() for k,v in self.app.vars.items()})

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
        self.handles=self.draw_outline(c,p,self.transform,w,h)

    @staticmethod
    def draw_outline(c,p,transform,w,h,background=False):
        handles={}
        ox,oy,scale=transform
        def xy(z,y):return ox+z*scale,oy+y*scale
        coords=[v for point in planform_outline(p) for v in xy(*point)]
        c.create_polygon(coords,fill='' if background else '#dbeafe',outline='#2563eb',width=2,tags='planform_outline')
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
            x,yy=xy(z,y);handles[key]=(x,yy)
            if key=='span':c.create_line(*xy(p['span'],le+ch/2),x,yy,fill='#ea580c',dash=(2,2))
            if key=='ellipse_center_perc':c.create_line(*xy(0,p['root_chord']*q),x,yy,fill='#ea580c',dash=(2,2))
            c.create_oval(x-6,yy-6,x+6,yy+6,fill='#ea580c',outline='white',width=2,tags=('handle',key))
            c.create_text(x+(10 if z==0 else -10),yy-10,text=label,anchor='sw' if z==0 else 'se',fill='#9a3412',font=('Segoe UI',8))
        c.create_text(12,h-40,anchor='w',text=f"Radice a sinistra · estremità a destra · semiala {p['span']:g} mm · corde {p['root_chord']:g} / {p['tip_chord']:g} mm",fill='#334155')
        c.create_text(12,h-19,anchor='w',text='Trascina le maniglie arancioni oppure modifica i campi. Vista nominale, senza washout.',fill='#64748b')
        return handles

    def press(self,event):
        if getattr(self.app,'generating',False) or self.transform is None:return
        nearest=min(self.handles,key=lambda k:math.hypot(event.x-self.handles[k][0],event.y-self.handles[k][1]),default=None)
        if nearest and math.hypot(event.x-self.handles[nearest][0],event.y-self.handles[nearest][1])<=13:
            self.drag=(nearest,self.parameters(),event.x,event.y)

    def motion(self,event):
        if self.drag is None:return
        key,p,x0,y0=self.drag;scale=self.transform[2];dx=(event.x-x0)/scale;dy=(event.y-y0)/scale
        for name,value in handle_changes(p,key,dx,dy).items():
            self.app.vars[name].set(value)

    def release(self,event):
        self.drag=None;self.draw()


class PlanformTracingEditor(AirfoilEditor):
    library_label='Libreria piante'
    save_label='Salva pianta'
    name_label='Nome della pianta:'
    replace_label='Sostituire la pianta già salvata?'
    saved_label='Pianta salvata nella libreria.'
    notes_label='Note della pianta'
    geometry_label='Pianta alare'
    edit_label='Modifica pianta'
    reset_label='Ripristina pianta iniziale'
    image_title='Importa immagine della pianta'
    edit_status='Rotella e trascinamento spostano la vista. Con Maiusc agiscono solo sullo sfondo. Tasto destro sul bordo blu per aggiungere un nodo.'
    modes={'trapezoidal':'Trapezoidale','elliptical':'Ellittica'}

    def __init__(self,app,owner):
        super().__init__(app,'planform')
        self.owner=owner
        self.preferences_path=LIBRARY_PATH.with_name('planform_editor.json')
        self.library_path=LIBRARY_PATH.with_name('planform_library.json')

    def editor_title(self):
        return 'Editor pianta alare'

    def build_geometry_controls(self):
        bar=ttk.Frame(self.window,padding=(8,4))
        bar.pack(fill='x')
        labels=('Semiala (mm)','Corda radice (mm)','Corda estremità (mm)','Freccia (mm)','Centro ellisse (%)')
        self.fields={}
        self.handles={}
        self.selected_node=None
        self.tangent_grips={}
        self.last_view=None
        self.view_zoom=1.
        self.view_offset=(0.,0.)
        self.view_drag=None
        self.editing_fields=False
        for index,(key,label) in enumerate(zip(DIMENSIONS,labels)):
            bar.columnconfigure(index,weight=1)
            ttk.Label(bar,text=label).grid(row=0,column=index,sticky='w',padx=3)
            value=self.fields[key]=tk.StringVar()
            entry=ttk.Entry(bar,textvariable=value,width=10)
            entry.grid(row=1,column=index,sticky='ew',padx=3)
            value.trace_add('write',self.fields_changed)
            if key=='ellipse_center_perc':self.center_field=entry

    def fields_changed(self,*_):
        if not self.editing_fields:self.draw()

    def set_fields(self,values):
        self.editing_fields=True
        try:
            for key,value in values.items():self.fields[key].set(value)
        finally:self.editing_fields=False

    def load_current(self):
        self.initial_mode=self.app.vars['planform'].get()
        self.initial_values={key:self.app.vars[key].get() for key in DIMENSIONS}
        self.initial_name=self.app.vars['planform_name'].get()
        self.initial_notes=self.app.vars['planform_notes'].get()
        self.initial_nodes=self.app.vars['planform_nodes'].get()
        self.reset_geometry(redraw=False)

    def set_geometry(self,mode,values,name='',notes='',nodes=''):
        if mode not in self.modes or set(values)!=set(DIMENSIONS):
            raise ValueError('Pianta salvata non valida.')
        planform_nodes(nodes)
        self.nodes=nodes
        self.selected_node=None
        self.code=mode
        self.set_fields(values)
        self.profile_name=name
        self.notes.delete('1.0','end')
        self.notes.insert('1.0',notes)
        self.center_field.configure(state='normal' if mode=='elliptical' else 'disabled')

    def default_choice(self):
        return self.app.tr(self.modes[self.code])

    def update_choices(self):
        self.library_choices={f'★ {name}':name for name in sorted(self.library,key=str.casefold)}
        self.mode_choices={self.app.tr(label):mode for mode,label in self.modes.items()}
        self.picker.configure(values=[*self.mode_choices,*self.library_choices])

    def select_profile(self,_event=None):
        selected=self.profile_choice.get()
        try:
            if selected in self.library_choices:
                saved=self.library[self.library_choices[selected]]
                data=json.loads(saved['profile'])
                self.set_geometry(saved['code'],data['dimensions'],data['name'],data['notes'],data.get('nodes',''))
            else:
                self.set_geometry(self.mode_choices[selected],{key:v.get() for key,v in self.fields.items()},
                    notes=self.notes.get('1.0','end-1c'),nodes=self.nodes)
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            messagebox.showerror(self.geometry_label,str(exc),parent=self.window)
            return
        self.set_mode('edit')

    def reset_geometry(self,redraw=True):
        self.set_geometry(self.initial_mode,self.initial_values,self.initial_name,self.initial_notes,self.initial_nodes)
        if redraw:
            self.profile_choice.set(f'★ {self.profile_name}' if self.profile_name in self.library else self.default_choice())
            self.set_mode('edit')

    def parameters(self):
        values={key:var.get() for key,var in self.app.vars.items()}
        values.update({key:var.get() for key,var in self.fields.items()})
        values['planform']=self.code
        values['planform_nodes']=self.nodes
        return read_dimensions(values)

    def raw_profile(self):
        self.parameters()
        notes=self.notes.get('1.0','end-1c')
        if len(notes)>2000:raise ValueError('Le note della pianta possono contenere al massimo 2000 caratteri.')
        return json.dumps(dict(dimensions={key:var.get() for key,var in self.fields.items()},
            name=self.profile_name,notes=notes,nodes=self.nodes),ensure_ascii=False)

    def apply_profile(self,raw):
        data=json.loads(raw)
        self.app.loading_configuration=True
        try:
            for key,value in data['dimensions'].items():self.app.vars[key].set(value)
            self.app.vars['planform'].set(self.code)
            self.app.vars['planform_name'].set(data['name'])
            self.app.vars['planform_notes'].set(data['notes'])
            self.app.vars['planform_nodes'].set(data['nodes'])
        finally:self.app.loading_configuration=False
        self.app._refresh_configuration_views()

    def chord(self):
        # This editor's drawing coordinates are already in millimetres.
        return 1.

    def calibration_default(self):
        try:return self.parameters()['span']
        except (ValueError,TypeError,IndexError):return 100.

    def transform(self):
        if self.drag is not None:return self.drag[-1]
        w=max(500,self.canvas.winfo_width())
        h=max(360,self.canvas.winfo_height())
        try:
            p=self.parameters()
            ys=[y for _,y in planform_outline(p)]
            scale=min((w-170)/p['span'],(h-110)/max(1,max(ys)-min(ys)))
            self.last_view=(80,52-min(ys)*scale,scale)
        except (ValueError,TypeError,IndexError):
            pass
        ox,oy,scale=self.last_view or (80,52,1.)
        dx,dy=self.view_offset
        return ox*self.view_zoom+dx,oy*self.view_zoom+dy,scale*self.view_zoom

    def zoom_image(self,event):
        if any(drag is not None for drag in (self.drag,self.view_drag,self.image_drag,
                                             self.rotation_drag,self.pivot_drag)):
            return 'break'
        if event.state & 0x0001:  # Tk Shift modifier
            return super().zoom_image(event)
        steps=max(-10.,min(10.,event.delta/120))
        zoom=max(.2,min(12.,self.view_zoom*1.2**steps))
        ratio=zoom/self.view_zoom
        x,y=self.view_offset
        self.view_offset=(event.x+(x-event.x)*ratio,event.y+(y-event.y)*ratio)
        self.view_zoom=zoom
        self.draw()
        return 'break'

    def reset_view(self):
        self.release(None)
        self.view_zoom=1.
        self.view_offset=(0.,0.)
        self.draw()

    def draw_geometry(self,w,h):
        self.tangent_grips={}
        try:p=self.parameters()
        except (ValueError,TypeError,IndexError) as exc:
            self.handles={}
            self.canvas.create_text(18,25,text=str(exc),anchor='nw',width=max(250,w-36),fill='#b91c1c')
            return
        self.handles=self.owner.draw_outline(self.canvas,p,self.transform(),w,h,background=self.image is not None)
        ox,oy,scale=self.transform()
        edges=planform_nodes(self.nodes)
        trailing_end=trailing_end_settings(self.nodes)
        for side,nodes in enumerate(edges):
            for index,node in enumerate(nodes):
                fraction,offset=node[:2]
                z=fraction*p['span']
                chord,leading,_=base_planform_section(p,z)
                x,y=ox+z*scale,oy+(leading+side*chord+offset)*scale
                self.handles[(side,index)]=(x,y)
                self.canvas.create_oval(x-6,y-6,x+6,y+6,fill='#2563eb',outline='white',width=2)
        if self.selected_node=='tip_chord' and edges[1]:
            points=curve_controls(edges[1],trailing_end)
            length=segment_handles(points[-2],points[-1])[1]
            slope=local_slope(lambda f:planform_base_edge(p,1,f),1.)+points[-1][2]
            x,y=self.handles['tip_chord']
            gx,gy=x-p['span']*scale*length,y-slope*scale*length
            self.canvas.create_line(x,y,gx,gy,fill='#7c3aed',width=2)
            self.canvas.create_oval(gx-5,gy-5,gx+5,gy+5,fill='#7c3aed',outline='white',width=2)
            self.tangent_grips={-1:(gx,gy)}
        elif isinstance(self.selected_node,tuple) and self.selected_node in self.handles:
            side,index=self.selected_node
            nodes=edges[side]
            end=trailing_end if side==1 else None
            fraction=nodes[index][0]
            slope=local_slope(lambda f:planform_base_edge(p,side,f),fraction)+curve_offset(nodes,fraction,end)[1]
            self.tangent_grips=draw_node_tangent(self.canvas,self.handles[self.selected_node],slope,
                                                p['span'],scale,node_handle_lengths(nodes,index,end))

    def add_geometry_menu(self,menu,event):
        menu.add_command(label=self.app.tr('Ripristina vista'),command=self.reset_view)
        if trailing_end_settings(self.nodes):
            menu.add_command(label=self.app.tr('Tangente terminale automatica'),
                             command=lambda:self.set_nodes(planform_nodes(self.nodes),()))
        target=(event.x,event.y)
        node=min((key for key in self.handles if isinstance(key,tuple)),
                 key=lambda key:math.dist(target,self.handles[key]),default=None)
        if node is not None and math.dist(target,self.handles[node])<=12:
            menu.add_separator()
            menu.add_command(label=self.app.tr('Elimina nodo'),command=lambda:self.delete_node(node))
            return
        hit=self.edge_hit(target)
        if hit is not None:
            menu.add_separator()
            menu.add_command(label=self.app.tr('Inserisci nodo'),command=lambda:self.insert_node(*hit))

    def edge_hit(self,target):
        try:p=self.parameters()
        except (ValueError,TypeError,IndexError):return None
        outline=planform_outline(p)
        ox,oy,scale=self.transform()
        best=(12.,None)
        for side,edge in enumerate((outline[:len(outline)//2],outline[len(outline)//2:])):
            for (za,ya),(zb,yb) in zip(edge,edge[1:]):
                a=(ox+za*scale,oy+ya*scale)
                dx,dy=(zb-za)*scale,(yb-ya)*scale
                t=max(0.,min(1.,((target[0]-a[0])*dx+(target[1]-a[1])*dy)/(dx*dx+dy*dy)))
                distance=math.dist(target,(a[0]+t*dx,a[1]+t*dy))
                fraction=(za+(zb-za)*t)/p['span']
                nodes=planform_nodes(self.nodes)[side]
                if distance<best[0] and len(nodes)<64 and all(abs(fraction-f)>.001 for f in (0.,1.,*(node[0] for node in nodes))):
                    best=(distance,(side,fraction))
        return best[1]

    def set_nodes(self,nodes,trailing_end=None):
        previous=self.nodes
        values=dict(zip(PLANFORM_EDGES,nodes))
        end=trailing_end_settings(previous) if trailing_end is None else trailing_end
        if end and nodes[1]:values['trailing_end']=end
        self.nodes=json.dumps(values,separators=(',',':')) if any(nodes) else ''
        try:self.parameters()
        except (ValueError,TypeError,IndexError) as exc:
            self.nodes=previous
            self.status.set(str(exc))
            return
        self.draw()

    def insert_node(self,side,fraction):
        nodes=[list(edge) for edge in planform_nodes(self.nodes)]
        end=trailing_end_settings(self.nodes) if side==1 else None
        split_final=side==1 and nodes[1] and fraction>nodes[1][-1][0]
        slope=curve_controls(nodes[1],end)[-1][2] if split_final else None
        nodes[side]=insert_curve_node(nodes[side],fraction,end)
        self.selected_node=(side,next(i for i,node in enumerate(nodes[side]) if node[0]==fraction))
        self.set_nodes(nodes,(slope,nodes[1][-1][6]) if split_final else end)

    def delete_node(self,node):
        side,index=node
        nodes=[list(edge) for edge in planform_nodes(self.nodes)]
        del nodes[side][index]
        self.selected_node=None
        self.set_nodes(nodes)

    def press(self,event):
        if self.mode!='edit' or event.state & 0x0001:
            super().press(event)
        elif not self.press_geometry(event):
            self.view_drag=(event.x,event.y,*self.view_offset)

    def motion(self,event):
        if self.view_drag is None:
            super().motion(event)
            return
        x,y,dx,dy=self.view_drag
        self.view_offset=(dx+event.x-x,dy+event.y-y)
        self.draw()

    def press_geometry(self,event):
        if event.state & 0x0001:return False
        for direction,grip in self.tangent_grips.items():
            distance=math.dist((event.x,event.y),grip)
            if distance<=10 and distance<math.dist((event.x,event.y),self.handles[self.selected_node]):
                self.drag=(('tangent',self.selected_node,direction),self.parameters(),event.x,event.y,self.transform())
                return True
        nearest=min(self.handles,key=lambda k:math.dist((event.x,event.y),self.handles[k]),default=None)
        if nearest is None or math.dist((event.x,event.y),self.handles[nearest])>13:return False
        self.selected_node=nearest if isinstance(nearest,tuple) or nearest=='tip_chord' else None
        self.drag=(nearest,self.parameters(),event.x,event.y,self.transform())
        self.draw()
        return True

    def motion_geometry(self,event):
        key,p,x,y,view=self.drag
        scale=view[2]
        if isinstance(key,tuple):
            if key[0]=='tangent':
                _,selected,direction=key
                if selected=='tip_chord':
                    nodes=planform_nodes(p.get('planform_nodes',''))
                    cx,cy=self.handles[selected]
                    width=1-nodes[1][-1][0]
                    dx=max(1.,cx-event.x)
                    length=max(.001*width,min(.95*width,dx/(scale*p['span'])))
                    base=local_slope(lambda f:planform_base_edge(p,1,f),1.)
                    slope=p['span']*max(-12.,min(12.,(cy-event.y)/dx))-base
                    self.set_nodes(nodes,(slope,length))
                    return
                side,index=selected
                nodes=[list(edge) for edge in planform_nodes(p.get('planform_nodes',''))]
                fraction=nodes[side][index][0]
                base=local_slope(lambda f:planform_base_edge(p,side,f),fraction)
                end=trailing_end_settings(self.nodes) if side==1 else None
                nodes[side][index]=move_tangent_handle(nodes[side],index,self.handles[selected],event,direction,p['span'],scale,base,end)
                self.set_nodes(nodes)
                return
            side,index=key
            nodes=[list(edge) for edge in planform_nodes(p.get('planform_nodes',''))]
            fraction,offset,*tangent=nodes[side][index]
            original_chord,original_lead,_=base_planform_section(p,fraction*p['span'])
            lower=nodes[side][index-1][0] if index else 0.
            upper=nodes[side][index+1][0] if index+1<len(nodes[side]) else 1.
            fraction=max(lower+.0001,min(upper-.0001,fraction+(event.x-x)/scale/p['span']))
            chord,lead,_=base_planform_section(p,fraction*p['span'])
            nodes[side][index]=(fraction,offset+original_lead+side*original_chord+(event.y-y)/scale-lead-side*chord,*tangent)
            self.set_nodes(nodes)
            return
        self.set_fields(handle_changes(p,key,(event.x-x)/scale,(event.y-y)/scale))
        self.draw()

    def release(self,event):
        refit=self.drag is not None
        self.view_drag=None
        super().release(event)
        if refit:self.draw()
