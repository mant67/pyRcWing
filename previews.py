"""Anteprime 2D leggere del wizard; nessuna modifica ai solidi esportati."""
# File revision: 7
import math
import tkinter as tk
from tkinter import messagebox, ttk
from airfoil_editor import AirfoilEditor, read_preferences
from core import *
from planform import PLANFORM_EDGES, insert_curve_node, node_handle_lengths, with_node_stations
from planform_ui import draw_node_tangent, local_slope, move_tangent_handle
from sections import section_preview, clip_polygon
from tip_ui import TipEditor
from spars_ui import SparEditor
from aileron_ui import AileronEditor, HorizontalView
from slots_ui import SlotsPreview


class View:
    def __init__(self,canvas,rect,bounds):
        self.canvas=canvas;self.rect=rect;self.bounds=bounds
        left,top,right,bottom=rect;x0,x1,z0,z1=bounds
        self.scale=min((right-left)/max(x1-x0,1e-6),(bottom-top)/max(z1-z0,1e-6))
        self.ox=(left+right)/2-(x0+x1)*self.scale/2
        self.oy=(top+bottom)/2+(z0+z1)*self.scale/2

    def xy(self,x,z):return self.ox+x*self.scale,self.oy-z*self.scale

    def coords(self,points):return [v for p in points for v in self.xy(*p)]

    def polygon(self,points,**kwargs):
        if len(points)>=3:return self.canvas.create_polygon(*self.coords(points),**kwargs)

    def line(self,points,**kwargs):
        if len(points)>=2:return self.canvas.create_line(*self.coords(points),**kwargs)

    def text(self,x,z,text,**kwargs):return self.canvas.create_text(*self.xy(x,z),text=text,**kwargs)


