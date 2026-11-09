"""Interactive root/tip airfoil editor with spline handles and calibrated raster tracing."""
# File revision: 10
import base64
import io
import json
import math
import os
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


HANDLE_X=(0.,.025,.07,.15,.28,.45,.65,.82,1.)
DEFAULT_NACA='2412'
NACA_LIBRARY=('0006','0009','0010','0012','0015','0018','0021','0024',
              '1408','1412','2309','2408','2410','2412','2415','2418','4412','4415','4418','6409')
PREFERENCES_DIR=Path(__file__).resolve().parent/'preferences'
LIBRARY_PATH=PREFERENCES_DIR/'airfoil_profiles.json'


def read_preferences(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        # Older installations saved these files next to the scripts.
        if path.parent!=PREFERENCES_DIR:raise
        legacy=PREFERENCES_DIR.parent/path.name
        return json.loads(legacy.read_text(encoding='utf-8'))


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
    split=(len(profile)-1)//2
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
    if 'upper' not in data and 'lower' not in data and set(data)<= {'notes','name'}:
        return None
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
    if any(abs(points[0][0])>1e-8 or abs(points[-1][0]-1)>1e-8 for points in result.values()):
        raise ValueError('I bordi del profilo devono coincidere con gli estremi della corda.')
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
    if upper[-1][1]<lower[-1][1] or any(u[1]<=l[1] for u,l in zip(upper[1:-1],lower[1:-1])):
        raise ValueError('Il dorso deve rimanere sopra il ventre lungo tutto il profilo.')
    return [tuple(p) for p in upper]+[tuple(lower[-1])]+[tuple(p) for p in reversed(lower[1:-1])]


class AirfoilEditor:
    library_label='Libreria profili'
    save_label='Salva profilo'
    name_label='Nome del profilo:'
    replace_label='Sostituire il profilo già salvato?'
    saved_label='Profilo salvato nella libreria.'
    notes_label='Note del profilo'
    geometry_label='Profilo alare'
    edit_label='Modifica profilo'
    reset_label='Ripristina NACA'
    image_title='Importa immagine del profilo'
    edit_status='Trascina le maniglie per modificare il profilo o lo sfondo per spostarlo.'

    def __init__(self,app,side):
        self.app=app;self.side=side
        self.code_key='airfoil' if side=='root' else 'airfoil_tip'
        self.custom_key='custom_airfoil_root' if side=='root' else 'custom_airfoil_tip'
        self.chord_key='root_chord' if side=='root' else 'tip_chord'
        self.window=None;self.canvas=None;self.controls=None;self.drag=None
        self.mode='edit';self.calibration=[];self.image=None;self.photo=None
        self.image_scale=1.;self.image_origin=[0.,0.];self.image_drag=None
        self.photo_key=None
        self.image_angle=0.
        self.rotation_drag=None
        self.image_pivot=None
        self.pivot_drag=None
        self.calibration_mm=None
        self.calibration_reference=[]
        self.image_locked=False
        self.preferences_path=LIBRARY_PATH.with_name(f'airfoil_editor_{side}.json')
        self.library_path=LIBRARY_PATH

    def save_editor_settings(self):
        data={'geometry':self.window.wm_geometry(),'mode':self.mode}
        if self.image is not None:
            buffer=io.BytesIO()
            self.image.save(buffer,format='PNG')
            try:mm_per_pixel=self.image_scale*self.chord()
            except ValueError:mm_per_pixel=None
            data['background']={
                'png':base64.b64encode(buffer.getvalue()).decode('ascii'),
                'scale':self.image_scale,'mm_per_pixel':mm_per_pixel,
                'origin':self.image_origin,'angle':self.image_angle,'pivot':self.image_pivot,
                'locked':self.image_locked,
                'calibration_mm':self.calibration_mm,'reference':self.calibration_reference,
                'pending_points':self.calibration,
            }
        temporary=None
        try:
            self.preferences_path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.preferences_path.parent,delete=False) as stream:
                temporary=Path(stream.name)
                json.dump(data,stream,allow_nan=False)
            os.replace(temporary,self.preferences_path)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)

    def restore_editor_settings(self):
        try:
            data=read_preferences(self.preferences_path)
        except FileNotFoundError:
            return
        self.window.geometry(data.get('geometry','940x700'))
        background=data.get('background')
        if not background:return
        self.restore_background(background)
        mode=data.get('mode','edit')
        self.set_mode(mode if mode in ('edit','rotate','calibrate') else 'edit')
        if self.mode=='calibrate':
            self.calibration=background.get('pending_points',[])[:1]

    def restore_background(self,background):
        from PIL import Image
        origin=[float(value) for value in background['origin']]
        scale=float(background['scale'])
        if background.get('mm_per_pixel') is not None:
            try:scale=float(background['mm_per_pixel'])/self.chord()
            except ValueError:pass
        angle=float(background.get('angle',0.))
        pivot=background.get('pivot')
        if pivot is not None:
            pivot=tuple(float(value) for value in pivot)
            if len(pivot)!=2 or not all(math.isfinite(value) for value in pivot):
                raise ValueError('Pivot di rotazione non valido.')
        if len(origin)!=2 or not all(math.isfinite(value) for value in (*origin,angle)) or not 1e-12<=scale<=1e6:
            raise ValueError('Trasformazione dello sfondo non valida.')
        with Image.open(io.BytesIO(base64.b64decode(background['png'],validate=True))) as source:
            self.image=source.convert('RGBA')
        self.image_origin=origin
        self.image_scale=scale
        self.image_angle=angle
        self.image_pivot=pivot
        self.image_locked=background.get('locked') is True
        self.calibration_mm=background.get('calibration_mm')
        self.calibration_reference=background.get('reference',[])

    def read_library(self):
        try:
            data=read_preferences(self.library_path)
        except FileNotFoundError:
            return {}
        if not isinstance(data,dict):
            raise ValueError('Libreria dei profili non valida.')
        return data

    def set_profile(self,code,raw=''):
        from core import naca_profile
        reference=naca_profile(code,160)
        controls=parse_controls(raw)
        metadata=json.loads(raw) if raw else {}
        if any(not isinstance(metadata.get(key,''),str) for key in ('name','notes')):
            raise ValueError('Nome o note del profilo non validi.')
        self.code=code
        self.reference=reference
        self.edited=controls is not None
        self.controls=controls or controls_from_profile(reference)
        # Anchor the nose and the midpoint of the trailing edge to the chord.
        # Use a linear correction for profiles saved with movable endpoints.
        nose=sum(self.controls[side][0][1] for side in ('upper','lower'))/2
        tail=sum(self.controls[side][-1][1] for side in ('upper','lower'))/2
        for points in self.controls.values():
            for point in points:
                x,y=point
                point[1]=y-(nose+(tail-nose)*x)
            points[0]=[0.,0.]
        self.profile_name=metadata.get('name','')
        self.notes.delete('1.0','end')
        self.notes.insert('1.0',metadata.get('notes',''))

    def raw_profile(self):
        notes=self.notes.get('1.0','end-1c').strip()
        if len(notes)>2000:
            raise ValueError('Le note del profilo possono contenere al massimo 2000 caratteri.')
        data={}
        if self.edited:
            data={side:[[round(x,8),round(y,8)] for x,y in points]
                  for side,points in self.controls.items()}
        if notes:data['notes']=notes
        if self.profile_name:data['name']=self.profile_name
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':')) if data else ''
        profile_from_controls(raw,160)
        if self.edited:
            try:resolution=max(20,int(self.app.vars['points'].get()))
            except ValueError:resolution=80
            profile_from_controls(raw,resolution)
        return raw

    def select_profile(self,_event=None):
        selection=self.profile_choice.get()
        try:
            if selection in self.library_choices:
                saved=self.library[self.library_choices[selection]]
                self.set_profile(saved['code'],saved['profile'])
            else:
                self.set_profile(selection.removeprefix('NACA '))
        except (ValueError,KeyError,TypeError) as exc:
            messagebox.showerror('Profilo alare',str(exc),parent=self.window)
            return
        self.set_mode('edit')

    def update_choices(self):
        self.library_choices={f'★ {name}':name for name in sorted(self.library,key=str.casefold)}
        codes=sorted(set(NACA_LIBRARY+(self.code,)))
        self.picker.configure(values=[*(f'NACA {code}' for code in codes),*self.library_choices])

    def save_profile(self):
        name=simpledialog.askstring(self.app.tr(self.save_label),self.app.tr(self.name_label),initialvalue=self.profile_name,parent=self.window)
        if not name or not name.strip():return
        name=name.strip()
        if len(name)>100:
            messagebox.showerror(self.save_label,'Usa un nome di massimo 100 caratteri.',parent=self.window)
            return
        old_name=self.profile_name
        self.profile_name=name
        temporary=None
        try:
            raw=self.raw_profile()
            library=self.read_library()
            if name in library and not messagebox.askyesno(self.save_label,self.replace_label,parent=self.window):
                self.profile_name=old_name
                return
            library[name]={'code':self.code,'profile':raw}
            self.library_path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.library_path.parent,delete=False) as stream:
                temporary=Path(stream.name)
                json.dump(library,stream,ensure_ascii=False,indent=2)
            os.replace(temporary,self.library_path)
        except (OSError,ValueError,TypeError) as exc:
            self.profile_name=old_name
            messagebox.showerror(self.save_label,str(exc),parent=self.window)
            return
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
        self.library=library
        self.update_choices()
        self.profile_choice.set(f'★ {name}')
        self.status.set(self.saved_label)
        self.draw()

    def apply(self):
        try:
            raw=self.raw_profile()
            if self.image is not None and not self.apply_angle():
                return
            self.save_editor_settings()
        except (OSError,ValueError,TypeError) as exc:
            messagebox.showerror(self.geometry_label,str(exc),parent=self.window)
            return
        self.apply_profile(raw)
        self.window.destroy()

    def apply_profile(self,raw):
        self.app.vars[self.code_key].set(self.code)
        self.app.vars[self.custom_key].set(raw)
        self.app.draw_washout_preview()
        self.app.planform_editor.changed()
        self.app.refresh_summary()

    def editor_title(self):
        return 'Editor profilo radice' if self.side=='root' else 'Editor profilo estremità'

    def load_current(self):
        code=self.app.vars[self.code_key].get().strip() or DEFAULT_NACA
        self.set_profile(code,self.app.vars[self.custom_key].get())

    def default_choice(self):
        return f'NACA {self.code}'

    def build_geometry_controls(self):
        pass

    def open(self):
        if self.window and self.window.winfo_exists():self.window.lift();return
        title=self.editor_title()
        self.window=tk.Toplevel(self.app);self.window.title(self.app.tr(title));self.window.geometry('940x700');self.window.minsize(760,580)
        self.window.transient(self.app)
        self.window.protocol('WM_DELETE_WINDOW',self.apply)
        self.mode='edit';self.calibration=[];self.drag=None;self.image_drag=None
        self.image=None;self.photo=None;self.photo_key=None
        self.image_locked=False
        self.image_angle=0.;self.rotation_drag=None
        self.image_pivot=None;self.pivot_drag=None
        self.calibration_mm=None;self.calibration_reference=[]
        library_bar=ttk.Frame(self.window,padding=(8,8,8,0));library_bar.pack(fill='x')
        ttk.Label(library_bar,text=self.library_label).pack(side='left',padx=3)
        self.profile_choice=tk.StringVar()
        self.picker=ttk.Combobox(library_bar,textvariable=self.profile_choice,state='readonly',width=32)
        self.picker.pack(side='left',padx=6)
        self.picker.bind('<<ComboboxSelected>>',self.select_profile)
        ttk.Button(library_bar,text=self.save_label,command=self.save_profile).pack(side='left',padx=3)
        ttk.Button(library_bar,text='Chiudi e applica',command=self.apply).pack(side='right',padx=3)
        self.status=tk.StringVar(value=self.edit_status)
        self.build_geometry_controls()
        ttk.Label(self.window,textvariable=self.status,padding=(10,0),wraplength=880).pack(fill='x')
        self.canvas=tk.Canvas(self.window,background='white',highlightthickness=1,highlightbackground='#94a3b8')
        self.canvas.pack(fill='both',expand=True,padx=10,pady=8)
        angle_box=ttk.Frame(self.canvas,padding=3,relief='solid',borderwidth=1)
        self.angle_value=tk.StringVar(value='0')
        self.angle_entry=ttk.Entry(angle_box,textvariable=self.angle_value,width=8)
        self.angle_entry.pack(side='left')
        ttk.Label(angle_box,text='°').pack(side='left',padx=(3,0))
        ttk.Button(angle_box,text='Fine rotazione',command=self.finish_rotation).pack(side='left',padx=(6,0))
        self.angle_entry.bind('<Return>',self.finish_rotation)
        self.angle_entry.bind('<FocusOut>',self.apply_angle)
        self.angle_window=self.canvas.create_window(0,0,window=angle_box,anchor='w',state='hidden')
        ttk.Label(self.window,text='Rotella per lo zoom dello sfondo. Tasto destro per i comandi del profilo e dello sfondo.',padding=(10,0,10,10)).pack(fill='x')
        notes_box=ttk.LabelFrame(self.window,text=self.notes_label,padding=6)
        notes_box.pack(fill='x',padx=10,pady=(0,8))
        self.notes=tk.Text(notes_box,height=3,wrap='word',undo=True)
        self.notes.pack(fill='x')
        try:
            self.load_current()
        except (ValueError,TypeError) as exc:
            messagebox.showerror(self.geometry_label,str(exc),parent=self.window)
            self.window.destroy()
            return
        try:
            self.library=self.read_library()
        except (OSError,ValueError) as exc:
            self.library={}
            messagebox.showerror(self.library_label,str(exc),parent=self.window)
        self.update_choices()
        self.profile_choice.set(f'★ {self.profile_name}' if self.profile_name in self.library else self.default_choice())
        self.image_menu=tk.Menu(self.window,tearoff=False)
        self.canvas.bind('<Button-3>',self.show_image_menu)
        self.canvas.bind('<MouseWheel>',self.zoom_image)
        self.canvas.bind('<Configure>',lambda _e:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.window.bind('<Escape>',self.escape)
        self.window.grab_set()
        try:
            self.restore_editor_settings()
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
            messagebox.showwarning('Impostazioni editor',str(exc),parent=self.window)
        self.sync_angle()
        self.draw()

    def transform(self):
        w=max(500,self.canvas.winfo_width());h=max(360,self.canvas.winfo_height());scale=min(w-100,(h-90)/.32)
        return (w-scale)/2,h/2,scale

    def chord(self):
        chord=float(self.app.vars[self.chord_key].get().replace(',','.'))
        if not math.isfinite(chord) or chord<=0:
            raise ValueError('Imposta una corda positiva nel pannello Geometria.')
        return chord

    def calibration_default(self):
        return self.chord()

    def image_transform(self):
        ox,oy,scale=self.transform()
        return ox+self.image_origin[0]*scale,oy+self.image_origin[1]*scale,self.image_scale*scale

    def image_pixel(self,x,y):
        ox,oy,scale=self.image_transform()
        return self.rotate_vector((x-ox)/scale,(y-oy)/scale,-self.image_angle)

    @staticmethod
    def rotate_vector(x,y,angle):
        radians=math.radians(angle)
        c,s=math.cos(radians),math.sin(radians)
        return c*x-s*y,s*x+c*y

    def image_point(self,x,y):
        ox,oy,scale=self.image_transform()
        dx,dy=self.rotate_vector(x,y,self.image_angle)
        return ox+dx*scale,oy+dy*scale

    def pivot_pixel(self):
        if self.image_pivot is not None:
            return self.image_pivot
        return self.image.width/2,self.image.height/2

    def sync_angle(self):
        self.angle_entry.configure(state='normal' if self.image is not None else 'disabled')
        self.angle_value.set(f'{self.image_angle:.8f}'.rstrip('0').rstrip('.') or '0')

    def apply_angle(self,_event=None):
        if self.image is None or self.image_locked:return True
        try:
            angle=float(self.angle_value.get().replace(',','.'))
            if not math.isfinite(angle):raise ValueError
        except ValueError:
            self.status.set('Inserisci un angolo di rotazione valido.')
            return False
        self.rotate_image(angle)
        return True

    def finish_rotation(self,_event=None):
        if self.apply_angle():
            self.rotation_drag=None
            self.pivot_drag=None
            self.set_mode('edit')
            self.canvas.focus_set()
        else:
            self.angle_entry.focus_set()
        return 'break'

    def escape(self,_event):
        if self.mode=='rotate':
            self.sync_angle()
            return self.finish_rotation()
        self.apply()
        return 'break'

    def rotate_image(self,angle):
        angle=math.remainder(angle,360.)
        if not math.isclose(angle,self.image_angle,abs_tol=1e-8):
            cx,cy=self.pivot_pixel()
            old_x,old_y=self.rotate_vector(cx,cy,self.image_angle)
            new_x,new_y=self.rotate_vector(cx,cy,angle)
            self.image_origin[0]+=(old_x-new_x)*self.image_scale
            self.image_origin[1]+=(old_y-new_y)*self.image_scale
            self.image_angle=angle
            self.draw()
        self.sync_angle()

    def resize_image(self,factor,anchor):
        px,py=self.rotate_vector(*self.image_pixel(*anchor),self.image_angle)
        ox,oy,scale=self.transform()
        new_scale=self.image_scale*factor
        if not math.isfinite(new_scale) or not 1e-12<=new_scale<=1e6:
            self.status.set('Scala dell’immagine fuori intervallo.')
            return False
        self.image_origin=[(anchor[0]-ox)/scale-px*new_scale,(anchor[1]-oy)/scale-py*new_scale]
        self.image_scale=new_scale
        return True

    def show_image_menu(self,event):
        menu=self.image_menu
        menu.delete(0,'end')
        menu.add_command(label=self.app.tr('Carica immagine…'),command=self.import_image,
                         state='disabled' if self.image_locked else 'normal')
        lock_label='Sblocca sfondo' if self.image_locked else 'Blocca sfondo'
        menu.add_command(label=self.app.tr(lock_label),command=self.toggle_image_lock,
                         state='normal' if self.image is not None else 'disabled')
        rotation_command=('Fine rotazione',self.finish_rotation) if self.mode=='rotate' else ('Ruota',lambda:self.set_mode('rotate'))
        commands=(
            rotation_command,
            ('Calibra',self.start_calibration),
            ('Rimuovi immagine',self.remove_image),
        )
        for label,command in commands:
            menu.add_command(label=self.app.tr(label),command=command,
                             state='normal' if self.image is not None and not self.image_locked else 'disabled')
        menu.add_separator()
        menu.add_command(label=self.app.tr(self.edit_label),command=lambda:self.set_mode('edit'))
        menu.add_command(label=self.app.tr(self.reset_label),command=self.reset_geometry)
        self.add_geometry_menu(menu,event)
        try:
            menu.tk_popup(event.x_root,event.y_root)
        finally:
            menu.grab_release()

    def add_geometry_menu(self,menu,event):
        pass

    def toggle_image_lock(self):
        if self.image is None:return
        self.image_locked=not self.image_locked
        self.release(None)
        self.set_mode('edit')

    def zoom_image(self,event):
        if self.image is not None and not self.image_locked and event.delta:
            factor=1.2**max(-10,min(10,event.delta/120))
            if self.resize_image(factor,(event.x,event.y)):
                self.draw()
        return 'break'

    def remove_image(self):
        self.image=None
        self.photo=None
        self.photo_key=None
        self.image_angle=0.
        self.image_pivot=None;self.pivot_drag=None
        self.calibration_mm=None;self.calibration_reference=[]
        self.sync_angle()
        self.set_mode('edit')

    def xy(self,x,y):
        ox,oy,scale=self.transform();return ox+x*scale,oy-y*scale

    def profile_xy(self,cx,cy):
        ox,oy,scale=self.transform();return (cx-ox)/scale,(oy-cy)/scale

    def draw(self):
        if not self.canvas:return
        # Keep the entry widget mapped while redrawing so its focus and
        # selection survive a canvas refresh.
        for item in self.canvas.find_all():
            if item!=self.angle_window:self.canvas.delete(item)
        w=self.canvas.winfo_width();h=self.canvas.winfo_height()
        self.draw_background(w,h)
        self.draw_geometry(w,h)
        self.draw_image_controls(w,h)

    def draw_background(self,w,h):
        if self.image is not None:
            from PIL import Image, ImageTk
            ix,iy,ratio=self.image_transform()
            key=(id(self.image),w,h,ix,iy,ratio,self.image_angle)
            if key!=self.photo_key:
                c,s=self.rotate_vector(1.,0.,self.image_angle)
                rendered=self.image.transform((w,h),Image.Transform.AFFINE,
                    (c/ratio,s/ratio,-(c*ix+s*iy)/ratio,
                     -s/ratio,c/ratio,(s*ix-c*iy)/ratio),resample=Image.Resampling.BILINEAR)
                self.photo=ImageTk.PhotoImage(rendered,master=self.canvas)
                self.photo_key=key
            self.canvas.create_image(0,0,image=self.photo,anchor='nw',tags='background')

    def draw_geometry(self,w,h):
        ox,oy,scale=self.transform()
        self.canvas.create_line(ox,oy,ox+scale,oy,fill='#64748b',dash=(4,3))
        dim_y=h-24
        for x in (ox,ox+scale):
            self.canvas.create_line(x,oy,x,dim_y+5,fill='#64748b',dash=(2,4))
        self.canvas.create_line(ox,dim_y,ox+scale,dim_y,fill='#334155',arrow='both')
        try:dimension=f'{self.chord():g} mm'
        except ValueError:dimension='— mm'
        self.canvas.create_text(ox+scale/2,dim_y-10,text=dimension,fill='#334155',font=('Segoe UI',10,'bold'))
        try:profile=profile_from_controls(json.dumps(self.controls),160) if self.edited else self.reference
        except ValueError as exc:self.status.set(str(exc));profile=[]
        if profile:
            coords=[v for x,y in profile+[profile[0]] for v in self.xy(x,y)]
            self.canvas.create_line(*coords,fill='#1d4ed8',width=2,tags='profile')
        for side,color in (('upper','#dc2626'),('lower','#059669')):
            for index,(x,y) in enumerate(self.controls[side]):
                if index in (0,len(self.controls[side])-1):continue
                cx,cy=self.xy(x,y);r=6
                self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=color,outline='white',width=2,tags=('handle',f'{side}:{index}'))
        self.canvas.create_text(12,12,anchor='nw',text=self.profile_name or f'NACA {self.code}',fill='#334155')

    def draw_image_controls(self,w,h):
        for index,(px,py) in enumerate(self.calibration,1):
            x,y=self.image_point(px,py)
            self.canvas.create_oval(x-5,y-5,x+5,y+5,fill='#7c3aed',outline='white');self.canvas.create_text(x+9,y-9,text=str(index),fill='#7c3aed')
        if self.image is not None and self.mode=='rotate':
            x,y=self.image_point(*self.pivot_pixel())
            self.canvas.create_oval(x-9,y-9,x+9,y+9,outline='#7c3aed',width=2)
            self.canvas.create_line(x-8,y,x+8,y,fill='#7c3aed',width=2)
            self.canvas.create_line(x,y-8,x,y+8,fill='#7c3aed',width=2)
            box_width=self.angle_entry.master.winfo_reqwidth()
            box_x=x+12 if x+12+box_width<=w-4 else x-12-box_width
            box_x=max(4,min(w-box_width-4,box_x))
            self.canvas.coords(self.angle_window,box_x,max(16,min(h-16,y)))
            self.canvas.itemconfigure(self.angle_window,state='normal')
            self.canvas.tag_raise(self.angle_window)
        else:
            self.canvas.itemconfigure(self.angle_window,state='hidden')

    def set_mode(self,mode):
        if self.image_locked:mode='edit'
        self.mode=mode;self.calibration=[]
        messages={'edit':'Sfondo bloccato. Le maniglie restano modificabili.' if self.image_locked else self.edit_status,
                  'rotate':'Trascina la croce per spostare il pivot. Trascina altrove per ruotare.',
                  'calibrate':'Seleziona due punti sull’immagine corrispondenti a una distanza nota.'}
        self.status.set(messages[mode]);self.draw()

    def press(self,event):
        if self.mode=='calibrate':
            px,py=self.image_pixel(event.x,event.y)
            if not (0<=px<self.image.width and 0<=py<self.image.height):
                self.status.set('Seleziona un punto all’interno dell’immagine.')
                return
            self.calibration.append((px,py));self.draw()
            if len(self.calibration)==2:self.finish_calibration()
            return
        if self.mode=='rotate' and self.image is not None:
            x,y=self.image_point(*self.pivot_pixel())
            dx,dy=event.x-x,event.y-y
            if math.hypot(dx,dy)<=12:
                self.pivot_drag=(dx,dy)
            else:
                self.rotation_drag=(x,y,math.atan2(dy,dx),self.image_angle)
            return
        if self.press_geometry(event):return
        if self.image is not None and not self.image_locked:
            px,py=self.image_pixel(event.x,event.y)
            if 0<=px<self.image.width and 0<=py<self.image.height:
                self.image_drag=(event.x,event.y,*self.image_origin)

    def press_geometry(self,event):
        candidates=[]
        for side in ('upper','lower'):
            for index,(x,y) in enumerate(self.controls[side]):
                if index in (0,len(self.controls[side])-1):continue
                cx,cy=self.xy(x,y);candidates.append((math.hypot(event.x-cx,event.y-cy),side,index))
        if candidates and min(candidates)[0]<15:
            self.drag=min(candidates)[1:]
            return True
        return False

    def motion(self,event):
        if self.pivot_drag is not None:
            dx,dy=self.pivot_drag
            self.image_pivot=self.image_pixel(event.x-dx,event.y-dy)
            self.draw()
            return
        if self.rotation_drag:
            x,y,start_angle,initial=self.rotation_drag
            if math.hypot(event.x-x,event.y-y)>2:
                delta=math.atan2(event.y-y,event.x-x)-start_angle
                self.rotate_image(initial+math.degrees(delta))
            return
        if self.image_drag:
            x,y,ox,oy=self.image_drag
            scale=self.transform()[2]
            self.image_origin=[ox+(event.x-x)/scale,oy+(event.y-y)/scale]
            self.draw()
            return
        if self.drag:self.motion_geometry(event)

    def motion_geometry(self,event):
        side,index=self.drag;x,y=self.profile_xy(event.x,event.y);points=self.controls[side]
        x=max(points[index-1][0]+.005,min(points[index+1][0]-.005,x))
        _,top=self.profile_xy(0,20)
        _,bottom=self.profile_xy(0,max(360,self.canvas.winfo_height())-48)
        y=max(max(-.35,bottom),min(min(.35,top),y))
        previous=points[index]
        points[index]=[x,y]
        try:
            profile_from_controls(json.dumps(self.controls),160)
        except ValueError as exc:
            points[index]=previous
            self.status.set(str(exc))
            return
        self.edited=True
        self.status.set('Profilo modificato. Premi Chiudi e applica per aggiornare l’ala.')
        self.draw()

    def release(self,_event):
        self.drag=None;self.image_drag=None;self.rotation_drag=None;self.pivot_drag=None

    def reset_geometry(self):
        self.set_profile(self.code)
        self.profile_choice.set(f'NACA {self.code}')
        self.set_mode('edit')

    def import_image(self):
        path=filedialog.askopenfilename(parent=self.window,title=self.image_title,filetypes=[('Immagini raster','*.png *.jpg *.jpeg *.bmp *.tif *.tiff'),('Tutti i file','*.*')])
        if not path:return
        try:
            from PIL import Image
            with Image.open(path) as source:image=source.convert('RGBA')
            alpha=image.getchannel('A').point(lambda a:round(a*.48));image.putalpha(alpha)
            self.image=image
            self.image_angle=0.
            self.image_pivot=None;self.pivot_drag=None
            self.calibration_mm=None;self.calibration_reference=[]
            w=max(500,self.canvas.winfo_width());h=max(360,self.canvas.winfo_height())
            ox,oy,scale=self.transform()
            self.image_scale=min((w-30)/image.width,(h-30)/image.height)/scale
            self.image_origin=[(15-ox)/scale,(15-oy)/scale]
            self.photo_key=None
            self.sync_angle()
            self.set_mode('edit')
        except Exception as exc:messagebox.showerror('Immagine',str(exc),parent=self.window)

    def start_calibration(self):
        if self.image is None:messagebox.showinfo('Calibrazione','Importa prima un’immagine raster.',parent=self.window);return
        self.set_mode('calibrate')

    def finish_calibration(self):
        a,b=self.calibration;distance=math.hypot(b[0]-a[0],b[1]-a[1])
        if distance<1e-6:
            self.calibration.pop()
            self.status.set('Scegli un secondo punto diverso dal primo.')
            self.draw()
            return
        try:chord=self.chord()
        except ValueError as exc:
            self.set_mode('edit')
            messagebox.showerror('Calibrazione',str(exc),parent=self.window)
            return
        length=simpledialog.askfloat(self.app.tr('Calibrazione'),self.app.tr('Distanza reale tra i due punti (mm):'),
            initialvalue=self.calibration_mm or self.calibration_default(),parent=self.window,minvalue=.001)
        if length is None:
            self.set_mode('edit')
            return
        factor=length/(chord*distance*self.image_scale)
        if self.resize_image(factor,self.image_point(*a)):
            self.calibration_mm=length
            self.calibration_reference=[a,b]
            self.set_mode('edit')
            self.status.set(f'Immagine calibrata: {length:g} mm. Trascinala per allinearla.')
