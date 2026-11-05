"""Nominal plan and section details for hinge pockets; no export changes."""
import math
from core import (hinge_slot_parameters,wing_section_at,section_profile,smooth_tip_profile)
from sections import clip_polygon
from aileron_ui import HorizontalView,AileronEditor,clipped_box,at

GREEN='#15803d'
PURPLE='#7c3aed'
RED='#dc2626'


class SectionView:
    def __init__(self,rect,points):
        left,top,right,bottom=rect;xs,ys=zip(*points)
        self.scale=min((right-left)/max(.01,max(xs)-min(xs)),(bottom-top)/max(.01,max(ys)-min(ys)))
        self.ox=(left+right)/2-(min(xs)+max(xs))*self.scale/2
        self.oy=(top+bottom)/2+(min(ys)+max(ys))*self.scale/2
    def xy(self,x,y):return self.ox+x*self.scale,self.oy-y*self.scale
    def coords(self,points):return [v for point in points for v in self.xy(*point)]


class SlotsPreview:
    def __init__(self,owner):
        self.owner=owner;self.data=None;self.slots=None;self.view=None;self.detail_view=None;self.section=None

    def pockets(self,p,a,slots,z):
        """True projected footprints of the wing and bevelled movable pocket."""
        length=slots['lunghezza_asole_cerniere'];depth=slots['profondita_asole_cerniere']
        offset=slots['distanza_asole_estradosso'];height=slots['altezza_asole_cerniere']
        gap=a['gioco_alettone'];bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
        left=[];right=[]
        for zz in (z-length/2,z+length/2):
            hx,_=self.owner.hinge(p,a,zz)
            left.append((hx-gap/2-depth,hx-gap/2,zz))
            right.append((hx+gap/2+bevel*(offset-height/2),hx+gap/2+bevel*(offset+height/2)+depth,zz))
        def polygon(rows):
            (lo,hi,z0),(lo1,hi1,z1)=rows
            return [(lo,z0),(hi,z0),(hi1,z1),(lo1,z1)]
        return polygon(left),polygon(right)

    def ramp(self,c,view,p,a,slots,z,tag,box=None):
        # Footprint of the supporting wedge, before the pocket in printing Z.
        length=slots['lunghezza_asole_cerniere'];depth=slots['profondita_asole_cerniere']
        skin=p['skin'];top=z-length/2-skin;bottom=top-slots['lunghezza_rampa_z']
        hx0,_=self.owner.hinge(p,a,bottom);hx1,_=self.owner.hinge(p,a,top)
        gap=a['gioco_alettone'];bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
        extent=bevel*(slots['distanza_asole_estradosso']+slots['altezza_asole_cerniere']/2)
        for sign in (-1,1):
            f0=hx0+sign*gap/2;f1=hx1+sign*gap/2
            poly=[(f0,bottom),(f1+sign*(depth+skin+(extent if sign>0 else 0)),top),(f1,top)]
            if box:poly=clipped_box(poly,*box)
            if len(poly)>=3:c.create_polygon(view.coords(poly),fill='',outline=PURPLE,dash=(3,3),tags=tag)

    @staticmethod
    def dimension(c,view,first,last,label,color=GREEN,dx=0,dy=0):
        a,b=view.xy(*first),view.xy(*last)
        c.create_line(*a,*b,arrow='both',arrowshape=(4,5,2),fill=color,tags=('dimension','slot_dimension_'+label))
        # Extension ticks remain visible even for sub-pixel clearances.
        horizontal=abs(a[1]-b[1])<abs(a[0]-b[0])
        for x,y in (a,b):
            c.create_line(x-(0 if horizontal else 4),y-(4 if horizontal else 0),x+(0 if horizontal else 4),y+(4 if horizontal else 0),fill=color)
        c.create_text((a[0]+b[0])/2+dx,(a[1]+b[1])/2+dy,text=label,fill=color,font=('Segoe UI',9,'bold'),tags='dimension')

    def draw(self,c,p,w,h):
        self.section=None;self.detail_view=None
        data=self.owner.aileron_editor.geometry(p);self.data=data;body=data['body'];a=data['a']
        view=HorizontalView((30,65,w*.47-24,h-85),body);self.view=view
        c.create_polygon(view.coords(body),fill='#dbeafe',outline='#64748b',tags='slots_wing')
        self.owner.note(c,16,10,'Asole e cerniere · radice a sinistra, punta a destra',w*.46-20)
        if a:AileronEditor.paint(c,view,data)
        slots=hinge_slot_parameters(p);self.slots=slots
        left=w*.50+14;right=w-22
        if not a or not slots:
            self.owner.note(c,left,60,'Asole disattivate.\nAttivale per vedere distribuzione e dettaglio quotato.',right-left)
            return
        centers=slots['centri'];length=slots['lunghezza_asole_cerniere'];depth=slots['profondita_asole_cerniere']
        height=slots['altezza_asole_cerniere'];offset=slots['distanza_asole_estradosso']
        for i,z in enumerate(centers):
            for poly in self.pockets(p,a,slots,z):c.create_polygon(view.coords(poly),fill='#ddd6fe',outline=PURPLE,tags=('slot_position','slot_pair_'+str(i)))
            self.ramp(c,view,p,a,slots,z,'slot_ramp')
        if len(centers)>1:
            low=max(x for x,z in body)+18/view.scale
            for z in centers[:2]:
                hx,_=self.owner.hinge(p,a,z)
                c.create_line(*view.xy(hx,z),*view.xy(low,z),fill=GREEN,dash=(2,3))
            self.dimension(c,view,(low,centers[0]),(low,centers[1]),'E',dy=14)
        self.owner.note(c,16,h-46,'Viola: asole · tratteggio: sviluppo degli inviti di sostegno.',w*.46-20)
        self.owner.note(c,16,h-23,f'{len(centers)} coppie nella vista generale · pianta senza washout.',w*.46-20)
        selected=min(range(len(centers)),key=lambda i:abs(centers[i]-(a['inizio_alettone']+a['lunghezza_alettone']/2)))
        z=centers[selected];self.selected_index=selected;self.selected_z=z
        self.owner.note(c,left,10,'Dettaglio in pianta · ala e alettone reali',right-left)
        self.owner.note(c,left,33,f'Cerniera {selected+1} di {len(centers)} · una sola coppia d’esempio',right-left)
        wing,movable=self.pockets(p,a,slots,z)
        z0=max(data['body_rows'][0][0],z-length/2-slots['lunghezza_rampa_z']-3)
        z1=min(data['body_rows'][-1][0],z+length/2+max(3,length*.6))
        samples=[z0,z1]+[zz for zz,_,_ in data['part_rows'] if z0<=zz<=z1]
        x0=min(x for x,zz in wing)-max(2,depth*.5)
        x1=max(at(data['part_rows'],zz)[1] for zz in samples)+2
        box=(x0,x1,z0,z1)
        detail=HorizontalView((left+38,66,right-38,222),[(x0,z0),(x1,z1)]);self.detail_view=detail
        AileronEditor.paint(c,detail,data,box,True)
        for side,poly in (('wing',wing),('movable',movable)):
            c.create_polygon(detail.coords(clipped_box(poly,*box)),fill='#ddd6fe',outline=PURPLE,width=1.5,tags=('slot_example','slot_example_'+side))
        self.ramp(c,detail,p,a,slots,z,'slot_example_ramp',box)
        xdim=min(x for x,zz in wing)-12/detail.scale
        self.dimension(c,detail,(xdim,z-length/2),(xdim,z+length/2),'A',dy=-12)
        # B is the insertion depth on the wing side; the movable face is bevelled.
        hx,_=self.owner.hinge(p,a,z+length/2)
        zd=z+length/2+14/detail.scale
        self.dimension(c,detail,(hx-a['gioco_alettone']/2-depth,zd),(hx-a['gioco_alettone']/2,zd),'B',dx=13)
        self.owner.note(c,left,246,'Sezione X/Y della stessa cerniera · profilo reale',right-left)
        self.draw_section(c,p,a,slots,z,(left+40,278,right-40,393))
        self.owner.note(c,left,408,'Quote in mm · scala uniforme in ciascuna vista · prima del washout',right-left)
        pitch=f"{slots['interasse_effettivo']:g}" if len(centers)>1 else '— (una coppia)'
        if len(centers)>1 and slots['interasse_asole_cerniere']==0:pitch+=' (auto)'
        entries=(('A',f'Lunghezza lungo Z: {length:g}',GREEN),('B',f'Profondità per lato: {depth:g}',GREEN),('C',f'Altezza asola: {height:g}',RED),('D',f'Estradosso → centro: {offset:g}',GREEN),('E',f'Interasse effettivo: {pitch}',GREEN))
        for i,(label,value,color) in enumerate(entries):
            c.create_text(left+(right-left)/2*(i%2),441+22*(i//2),anchor='nw',width=(right-left)/2-8,text=label+' · '+value,fill=color,font=('Segoe UI',9),tags=('dimension_legend','slot_legend_'+label))
        self.owner.note(c,left,512,f"{len(centers)} coppie · rampe {slots['angolo_rampe_sostegno_asole']:g}° · sviluppo Z {slots['lunghezza_rampa_z']:g} mm",right-left)
        self.owner.note(c,left,544,f"Margine asola/bordo: radice {slots['distanza_bordo_radice']:.2f} · punta {slots['distanza_bordo_estremita']:.2f} mm",right-left)

    def draw_section(self,c,p,a,slots,z,rect):
        ch,lead,_=wing_section_at(p,z);q=dict(p,points=max(100,p['points']))
        if z>p['span']:profile=smooth_tip_profile(q,(z-p['span'])/p['tip_length'],points=q['points'])
        else:
            te=max(.9,2*float(str(p.get('larghezza_linea_vaso',p['line_width'])).replace(',','.')))
            profile=[(lead+x*ch,y*ch) for x,y in section_profile(q,z,te/ch)]
        hx,hy=self.owner.hinge(p,a,z);gap=a['gioco_alettone']
        bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
        depth=slots['profondita_asole_cerniere'];height=slots['altezza_asole_cerniere'];offset=slots['distanza_asole_estradosso'];yc=hy-offset
        wing=clip_polygon(profile,lambda v:hx-gap/2-v[0])
        movable=clip_polygon(profile,lambda v:v[0]-hx-gap/2)
        movable=clip_polygon(movable,lambda v:v[0]-hx-gap/2-bevel*(hy-v[1]))
        xlo=hx-gap/2-depth;xhi=hx+gap/2+bevel*(offset+height/2)+depth
        ylo=yc-height/2;yhi=yc+height/2
        local=clipped_box(profile,xlo-3,xhi+3,-1e4,1e4)
        ys=[v[1] for v in local]+[hy,ylo,yhi]
        box=(xlo-3,xhi+3,min(ys)-.6,max(ys)+.6)
        view=SectionView(rect,[(box[0],box[2]),(box[1],box[3])])
        for side,poly,color in (('wing',wing,'#e2e8f0'),('movable',movable,'#fed7aa')):
            poly=clipped_box(poly,*box)
            if len(poly)>=3:c.create_polygon(view.coords(poly),fill=color,outline='#64748b',tags=('slot_section','slot_section_'+side))
            hole=clipped_box(poly,xlo,xhi,ylo,yhi)
            if len(hole)>=3:c.create_polygon(view.coords(hole),fill='#ddd6fe',outline=PURPLE,width=1.5,tags=('slot_section_void','slot_section_void_'+side))
        c.create_line(*view.xy(xlo-2,hy),*view.xy(xhi+2,hy),fill='#64748b',dash=(3,3),tags='slot_surface_reference')
        c.create_line(*view.xy(xlo-2,yc),*view.xy(xhi+2,yc),fill=PURPLE,dash=(2,3),tags='slot_center_reference')
        self.dimension(c,view,(xhi+12/view.scale,ylo),(xhi+12/view.scale,yhi),'C',RED,dx=12)
        self.dimension(c,view,(xlo-12/view.scale,hy),(xlo-12/view.scale,yc),'D',dx=-12)
        self.section=dict(view=view,hx=hx,hy=hy,yc=yc,ylo=ylo,yhi=yhi,wing=wing,movable=movable,box=box)
