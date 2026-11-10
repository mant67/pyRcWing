"""Horizontal aileron editor, from the existing nominal export projections."""
# File revision: 4
import json
import math
from core import (aileron_parameters,aileron_axial_bounds,aileron_cap_parameters,aileron_hinge,
    wing_section_at,upper_surface_at)
from sections import section_preview,clip_polygon


def projected_envelope(polygons):
    edges=[];levels=set()
    for poly in polygons:
        for x,z in poly:levels.add(round(z,10))
        edges.extend(zip(poly,poly[1:]+poly[:1]))
    rows=[]
    for z in sorted(levels):
        xs=[]
        for (xa,za),(xb,zb) in edges:
            if min(za,zb)-1e-8<=z<=max(za,zb)+1e-8:
                if abs(zb-za)<1e-10:xs.extend((xa,xb))
                else:
                    t=max(0.,min(1.,(z-za)/(zb-za)));xs.append(xa+(xb-xa)*t)
        if xs:rows.append((z,min(xs),max(xs)))
    if len(rows)<2:raise ValueError('Forma dell’alettone non disponibile: controlla posizione, lunghezza e larghezze.')
    return [(a,z) for z,a,b in rows]+[(b,z) for z,a,b in reversed(rows)],rows


def at(rows,z):
    if z<=rows[0][0]:return rows[0][1:]
    if z>=rows[-1][0]:return rows[-1][1:]
    for (za,a,b),(zb,c,d) in zip(rows,rows[1:]):
        if za<=z<=zb:
            f=(z-za)/(zb-za);return a+(c-a)*f,b+(d-b)*f
    raise ValueError('Quota fuori dalla rappresentazione.')


def clipped_box(poly,x0,x1,z0,z1):
    for distance in (lambda v:v[0]-x0,lambda v:x1-v[0],lambda v:v[1]-z0,lambda v:z1-v[1]):
        poly=clip_polygon(poly,distance)
    return poly


class HorizontalView:
    def __init__(self,rect,points):
        left,top,right,bottom=rect;xs=[x for x,z in points];zs=[z for x,z in points]
        self.scale=min((right-left)/max(.01,max(zs)-min(zs)),(bottom-top)/max(.01,max(xs)-min(xs)))
        self.ox=(left+right)/2-(min(zs)+max(zs))*self.scale/2
        self.oy=(top+bottom)/2-(min(xs)+max(xs))*self.scale/2
    def xy(self,x,z):return self.ox+z*self.scale,self.oy+x*self.scale
    def coords(self,points):return [v for point in points for v in self.xy(*point)]


