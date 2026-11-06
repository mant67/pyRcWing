"""Interactive root/tip airfoil editor with spline handles and calibrated raster tracing."""
import json, math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


HANDLE_X=(0.,.025,.07,.15,.28,.45,.65,.82,1.)


def _interp(points,x):
    points=sorted(points)
    if x<=points[0][0]:return points[0][1]
    if x>=points[-1][0]:return points[-1][1]
    for (x0,y0),(x1,y1) in zip(points,points[1:]):
        if x<=x1:
            t=(x-x0)/(x1-x0)
            return y0+(y1-y0)*t
    return points[-1][1]


def controls_from_profile(profile,count=9):
    split=max(range(len(profile)),key=lambda i:profile[i][0])
    upper=profile[:split+1]
    lower=list(reversed(profile[split+1:]))
    if not lower or lower[0][0]>1e-6:lower=[profile[0]]+lower
    if lower[-1][0]<.999:lower.append(profile[split])
    xs=HANDLE_X if count==len(HANDLE_X) else tuple(i/(count-1) for i in range(count))
    return {'upper':[[x,_interp(upper,x)] for x in xs],
            'lower':[[x,_interp(lower,x)] for x in xs]}


def parse_controls(raw):
    if not str(raw or '').strip():return None
    try:data=json.loads(raw)
    except (ValueError,TypeError) as exc:raise ValueError('Dati del profilo personalizzato non validi.') from exc
    if not isinstance(data,dict):raise ValueError('Profilo personalizzato non valido.')
    result={}
    for side in ('upper','lower'):
        values=data.get(side)
        if not isinstance(values,list) or len(values)<4:raise ValueError('Servono almeno quattro maniglie per superficie.')
        points=[]
        for value in values:
            if not isinstance(value,list) or len(value)!=2:raise ValueError('Maniglia del profilo non valida.')
            x,y=map(float,value)
            if not math.isfinite(x+y) or not 0<=x<=1 or abs(y)>.5:raise ValueError('Maniglia del profilo fuori intervallo.')
            points.append([x,y])
        if any(b[0]<=a[0] for a,b in zip(points,points[1:])):raise ValueError('Le maniglie devono procedere dal bordo d’attacco al bordo d’uscita.')
        result[side]=points
    if abs(result['upper'][0][0])>1e-8 or abs(result['lower'][0][0])>1e-8:
        raise ValueError('Il profilo deve iniziare sul bordo d’attacco.')
    return result


def _spline_y(points,x):
    """Cubic Hermite spline through ordered control points."""
    if x<=points[0][0]:return points[0][1]
    if x>=points[-1][0]:return points[-1][1]
    i=next(i for i in range(len(points)-1) if x<=points[i+1][0])
    x0,y0=points[i];x1,y1=points[i+1];h=x1-x0;t=(x-x0)/h
    def slope(j):
        if j==0:return (points[1][1]-points[0][1])/(points[1][0]-points[0][0])
        if j==len(points)-1:return (points[-1][1]-points[-2][1])/(points[-1][0]-points[-2][0])
        return (points[j+1][1]-points[j-1][1])/(points[j+1][0]-points[j-1][0])
    m0,m1=slope(i),slope(i+1)
    return (2*t**3-3*t*t+1)*y0+(t**3-2*t*t+t)*h*m0+(-2*t**3+3*t*t)*y1+(t**3-t*t)*h*m1


def profile_from_controls(raw,n=80,trailing_edge_ratio=0.):
    data=parse_controls(raw)
    if data is None:return None
    xs=[.5*(1-math.cos(math.pi*i/n)) for i in range(n+1)]
    upper=[[x,_spline_y(data['upper'],x)] for x in xs]
    lower=[[x,_spline_y(data['lower'],x)] for x in xs]
    if trailing_edge_ratio>0:
        current=upper[-1][1]-lower[-1][1];extra=max(0.,trailing_edge_ratio-current)
        for up,lo in zip(upper,lower):
            delta=.5*extra*up[0]**8;up[1]+=delta;lo[1]-=delta
    if any(u[1]<=l[1] for u,l in zip(upper[1:-1],lower[1:-1])):
        raise ValueError('Il dorso deve rimanere sopra il ventre lungo tutto il profilo.')
    return [tuple(p) for p in upper]+[tuple(lower[-1])]+[tuple(p) for p in reversed(lower[1:-1])]


