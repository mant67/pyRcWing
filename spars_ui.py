"""Horizontal planform and draggable spar positions/angles."""
import math
from core import airfoil_profile,spar_axis,spar_automatic,legacy_spar_angle


class SparEditor:
    def __init__(self,owner):
        self.owner=owner;self.app=owner.app;self.canvas=owner.canvases['spars']
        self.handles={};self.view=None;self.drag=None
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)

    def draw(self,c,p,w,h):
        self.handles={};settings=self.app.spar_params();spars=settings['spars']
        outline=[(z,x) for x,z in self.owner.outline(dict(p,washout_deg=0.))]
        axes=[];points=list(outline)
        for index,spar in enumerate(spars):
            root,delta=spar_axis(p,spar);length=spar.get('length',p['span'])
            end=tuple(a+b*length/p['span'] for a,b in zip(root,delta))
            axes.append((index,spar,root,end,delta));points.extend(((0.,root[0]),(length,end[0])))
        if self.drag is None:
            zs=[z for z,x in points];xs=[x for z,x in points]
            left,top,right,bottom=30.,62.,w*.59-22,h-66.
            scale=min((right-left)/max(1.,max(zs)-min(zs)),(bottom-top)/max(1.,max(xs)-min(xs)))
            self.view=(left+(right-left-(max(zs)-min(zs))*scale)/2-min(zs)*scale,
                       top+(bottom-top-(max(xs)-min(xs))*scale)/2-min(xs)*scale,scale)
        ox,oy,scale=self.view
        def xy(z,x):return ox+z*scale,oy+x*scale
        def coords(points):return [v for p in points for v in xy(*p)]
        c.create_polygon(coords(outline),fill='#dbeafe',outline='#64748b',tags='spars_wing')
        self.owner.note(c,16,10,'Longheroni · Ala orizzontale, radice a sinistra',w*.58-20)
        root_profile=[(x*p['root_chord'],y*p['root_chord']) for x,y in airfoil_profile(p,'root',80)]
        profile_view=self.owner.profile_view(c,root_profile,(w*.61,48,w-18,150))
        self.owner.note(c,w*.61,12,'Sezione alla radice',w*.37)
        labels=[]
        for index,spar,root,end,delta in axes:
            line=((0.,root[0]),(spar.get('length',p['span']),end[0]))
            c.create_line(*coords(line),fill='#2563eb',width=max(2.,spar['diameter']*scale),tags=('spar_axis',f'spar_axis_{index}'))
            for kind,point in (('position',line[0]),('angle',line[1])):
                x,y=xy(*point);self.handles[(index,kind)]=(x,y)
                c.create_oval(x-6,y-6,x+6,y+6,fill='#ea580c',outline='white',width=2,tags=('spar_handle',f'spar_{index}_{kind}'))
            x,y=xy(*line[1]);c.create_text(x-8,y-12,text=str(index+1),anchor='se',fill='#1d4ed8')
            x,y=profile_view.xy(root[0],root[1]);r=(spar['diameter']+settings['spar_clearance'])/2*profile_view.scale
            c.create_oval(x-r,y-r,x+r,y+r,fill='#bfdbfe',outline='#1d4ed8',tags='spar_root_section')
            angle=math.degrees(math.atan2(delta[0],delta[2]))
            labels.append(f"{index+1}. {spar['position']:g}% · Ø {spar['diameter']:g} · L {spar.get('length',p['span']):g} mm · {angle:.2f}°"+(' Auto' if spar_automatic(spar) else ''))
        if len(labels)>5:labels=labels[:5]+[f'… altri {len(labels)-5} longheroni']
        self.owner.note(c,w*.61,170,'\n'.join(labels) if labels else 'Nessun longherone configurato.',w*.37)
        c.create_text(16,h-43,anchor='w',text='Maniglia alla radice: posizione · Maniglia finale: inclinazione.',fill='#475569')
        c.create_text(16,h-23,anchor='w',text='Vista nominale senza washout · 0° perpendicolare alla radice.',fill='#64748b')

    def press(self,event):
        if self.app.generating or self.view is None or not self.handles:return
        key=min(self.handles,key=lambda k:math.hypot(event.x-self.handles[k][0],event.y-self.handles[k][1]))
        x,y=self.handles[key]
        if math.hypot(event.x-x,event.y-y)<=13:
            p=self.owner.params();spar=self.app.spar_params()['spars'][key[0]]
            self.drag=(key,p,spar,event.x,event.y,self.view)

    def motion(self,event):
        if self.drag is None or self.app.generating:return
        (index,kind),p,spar,x,y,view=self.drag
        if index>=len(self.app.spar_rows):return
        dx=(event.y-y)/view[2];row=self.app.spar_rows[index]
        if kind=='position':
            value=max(.1,min(99.9,spar['position']+100*dx/p['root_chord']))
            row['position'].set(f'{value:.6f}')
        else:
            root,delta=spar_axis(p,spar);length=spar.get('length',p['span'])
            end_x=root[0]+delta[0]*length/p['span']+dx
            angle=math.degrees(math.atan2(end_x-root[0],length))
            angle=max(-84.99,min(84.99,angle))
            row['angle_auto'].set('0');row['angle_deg'].set(f'{angle:.6f}')
        self.owner.draw('spars')

    def release(self,event):
        if self.drag is None:return
        self.drag=None;self.owner.draw('spars')