class AileronEditor:
    def __init__(self,owner,canvas=None):
        self.owner=owner;self.app=owner.app;self.canvas=canvas if canvas is not None else owner.canvases['aileron']
        self.handles={};self.view=None;self.detail_view=None;self.drag=None;self.data=None;self.body_cache=None;self.syncing=False
        if canvas is not None:return
        self.app.aileron_root_distance.trace_add('write',self.distance_changed)
        for key in ('inizio_alettone','gioco_alettone_radice'):self.app.vars[key].trace_add('write',self.model_distance_changed)
        self.sync_distance(force=True)

    def model_distance_changed(self,*_):
        if not self.syncing:self.sync_distance(force=True)

    def sync_distance(self,force=False):
        if self.syncing or getattr(self.app,'loading_configuration',False):return
        try:
            nominal=float(self.app.vars['inizio_alettone'].get().replace(',','.'))
            gap=float(self.app.vars['gioco_alettone_radice'].get().replace(',','.'))
            value=nominal+gap/2
            if not math.isfinite(value):return
        except (ValueError,TypeError):return
        try:current=float(self.app.aileron_root_distance.get().replace(',','.'))
        except ValueError:current=None
        if not force and current is not None and abs(current-value)<1e-9:return
        self.syncing=True
        try:self.app.aileron_root_distance.set(f'{value:.6f}'.rstrip('0').rstrip('.'))
        finally:self.syncing=False

    def distance_changed(self,*_):
        if self.syncing or getattr(self.app,'loading_configuration',False):return
        raw=self.app.aileron_root_distance.get();self.syncing=True
        try:
            try:
                value=float(raw.replace(',','.'));gap=float(self.app.vars['gioco_alettone_radice'].get().replace(',','.'))
                nominal=f'{value-gap/2:.10g}' if math.isfinite(value) and math.isfinite(gap) else raw
            except (ValueError,TypeError):nominal=raw
            self.app.vars['inizio_alettone'].set(nominal)
        finally:self.syncing=False

    def geometry(self,p):
        q=dict(p,crea_asole_cerniere=False,create_servo_void=False,chiudi_estremita_alettone=False,washout_deg=0.)
        keys=('span','root_chord','tip_chord','sweep','airfoil','airfoil_tip','custom_airfoil_root','custom_airfoil_tip',
              'points','stations','elliptical_tip','tip_length','wing_center_line_perc','planform','ellipse_center_perc',
              'planform_nodes','tip_nodes','line_width','larghezza_linea_vaso')
        key=json.dumps({k:q.get(k) for k in keys},sort_keys=True)
        if self.body_cache is None or self.body_cache[0]!=key:
            data=section_preview(dict(q,crea_alettone=False),'ala')
            body,body_rows=projected_envelope(data['polygons']);self.body_cache=(key,body,body_rows)
        _,body,body_rows=self.body_cache
        enabled=str(q.get('crea_alettone',False)).lower() in ('1','true','yes')
        try:negative_start=float(str(q.get('inizio_alettone',0)).replace(',','.'))<0
        except (ValueError,TypeError):negative_start=False
        if enabled and negative_start:raise ValueError('Distanza dalla radice inferiore a metà del gioco radice: riduci il gioco o aumenta la distanza.')
        a=aileron_parameters(q)
        if not a:return dict(body=body,body_rows=body_rows,a=None)
        bounds=aileron_axial_bounds(a);caps=aileron_cap_parameters(p)
        part_data=section_preview(q,'alettone')
        part,part_rows=projected_envelope([[(x,z+part_data['origin']) for x,z in poly] for poly in part_data['polygons']])
        hinge_xyz,levels=aileron_hinge(q,a)
        def hinge(z):return hinge_xyz(z)[0]
        lo,hi=bounds['cut_start'],bounds['cut_end']
        if levels:
            stations=sorted({lo,hi,*levels,*(z for z,_,_ in body_rows if lo<z<hi)})
            edge=[(max(at(body_rows,z)[0],hinge(z)-a['gioco_alettone']/2),z) for z in stations]
            cavity=edge+[(at(body_rows,z)[1],z) for z in reversed(stations)]
        else:
            cavity=clip_polygon(body,lambda v:v[1]-lo)
            cavity=clip_polygon(cavity,lambda v:hi-v[1])
            cavity=clip_polygon(cavity,lambda v:v[0]-hinge(v[1])+a['gioco_alettone']/2)
        return dict(body=body,body_rows=body_rows,a=a,bounds=bounds,caps=caps,part=part,part_rows=part_rows,cavity=cavity,hinge=hinge)

    def draw(self,c,p,w,h,trace_view=None):
        self.handles={};data=self.geometry(p);self.data=data
        tracing=trace_view is not None
        body=data['body'];a=data['a'];left_right=w-20 if tracing else w*.48-14
        if tracing:self.view=trace_view
        elif self.drag is None:self.view=HorizontalView((28,76,left_right,h-76),body)
        view=self.view
        c.create_polygon(view.coords(body),fill='' if tracing else '#dbeafe',
                         outline='#2563eb' if tracing else '#64748b',width=2 if tracing else 1,tags='aileron_wing')
        self.owner.note(c,16,10,'Alettone · Radice a sinistra, estremità a destra',left_right-20)
        if tracing and p['elliptical_tip']:
            span=p['span']
            lead,tail=at(data['body_rows'],span)
            c.create_line(*view.xy(lead,span),*view.xy(tail,span),fill='#2563eb',
                          width=2,dash=(5,4),tags='aileron_tip_limit')
        if not a:
            self.drag=None
            self.owner.note(c,16 if tracing else w*.51,60,'Alettone disattivato.',w*.46);return
        bounds=data['bounds'];part=data['part'];cavity=data['cavity'];rows=data['part_rows'];caps=data['caps']
        self.paint(c,view,data,tracing=tracing)
        z0,z1=bounds['part_start'],bounds['part_end'];zm=(z0+z1)/2
        x0,x1=at(rows,z0),at(rows,z1);xm=at(rows,zm)
        points={'start':(x0[1],z0),'end':(x1[1],z1),'width_root':(x0[0],z0),'width_tip':(x1[0],z1),'move':((xm[0]+xm[1])/2,zm)}
        if tracing:self.handles={key:view.xy(*point) for key,point in points.items()}
        for key,(x,y) in self.handles.items():c.create_oval(x-6,y-6,x+6,y+6,fill='#ea580c',outline='white',width=2,tags=('aileron_handle',key))
        low=min(x for x,z in body)-22/view.scale
        self.dimension(c,view.xy(low,0.),view.xy(low,z0),'R','#15803d',dy=-12)
        if not tracing:self.detail(c,data,w*.51+10,w-20,h)
        if tracing:self.owner.note(c,16,h-46,'Estremi: lunghezza · lato cerniera: larghezze · centro: sposta.',left_right-28)
        self.owner.note(c,16,h-23,'Bordo d’uscita vincolato all’ala · pianta senza washout.',left_right-28,color='#64748b')

    @staticmethod
    def dimension(c,a,b,label,color,dx=0,dy=0):
        if math.dist(a,b)>.8:c.create_line(*a,*b,arrow='both',arrowshape=(4,5,2),fill=color,width=1.3,tags=('aileron_dimension',label))
        else:c.create_line(a[0]-2,a[1]-2,a[0]+2,a[1]+2,fill=color,tags=('aileron_dimension',label))
        c.create_text((a[0]+b[0])/2+dx,(a[1]+b[1])/2+dy,text=label,fill=color,font=('Segoe UI',9,'bold'),tags=('aileron_dimension_label',label))

    @staticmethod
    def paint(c,view,data,box=None,detail=False,tracing=False):
        def polygon(points,**kwargs):
            if box:points=clipped_box(points,*box)
            if len(points)>=3:c.create_polygon(view.coords(points),**kwargs)
        if detail:polygon(data['body'],fill='#e2e8f0',outline='#94a3b8',tags='detail_wing')
        polygon(data['cavity'],fill='' if tracing else 'white',outline='#0284c7' if tracing else '#64748b',
                width=2 if tracing else 1,dash=() if tracing else (4,3),tags='detail_cavity' if detail else 'aileron_cavity')
        polygon(data['part'],fill='' if tracing else '#fed7aa',outline='#c2410c',width=1.5,tags='detail_aileron' if detail else 'aileron_part')
        if data['caps']:
            thick=data['caps']['spessore'];b=data['bounds']
            for lo,hi in ((b['part_start'],b['part_start']+thick),(b['part_end']-thick,b['part_end'])):
                band=clip_polygon(data['part'],lambda v:v[1]-lo);band=clip_polygon(band,lambda v:hi-v[1])
                polygon(band,fill='' if tracing else '#93c5fd',outline='#1d4ed8',tags='detail_caps' if detail else 'aileron_caps')

    def detail(self,c,data,left,right,h):
        a=data['a'];b=data['bounds'];rows=data['part_rows'];part=data['part'];cavity=data['cavity'];green='#15803d';red='#dc2626'
        xs=[x for x,z in part+cavity];zs=[z for x,z in part+cavity]
        padx=max(2.,3*a['gioco_alettone']);padz=max(2.,a['gioco_alettone_radice'],a['gioco_alettone_estremita'])
        box=(min(xs)-padx,max(xs)+padx,min(zs)-padz,max(zs)+padz)
        corners=[(box[x],box[z]) for x,z in ((0,2),(0,3),(1,2),(1,3))]
        view=HorizontalView((left+45,55,right-45,h-204),corners);self.detail_view=view
        self.paint(c,view,data,box,True)
        self.owner.note(c,left,10,'Dettaglio reale in pianta · stessa scala sui due assi',right-left)
        z0,z1=b['part_start'],b['part_end'];r0,r1=at(rows,z0),at(rows,z1);mid=(z0+z1)/2;rm=at(rows,mid)
        if data['caps']:
            zg=z0+data['caps']['spessore']/2;lo,hi=at(rows,zg);gx,gy=view.xy((lo+hi)/2,zg)
            c.create_line(gx,gy,gx+10,gy,fill='#1d4ed8')
            c.create_text(gx+14,gy,text='G',anchor='w',fill='#1d4ed8',font=('Segoe UI',9,'bold'),tags='closure_label')
        xdim=min(xs)-12/view.scale
        self.dimension(c,view.xy(xdim,z0),view.xy(xdim,z1),'A',green,dy=-13)
        self.dimension(c,view.xy(r0[0],z0-22/view.scale),view.xy(r0[1],z0-22/view.scale),'B',green,dx=-12)
        self.dimension(c,view.xy(r1[0],z1+22/view.scale),view.xy(r1[1],z1+22/view.scale),'C',green,dx=12)
        open_root=b['cut_start']<data['body_rows'][0][0]-1e-8
        open_tip=b['cut_end']>data['body_rows'][-1][0]+1e-8
        root_edge=max(b['cut_start'],data['body_rows'][0][0]);tip_edge=min(b['cut_end'],data['body_rows'][-1][0])
        _,dim_y=view.xy(max(xs)+16/view.scale,mid)
        for label,first,last,direction in (('D',root_edge,z0,-1),('E',z1,tip_edge,1)):
            for z,sign in ((first,-1),(last,1)):
                x,y=view.xy(at(data['body_rows'],z)[1],z)
                c.create_line(x,y,x,dim_y+4,fill=red,dash=(2,2),tags=('aileron_dimension',label))
                c.create_line(x+sign*10,dim_y,x,dim_y,arrow='last',arrowshape=(4,5,2),
                              fill=red,tags=('aileron_dimension',label))
            x,_=view.xy(0,first if direction<0 else last)
            c.create_text(x+direction*15,dim_y,text=label,anchor='e' if direction<0 else 'w',
                          fill=red,font=('Segoe UI',9,'bold'),tags=('aileron_dimension_label',label))
        front=data['hinge'](mid)-a['gioco_alettone']/2
        fx,fy=view.xy(front,mid)
        _,part_y=view.xy(rm[0],mid)
        for y in (fy,part_y):
            c.create_line(fx-4,y,fx+4,y,fill=red,tags=('aileron_dimension','F'))
        c.create_line(fx,fy,fx,part_y,fill=red,tags=('aileron_dimension','F'))
        label_x=fx+18
        c.create_line(fx+4,(fy+part_y)/2,label_x,dim_y-7,label_x,dim_y-4,
                      fill=red,dash=(2,2),tags=('aileron_dimension','F'))
        c.create_text(label_x,dim_y+1,text='F',fill=red,font=('Segoe UI',9,'bold'),
                      tags=('aileron_dimension_label','F'))
        entries=(('R',f"Distanza radice {z0:g} mm",green),
                 ('A',f"Lunghezza {z1-z0:g} mm\n(nominale {a['lunghezza_alettone']:g})",green),
                 ('B',f"Radice {r0[1]-r0[0]:.3g} mm\n(impostata {a['larghezza_alettone_radice']:g})",green),
                 ('C',f"Punta {r1[1]-r1[0]:.3g} mm\n(impostata {a['larghezza_alettone_estremita']:g})",green),
                 ('D',(f"Margine radice {z0-root_edge:g} mm\n(bordo aperto; impost. {a['gioco_alettone_radice']:g})" if open_root else f"Gioco radice {a['gioco_alettone_radice']:g} mm"),red),
                 ('E',(f"Margine punta {tip_edge-z1:g} mm\n(bordo aperto; impost. {a['gioco_alettone_estremita']:g})" if open_tip else f"Gioco punta {a['gioco_alettone_estremita']:g} mm"),red),
                 ('F',f"Cerniera in pianta {rm[0]-front:.3g} mm\n(impostato {a['gioco_alettone']:g})",red),
                 ('G',f"Chiusure {data['caps']['spessore']:g} mm" if data['caps'] else 'Chiusure disattivate','#1d4ed8'))
        for i,(label,text,color) in enumerate(entries):
            c.create_text(left+(right-left)/2*(i%2),h-158+31*(i//2),anchor='nw',text=label+' · '+text,width=(right-left)/2-6,fill=color,font=('Segoe UI',9),tags=('aileron_legend','legend_'+label))
        self.owner.note(c,left,h-29,'Quote reali in mm. Ai bordi aperti D/E sono margini; F include lo smusso in pianta a metà alettone.',right-left,color='#64748b')

    def press(self,event):
        if self.app.generating or self.view is None or not self.handles:return
        key=min(self.handles,key=lambda k:math.hypot(event.x-self.handles[k][0],event.y-self.handles[k][1]))
        x,y=self.handles[key]
        if math.hypot(event.x-x,event.y-y)<=13:self.drag=(key,self.owner.params(),dict(self.data['a']),event.x,event.y,self.view)

    def motion(self,event):
        if self.drag is None or self.app.generating:return
        key,p,a,x,y,view=self.drag;dz=(event.x-x)/view.scale;dx=(event.y-y)/view.scale
        start=a['inizio_alettone'];end=start+a['lunghezza_alettone'];wr=a['larghezza_alettone_radice'];wt=a['larghezza_alettone_estremita'];total=self.data['body_rows'][-1][0]
        if p['elliptical_tip']:
            total=min(total,p['span']-a['gioco_alettone_estremita']/2)
        minimum=(a['gioco_alettone_radice']+a['gioco_alettone_estremita'])/2+4*p['skin']+.01
        caps=aileron_cap_parameters(p)
        if caps:minimum=max(minimum,2*caps['spessore']+(a['gioco_alettone_radice']+a['gioco_alettone_estremita'])/2+.01)
        ns,ne=start,end
        if key=='move':
            ns=max(0.,min(total-(end-start),start+dz));ne=min(total,ns+end-start)
        elif key=='start':ns=max(0.,min(end-minimum,start+dz))
        elif key=='end':ne=min(total,max(start+minimum,end+dz))
        margin=2*p['skin']+a['gioco_alettone']+.01
        if key in ('move','start','end'):
            if ne-ns<minimum-1e-8 or ne>total+1e-8:return
            def valid(s,e):
                return wing_section_at(p,s)[0]>wr+margin and wing_section_at(p,e)[0]>wt+margin
            if not valid(ns,ne):
                lo,hi=0.,1.
                for _ in range(35):
                    f=(lo+hi)/2
                    if valid(start+(ns-start)*f,end+(ne-end)*f):lo=f
                    else:hi=f
                ns,ne=start+(ns-start)*lo,end+(ne-end)*lo
                if ne>total+1e-8:return
            self.app.vars['inizio_alettone'].set(f'{ns:.8f}');self.app.vars['lunghezza_alettone'].set(f'{ne-ns:.8f}')
        else:
            z=start if key=='width_root' else end;old=wr if key=='width_root' else wt
            upper=wing_section_at(p,z)[0]-margin
            value=max(a['gioco_alettone']/2+.1,min(upper,old-dx))
            field='larghezza_alettone_radice' if key=='width_root' else 'larghezza_alettone_estremita'
            self.app.vars[field].set(f'{value:.8f}')
        self.owner.draw('aileron')

    def release(self,event):
        if self.drag is None:return
        self.drag=None;self.owner.draw('aileron')