class AirfoilEditor:
    def __init__(self,app,side):
        self.app=app;self.side=side
        self.code_key='airfoil' if side=='root' else 'airfoil_tip'
        self.custom_key='custom_airfoil_root' if side=='root' else 'custom_airfoil_tip'
        self.chord_key='root_chord' if side=='root' else 'tip_chord'
        self.window=None;self.canvas=None;self.controls=None;self.drag=None
        self.mode='edit';self.calibration=[];self.image=None;self.photo=None
        self.image_scale=1.;self.image_origin=[0.,0.];self.image_drag=None

    def open(self):
        if self.window and self.window.winfo_exists():self.window.lift();return
        from core import naca_profile
        title='Editor profilo radice' if self.side=='root' else 'Editor profilo estremità'
        self.window=tk.Toplevel(self.app);self.window.title(title);self.window.geometry('940x650');self.window.minsize(760,540)
        bar=ttk.Frame(self.window,padding=8);bar.pack(fill='x')
        ttk.Button(bar,text='Importa immagine…',command=self.import_image).pack(side='left',padx=3)
        ttk.Button(bar,text='Calibra con due punti',command=self.start_calibration).pack(side='left',padx=3)
        ttk.Button(bar,text='Sposta sfondo',command=lambda:self.set_mode('move')).pack(side='left',padx=3)
        ttk.Button(bar,text='Modifica profilo',command=lambda:self.set_mode('edit')).pack(side='left',padx=3)
        ttk.Button(bar,text='Ripristina NACA',command=self.reset_naca).pack(side='left',padx=12)
        self.status=tk.StringVar(value='Trascina le maniglie. Il profilo viene aggiornato nella configurazione.')
        ttk.Label(self.window,textvariable=self.status,padding=(10,0),wraplength=880).pack(fill='x')
        self.canvas=tk.Canvas(self.window,background='white',highlightthickness=1,highlightbackground='#94a3b8')
        self.canvas.pack(fill='both',expand=True,padx=10,pady=8)
        ttk.Label(self.window,text='La scala del profilo usa la corda impostata nel pannello Geometria. La calibrazione ridimensiona soltanto l’immagine di ricalco.',padding=(10,0,10,10)).pack(fill='x')
        raw=self.app.vars[self.custom_key].get()
        parsed=parse_controls(raw) if raw.strip() else None
        self.controls=parsed or controls_from_profile(naca_profile(self.app.vars[self.code_key].get(),160))
        self.canvas.bind('<Configure>',lambda _e:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.window.bind('<Escape>',lambda _e:self.window.destroy());self.draw()

    def transform(self):
        w=max(500,self.canvas.winfo_width());h=max(360,self.canvas.winfo_height());scale=min(w-100,(h-90)/.32)
        return 55.,h/2,scale

    def xy(self,x,y):
        ox,oy,scale=self.transform();return ox+x*scale,oy-y*scale

    def profile_xy(self,cx,cy):
        ox,oy,scale=self.transform();return (cx-ox)/scale,(oy-cy)/scale

    def draw(self):
        if not self.canvas:return
        self.canvas.delete('all');w=self.canvas.winfo_width();h=self.canvas.winfo_height()
        if self.image is not None:
            from PIL import ImageTk
            size=(max(1,round(self.image.width*self.image_scale)),max(1,round(self.image.height*self.image_scale)))
            rendered=self.image.resize(size)
            self.photo=ImageTk.PhotoImage(rendered)
            self.canvas.create_image(*self.image_origin,image=self.photo,anchor='nw',tags='background')
        ox,oy,scale=self.transform();self.canvas.create_line(ox,oy,ox+scale,oy,fill='#94a3b8',dash=(4,3))
        raw=json.dumps(self.controls,separators=(',',':'))
        try:profile=profile_from_controls(raw,160)
        except ValueError as exc:self.status.set(str(exc));profile=[]
        if profile:
            coords=[v for x,y in profile+[profile[0]] for v in self.xy(x,y)]
            self.canvas.create_line(*coords,fill='#1d4ed8',width=2,smooth=True,tags='profile')
        for side,color in (('upper','#dc2626'),('lower','#059669')):
            for index,(x,y) in enumerate(self.controls[side]):
                cx,cy=self.xy(x,y);r=6
                self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=color,outline='white',width=2,tags=('handle',f'{side}:{index}'))
        for index,(x,y) in enumerate(self.calibration,1):
            self.canvas.create_oval(x-5,y-5,x+5,y+5,fill='#7c3aed',outline='white');self.canvas.create_text(x+9,y-9,text=str(index),fill='#7c3aed')
        chord=self.app.vars[self.chord_key].get();self.canvas.create_text(12,12,anchor='nw',text=f"NACA base {self.app.vars[self.code_key].get()} · corda {chord} mm",fill='#334155')

    def set_mode(self,mode):
        self.mode=mode;self.calibration=[]
        messages={'edit':'Trascina le maniglie rosse e verdi.','move':'Trascina l’immagine per allinearla al profilo.','calibrate':'Seleziona due punti sull’immagine corrispondenti a una distanza nota.'}
        self.status.set(messages[mode]);self.draw()

    def press(self,event):
        if self.mode=='calibrate':
            self.calibration.append((event.x,event.y));self.draw()
            if len(self.calibration)==2:self.finish_calibration()
            return
        if self.mode=='move' and self.image is not None:self.image_drag=(event.x,event.y,*self.image_origin);return
        candidates=[]
        for side in ('upper','lower'):
            for index,(x,y) in enumerate(self.controls[side]):
                cx,cy=self.xy(x,y);candidates.append((math.hypot(event.x-cx,event.y-cy),side,index))
        if candidates and min(candidates)[0]<15:self.drag=min(candidates)[1:]

    def motion(self,event):
        if self.image_drag:
            x,y,ox,oy=self.image_drag;self.image_origin=[ox+event.x-x,oy+event.y-y];self.draw();return
        if not self.drag:return
        side,index=self.drag;x,y=self.profile_xy(event.x,event.y);points=self.controls[side]
        if index==0:x=0.
        elif index==len(points)-1:x=1.
        else:x=max(points[index-1][0]+.005,min(points[index+1][0]-.005,x))
        y=max(-.35,min(.35,y))
        if index==0:
            self.controls['upper'][0]=[0.,y];self.controls['lower'][0]=[0.,y]
        else:self.controls[side][index]=[x,y]
        self.commit();self.draw()

    def release(self,_event):self.drag=None;self.image_drag=None

    def commit(self):
        raw=json.dumps(self.controls,separators=(',',':'))
        try:profile_from_controls(raw,80)
        except ValueError as exc:self.status.set(str(exc));return
        self.app.vars[self.custom_key].set(raw);self.status.set('Profilo personalizzato attivo e salvato nella configurazione.')

    def reset_naca(self):
        from core import naca_profile
        self.controls=controls_from_profile(naca_profile(self.app.vars[self.code_key].get(),160))
        self.app.vars[self.custom_key].set('');self.status.set('Ripristinato il profilo NACA del campo principale.');self.draw()

    def import_image(self):
        path=filedialog.askopenfilename(parent=self.window,title='Importa immagine del profilo',filetypes=[('Immagini raster','*.png *.jpg *.jpeg *.bmp *.tif *.tiff'),('Tutti i file','*.*')])
        if not path:return
        try:
            from PIL import Image
            image=Image.open(path).convert('RGBA');alpha=image.getchannel('A').point(lambda a:round(a*.48));image.putalpha(alpha)
            self.image=image
            w=max(500,self.canvas.winfo_width());h=max(360,self.canvas.winfo_height())
            self.image_scale=min((w-30)/image.width,(h-30)/image.height);self.image_origin=[15.,15.]
            self.set_mode('move');self.status.set('Immagine caricata. Spostala oppure avvia la calibrazione a due punti.')
        except Exception as exc:messagebox.showerror('Immagine',str(exc),parent=self.window)

    def start_calibration(self):
        if self.image is None:messagebox.showinfo('Calibrazione','Importa prima un’immagine raster.',parent=self.window);return
        self.set_mode('calibrate')

    def finish_calibration(self):
        a,b=self.calibration;distance=math.hypot(b[0]-a[0],b[1]-a[1])
        length=simpledialog.askfloat('Calibrazione','Distanza reale tra i due punti (mm):',parent=self.window,minvalue=.001)
        if not length:self.calibration=[];self.set_mode('edit');return
        chord=float(self.app.vars[self.chord_key].get().replace(',','.'))
        profile_px_per_mm=self.transform()[2]/chord
        original_distance=distance/self.image_scale;new_scale=profile_px_per_mm*length/original_distance
        original_point=((a[0]-self.image_origin[0])/self.image_scale,(a[1]-self.image_origin[1])/self.image_scale)
        self.image_origin=[a[0]-original_point[0]*new_scale,a[1]-original_point[1]*new_scale];self.image_scale=new_scale
        self.calibration=[];self.mode='move';self.status.set(f'Immagine calibrata: {length:g} mm. Trascinala per allinearla.');self.draw()