class ComponentTracingEditor(AirfoilEditor):
    """Component handles over the saved planform background, in millimetres."""
    def __init__(self,owner,key):
        super().__init__(owner.app,key)
        self.owner=owner
        self.key=key
        self.note=owner.note

    def open(self):
        if self.app.generating:return
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return
        self.image=None
        self.photo=None
        self.photo_key=None
        title='Editor punta alare' if self.key=='tip' else 'Editor alettone'
        self.window=tk.Toplevel(self.app)
        self.window.title(self.app.tr(title))
        self.window.geometry('940x700')
        self.window.minsize(640,430)
        self.window.transient(self.app)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Escape>',lambda _event:self.close())
        bar=ttk.Frame(self.window,padding=8)
        bar.pack(fill='x')
        ttk.Label(bar,text='Sfondo condiviso da Geometria. Trascina le maniglie per modificare il componente.').pack(side='left')
        ttk.Button(bar,text='Chiudi e applica',command=self.close).pack(side='right')
        self.canvas=tk.Canvas(self.window,background='white',highlightthickness=1,highlightbackground='#94a3b8')
        self.canvas.pack(fill='both',expand=True,padx=10,pady=(0,10))
        editor_class=TipEditor if self.key=='tip' else AileronEditor
        self.editor=editor_class(self,canvas=self.canvas)
        self.trace_view=None
        self.view_zoom=1.
        self.view_offset=(0.,0.)
        self.view_drag=None
        self.node_handles={}
        self.node_edges=[]
        self.node_drag=None
        self.selected_node=None
        self.tangent_grips={}
        self.node_key=f'{self.key}_nodes'
        self.image_menu=tk.Menu(self.window,tearoff=False)
        self.canvas.bind('<Button-3>',self.show_image_menu)
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<MouseWheel>',self.zoom_view)
        try:
            path=self.app.planform_editor.tracing_editor.preferences_path
            background=read_preferences(path).get('background')
            if background:self.restore_background(background)
        except FileNotFoundError:
            pass
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
            messagebox.showwarning('Immagine',str(exc),parent=self.window)
        self.image_locked=True
        self.canvas.bind('<Configure>',lambda _event:self.draw())
        self.window.grab_set()
        self.draw()

    def close(self):
        self.window.destroy()
        self.owner.draw(self.key)
        self.app.refresh_summary()

    def chord(self):
        return 1.

    def params(self):
        return self.owner.params()

    def transform(self):
        return self.trace_view.ox,self.trace_view.oy,self.trace_view.scale

    def draw(self,_key=None):
        c=self.canvas
        c.delete('all')
        self.editor.handles={}
        self.node_handles={}
        self.node_edges=[]
        self.tangent_grips={}
        w=max(640,c.winfo_width())
        h=max(380,c.winfo_height())
        try:
            p=self.params()
            edges=self.component_edges(p)
            if (self.editor.drag is None and self.node_drag is None) or self.trace_view is None:
                outline=[(x,z) for z,x in planform_outline(p)]
                outline.extend((x,z) for edge in edges for _,x,z in edge)
                if p['elliptical_tip']:
                    chord,lead,_=planform_section(p,p['span'])
                    outline.append((lead+chord*tip_center_percentage(p)/100,p['span']+p['tip_length']))
                self.trace_view=HorizontalView((64,68,w-55,h-65),outline)
                self.trace_view.ox=self.trace_view.ox*self.view_zoom+self.view_offset[0]
                self.trace_view.oy=self.trace_view.oy*self.view_zoom+self.view_offset[1]
                self.trace_view.scale*=self.view_zoom
            self.draw_background(c.winfo_width(),c.winfo_height())
            self.editor.draw(c,p,w,h,trace_view=self.trace_view)
            self.node_edges=edges
            if self.key=='aileron' and edges:
                c.create_line(*[value for _,x,z in edges[0] for value in self.trace_view.xy(x,z)],
                              fill='#c2410c',width=2,tags='aileron_editable_edge')
            for side,nodes in enumerate(planform_nodes(p.get(self.node_key,''))):
                if side>=len(edges):break
                for index,node in enumerate(nodes):
                    fraction=node[0]
                    point=min(edges[side],key=lambda point:abs(point[0]-fraction))
                    x,y=self.trace_view.xy(*point[1:])
                    self.node_handles[(side,index)]=(x,y)
                    c.create_oval(x-6,y-6,x+6,y+6,fill='#ea580c',outline='#fff',width=2)
            if self.key=='tip' and self.selected_node in self.node_handles:
                side,index=self.selected_node
                nodes=planform_nodes(p.get(self.node_key,''))[side]
                fraction=nodes[index][0]
                base=local_slope(lambda f:self.tip_base_edge(p,side,f),fraction)
                slope=base+curve_offset(nodes,fraction)[1]
                self.tangent_grips=draw_node_tangent(c,self.node_handles[self.selected_node],slope,
                    p['tip_length'],self.trace_view.scale,node_handle_lengths(nodes,index))
        except (ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError) as exc:
            self.note(c,16,48,str(exc),w-32,color='#b91c1c')

    def component_edges(self,p):
        if self.key=='tip':
            if not p['elliptical_tip']:return []
            edges=[[],[]]
            for fraction,_ in smooth_tip_sections(p):
                xy=smooth_tip_profile(p,fraction,points=80)
                z=p['span']+p['tip_length']*fraction
                xs=[x for x,_ in xy]
                for edge,x in zip(edges,(min(xs),max(xs))):edge.append((fraction,x,z))
            return edges
        a=aileron_parameters(p)
        if not a:return []
        hinge,_=aileron_hinge(p,a)
        start=a['inizio_alettone'];length=a['lunghezza_alettone']
        bounds=aileron_axial_bounds(a)
        nodes=planform_nodes(p.get(self.node_key,''))[0]
        levels={bounds['part_start'],bounds['part_end'],*(start+node[0]*length for node in nodes)}
        return [[((z-start)/length,hinge(z)[0]+a['gioco_alettone']/2,z) for z in sorted(levels)]]

    def nearest_node(self,target):
        key=min(self.node_handles,key=lambda k:math.dist(target,self.node_handles[k]),default=None)
        return key if key is not None and math.dist(target,self.node_handles[key])<=12 else None

    def edge_hit(self,target):
        nodes=planform_nodes(self.app.vars[self.node_key].get())
        best=(12.,None)
        for side,edge in enumerate(self.node_edges):
            if len(nodes[side])>=64:continue
            for (f,x,z),(g,u,v) in zip(edge,edge[1:]):
                a=self.trace_view.xy(x,z);b=self.trace_view.xy(u,v)
                dx,dy=b[0]-a[0],b[1]-a[1]
                norm=dx*dx+dy*dy
                if not norm:continue
                t=max(0.,min(1.,((target[0]-a[0])*dx+(target[1]-a[1])*dy)/norm))
                distance=math.dist(target,(a[0]+dx*t,a[1]+dy*t))
                fraction=f+(g-f)*t
                existing=(0.,1.,*(node[0] for node in nodes[side]))
                if distance<best[0] and 0<fraction<1 and all(abs(fraction-v)>.001 for v in existing):
                    best=(distance,(side,fraction))
        return best[1]

    def show_image_menu(self,event):
        menu=self.image_menu
        menu.delete(0,'end')
        for label in ('Carica immagine…','Sblocca sfondo','Ruota','Calibra','Rimuovi immagine',
                      'Modifica pianta','Ripristina pianta iniziale'):
            menu.add_command(label=self.app.tr(label),state='disabled')
        menu.add_separator()
        menu.add_command(label=self.app.tr('Ripristina vista'),command=self.reset_view)
        menu.add_separator()
        target=event.x,event.y
        node=self.nearest_node(target)
        hit=self.edge_hit(target) if node is None else None
        menu.add_command(label=self.app.tr('Inserisci nodo'),state='normal' if hit else 'disabled',
                         command=lambda:self.insert_node(*hit))
        menu.add_command(label=self.app.tr('Elimina nodo'),state='normal' if node is not None else 'disabled',
                         command=lambda:self.delete_node(node))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def save_nodes(self,nodes):
        raw=json.dumps(dict(zip(PLANFORM_EDGES,nodes)),separators=(',',':')) if any(nodes) else ''
        p=dict(self.params(),**{self.node_key:raw})
        try:
            if self.key=='tip':
                for fraction,_ in smooth_tip_sections(p):smooth_tip_profile(p,fraction,points=80)
            else:aileron_hinge(p,aileron_parameters(p))
        except ValueError as exc:
            self.canvas.delete('node_error')
            self.canvas.create_text(16,42,anchor='nw',text=str(exc),fill='#b91c1c',tags='node_error')
            return
        self.app.vars[self.node_key].set(raw)
        self.draw()

    def insert_node(self,side,fraction):
        nodes=[list(edge) for edge in planform_nodes(self.app.vars[self.node_key].get())]
        if self.key=='tip':
            nodes[side]=insert_curve_node(nodes[side],fraction)
            self.selected_node=(side,next(i for i,node in enumerate(nodes[side]) if node[0]==fraction))
        else:
            nodes[side].append((fraction,edge_offset(nodes[side],fraction)))
            nodes[side].sort()
        self.save_nodes(nodes)

    def delete_node(self,node):
        nodes=[list(edge) for edge in planform_nodes(self.app.vars[self.node_key].get())]
        side,index=node
        del nodes[side][index]
        self.selected_node=None
        self.save_nodes(nodes)

    def zoom_view(self,event):
        if self.view_drag is not None or self.node_drag is not None or self.editor.drag is not None:
            return
        steps=max(-10.,min(10.,event.delta/120))
        zoom=max(.2,min(12.,self.view_zoom*1.2**steps))
        ratio=zoom/self.view_zoom
        x,y=self.view_offset
        self.view_offset=(event.x+(x-event.x)*ratio,event.y+(y-event.y)*ratio)
        self.view_zoom=zoom
        self.draw()

    def reset_view(self):
        self.view_zoom=1.
        self.view_offset=(0.,0.)
        self.draw()

    def press(self,event):
        for direction,grip in self.tangent_grips.items():
            distance=math.dist((event.x,event.y),grip)
            if distance<=10 and distance<math.dist((event.x,event.y),self.node_handles[self.selected_node]):
                p=self.params()
                self.node_drag=(('tangent',self.selected_node,direction),event.x,event.y,p,planform_nodes(p.get(self.node_key,'')))
                return
        node=self.nearest_node((event.x,event.y))
        if node is None:
            self.editor.press(event)
            if self.editor.drag is None:
                self.view_drag=(event.x,event.y,*self.view_offset)
            return
        p=self.params()
        self.selected_node=node
        self.node_drag=(node,event.x,event.y,p,planform_nodes(p.get(self.node_key,'')))
        self.draw()

    @staticmethod
    def tip_base_edge(p,side,fraction):
        xs=[x for x,_ in base_smooth_tip_profile(p,fraction,points=80)]
        return max(xs) if side else min(xs)

    def motion(self,event):
        if self.view_drag is not None:
            x,y,offset_x,offset_y=self.view_drag
            self.view_offset=(offset_x+event.x-x,offset_y+event.y-y)
            self.draw()
            return
        if self.node_drag is None:
            self.editor.motion(event)
            return
        key,x,y,p,original=self.node_drag
        nodes=[list(edge) for edge in original]
        if key[0]=='tangent':
            _,selected,direction=key
            side,index=selected
            fraction=nodes[side][index][0]
            base=local_slope(lambda f:self.tip_base_edge(p,side,f),fraction)
            nodes[side][index]=move_tangent_handle(nodes[side],index,self.node_handles[selected],
                event,direction,p['tip_length'],self.trace_view.scale,base)
            self.save_nodes(nodes)
            return
        side,index=key
        fraction,offset,*tangent=nodes[side][index]
        scale=self.trace_view.scale
        if self.key=='tip':
            length=p['tip_length']
            def baseline(f):return self.tip_base_edge(p,side,f)
        else:
            a=aileron_parameters(p);start,length=a['inizio_alettone'],a['lunghezza_alettone']
            hinge,_=aileron_hinge(dict(p,aileron_nodes=''),a)
            def baseline(f):return hinge(start+length*f)[0]
        low=nodes[side][index-1][0] if index else 0.
        high=nodes[side][index+1][0] if index+1<len(nodes[side]) else 1.
        f=max(low+.0001,min(high-.0001,fraction+(event.x-x)/scale/length))
        nodes[side][index]=(f,offset+baseline(fraction)-baseline(f)+(event.y-y)/scale,*tangent)
        self.save_nodes(nodes)

    def release(self,event):
        if self.view_drag is not None:
            self.view_drag=None
        elif self.node_drag is not None:
            self.node_drag=None
            self.draw()
        else:self.editor.release(event)


class WizardPreviews:
    def __init__(self,app):
        self.app=app;self.canvases={};self.pending=None;self.traced=set();self.last_error={}
        for key,index in (('tip',3),('spars',4),('aileron',5),('slots',6),('summary',10)):
            canvas=tk.Canvas(app.pages[index],height=320 if key in ('tip','spars') else 570 if key=='slots' else 480 if key=='aileron' else 280,background='white',highlightthickness=1,highlightbackground='#cbd5e1')
            options=dict(fill='x',pady=(10,6))
            if key=='summary':options['before']=app.export_button.master
            canvas.pack(**options);self.canvases[key]=canvas
        self.canvases['connector']=app.connector_preview_canvas
        for key,canvas in self.canvases.items():canvas.bind('<Configure>',lambda event,k=key:self.draw(k))
        self.tip_editor=TipEditor(self)
        self.spar_editor=SparEditor(self)
        self.aileron_editor=AileronEditor(self)
        self.component_tracers={}
        for key,index,label in (('tip',3,'Editor punta…'),('aileron',5,'Editor alettone…')):
            tracer=ComponentTracingEditor(self,key)
            self.component_tracers[key]=tracer
            ttk.Button(app.pages[index],text=label,command=tracer.open).pack(
                anchor='w',pady=(6,0),before=self.canvases[key])
        self.slots_preview=SlotsPreview(self)
        self.sync_traces()

    def sync_traces(self):
        variables=list(self.app.vars.values())+list(self.app.connector_vars.values())
        variables.extend((self.app.spar_count,self.app.spar_clearance))
        variables.extend(v for row in self.app.spar_rows for v in row.values())
        for var in variables:
            key=str(var)
            if key not in self.traced:
                var.trace_add('write',lambda *_:self.schedule());self.traced.add(key)

    def schedule(self):
        if getattr(self.app,"loading_configuration",False):return
        if self.pending is not None:self.app.after_cancel(self.pending)
        self.pending=self.app.after(160,self.redraw_visible)

    def redraw_visible(self):
        self.pending=None
        key={3:'tip',4:'spars',5:'aileron',6:'slots',8:'connector',10:'summary'}.get(self.app.step_index)
        if key:self.draw(key)

    def params(self):
        p={k:v.get().strip() for k,v in self.app.vars.items()}
        for key in ('span','root_chord','tip_chord','sweep','line_width'):
            p[key]=float(p[key].replace(',','.'))
            if not math.isfinite(p[key]):raise ValueError('Completa i valori numerici della geometria.')
        if min(p[k] for k in ('span','root_chord','tip_chord','line_width'))<=0:raise ValueError('Le dimensioni devono essere positive.')
        for key in ('points','stations'):p[key]=int(p[key])
        if p['points']<20 or p['stations']<8:raise ValueError('Usa almeno 20 punti e 8 stazioni.')
        for key,default in (('rib_pitch',40.),('rib_angle',45.)):
            p[key]=float(p[key].replace(',','.')) if wing_ribs_enabled(p) else default
        p['skin']=p['rib_thickness']=p['line_width'];airfoil_tip_code(p)
        p['elliptical_tip'],p['tip_length']=tip_parameters(p);washout_parameters(p)
        return p

    def draw(self,key):
        canvas=self.canvases[key];canvas.delete('all');self.last_error.pop(key,None)
        if key=='tip':self.tip_editor.handles={}
        if key=='spars':self.spar_editor.handles={}
        if key=='aileron':self.aileron_editor.handles={}
        width=max(280,canvas.winfo_width());height=int(canvas.cget('height'))
        try:
            p=self.params();getattr(self,'draw_'+key)(canvas,p,width,height)
        except (ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError) as exc:
            canvas.delete('all');self.last_error[key]=str(exc)
            if key=='tip':self.tip_editor.view=None
            if key=='spars':self.spar_editor.view=None
            if key=='aileron':self.aileron_editor.view=None
            canvas.create_text(18,22,anchor='nw',text=str(exc),width=width-36,fill='#b91c1c',tags='preview_error')

    @staticmethod
    def note(canvas,x,y,text,width=350,color='#475569'):
        canvas.create_text(x,y,anchor='nw',text=text,width=max(100,width),fill=color,font=('Segoe UI',9),tags='annotation')

    def outline(self,p):
        high=dict(p,points=80);rings=[]
        for z in with_node_stations(p,[p['span']*i/24 for i in range(25)]):
            ch,lead,_=planform_section(p,z)
            rings.append((z,[(lead+x*ch,y*ch) for x,y in section_profile(high,z)]))
        if p['elliptical_tip']:
            for f,_ in smooth_tip_sections(p)[1:]:rings.append((p['span']+p['tip_length']*f,smooth_tip_profile(high,f)))
        edges=[]
        for z,profile in rings:
            xs=[washout_point(p,(x,y,z))[0] for x,y in profile]
            edges.append((min(xs),max(xs),z))
        return [(a,z) for a,b,z in edges]+[(b,z) for a,b,z in reversed(edges)]

    def plan(self,canvas,p,rect):
        outline=self.outline(p);xs=[x for x,z in outline];zs=[z for x,z in outline]
        view=View(canvas,rect,(min(xs)-4,max(xs)+4,-4,max(zs)+4))
        view.polygon(outline,fill='#e2e8f0',outline='#64748b',tags='wing')
        view.text(min(xs),0,'Radice',anchor='ne',fill='#64748b',font=('Segoe UI',8))
        view.text(min(xs),max(zs),'Z ↑',anchor='se',fill='#64748b',font=('Segoe UI',8))
        return view,outline

    def profile_view(self,canvas,points,rect,color='#2563eb'):
        xs=[x for x,y in points];ys=[y for x,y in points]
        view=View(canvas,rect,(min(xs)-2,max(xs)+2,min(ys)-4,max(ys)+4))
        view.polygon(points,fill='#eff6ff',outline=color,tags='section')
        return view

    @staticmethod
    def hinge(p,a,z):
        ends=[]
        for zz,width in ((a['inizio_alettone'],a['larghezza_alettone_radice']),(a['inizio_alettone']+a['lunghezza_alettone'],a['larghezza_alettone_estremita'])):
            ch,lead,_=wing_section_at(p,zz);x=lead+ch-width;ends.append((x,upper_surface_at(p,zz,x)))
        t=(z-a['inizio_alettone'])/a['lunghezza_alettone']
        return tuple(x+(y-x)*t for x,y in zip(*ends))

    def draw_tip(self,c,p,w,h):
        self.tip_editor.draw(c,p,w,h)

    def draw_spars(self,c,p,w,h):
        self.spar_editor.draw(c,p,w,h)

    def aileron_plan(self,c,p,rect):
        view,outline=self.plan(c,p,rect);a=aileron_parameters(p)
        if not a:return view,None
        q=dict(p,crea_asole_cerniere=False,create_servo_void=False,chiudi_estremita_alettone=False)
        data=section_preview(q,'alettone')
        for poly in data['polygons']:view.polygon([(x,z+data['origin']) for x,z in poly],fill='#fdba74',outline='',tags='feature')
        return view,a

    def draw_aileron(self,c,p,w,h):
        self.aileron_editor.draw(c,p,w,h)

    def draw_slots(self,c,p,w,h):
        self.slots_preview.draw(c,p,w,h)

    def connector_data(self,p):
        q=dict(p);q.update({k:v.get() for k,v in self.app.connector_vars.items()});q.update(self.app.spar_params())
        q['genera_raccordo_centrale']='1';settings=connector_parameters(q)
        for key,default in (('rib_pitch',40.),('rib_angle',45.)):
            q[key]=float(self.app.vars[key].get().replace(',','.')) if connector_ribs_enabled(q) else default
        connector_structure_parameters(q)
        chord=q['root_chord'];profile=airfoil_profile(q,'root',q['points'],max(.9,2*q['line_width'])/chord)
        angle=math.radians(settings['diedro_semiala']);directions=[]
        for spar in q['spars']:
            _,(dx,dy,dz)=spar_axis(q,spar);norm=math.sqrt(dx*dx+dy*dy+dz*dz)
            directions.append((-dy*math.sin(angle)+q['span']*math.cos(angle))/norm)
        reference=dict(q,create_connector_ribs=False)
        half=connector_half_span(reference,settings,profile,directions)
        return q,reference,settings,profile,half

    def draw_connector(self,c,p,w,h):
        q,reference,s,profile,half=self.connector_data(p);enabled=self.app.connector_vars['genera_raccordo_centrale'].get()=='1'
        angle=math.radians(s['diedro_semiala']);cs,sn=math.cos(angle),math.sin(angle);ch=q['root_chord'];ys=[y*ch for x,y in profile];low,high=min(ys),max(ys);ext=max(25,half*1.2)
        self.note(c,12,8,'Schema frontale di assemblaggio (Z/Y)',w-24)
        front=View(c,(18,43,w-18,h*.45),(-half-ext,half+ext,low-3,max(high,ext*sn)+5))
        front.polygon([(-half+low*sn,low*cs),(0,low),(half-low*sn,low*cs),(half-high*sn,high*cs),(0,high),(-half+high*sn,high*cs)],fill='#bfdbfe' if enabled else '#e2e8f0',outline='#64748b',tags='connector')
        for sign in (-1,1):
            front.line([(sign*half,0),(sign*(half+ext*cs),ext*sn)],fill='#334155',width=3,tags='dihedral')
        self.note(c,12,h*.43,f"Diedro {s['diedro_semiala']:g}° per semiala · {2*s['diedro_semiala']:g}° complessivi",w-24)
        data=section_preview(reference,'raccordo');view=View(c,(18,h*.54,w-18,h-45),(data['xmin']-3,data['xmax']+3,-2,data['height']+2))
        for poly in data['polygons']:view.polygon(poly,fill='#dbeafe' if enabled else '#e2e8f0',outline='',tags='connector')
        self.note(c,12,h*.5,'Posizione di stampa (X/Z) · nervature schematiche',w-24)
        if connector_ribs_enabled(q):
            mirrored=str(q.get('nervature_specchiate_raccordo','0')).lower() in ('1','true','yes')
            for family,points in connector_rib_segments(data['xmin'],data['xmax'],data['height'],float(q['rib_pitch']),float(q['rib_angle']),mirrored):
                view.line(points,fill='#a78bfa',width=1,tags=('ribs','ribs_'+family))
        roll=math.pi+angle
        raw=[(y*ch*cs,-half+y*ch*sn) for x,y in profile]+[(y*ch,0.) for x,y in profile]+[(y*ch*cs,half-y*ch*sn) for x,y in profile]
        shift=-min(y*math.sin(roll)+z*math.cos(roll) for y,z in raw)
        double=str(q.get('doppio_rinforzo_raccordo','1')).lower() in ('1','true','yes')
        for i,spar in enumerate(q['spars'],1):
            u=spar['position']/100;yc,_=profile_camber_thickness(q,u,'root')
            _,(dx,dy,dz)=spar_axis(q,spar);norm=math.sqrt(dx*dx+dy*dy+dz*dz)
            direction=(dx/norm,dy/norm*cs+q['span']/norm*sn,-dy/norm*sn+q['span']/norm*cs)
            for side in (-1,1):
                root=(u*ch,yc*ch*cs,side*(half-yc*ch*sn))
                end=(root[0]-direction[0]*s['lunghezza_innesto_longheroni'],root[1]-direction[1]*s['lunghezza_innesto_longheroni'],root[2]-side*direction[2]*s['lunghezza_innesto_longheroni'])
                front.line([(root[2],root[1]),(end[2],end[1])],fill='#d97706',width=max(2,spar['diameter']*front.scale),tags='seats')
                midz=(root[2]+end[2])/2;midy=(root[1]+end[1])/2;r=spar['diameter']/2
                front.line([(midz,low),(midz,midy-r)],fill='#7c3aed',width=2,tags='reinforcement')
                if double:front.line([(midz,midy+r),(midz,high)],fill='#7c3aed',width=2,tags='reinforcement')
                transformed=[(x,y*math.sin(roll)+z*math.cos(roll)+shift) for x,y,z in (root,end)]
                view.line(transformed,fill='#d97706',width=max(2,spar['diameter']*view.scale),tags='seats')
        status='Generazione attiva' if enabled else 'Generazione disattivata · anteprima di riferimento'
        if connector_ribs_enabled(q) and not q['spars']:status='Per esportare: aggiungi un longherone o disattiva le nervature.'
        if q['spars']:status+='\nArancio: innesti · Viola: collegamenti '+('doppi' if double else 'singoli')
        self.note(c,12,h-35,status,w-24,color='#92400e' if not enabled or not q['spars'] and connector_ribs_enabled(q) else '#475569')

    def draw_summary(self,c,p,w,h):
        self.note(c,16,9,'Vista d’insieme dei componenti configurati',w-32)
        for i,(component,title) in enumerate((('ala','Ala'),('alettone','Alettone'),('raccordo','Raccordo centrale'))):
            left=w*i/3;right=w*(i+1)/3
            self.note(c,left+18,34,title,right-left-30)
            try:
                q=dict(p,crea_asole_cerniere=False)
                if component=='raccordo':
                    if self.app.connector_vars['genera_raccordo_centrale'].get()!='1':raise ValueError('Disattivato')
                    q=self.connector_data(p)[1]
                data=section_preview(q,component);view=View(c,(left+25,65,right-20,h-20),(data['xmin']-3,data['xmax']+3,-2,data['height']+2))
                for poly in data['polygons']:view.polygon(poly,fill=('#fdba74' if component=='alettone' else '#bfdbfe'),outline='',tags='component_'+component)
                for outline,color in zip(data.get('servo_outlines',[]),('#d97706','#b91c1c')):view.line(outline,fill=color,width=1.5)
            except (ValueError,KeyError,TypeError) as exc:self.note(c,left+20,90,str(exc),right-left-35)


def servo_depth_at_center(p,s):
    # Gli stessi piani dei tagli CAD: corpo ruotato, ingresso e battuta.
    from servo import servo_surface
    x,z=s['center_x'],s['center_z']
    lower=servo_surface(p,z,x);upper=servo_surface(p,z,x,True)
    angle=math.radians(s['servo_rotate_z_deg'])
    body_top=s['center_y']+(s['servo_height_mm']/2+s['servo_clearance_mm'])/math.cos(angle)
    entry_top=lower+s['servo_lid_depth_mm']+2*vase_parameters(p)['legamento']
    return max(0.,min(upper,max(body_top,entry_top))-lower)


def draw_servo_dimensions(c,s,left,right,p):
    """Quote locali della sagoma di accesso; rotazioni mostrate nella vista ala."""
    green='#15803d';red='#dc2626';orange='#d97706';gray='#64748b'
    def note(x,y,text,color=gray):
        c.create_text(x,y,anchor='nw',text=text,width=right-left,font=('Segoe UI',9),fill=color,tags='servo_dimension_note')
    def dimension(label,x0,y0,x1,y1,color=green):
        c.create_line(x0,y0,x1,y1,fill=color,arrow='both',arrowshape=(4,5,2),tags=('servo_dimension','servo_dimension_'+label))
        horizontal=abs(y1-y0)<.01
        for x,y in ((x0,y0),(x1,y1)):
            c.create_line(x if horizontal else x-5,y-5 if horizontal else y,x if horizontal else x+5,y+5 if horizontal else y,fill=color)
        c.create_text((x0+x1)/2 if horizontal else x0+12,y0-12 if horizontal else (y0+y1)/2,text=label,fill=color,font=('Segoe UI',9,'bold'))
    poly=s['inner_polygon'];access_w=math.dist(poly[0],poly[1]);access_l=math.dist(poly[1],poly[2])
    note(left,20,'Dettaglio accesso e battuta · vista locale apertura')
    scale=min((right-left-125)/access_w,115/access_l)
    cx=(left+right)/2;ww=access_w*scale;hh=access_l*scale
    x0=cx-ww/2;x1=cx+ww/2;y0=85;y1=y0+hh;lip=14
    c.create_rectangle(x0-lip,y0-lip,x1+lip,y1+lip,fill='#ffedd5',outline=orange,tags='servo_dimension_seat')
    c.create_rectangle(x0,y0,x1,y1,fill='#fee2e2',outline=red,tags='servo_dimension_access')
    for x in (x0,x1):c.create_line(x,y0,x,55,fill=green)
    dimension('A',x0,58,x1,58)
    for y in (y0,y1):c.create_line(x1,y,x1+35,y,fill=green)
    dimension('B',x1+30,y0,x1+30,y1)
    dimension('C',x0-lip,y1+32,x0,y1+32,orange)
    note(left,247,'Sezione schematica · battuta e fondo dello scasso')
    sx=left+45;ex=right-48;step=sx+52;top=274;bottom=291;floor=326
    c.create_polygon(sx,top,step,top,step,bottom,step+35,bottom,step+35,floor,ex,floor,ex,345,sx,345,fill='#e2e8f0',outline='#94a3b8',tags='servo_dimension_section')
    c.create_line(sx,top,step,top,step,bottom,step+35,bottom,step+35,floor,ex,floor,fill=orange,width=2)
    dimension('D',step+18,top,step+18,bottom,orange)
    dimension('E',ex+22,top,ex+22,floor,green)
    c.create_line(step,top,ex+25,top,fill=orange,dash=(2,2))
    depth=servo_depth_at_center(p,s)
    note(left,350,'mm · E: intradosso → fondo al centro, lungo Y (prima del washout)')
    entries=(('A',f'Larghezza accesso: {access_w:.2f}',green),
             ('B',f'Lunghezza accesso: {access_l:.2f}',green),
             ('C',f'Battuta per lato: {s["servo_lid_lip_mm"]:g}',orange),
             ('D',f'Profondità battuta: {s["servo_lid_depth_mm"]:g}',orange),
             ('E',f'Profondità totale al centro: {depth:.2f}',green))
    for i,(label,text,color) in enumerate(entries):
        c.create_text(left+(right-left)/2*(i%2),374+19*(i//2),anchor='nw',text=label+' · '+text,fill=color,font=('Segoe UI',9),tags=('servo_dimension_legend','servo_legend_'+label))
    note(left,440,f"Corpo X/Y/Z: {s['servo_width_mm']:g} / {s['servo_height_mm']:g} / {s['servo_length_mm']:g} · gioco per lato: {s['servo_clearance_mm']:g} mm")
    note(left,462,f"Centro: radice {s['servo_dist_root_mm']:g} · bordo d’attacco {s['servo_dist_le_mm']:g} mm")
    note(left,484,f"Offset verso l’intradosso: {s['servo_dist_depth_mm']:g} mm · coperchio da realizzare a parte")


def connector_rib_segments(xmin,xmax,height,pitch,angle,mirrored):
    """Tracce schematiche dei piani CAD: specchiatura Z -> altezza - Z."""
    if not all(math.isfinite(v) for v in (xmin,xmax,height,pitch,angle)) or pitch<=0:
        raise ValueError('Passo e dimensioni delle nervature devono essere finiti; passo positivo richiesto.')
    if not 20<=angle<=70:raise ValueError('Angolo nervature richiesto tra 20 e 70 gradi.')
    slope=math.tan(math.radians(angle))
    base=math.floor(-slope*xmax/pitch)*pitch
    last=height-slope*xmin
    for k in range(max(0,int(math.floor((last-base)/pitch))+1)):
        z0=base+k*pitch
        # Intersezione con il rettangolo di ingombro; evita punti duplicati
        # negli spigoli, che produrrebbero segmenti di lunghezza nulla.
        lo=max(xmin,-z0/slope);hi=min(xmax,(height-z0)/slope)
        if hi-lo<=1e-8:continue
        points=[(lo,min(height,max(0.,z0+slope*lo))),
                (hi,min(height,max(0.,z0+slope*hi)))]
        yield 'original',points
        if mirrored:
            yield 'mirrored',[(x,height-z) for x,z in points]
