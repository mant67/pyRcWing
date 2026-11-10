from mesh_checks import final_mesh_checks
"""Wizard di configurazione; la geometria risiede nel modulo core v91."""
# File revision: 8
import tkinter as tk
import copy
from tkinter import ttk, filedialog, messagebox, simpledialog
import queue
import threading
from core import *
from sections import SectioningPanel
from previews import WizardPreviews, draw_servo_dimensions
from aileron_ui import HorizontalView
from servo import SERVO_NAMES, SERVO_CATALOG_PATH, SERVO_PRESET_FIELDS, load_servo_catalog, validate_servo_preset
from planform_ui import PlanformEditor

from configuration import ConfigurationMixin, write_configuration

from menu import MenuMixin
from airfoil_editor import AirfoilEditor

class App(MenuMixin,ConfigurationMixin,tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("pyRcWing v"+VERSION)
        self.geometry(f"{min(1100,max(900,self.winfo_screenwidth()-80))}x{min(920,max(600,self.winfo_screenheight()-100))}")
        self.minsize(900,600)
        self.step_names=('Stampa zero retrazioni','Geometria','Washout','Punta','Longheroni',
                         'Alettone e chiusure','Asole cerniere','Servo','Diedro e raccordo','Sezionatura 2D','Riepilogo ed esportazione')
        header=ttk.Frame(self,padding=(16,12));header.pack(fill='x')
        ttk.Label(header,text='pyRcWing v'+VERSION,font=('Segoe UI',18,'bold')).pack(anchor='w')
        self.step_label=tk.StringVar()
        ttk.Label(header,textvariable=self.step_label,font=('Segoe UI',11)).pack(anchor='w',pady=(6,0))
        navigation=ttk.Frame(self,padding=12);navigation.pack(side='bottom',fill='x')
        self.back_button=ttk.Button(navigation,text='← Indietro',command=lambda:self.show_step(self.step_index-1))
        self.back_button.pack(side='left')
        self.next_button=ttk.Button(navigation,text='Avanti →',command=lambda:self.show_step(self.step_index+1))
        self.next_button.pack(side='right')
        self.step_picker=ttk.Combobox(navigation,values=self.step_names,state='readonly',width=32)
        self.step_picker.pack(side='right',padx=16)
        self.step_picker.bind('<<ComboboxSelected>>',lambda event:self.show_step(self.step_picker.current()))
        style=ttk.Style(self);style.layout('Wizard.TNotebook.Tab',[])
        self.tabs=ttk.Notebook(self,style='Wizard.TNotebook');self.tabs.pack(fill='both',expand=True)
        self.pages=[];self.page_canvases=[]
        for name in self.step_names:
            page=ttk.Frame(self.tabs);self.tabs.add(page,text=name)
            canvas=tk.Canvas(page,highlightthickness=0)
            scrollbar=ttk.Scrollbar(page,orient='vertical',command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
            content=ttk.Frame(canvas,padding=16)
            window=canvas.create_window((0,0),window=content,anchor='nw')
            content.bind('<Configure>',lambda event,c=canvas:c.configure(scrollregion=c.bbox('all')))
            canvas.bind('<Configure>',lambda event,c=canvas,w=window:c.itemconfigure(w,width=event.width))
            self.pages.append(content);self.page_canvases.append(canvas)
        self.step_index=0
        self.bind('<MouseWheel>',lambda event:self.page_canvases[self.step_index].yview_scroll(-int(event.delta/120),'units'))
        self.wing_tab=self.pages[1];self.connector_tab=self.pages[8]
        root=self.pages[1]
        body=ttk.Frame(root); body.pack(fill="x", pady=(0,8))
        left=ttk.LabelFrame(body,text="Geometria ala",padding=10); left.pack(side="left",fill="both",expand=True,padx=(0,6))
        right=ttk.LabelFrame(body,text="Nervature e alleggerimenti",padding=10); right.pack(side="left",fill="both",expand=True,padx=(6,0))
        fields=[
            (left,"Semiala Z senza punta (mm)","span","200"),
            (left,"Corda radice (mm)","root_chord","180"),
            (left,"Corda estremità (mm)","tip_chord","120"),
            (left,"Freccia bordo attacco (mm)","sweep","15"),
            (left,"NACA radice (4 cifre)","airfoil","2412"),
            (left,"NACA estremità (4 cifre)","airfoil_tip","2412"),
            (left,"Punti profilo","points","20"),
            (left,"Stazioni lungo Z","stations","8"),
            (right,"Pareti alloggiamenti asole (mm)","line_width","0.4"),
            (right,"Passo nervature (mm)","rib_pitch","40"),
            (right,"Angolo diagonali (°)","rib_angle","45"),
            (right,"Numero ovali per nervatura","hole_count","3"),
            (right,"Lunghezza ovale (mm)","hole_width","18"),
            (right,"Altezza ovale (mm)","hole_height","10"),
        ]
        self.vars={'custom_airfoil_root':tk.StringVar(value=''),'custom_airfoil_tip':tk.StringVar(value='')}
        for key in ('tip_nodes','aileron_nodes'):self.vars[key]=tk.StringVar()
        self.airfoil_editors={'airfoil':AirfoilEditor(self,'root'),'airfoil_tip':AirfoilEditor(self,'tip')}
        self.geometry_labels={}
        self.vars['create_ribs']=tk.StringVar(value='1')
        self.vars['nervature_specchiate_ala']=tk.StringVar(value='0')
        self.rib_entries=[]
        self.oval_entries=[]
        self.vars['create_oval_holes']=tk.StringVar(value='0')
        ttk.Checkbutton(right,text='Crea nervature interne',variable=self.vars['create_ribs'],onvalue='1',offvalue='0',command=self.toggle_ribs).pack(anchor='w',pady=(0,8))
        self.mirror_ribs_check=ttk.Checkbutton(right,text='Nervature specchiate (ala e alettone)',variable=self.vars['nervature_specchiate_ala'],onvalue='1',offvalue='0')
        self.mirror_ribs_check.pack(anchor='w',pady=(0,8))
        ttk.Label(right,text='Seconda famiglia con inclinazione opposta e protezioni agli incroci; verifica PrusaSlicer opzionale prima del salvataggio STL.',wraplength=380).pack(anchor='w',pady=(0,6))
        ttk.Label(right,text='La scelta vale per ala, punta e alettone.',wraplength=380).pack(anchor='w',pady=(0,8))
        self.oval_check=ttk.Checkbutton(right,text='Alleggerimenti con fori ovali',variable=self.vars['create_oval_holes'],onvalue='1',offvalue='0',command=self.toggle_ribs)
        self.oval_check.pack(anchor='w',pady=(0,8))
        for parent,label,key,val in fields:
            row=ttk.Frame(parent); row.pack(fill="x",pady=3)
            self.geometry_labels[key]=ttk.Label(row,text=label,width=24 if key in ('airfoil','airfoil_tip') else 29)
            self.geometry_labels[key].pack(side="left")
            v=tk.StringVar(value=val); self.vars[key]=v
            entry=(ttk.Spinbox(row,textvariable=v,width=14,from_=1,to=50,increment=1) if key=="hole_count" else ttk.Entry(row,textvariable=v,width=14))
            if key in ('airfoil','airfoil_tip'):
                ttk.Button(row,text='Editor…',command=self.airfoil_editors[key].open,width=10).pack(side='right',padx=(6,0))
                entry.configure(width=9);entry.pack(side='right')
            else:entry.pack(side="right",fill="x",expand=True)
            if key in ('rib_pitch','rib_angle'):self.rib_entries.append(entry)
            if key in ('hole_count','hole_width','hole_height'):self.oval_entries.append(entry)
        self.vars['create_ribs'].trace_add('write',lambda *_:self.toggle_ribs())
        self.vars['create_oval_holes'].trace_add('write',lambda *_:self.toggle_ribs())
        self.toggle_ribs()
        ttk.Label(right,text='Da 1 a 50 posizioni per nervatura, uniformi tra il 22% e il 74% della corda (una sola: 48%). Le posizioni incompatibili con bordi, sedi e scassi sono escluse. Percorso verificabile con PrusaSlicer abilitando la verifica opzionale.',wraplength=380).pack(anchor='w',pady=(6,0))
        previews=ttk.Frame(root)
        previews.pack(fill='x',pady=8)
        previews.columnconfigure((0,1),weight=1,uniform='geometry_preview')
        profiles=ttk.LabelFrame(previews,text='Profili alari')
        profiles.grid(row=0,column=1,sticky='nsew',padx=(4,0))
        self.profile_canvas=tk.Canvas(profiles,height=220,width=300,background='white',highlightthickness=1,highlightbackground='#cbd5e1')
        self.profile_canvas.pack(fill='both',expand=True,padx=4,pady=4)
        self.profile_canvas.bind('<Configure>',lambda event:self.draw_profile_preview())
        for key in ('airfoil','airfoil_tip','custom_airfoil_root','custom_airfoil_tip','root_chord','tip_chord'):self.vars[key].trace_add('write',lambda *_:self.draw_profile_preview())
        self.draw_profile_preview()
        plan=ttk.LabelFrame(previews,text='Pianta alare')
        plan.grid(row=0,column=0,sticky='nsew',padx=(0,4))
        self.planform_editor=PlanformEditor(self,plan,left)
        root=self.pages[2]
        box=ttk.LabelFrame(root,text='Svergolamento progressivo dell’ala (washout)',padding=12)
        box.pack(fill='x')
        for label,key,value in (('Washout finale (gradi)','washout_deg','2'),
                                ('Inizio dalla radice (mm)','washout_start','60'),
                                ('Perno (% corda dal bordo d’attacco)','washout_pivot_perc','25')):
            row=ttk.Frame(box);row.pack(fill='x',pady=7)
            ttk.Label(row,text=label,width=44).pack(side='left')
            self.vars[key]=tk.StringVar(value=value)
            ttk.Entry(row,textvariable=self.vars[key],width=12).pack(side='left')
        ttk.Label(box,text='0° disattiva il washout. La rotazione cresce linearmente dall’inizio scelto fino all’estremità della semiala; la punta aggiuntiva mantiene l’angolo finale. Il perno si trova sulla linea di corda (Y=0). Un valore positivo solleva il bordo d’uscita rispetto al bordo d’attacco.',wraplength=850).pack(anchor='w',pady=10)
        ttk.Label(box,text='Ruota le sezioni complete, comprese nervature, sedi e alettone. Le sedi fuori dal perno seguono lo svergolamento: valutarne l’accoppiamento con longheroni rigidi. Il raccordo centrale mantiene il profilo della radice.',wraplength=850).pack(anchor='w',pady=5)
        self.washout_canvas=tk.Canvas(root,height=230,background='white',highlightthickness=1,highlightbackground='#cbd5e1')
        self.washout_canvas.pack(fill='x',pady=15)
        self.washout_canvas.bind('<Configure>',lambda event:self.draw_washout_preview())
        for key in ('washout_deg','washout_start','washout_pivot_perc','span','airfoil','airfoil_tip','root_chord','tip_chord'):
            self.vars[key].trace_add('write',lambda *_:self.draw_washout_preview())
        self.draw_washout_preview()
        root=self.pages[0]
        vase_box=ttk.LabelFrame(root,text="Spiral Vase a fessure — modalità sperimentale",padding=6)
        vase_box.pack(fill='x',pady=(0,8))
        ttk.Label(vase_box,text='Modalità zero retrazioni attiva. Le chiusure piene dell’alettone usano impostazioni dedicate.').grid(row=0,column=0,columnspan=6,sticky='w')
        fields_vase=(('Diametro ugello (mm)','diametro_ugello','0.4'),('Larghezza linea vaso (mm)','larghezza_linea_vaso','0.55'),
                     ('Altezza strato prova (mm)','altezza_strato_vaso','0.2'),('Fessura invisibile (mm)','fessura_vaso','0.05'))
        for index,(label,key,default) in enumerate(fields_vase):
            self.vars[key]=tk.StringVar(value=default)
            row=1+index//2;col=(index%2)*2
            ttk.Label(vase_box,text=label).grid(row=row,column=col,sticky='w',padx=5,pady=3)
            ttk.Entry(vase_box,textvariable=self.vars[key],width=9).grid(row=row,column=col+1,padx=8)
        self.vars['verifica_prusaslicer']=tk.StringVar(value='0')
        ttk.Checkbutton(vase_box,text='Verifica opzionale zero retrazioni con PrusaSlicer durante l’esportazione',variable=self.vars['verifica_prusaslicer'],onvalue='1',offvalue='0').grid(row=5,column=0,columnspan=6,sticky='w',pady=(8,2))
        ttk.Label(vase_box,text='Disattivata: esporta senza PrusaSlicer mantenendo i controlli geometrici e della mesh. Attiva: richiede PrusaSlicer e blocca l’esportazione se la verifica non passa.',wraplength=850).grid(row=6,column=0,columnspan=6,sticky='w')
        def adapt_nozzle():
            try:nozzle=float(self.vars['diametro_ugello'].get().replace(',','.'))
            except ValueError:return
            self.vars['larghezza_linea_vaso'].set(f'{nozzle*1.375:g}')
            self.vars['altezza_strato_vaso'].set(f'{nozzle*.5:g}')
        ttk.Button(vase_box,text="Adatta valori all’ugello",command=adapt_nozzle).grid(row=3,column=0,sticky='w',pady=4)
        ttk.Button(vase_box,text="Verifica G-code PrusaSlicer…",command=self.analyze_vase_file).grid(row=3,column=2,sticky='w',pady=4)
        ttk.Label(vase_box,text="Punta con nervature opzionali, sedi longheroni a lunghezza indipendente e alettone separato possono essere combinati. Il vano può terminare prima dell’estremità: l’eventuale sbalzo viene mantenuto nel modello, in attesa della futura suddivisione dell’ala. Asole cerniere disponibili anche in Spiral Vase, con interruzione locale delle nervature presso le tasche. "
                  "Esporta anche impostazioni PrusaSlicer senza ritrazioni e rapporto CAD; stampare un corpo alla volta e verificare assenza di travel nel G-code e un provino prima della stampa dell’ala.",
                  wraplength=940).grid(row=4,column=0,columnspan=6,sticky='w',pady=4)
        root=self.pages[3]
        tip_controls = ttk.LabelFrame(root, text="Punta rastremata opzionale — nervature secondo la scelta iniziale", padding=6)
        tip_controls.pack(fill="x", pady=(0,8))
        self.vars['elliptical_tip']=tk.StringVar(value='0')
        self.vars['tip_length']=tk.StringVar(value='40')
        self.vars['wing_center_line_perc']=tk.StringVar(value='25')
        self.tip_check=ttk.Checkbutton(tip_controls,text='Aggiungi punta ellittica',
            variable=self.vars['elliptical_tip'],onvalue='1',offvalue='0')
        self.tip_check.grid(row=0,column=0,columnspan=2,sticky='w',pady=5)
        self.tip_entries=[]
        for row,(key,label) in enumerate((('tip_length','Lunghezza aggiuntiva Z (mm)'),
                                         ('wing_center_line_perc','Linea centrale (% corda estremità, dal bordo d’attacco)')),1):
            ttk.Label(tip_controls,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=6)
            entry=ttk.Entry(tip_controls,textvariable=self.vars[key],width=10,state='disabled')
            entry.grid(row=row,column=1,sticky='w',padx=12,pady=6);self.tip_entries.append(entry)
        def toggle_tip(*_):
            for entry in self.tip_entries:entry.configure(state='normal' if self.vars['elliptical_tip'].get()=='1' else 'disabled')
        self.vars['elliptical_tip'].trace_add('write',toggle_tip)
        self.planform_editor.changed()
        ttk.Label(tip_controls,text='25%: linea al quarto della corda. 50% riproduce la punta centrata delle versioni precedenti. 0% = bordo d’attacco; 100% = bordo d’uscita. La giunzione con la semiala rimane nella stessa posizione. Raccordo continuo e chiusura arrotondata della punta.',wraplength=800).grid(row=3,column=0,columnspan=2,sticky='w',padx=6,pady=6)
        ttk.Label(tip_controls,text='Longheroni entro la semiala principale').grid(row=4,column=0,columnspan=2,sticky='w',padx=6,pady=6)
        root=self.pages[5]
        aileron_frame=ttk.LabelFrame(root,text="Alettone separato — esportazione dedicata",padding=6)
        aileron_frame.pack(fill="x",pady=(0,8))
        self.vars['crea_alettone']=tk.StringVar(value='1')
        entries=[]
        def toggle_aileron():
            if hasattr(self,'cap_toggle'):self.cap_toggle()
            for entry in entries:entry.configure(state='normal' if self.vars['crea_alettone'].get()=='1' else 'disabled')
            if hasattr(self,'aileron_export_button'):
                self.aileron_export_button.configure(state='normal' if self.vars['crea_alettone'].get()=='1' and not self.generating else 'disabled')
        self.aileron_toggle=toggle_aileron
        ttk.Checkbutton(aileron_frame,text="Crea alettone separato e lascia il vano libero nell’ala",variable=self.vars['crea_alettone'],
                        onvalue='1',offvalue='0',command=toggle_aileron).grid(row=0,column=0,columnspan=6,sticky='w')
        labels=(('Larghezza lato radice (mm)','larghezza_alettone_radice'),
                ('Larghezza lato estremità (mm)','larghezza_alettone_estremita'),
                ('Lunghezza nominale Z (mm)','lunghezza_alettone'),
                ('Distanza dalla radice (mm)','inizio_alettone'),
                ('Gioco lungo cerniera (mm)','gioco_alettone'),
                ('Gioco estremità radice (mm)','gioco_alettone_radice'),
                ('Gioco estremità punta (mm)','gioco_alettone_estremita'),
                ('Angolo smusso (gradi)','angolo_smusso_alettone'))
        for index,(label,key) in enumerate(labels):
            row=1+index//3;column=(index%3)*2
            ttk.Label(aileron_frame,text=label).grid(row=row,column=column,sticky='w',padx=5,pady=3)
            self.vars[key]=tk.StringVar(value=f'{ALET_DEFAULTS.get(key,.5):g}')
            entry_var=self.vars[key]
            if key=='inizio_alettone':
                self.aileron_root_distance=tk.StringVar(value='');entry_var=self.aileron_root_distance
            entry=ttk.Entry(aileron_frame,textvariable=entry_var,width=8)
            entry.grid(row=row,column=column+1,padx=(0,12));entries.append(entry)
        self.vars['chiudi_estremita_alettone']=tk.StringVar(value='0')
        self.vars['spessore_chiusure_alettone']=tk.StringVar(value='0.8')
        cap_entry=ttk.Entry(aileron_frame,textvariable=self.vars['spessore_chiusure_alettone'],width=8,state='disabled')
        def toggle_caps():
            cap_check.configure(state='normal' if self.vars['crea_alettone'].get()=='1' else 'disabled')
            cap_entry.configure(state='normal' if self.vars['chiudi_estremita_alettone'].get()=='1' and self.vars['crea_alettone'].get()=='1' else 'disabled')
        cap_check=ttk.Checkbutton(aileron_frame,text='Chiudi entrambe le estremità dell’alettone: sotto e sopra',
            variable=self.vars['chiudi_estremita_alettone'],onvalue='1',offvalue='0',command=toggle_caps)
        self.cap_toggle=toggle_caps
        cap_check.grid(row=4,column=0,columnspan=3,sticky='w',padx=5)
        ttk.Label(aileron_frame,text='Spessore chiusure Z (mm)').grid(row=4,column=3,sticky='w')
        cap_entry.grid(row=4,column=4,sticky='w')
        ttk.Label(aileron_frame,text='In modalità a labirinto, con chiusure: usare il file .chiusure.ini. Superfici piene e ritrazioni disattivate; stampa a strati, con possibili spostamenti a vuoto. La chiusura superiore può essere a sbalzo.',wraplength=950).grid(row=6,column=0,columnspan=6,sticky='w',pady=4)
        ttk.Label(aileron_frame,text="Distanza dalla radice: posizione reale del primo estremo dell’alettone, minimo metà del gioco radice; azzera il gioco per partire da Z=0. I giochi alle estremità sono separati dalla posizione e dal gioco cerniera. Il bordo d’uscita dell’alettone resta vincolato a quello dell’ala. Le quote nominali sono divise a metà: il vano si allarga e l’alettone si accorcia di metà del rispettivo gioco. Se il vano sbocca su un bordo, non viene aggiunta una parete. Larghezze misurate dal bordo d’uscita. Inizio + lunghezza devono rientrare nell’apertura totale. "
                  "Due STL separati, senza ponticelli. L’alettone viene appoggiato con la propria radice su Z=0; montaggio con cerniere dopo la stampa. "
                  "Punta e sedi longheroni restano utilizzabili. L’eventuale porzione di ala sopra il vano viene mantenuta, anche a sbalzo.",wraplength=960).grid(row=5,column=0,columnspan=6,sticky='w',pady=4)
        root=self.pages[6]
        slot_frame=ttk.LabelFrame(root,text="Asole per le cerniere — coppie abbinate su ala e alettone",padding=6)
        slot_frame.pack(fill="x",pady=(0,8))
        self.vars['crea_asole_cerniere']=tk.StringVar(value='0')
        slot_entries=[]
        def toggle_slots():
            for entry in slot_entries:entry.configure(state='normal' if self.vars['crea_asole_cerniere'].get()=='1' else 'disabled')
        self.hinge_toggle=toggle_slots
        ttk.Checkbutton(slot_frame,text="Crea asole per le cerniere",variable=self.vars['crea_asole_cerniere'],
                        onvalue='1',offvalue='0',command=toggle_slots).grid(row=0,column=0,columnspan=6,sticky='w')
        slot_labels=(('Numero coppie di asole','numero_asole_cerniere'),
                     ('Interasse Z (mm, 0 = automatico)','interasse_asole_cerniere'),
                     ('Lunghezza asole Z (mm)','lunghezza_asole_cerniere'),
                     ('Altezza asole (mm)','altezza_asole_cerniere'),
                     ('Profondità per lato (mm)','profondita_asole_cerniere'),
                     ('Distanza centro sotto estradosso (mm)','distanza_asole_estradosso'),
                     ('Angolo rampe sostegno asole (°)','angolo_rampe_sostegno_asole'))
        for index,(label,key) in enumerate(slot_labels):
            row=1+index//2;column=(index%2)*2
            ttk.Label(slot_frame,text=label).grid(row=row,column=column,sticky='w',padx=5,pady=3)
            self.vars[key]=tk.StringVar(value=f'{ASOLE_DEFAULTS[key]:g}')
            entry=ttk.Entry(slot_frame,textvariable=self.vars[key],width=8,state='disabled')
            entry.grid(row=row,column=column+1,padx=(0,18));slot_entries.append(entry)
        ttk.Label(slot_frame,text="Lunghezza lungo Z; altezza = spessore della linguetta. Distanza misurata dalla linea "
                  "di cerniera sull’estradosso al centro dell’asola. Interasse 0: distribuzione uniforme con margini uguali ai bordi effettivi dell’alettone; "
                  "interasse impostato: gruppo centrato con margini uguali. Rampe prima delle tasche: angolo dalla verticale Z; "
                  "un angolo minore genera una rampa più lunga. Disponibili anche in Spiral Vase; le nervature si interrompono localmente presso le tasche.",wraplength=960).grid(
                  row=5,column=0,columnspan=6,sticky='w',pady=4)
        root=self.pages[7]
        box=ttk.LabelFrame(root,text='Alloggiamento servo e sede per il futuro pannello di chiusura',padding=10)
        box.pack(fill='x')
        self.vars['create_servo_void']=tk.StringVar(value='1')
        self.servo_entries=[]
        ttk.Checkbutton(box,text='Predisponi scasso servo sull’intradosso',variable=self.vars['create_servo_void'],onvalue='1',offvalue='0',command=self.toggle_servo).grid(row=0,column=0,columnspan=4,sticky='w',pady=6)
        self.vars['servo_rotation_axis']=tk.StringVar(value='z')
        try:
            self.servo_catalog=load_servo_catalog()
        except (OSError,ValueError) as exc:
            self.servo_catalog=load_servo_catalog(path=None)
            self.after_idle(lambda error=str(exc):messagebox.showwarning(
                self.tr('Tipo servo'),f'{SERVO_CATALOG_PATH}\n{error}',parent=self))
        initial=next(iter(self.servo_catalog))
        self.vars['servo_type']=tk.StringVar(value=initial)
        self.servo_name=tk.StringVar(value=initial)
        self.vars['servo_type'].trace_add('write',self.sync_servo_name)
        ttk.Label(box,text='Tipo servo').grid(row=1,column=0,sticky='w',pady=5)
        self.servo_type_combo=ttk.Combobox(box,textvariable=self.servo_name,values=tuple(self.servo_catalog),state='readonly',width=20)
        self.servo_type_combo.grid(row=1,column=1,sticky='w');self.servo_type_combo.bind('<<ComboboxSelected>>',lambda event:self.load_servo_preset())
        body=ttk.LabelFrame(box,text='Dimensioni del servo',padding=6)
        cavity=ttk.LabelFrame(box,text='Quote dello scasso',padding=6)
        placement=ttk.LabelFrame(box,text='Posizione e rotazione',padding=6)
        for col,group in enumerate((body,cavity,placement)):
            box.columnconfigure(col,weight=1)
            group.grid(row=3,column=col,sticky='nsew',padx=4,pady=4)
            group.columnconfigure(0,weight=1)
        self.servo_axis_buttons=[]
        labels=((placement,'Centro dalla radice (mm)','servo_dist_root_mm','100'),
                (placement,'Centro dal bordo d’attacco locale (mm)','servo_dist_le_mm','64'),
                (placement,'Offset verso l’intradosso (mm)','servo_dist_depth_mm','10'),
                (placement,'Rotazione attorno a Z','servo_rotate_z_deg','-7'),
                (placement,'Rotazione in pianta (asse Y)','servo_rotate_y_deg','45'),
                (body,'Larghezza corpo X (mm)','servo_width_mm','8.5'),
                (body,'Altezza corpo Y (mm)','servo_height_mm','16'),
                (body,'Lunghezza corpo Z (mm)','servo_length_mm','20'),
                (cavity,'Gioco per lato (mm)','servo_clearance_mm','0.3'),
                (cavity,'Larghezza battuta perimetrale (mm)','servo_lid_lip_mm','2'),
                (cavity,'Profondità sede coperchio (mm)','servo_lid_depth_mm','0.8'))
        for group,label,key,default in labels:
            row=group.grid_size()[1]
            preset=self.servo_catalog[initial]
            self.vars[key]=tk.StringVar(value=f'{preset[key]:g}' if key in preset else default)
            if key.startswith('servo_rotate_'):
                caption=ttk.Radiobutton(group,text=label,variable=self.vars['servo_rotation_axis'],value=key.split('_')[2],command=self.toggle_servo)
                self.servo_axis_buttons.append(caption)
            else:caption=ttk.Label(group,text=label)
            caption.grid(row=row,column=0,sticky='w',padx=3,pady=2)
            entry=ttk.Entry(group,textvariable=self.vars[key],width=8);entry.grid(row=row,column=1,padx=3,pady=2)
            self.servo_entries.append(entry);self.vars[key].trace_add('write',lambda *_:self.draw_servo_preview())
            if key=='servo_rotate_z_deg':self.servo_z_entry=entry
            if key=='servo_rotate_y_deg':self.servo_y_entry=entry
        actions=ttk.Frame(box)
        actions.grid(row=9,column=0,columnspan=4,sticky='w',pady=4)
        self.servo_preset_button=ttk.Button(actions,text='Ricarica parametri del modello',command=self.load_servo_preset)
        self.servo_preset_button.pack(side='left',padx=(0,8))
        self.servo_save_button=ttk.Button(actions,text='Salva modello servo…',command=self.save_servo_preset)
        self.servo_save_button.pack(side='left')
        ttk.Label(box,text='Le misure iniziali sono indicative e modificabili: il peso non identifica un ingombro standard. Le distanze individuano il centro del corpo. Offset positivo sposta il servo verso l’esterno dell’intradosso: in Y il corpo va da −offset ad altezza−offset, prima della rotazione. La battuta segue il profilo inferiore; il pannello di chiusura non viene generato. Se il corpo sporge, il futuro coperchio dovrà prevedere il relativo ingombro oppure andranno adattate misure e offset. Le modalità Z e in pianta sono alternative; l’angolo inattivo viene ignorato.',wraplength=900).grid(row=10,column=0,columnspan=4,sticky='w',pady=8)
        self.servo_canvas=tk.Canvas(root,height=320,background='white',highlightthickness=1,highlightbackground='#cbd5e1')
        self.servo_canvas.pack(fill='x',pady=6);self.servo_canvas.bind('<Configure>',lambda event:self.draw_servo_preview())
        self.vars['create_servo_void'].trace_add('write',lambda *_:self.toggle_servo())
        self.vars['servo_rotation_axis'].trace_add('write',lambda *_:self.toggle_servo())
        self.toggle_servo()
        root=self.pages[4]
        self.spar_tab = ttk.LabelFrame(root, text="Longheroni — numero, posizione, diametro e lunghezza", padding=8)
        self.spar_tab.pack(fill="both", expand=True)
        self.create_spar_ui()
        root=self.pages[10]
        self.summary=tk.StringVar()
        ttk.Label(root,text='Riepilogo configurazione',font=('Segoe UI',15,'bold')).pack(anchor='w',pady=8)
        ttk.Label(root,textvariable=self.summary,wraplength=850,justify='left').pack(anchor='w',pady=12)
        self.status=tk.StringVar(value="Pronto. Imposta i parametri e scegli il file STL.")
        ttk.Label(navigation,textvariable=self.status,wraplength=850).pack(side="top",fill="x",before=self.back_button,pady=(0,8))
        progress_frame=ttk.Frame(navigation)
        self.progress_frame=progress_frame
        self.is_export_operation=False
        self.progress_value=0.
        self.progress_stage='model'
        self.progress_text=tk.StringVar(value='In attesa di esportazione')
        ttk.Label(progress_frame,textvariable=self.progress_text).pack(anchor='w')
        self.progress_bar=ttk.Progressbar(progress_frame,mode='determinate',maximum=100,value=0)
        self.progress_bar.pack(fill='x',pady=(4,0))
        self.operation_name='Esportazione'
        ttk.Label(root,text="Queste esportazioni producono i componenti interi. Per esportare i pezzi usa il pannello Sezionatura 2D.",wraplength=850).pack(anchor="w",pady=6)
        buttons=ttk.Frame(root); buttons.pack(fill="x")
        self.export_button = ttk.Button(buttons,text="Esporta STL ala intera…",command=self.export_stl)
        self.export_button.pack(side="left",padx=(0,8))
        self.aileron_export_button=ttk.Button(buttons,text="Esporta STL alettone intero…",command=lambda:self.export_stl('alettone'))
        self.aileron_export_button.pack(side='left',padx=(0,8))
        self.events = queue.Queue()
        self.generating = False
        ttk.Button(buttons,text="Apri cartella output…",command=self.open_dir).pack(side="left")
        self.last_dir=Path.cwd()
        ttk.Label(root,text="v9.1: larghezza delle giunzioni unificata con la linea del primo pannello. PrusaSlicer opzionale. Spiral Vase sperimentale: verificare ciascun G-code e stampare prima un provino.",foreground="#9b3b22",wraplength=900).pack(anchor="w",pady=(10,0))
        self.create_connector_ui()
        self.section_panel=SectioningPanel(self.pages[9],self)
        self.previews=WizardPreviews(self)
        self.create_configuration_ui()
        self.show_step(0)
        self.setup_menus()

    def draw_profile_preview(self):
        if getattr(self,"loading_configuration",False):return
        canvas=self.profile_canvas;canvas.delete('all');width=max(100,canvas.winfo_width());height=max(120,canvas.winfo_height())
        try:
            p=dict(airfoil=self.vars['airfoil'].get().strip(),airfoil_tip=self.vars['airfoil_tip'].get().strip(),
                   custom_airfoil_root=self.vars['custom_airfoil_root'].get(),custom_airfoil_tip=self.vars['custom_airfoil_tip'].get(),points=80,span=1.)
            root_chord=float(self.vars['root_chord'].get().replace(',','.'))
            tip_chord=float(self.vars['tip_chord'].get().replace(',','.'))
            if not all(math.isfinite(v) and v>0 for v in (root_chord,tip_chord)):
                raise ValueError('Le corde di radice ed estremità devono essere positive e finite.')
            shape=dict(p,root_chord=root_chord,tip_chord=tip_chord,sweep=0.,planform=self.vars['planform'].get() if 'planform' in self.vars else 'trapezoidal')
            if 'planform_nodes' in self.vars:shape['planform_nodes']=self.vars['planform_nodes'].get()
            chords=[planform_section(shape,f)[0] for f in (0.,.5,1.)]
            profiles=[[(x*chord,y*chord) for x,y in section_profile(p,f)]
                      for f,chord in zip((0.,.5,1.),chords)]
            all_points=[point for profile in profiles for point in profile]
            xmin=min(x for x,y in all_points);xmax=max(x for x,y in all_points)
            ymin=min(y for x,y in all_points);ymax=max(y for x,y in all_points)
            scale=min((width-40)/max(.01,xmax-xmin),(height-80)/max(.02,ymax-ymin))
            ox=(width-scale*(xmin+xmax))/2;oy=(height+55+scale*(ymin+ymax))/2
            canvas.create_line(ox,oy,ox+max(chords)*scale,oy,dash=(3,3),fill='#cbd5e1')
            for profile,color,dash,key in zip(profiles,('#2563eb','#64748b','#ea580c'),((),(4,3),()),('root','middle','tip')):
                coords=[coord for x,y in profile+[profile[0]] for coord in (ox+x*scale,oy-y*scale)]
                canvas.create_line(*coords,fill=color,width=2,dash=dash,tags=('profile','profile_'+key))
            def display_profile(code,custom):
                data=json.loads(p[custom]) if p[custom] else {}
                return data.get('name') or (p[code]+' *' if 'upper' in data else p[code])
            labels=(f"Radice {display_profile('airfoil','custom_airfoil_root')} · {root_chord:g} mm",
                    f"Metà apertura · {chords[1]:g} mm",
                    f"Estremità {display_profile('airfoil_tip','custom_airfoil_tip')} · {tip_chord:g} mm")
            for i,(text,color) in enumerate(zip(labels,('#2563eb','#64748b','#ea580c'))):
                canvas.create_text(12,12+i*16,text=text,anchor='w',fill=color,font=('Segoe UI',9),tags='profile_legend')
        except (ValueError,TypeError,ZeroDivisionError,OverflowError) as exc:
            canvas.create_text(width/2,height/2,text=str(exc),width=width-30,fill='#b91c1c',tags='profile_error')

    def toggle_ribs(self):
        if getattr(self,"loading_configuration",False):return
        enabled=self.vars['create_ribs'].get()=='1'
        for entry in self.rib_entries:entry.configure(state='normal' if enabled else 'disabled')
        self.oval_check.configure(state='normal' if enabled else 'disabled')
        self.mirror_ribs_check.configure(state='normal' if enabled else 'disabled')
        for entry in self.oval_entries:entry.configure(state='normal' if enabled and self.vars['create_oval_holes'].get()=='1' else 'disabled')

    def toggle_servo(self):
        if getattr(self,"loading_configuration",False):return
        enabled=self.vars['create_servo_void'].get()=='1'
        for entry in self.servo_entries:entry.configure(state='normal' if enabled else 'disabled')
        for button in self.servo_axis_buttons:button.configure(state='normal' if enabled else 'disabled')
        self.servo_z_entry.configure(state='normal' if enabled and self.vars['servo_rotation_axis'].get()=='z' else 'disabled')
        self.servo_y_entry.configure(state='normal' if enabled and self.vars['servo_rotation_axis'].get()=='y' else 'disabled')
        self.servo_type_combo.configure(state='readonly' if enabled else 'disabled')
        self.servo_preset_button.configure(state='normal' if enabled and self.servo_name.get() in self.servo_catalog else 'disabled')
        self.servo_save_button.configure(state='normal' if enabled else 'disabled')
        self.draw_servo_preview()

    def sync_servo_name(self,*_):
        model=self.vars['servo_type'].get()
        self.servo_name.set(SERVO_NAMES.get(model,model))

    def load_servo_preset(self):
        model=self.servo_name.get()
        if model not in self.servo_catalog:return
        self.vars['servo_type'].set(model)
        for key,value in self.servo_catalog[model].items():
            self.vars[key].set(f'{value:g}')
        self.toggle_servo()

    def save_servo_preset(self):
        title=self.tr('Salva modello servo…')
        current=self.servo_name.get()
        try:
            fields={key:float(self.vars[key].get().replace(',','.')) for key in SERVO_PRESET_FIELDS}
            validate_servo_preset(current,fields)
            catalog=load_servo_catalog()
            previous=catalog.get(current)
            if previous==fields:
                messagebox.showinfo(title,self.tr('I parametri del modello sono già salvati.'),parent=self)
                return
            update=False
            if previous is not None:
                choice=messagebox.askyesnocancel(title,self.tr(
                    'I parametri sono cambiati. Sì aggiorna il modello attuale. No crea un nuovo modello.'),parent=self)
                if choice is None:return
                update=choice
            name=current
            while not update:
                entered=simpledialog.askstring(title,self.tr('Nome del nuovo modello servo'),parent=self)
                if entered is None:return
                name=entered.strip()
                catalog=load_servo_catalog()
                if any(name.casefold()==existing.casefold() for existing in catalog):
                    messagebox.showwarning(title,self.tr('Esiste già un modello con questo nome.'),parent=self)
                    continue
                try:
                    validate_servo_preset(name,fields)
                except ValueError as exc:
                    messagebox.showwarning(title,str(exc),parent=self)
                    continue
                break
            if update:
                catalog=load_servo_catalog()
                if catalog.get(name)!=previous:
                    raise ValueError(self.tr('Il modello è cambiato su disco. Riapri il salvataggio.'))
            catalog[name]=fields
            SERVO_CATALOG_PATH.parent.mkdir(parents=True,exist_ok=True)
            write_configuration(SERVO_CATALOG_PATH,catalog)
        except (OSError,ValueError) as exc:
            messagebox.showerror(title,str(exc),parent=self)
            return
        self.servo_catalog=catalog
        self.servo_type_combo.configure(values=tuple(catalog))
        self.vars['servo_type'].set(name)
        self.toggle_servo()
        self.status.set(self.tr('Modello servo salvato.'))

    def draw_servo_preview(self):
        if getattr(self,"loading_configuration",False):return
        if not hasattr(self,'servo_canvas') or not hasattr(self,'section_panel'):return
        canvas=self.servo_canvas;canvas.delete('all');width=max(600,canvas.winfo_width())
        try:
            p=params_from_ui(self.vars);layout=servo_layout(p)
            if not layout:
                canvas.create_text(20,30,anchor='w',text='Scasso servo disattivato.');return
            outline=[(x,z) for z,x in planform_outline(p)]
            view=HorizontalView((24,48,width*.43-20,214),outline)
            xy=view.xy
            canvas.create_polygon(*[v for point in outline for v in xy(*point)],fill='#e2e8f0',outline='#64748b')
            for key,color in (('outer_bounds','#d97706'),('inner_bounds','#dc2626')):
                coords=[]
                for x,z in servo_footprint(layout,key,closed=True):
                    xx,yy,zz=washout_point(p,(x,servo_surface(p,z,x),z));coords.extend(xy(xx,zz))
                canvas.create_line(*coords,fill=color,width=2,tags='servo')
            canvas.create_text(20,20,anchor='nw',text='Scasso servo sull’intradosso · posizione in pianta',fill='#475569',font=('Segoe UI',9))
            draw_servo_dimensions(canvas,layout,width*.46,width-24,p)
            canvas.create_text(20,231,anchor='nw',width=width*.43-25,font=('Segoe UI',9),text=f"Rosso: accesso · arancio: sede coperchio\nRotazione: {'in pianta (Y)' if layout['servo_rotation_axis']=='y' else 'asse Z'} {layout['servo_rotate_y_deg'] if layout['servo_rotation_axis']=='y' else layout['servo_rotate_z_deg']:g}°\nSporgenza corpo stimata: {layout['protrusion_under_mm']:.1f} mm\nMargine verso estradosso: {layout['upper_margin_mm']:.1f} mm",fill=('#b91c1c' if layout['upper_margin_mm']<.715 else '#334155'))
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
            canvas.create_text(20,30,anchor='nw',text=str(exc),width=width-40,fill='#b91c1c',tags='servo_preview_error')

    def draw_washout_preview(self):
        if getattr(self,"loading_configuration",False):return
        canvas=self.washout_canvas;canvas.delete('all');width=max(600,canvas.winfo_width());height=230
        try:
            p={k:v.get().strip() for k,v in self.vars.items()}
            for key in ('span','root_chord','tip_chord'):
                p[key]=float(p[key].replace(',','.'))
                if not math.isfinite(p[key]) or p[key]<=0:raise ValueError('Apertura e corde devono essere positive e finite.')
            w=washout_parameters(p);angle=math.radians(w['washout_deg'])
            cr,ct=p['root_chord'],p['tip_chord'];pivot=ct*w['washout_pivot_perc']/100
            root=[(x*cr,y*cr) for x,y in airfoil_profile(p,'root',80)]
            tip=[(x*ct,y*ct) for x,y in airfoil_profile(p,'tip',80)]
            c,s=math.cos(angle),math.sin(angle)
            rotated=[(pivot+(x-pivot)*c-y*s,(x-pivot)*s+y*c) for x,y in tip]
            all_points=root+tip+rotated+[(pivot,0.)]
            xmin=min(x for x,y in all_points);xmax=max(x for x,y in all_points)
            ymin=min(y for x,y in all_points);ymax=max(y for x,y in all_points)
            scale=min((width-48)/max(.01,xmax-xmin),(height-120)/max(.01,ymax-ymin))
            ox=width/2-(xmin+xmax)*scale/2;oy=120+(ymin+ymax)*scale/2
            canvas.create_line(ox,oy,ox+max(cr,ct)*scale,oy,dash=(3,3),fill='#cbd5e1')
            for points,color,dash,tag in ((root,'#64748b',(),'washout_root'),(tip,'#ea580c',(4,3),'riferimento'),(rotated,'#2563eb',(),'washout')):
                canvas.create_line(*[v for x,y in points+[points[0]] for v in (ox+x*scale,oy-y*scale)],fill=color,width=2,dash=dash,tags=tag)
            x=ox+pivot*scale
            canvas.create_oval(x-4,oy-4,x+4,oy+4,fill='#dc2626',outline='',tags='washout_pivot')
            legends=((f"Radice NACA {p['airfoil']}\nCorda {cr:g} mm",'#64748b'),
                     (f"Estremità NACA {p['airfoil_tip']}\nCorda {ct:g} mm · senza washout",'#ea580c'),
                     (f"Estremità con washout {w['washout_deg']:g}°\nPerno {w['washout_pivot_perc']:g}% della corda terminale",'#2563eb'))
            for i,(text,color) in enumerate(legends):
                canvas.create_text(16+i*(width-32)/3,12,text=text,anchor='nw',width=(width-40)/3,fill=color,font=('Segoe UI',9),tags='washout_legend')
            canvas.create_text(20,193,anchor='nw',width=width-40,text='Scala comune in mm · Profili allineati al bordo d’attacco prima del washout.',fill='#475569',tags='washout_note')
            canvas.create_text(20,213,anchor='nw',width=width-40,text=f"Inizio washout a {w['washout_start']:g} mm; angolo finale a {p['span']:g} mm dalla radice.",fill='#475569',tags='washout_note')
        except (ValueError,KeyError,TypeError,ZeroDivisionError,OverflowError) as exc:
            canvas.create_text(20,40,anchor='w',text=str(exc),fill='#b91c1c',width=width-40,tags='washout_error')

    def begin_operation(self,label):
        self._schedule_ui_update()
        if getattr(self,'_configuration_progress_hide',None) is not None:
            self.after_cancel(self._configuration_progress_hide);self._configuration_progress_hide=None
        self.generating=True
        for button in self.configuration_buttons:button.configure(state='disabled')
        self.section_panel.set_busy(True)
        self.operation_name=label
        self.is_export_operation=label.startswith('Esportazione')
        self.progress_value=0.
        self.progress_stage='model'
        self.progress_frame.pack_forget()
        self.status.set(label+' in corso…')
        for button in (self.export_button,self.aileron_export_button,self.connector_button):
            button.configure(state='disabled')
        if self.is_export_operation:
            self.progress_frame.pack(side='top',fill='x',before=self.back_button,pady=(0,8))
            self.update_operation_progress('model')

    def queue_export_progress(self,stage,completed=None,total=None):
        self.events.put(('export_progress',(stage,completed,total)))

    def update_model_progress(self,message):
        if not self.is_export_operation or self.progress_stage!='model':return
        text=message.lower()
        milestones=(('solido nominale',1),('radici inclinate',1),
                    ('punta ellittica',2),('canali coassiali',2),('separazione del vano',2),
                    ('nervature e setti',3),('fessure delle nervature',3),('ricalcolo separato',3),
                    ('contorni',4))
        for token,step in milestones:
            if token in text:
                self.update_operation_progress('model',step,5)
                break

    def update_operation_progress(self,stage,completed=None,total=None):
        if not self.is_export_operation:return
        # Quote delle fasi del lavoro, non una stima del tempo trascorso/residuo.
        stages={'model':(1,'Preparazione del modello',0,20),
                'triangulation':(2,'Triangolazione STL',20,40),
                'vertices':(3,'Verifica dei vertici',40,55),
                'mesh_check':(3,'Verifica chiusura e orientamento',55,60),
                'mesh_sections':(4,'Verifica sezioni sulla mesh finale',73,75),
                'washout':(4,'Applicazione washout',60,70),
                'write':(4,'Scrittura del file STL',70,80),
                'slicer':(5,'Verifica zero retrazioni',80,90),
                'reports':(5,'Salvataggio impostazioni e rapporti',90,100)}
        number,text,start,end=stages[stage]
        fraction=max(0,min(1,completed/total)) if completed is not None and total is not None and total>0 else 0
        self.progress_value=max(self.progress_value,start+(end-start)*fraction)
        self.progress_stage=stage
        self.progress_bar.configure(mode='determinate',value=self.progress_value)
        self.progress_text.set(f'{self.operation_name} — Fase {number}/5: {text} — {self.progress_value:.0f}% (avanzamento fasi)')

    def finish_operation(self,success):
        self._schedule_ui_update()
        for button in self.configuration_buttons:button.configure(state='normal')
        if not self.is_export_operation:return
        if success:self.progress_value=100.
        self.progress_bar.configure(mode='determinate',value=self.progress_value)
        self.progress_text.set(self.operation_name+(' completata — 100%' if success else ' non completata — errore'))

    def show_step(self,index):
        index=max(0,min(len(self.pages)-1,index))
        self.step_index=index
        self.tabs.select(index)
        self.step_label.set(f'Passo {index+1} di {len(self.pages)} — {self.step_names[index]}')
        self.step_picker.current(index)
        self.back_button.configure(state='disabled' if index==0 else 'normal')
        self.next_button.configure(state='disabled' if index==len(self.pages)-1 else 'normal')
        if index==7:self.draw_servo_preview()
        if index==8:self.refresh_connector_summary()
        if index==9:self.section_panel.refresh()
        if index==10:self.refresh_summary()
        if hasattr(self,'previews'):self.previews.redraw_visible()

    def refresh_summary(self):
        try:
            p=params_from_ui(self.vars);p.update(self.spar_params())
            # Valida anche interferenze e lunghezze dei longheroni.
            vase_parameters(p)
            a=aileron_parameters(p);caps=aileron_cap_parameters(p);slots=hinge_slot_parameters(p);servo=servo_parameters(p)
            lines=[f"Pianta: {'ellittica con terminale finito' if elliptical_planform(p) else 'trapezoidale'}",f"NACA {p['airfoil']} → {airfoil_tip_code(p)} | Semiala {p['span']:g} mm | Corde {p['root_chord']:g} / {p['tip_chord']:g} mm",
                   (f"Punta: {p['tip_length']:g} mm | Linea centrale: {tip_center_percentage(p):g}% dal bordo d’attacco" if p['elliptical_tip'] else 'Punta disattivata')+f" | Sedi longheroni: {len(p['spars'])}",
                   f"Ugello {float(p['diametro_ugello'].replace(',','.')):g} mm | Linea {float(p['larghezza_linea_vaso'].replace(',','.')):g} mm | Strato {float(p['altezza_strato_vaso'].replace(',','.')):g} mm",
                   (('Nervature ala, punta e alettone: attive' + (' · specchiate' if wing_mirrored_enabled(p) else '')) if wing_ribs_enabled(p) else 'Nervature ala, punta e alettone: disattivate'),
                   f"Washout: {p['washout_deg']:g}° | Inizio {p['washout_start']:g} mm | Perno {p['washout_pivot_perc']:g}%",
                   f"Alettone: {'attivo' if a else 'disattivato'} | Asole: {len(slots['centri']) if slots else 0}",
                   ('Servo: disattivato' if not servo else f"Servo tipo {servo['servo_type']}: centro Z={servo['servo_dist_root_mm']:g} mm, dal LE={servo['servo_dist_le_mm']:g} mm; battuta {servo['servo_lid_lip_mm']:g} mm; rotazione {servo['servo_rotation_axis'].upper()} {servo['servo_rotate_y_deg'] if servo['servo_rotation_axis']=='y' else servo['servo_rotate_z_deg']:g}°"),
                   ('Giochi alettone: disattivato' if not a else f"Giochi: cerniera {a['gioco_alettone']:g} mm | radice {a['gioco_alettone_radice']:g} mm | punta {a['gioco_alettone_estremita']:g} mm"),
                   f"Chiusure: {caps['spessore'] if caps else 0:g} mm",
                   'Alettone con chiusure: stampa a strati con .chiusure.ini; ritrazioni disattivate, spostamenti a vuoto possibili.' if caps else 'Esportazione con impostazioni Spiral Vase senza ritrazioni.',
                   'Ogni corpo viene esportato separatamente.']
            oval=oval_parameters(p)
            lines.append(f"Alleggerimenti ovali: fino a {oval['hole_count']} per nervatura, {oval['hole_width']:g} × {oval['hole_height']:g} mm; vincolo zero retrazioni" if oval else 'Alleggerimenti ovali disattivati')
            self.summary.set('\n'.join(lines))
        except (ValueError,TypeError) as exc:self.summary.set('Configurazione da correggere prima dell’esportazione:\n\n'+str(exc))

    def create_connector_ui(self):
        parent=self.connector_tab
        ttk.Label(parent,text='Diedro e raccordo centrale',font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(0,6))
        layout=ttk.Frame(parent);layout.pack(fill='both',expand=True)
        layout.columnconfigure(0,weight=0,minsize=345);layout.columnconfigure(1,weight=1,minsize=330)
        controls=ttk.Frame(layout);controls.grid(row=0,column=0,sticky='nw',padx=(0,12))
        graphic=ttk.LabelFrame(layout,text='Anteprima del raccordo',padding=3);graphic.grid(row=0,column=1,sticky='nsew')
        self.connector_preview_canvas=tk.Canvas(graphic,width=360,height=440,background='white',highlightthickness=0)
        self.connector_preview_canvas.pack(fill='both',expand=True)
        self.connector_vars={'genera_raccordo_centrale':tk.StringVar(value='0')};self.connector_controls=[]
        ttk.Checkbutton(controls,text='Genera raccordo centrale',variable=self.connector_vars['genera_raccordo_centrale'],onvalue='1',offvalue='0').pack(anchor='w',pady=(0,6))
        box=ttk.LabelFrame(controls,text='Dimensioni e innesti',padding=5);box.pack(fill='x')
        labels=(('Diedro per semiala (°)','diedro_semiala'),('Lunghezza innesto (mm)','lunghezza_innesto_longheroni'),
                ('Gioco diametrale (mm)','gioco_innesti_raccordo'),('Spazio sedi e fondi (mm)','spessore_pareti_raccordo'))
        for row,(label,key) in enumerate(labels):
            ttk.Label(box,text=label).grid(row=row,column=0,sticky='w',padx=3,pady=3)
            self.connector_vars[key]=tk.StringVar(value=f'{RACCORDO_DEFAULTS[key]:g}')
            entry=ttk.Entry(box,textvariable=self.connector_vars[key],width=9);entry.grid(row=row,column=1,padx=7,pady=3);self.connector_controls.append(entry)
        self.connector_vars['create_connector_ribs']=tk.StringVar(value='1')
        self.connector_vars['doppio_rinforzo_raccordo']=tk.StringVar(value='1')
        self.connector_vars['nervature_specchiate_raccordo']=tk.StringVar(value='0')
        for text,key in (('Crea nervature interne','create_connector_ribs'),('Doppio rinforzo dei longheroni','doppio_rinforzo_raccordo'),('Nervature specchiate','nervature_specchiate_raccordo')):
            button=ttk.Checkbutton(controls,text=text,variable=self.connector_vars[key],onvalue='1',offvalue='0')
            button.pack(anchor='w',pady=3);self.connector_controls.append(button)
            if key=='nervature_specchiate_raccordo':self.connector_mirror_check=button
        self.connector_summary=tk.StringVar();ttk.Label(controls,textvariable=self.connector_summary,wraplength=330).pack(anchor='w',pady=6)
        self.connector_button=ttk.Button(controls,text='Esporta STL raccordo intero…',command=self.export_connector,state='disabled');self.connector_button.pack(anchor='w',pady=5)
        self.connector_status=tk.StringVar(value='Senza nervature, i longheroni sono facoltativi.')
        ttk.Label(controls,textvariable=self.connector_status,wraplength=330,foreground='#475569').pack(anchor='w',pady=3)
        ttk.Label(controls,text='Profilo di radice e sedi derivano dalla semiala. Senza longheroni, lunghezza innesto e spazio riservato definiscono l’ingombro. Le nervature del raccordo sono indipendenti da quelle dell’ala.',wraplength=330,foreground='#475569').pack(anchor='w',pady=5)
        self.connector_vars['genera_raccordo_centrale'].trace_add('write',lambda *_:self.toggle_connector())
        self.connector_vars['create_connector_ribs'].trace_add('write',lambda *_:self.toggle_connector())
        self.toggle_connector();self.tabs.bind('<<NotebookTabChanged>>',lambda event:self.refresh_connector_summary())

    def toggle_connector(self):
        if getattr(self,"loading_configuration",False):return
        enabled=self.connector_vars['genera_raccordo_centrale'].get()=='1'
        for control in self.connector_controls:
            control.configure(state='normal' if enabled else 'disabled')
        self.connector_mirror_check.configure(state='normal' if enabled and self.connector_vars['create_connector_ribs'].get()=='1' else 'disabled')
        self.connector_button.configure(state='normal' if self.connector_vars['genera_raccordo_centrale'].get()=='1' and not self.generating else 'disabled')
        self.refresh_connector_summary()

    def refresh_connector_summary(self):
        if getattr(self,"loading_configuration",False):return
        if not hasattr(self,'connector_summary'):return
        self.connector_summary.set(f"NACA {self.vars['airfoil'].get()} → {self.vars['airfoil_tip'].get()} · radice {self.vars['root_chord'].get()} mm\n"
                                   f"Longheroni: {self.spar_count.get()} · Nervature: {'attive' if self.connector_vars['create_connector_ribs'].get()=='1' else 'disattivate'}\n"
                                   f"Passo {self.vars['rib_pitch'].get()} mm · angolo {self.vars['rib_angle'].get()}°")

    def connector_inputs(self):
        p={'create_connector_ribs':self.connector_vars['create_connector_ribs'].get(),
           'planform':self.vars['planform'].get(),'ellipse_center_perc':self.vars['ellipse_center_perc'].get()}
        for key in ('span','root_chord','tip_chord','sweep','line_width'):
            try:p[key]=float(self.vars[key].get().replace(',','.'))
            except ValueError as exc:raise ValueError(f"Parametro semiala non valido: {key}.") from exc
            if not math.isfinite(p[key]) or (key!='sweep' and p[key]<=0):raise ValueError(f"Parametro semiala non valido: {key}.")
        p['points']=int(self.vars['points'].get());p['airfoil']=self.vars['airfoil'].get().strip();p['airfoil_tip']=self.vars['airfoil_tip'].get().strip()
        p['custom_airfoil_root']=self.vars['custom_airfoil_root'].get();p['custom_airfoil_tip']=self.vars['custom_airfoil_tip'].get()
        airfoil_tip_code(p)
        for key,default in (('rib_pitch',40.),('rib_angle',45.)):
            p[key]=float(self.vars[key].get().replace(',','.')) if connector_ribs_enabled(p) else default
        p['skin']=p['rib_thickness']=p['line_width']
        connector_structure_parameters(p)
        p.update(self.spar_params())
        if not p['spars'] and connector_ribs_enabled(p):raise ValueError('Con nervature attive, configura almeno un longherone nel passo Longheroni.')
        airfoil_profile(p,'root',p['points']);airfoil_profile(p,'tip',p['points'])
        if p['points']<20:raise ValueError('Usa almeno 20 punti profilo.')
        p.update({key:self.vars[key].get() for key in ('diametro_ugello','larghezza_linea_vaso','altezza_strato_vaso','fessura_vaso','verifica_prusaslicer')})
        p.update({key:value.get() for key,value in self.connector_vars.items()})
        p.update(planform_parameters(p))
        connector_parameters(p)
        return p

    def export_connector(self):
        if self.generating:return
        try:p=self.connector_inputs()
        except Exception as exc:messagebox.showerror('Parametri raccordo non validi',str(exc));return
        path=filedialog.asksaveasfilename(title='Salva raccordo centrale',defaultextension='.stl',
             initialfile='raccordo_centrale_v91.stl',filetypes=[('File STL','*.stl')])
        if not path:return
        self.begin_operation('Esportazione raccordo centrale')
        def worker():
            try:
                with final_mesh_checks():
                    solid,info=build_central_connector(p,lambda msg:self.events.put(('progress',msg)))
                self.events.put(('progress','Esportazione e verifica STL del raccordo…'))
                size=export_verified_stl(solid,path,min(vase_parameters(p)['fessura_vaso']/10,.005),progress=self.queue_export_progress,params=p)
                self.queue_export_progress('reports')
                write_vase_sidecars(p,path)
                self.events.put(('connector_done',(path,size,info)))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
        self.after(100,self.poll_generation)

    def create_spar_ui(self):
        parent = self.spar_tab
        ttk.Label(parent, text="Sedi per barre/tubi inseriti dopo la stampa", font=("Segoe UI",12,"bold")).pack(anchor="w")
        ttk.Label(parent, text="Posizione: distanza dal bordo d’entrata in % della corda. Diametro: barra/tubo da inserire. "
                  "Lunghezza Z: mm dalla radice; vuota = intera semiala. Imposta un numero maggiore di zero per abilitare i campi.",
                  wraplength=850).pack(anchor="w", pady=8)
        controls = ttk.Frame(parent); controls.pack(fill="x")
        ttk.Label(controls, text="Numero longheroni (0 = nessuno)").pack(side="left")
        self.spar_count = tk.StringVar(value="0")
        spinner = ttk.Spinbox(controls, from_=0, to=20, width=5, textvariable=self.spar_count,
                              command=self.refresh_spar_rows)
        spinner.pack(side="left", padx=(8,20))
        spinner.bind("<Return>", lambda event: self.refresh_spar_rows())
        spinner.bind("<FocusOut>", lambda event: self.refresh_spar_rows())
        ttk.Button(controls, text="Aggiorna elenco", command=self.refresh_spar_rows).pack(side="left")
        ttk.Label(controls, text="Gioco diametrale (mm)").pack(side="left", padx=(25,8))
        self.spar_clearance = tk.StringVar(value="0.2")
        ttk.Entry(controls, textvariable=self.spar_clearance, width=8).pack(side="left")
        area=ttk.Frame(parent); area.pack(fill="both", expand=True, pady=10)
        canvas=tk.Canvas(area, height=90, highlightthickness=0)
        scroll=ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        self.spar_rows_frame=ttk.Frame(canvas)
        window=canvas.create_window((0,0), window=self.spar_rows_frame, anchor="nw")
        self.spar_rows_frame.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window,width=event.width))
        self.spar_rows=[]
        self.spar_cache=[]
        self.refresh_spar_rows()
        for key in ('span','root_chord','tip_chord','sweep','planform','ellipse_center_perc'):
            self.vars[key].trace_add('write',lambda *_:self.update_spar_angles())
        ttk.Label(parent,text='Auto conserva la direzione attuale. In manuale: 0° perpendicolare alla radice; positivo verso il bordo d’uscita. Le maniglie regolano posizione e inclinazione.',wraplength=850).pack(anchor='w',pady=6)
        ttk.Label(parent, text="Sedi con lunghezze indipendenti e canali coassiali collegati al profilo. "
                  "Controllare il percorso zero retrazioni nell’anteprima dello slicer.",
                  wraplength=850).pack(anchor="w", pady=8)

    def refresh_spar_rows(self):
        try:
            count=int(self.spar_count.get())
            if not 0 <= count <= 20:
                return
        except ValueError:
            return
        for index, row in enumerate(self.spar_rows):
            values={key:value.get() for key,value in row.items()}
            if index < len(self.spar_cache): self.spar_cache[index]=values
            else: self.spar_cache.append(values)
        for child in self.spar_rows_frame.winfo_children(): child.destroy()
        self.spar_rows=[];self.spar_angle_entries=[]
        for column,text in enumerate(('N.','Posizione (% corda)','Diametro (mm)','Lunghezza Z (mm)','Inclinazione in pianta (°)','Direzione')):
            ttk.Label(self.spar_rows_frame,text=text).grid(row=0,column=column,padx=8,pady=6)
        for index in range(max(1,count)):
            values=dict(position=str(min(25+index*20,85)),diameter='4',length='',angle_deg='',angle_auto='1')
            if index<len(self.spar_cache):values.update(self.spar_cache[index])
            row={key:tk.StringVar(value=value) for key,value in values.items()}
            self.spar_rows.append(row)
            ttk.Label(self.spar_rows_frame,text=str(index+1)).grid(row=index+1,column=0,padx=8,pady=5)
            for column,key in enumerate(('position','diameter','length','angle_deg'),1):
                entry=ttk.Entry(self.spar_rows_frame,textvariable=row[key],width=12,state='normal' if count else 'disabled')
                entry.grid(row=index+1,column=column,padx=8,pady=5)
                if key=='angle_deg':self.spar_angle_entries.append(entry)
            ttk.Checkbutton(self.spar_rows_frame,text='Auto',variable=row['angle_auto'],onvalue='1',offvalue='0',state='normal' if count else 'disabled').grid(row=index+1,column=5,padx=6)
            for key in ('position','angle_auto'):row[key].trace_add('write',lambda *_:self.update_spar_angles())
        self.update_spar_angles()

        if hasattr(self,'previews'):
            self.previews.sync_traces();self.previews.schedule()

    def update_spar_angles(self):
        if getattr(self,'loading_configuration',False):return
        try:count=int(self.spar_count.get())
        except ValueError:count=0
        p={k:v.get() for k,v in self.vars.items()}
        try:
            for key in ('span','root_chord','tip_chord','sweep'):
                p[key]=float(p[key].replace(',','.'))
                if not math.isfinite(p[key]):raise ValueError()
            if p['span']<=0:raise ValueError()
            valid=True
        except (ValueError,TypeError):valid=False
        for row,entry in zip(self.spar_rows,self.spar_angle_entries):
            automatic=row['angle_auto'].get()=='1'
            entry.configure(state='normal' if count and not automatic else 'disabled')
            if automatic and valid:
                try:
                    value=legacy_spar_angle(p,row['position'].get())
                    if math.isfinite(value):row['angle_deg'].set(f'{value:.6f}')
                except (ValueError,TypeError,ZeroDivisionError):pass

    def spar_params(self):
        try: count=int(self.spar_count.get())
        except ValueError as exc: raise ValueError("Numero longheroni intero tra 0 e 20 richiesto.") from exc
        if not 0 <= count <= 20:
            raise ValueError("Numero longheroni compreso tra 0 e 20 richiesto.")
        if max(1,count) != len(self.spar_rows):
            self.refresh_spar_rows()
            raise ValueError("Elenco aggiornato: configura posizione e diametro dei longheroni prima di esportare.")
        spars, clearance=parse_spars([{k:v.get() for k,v in row.items()} for row in self.spar_rows[:count]], self.spar_clearance.get(), float(self.vars["span"].get().replace(",", ".")))
        return dict(spars=spars, spar_clearance=clearance)

    def analyze_vase_file(self):
        if self.generating:return
        try:
            height=float(self.vars['altezza_strato_vaso'].get().replace(',','.'))
            if not math.isfinite(height) or height<=0:raise ValueError('Altezza strato non valida.')
        except ValueError as exc:messagebox.showerror('Analisi G-code',str(exc));return
        path=filedialog.askopenfilename(title='Verifica G-code PrusaSlicer — non esegue la stampa',filetypes=[('G-code testuale','*.gcode *.gco')])
        if not path:return
        self.begin_operation('Analisi G-code')
        def worker():
            try:
                self.events.put(('progress','Analisi travel, ritrazioni e crescita Z nel G-code…'))
                report=analyze_vase_gcode(path,5*height)
                config=Path(path).read_text(encoding='utf-8',errors='replace')
                report['spirale_disattivata']='; spiral_vase = 0' in config
                target=Path(path).with_suffix('.analisi_vaso.json')
                target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                self.events.put(('vase_analysis_done',(str(target),report)))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start();self.after(100,self.poll_generation)

    def wing_for_export(self,p,component):
        enabled=not (component=="alettone" and aileron_cap_parameters(p))
        with final_mesh_checks(enabled):return self._wing_for_export(p,component)

    def _wing_for_export(self,p,component):
        key=json.dumps({k:v for k,v in p.items() if not k.startswith('_')},sort_keys=True)
        cached=self.section_panel.cache.get(component)
        if cached and cached[0]==key:
            p.update(copy.deepcopy(cached[2]))
            self.events.put(('progress','Geometria invariata: riuso del modello già calcolato'))
            self.queue_export_progress('model',5,5)
            return cached[1],p['_verifica_vaso']['nervature']
        solid,count=build_solid(p,lambda msg:self.events.put(('progress',msg)))
        self.section_panel.cache[component]=(key,solid,copy.deepcopy(p))
        return solid,count

    def export_stl(self,component='ala'):
        if self.generating:
            return
        try:
            p=params_from_ui(self.vars)
            p.update(self.spar_params())
            if component=='alettone' and not aileron_parameters(p):
                raise ValueError('Attiva Crea alettone separato prima di esportarlo.')
            p['_componente_esportazione']=component
        except Exception as e:
            messagebox.showerror("Parametri non validi",str(e)); return
        filename='alettone_v91.stl' if component=='alettone' else 'semiala_v91.stl'
        path=filedialog.asksaveasfilename(title="Salva STL "+component,defaultextension=".stl",initialfile=filename,filetypes=[("File STL","*.stl")])
        if not path: return
        self.begin_operation('Esportazione '+('alettone' if component=='alettone' else 'semiala'))
        def worker():
            try:
                solid, rib_count = self.wing_for_export(p,component)
                self.events.put(("progress", "Esportazione e verifica STL…"))
                tolerance=min(vase_parameters(p)['fessura_vaso']/10,.005)
                size = export_verified_stl(solid, path,tolerance=tolerance,progress=self.queue_export_progress,params=p)
                self.queue_export_progress('reports')
                write_vase_sidecars(p,path)
                self.events.put(("caps_done" if component=="alettone" and aileron_cap_parameters(p) else "vase_done", (path, rib_count, size, len(p['spars']) if component=='ala' else 0,component)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self.poll_generation)

    def poll_generation(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event=='sections_progress':
                    self.section_panel.update_progress(data)
                    continue
                if event=='export_progress':
                    self.update_operation_progress(*data)
                    continue
                if event == "progress":
                    self.status.set(data)
                    self.update_model_progress(data)
                    self.connector_status.set(data)
                    continue
                self.finish_operation(event!="error")
                self.generating = False
                self.section_panel.set_busy(False)
                self.export_button.configure(state="normal")
                self.aileron_export_button.configure(state='normal' if self.vars['crea_alettone'].get()=='1' else 'disabled')
                self.toggle_connector()
                if event == "error":
                    self.status.set("Generazione non riuscita")
                    self.connector_status.set(data)
                    messagebox.showerror("Errore durante la generazione", data)
                elif event=='sections_done':
                    self.last_dir=Path(data['directory'])
                    self.status.set(f"{data['component']}: esportati {len(data['files'])} pezzi")
                    messagebox.showinfo('Sezionatura completata',data['directory']+'\n\n'+'\n'.join(data['files'])+'\n\nOgni pezzo ha impostazioni e rapporto dedicati. Stampare i pezzi separatamente e verificare l’anteprima dello slicer.')
                elif event=='vase_analysis_done':
                    path,report=data
                    text=f"Esito: {'continuo nel tratto analizzato' if report['esito'] else 'da correggere'} | Strati: {report['strati_analizzati']} | travel XY: {report['travel_xy']} | ritrazioni: {report['ritrazioni']} | spirale rilevata: {report['movimenti_con_crescita_z']>0}"
                    if report.get('spirale_disattivata'):
                        text=f"Stampa a strati: controllo spirale non applicabile | travel XY: {report['travel_xy']} | ritrazioni: {report['ritrazioni']}. Gli spostamenti a vuoto sono ammessi nelle chiusure."
                    self.status.set(text)
                    messagebox.showinfo('Analisi G-code',text+f"\nRapporto: {path}\n\nEscluse base e transizione (3 strati pieni + transizione, come nel frammento esportato) e ritrazione finale. Non certifica resistenza o fusione del filamento.")
                elif event=='caps_done':
                    path,count,size,spars,component=data;self.last_dir=Path(path).parent
                    self.status.set(f'STL alettone con chiusure creato: {size/1024:.0f} KiB')
                    messagebox.showinfo('Alettone con chiusure',f'{path}\n\nCaricare il file .chiusure.ini nel proprio profilo PrusaSlicer: stampa a strati, chiusure piene sotto e sopra e ritrazioni disattivate. La spirale continua è disattivata; sono possibili spostamenti a vuoto. La chiusura superiore può essere a sbalzo. Verificare l’anteprima.')
                elif event=='vase_done':
                    path,count,size,spars,component=data;self.last_dir=Path(path).parent
                    self.status.set(f"STL {component} Spiral Vase creato: {size/1024:.0f} KiB | fessure: {count} | sedi: {spars}")
                    messagebox.showinfo('STL Spiral Vase',f"{path}\n\nEsportati anche il file impostazioni (.spiral_vase.ini oppure .chiusure.ini) e .verifica_vaso.json.\nApplicare le impostazioni al proprio profilo macchina e verificare il G-code. Il controllo CAD campiona sezioni e transizioni; non sostituisce slicing e prova stampata.")
                elif event=='connector_done':
                    path,size,info=data
                    self.last_dir=Path(path).parent
                    text=f"Raccordo creato: {size/1024:.0f} KiB | diedro {info['diedro_semiala']:g}° per semiala | innesti: {info['numero_innesti']} | nervature: {info.get('numero_nervature',0)} | mesh verificata"
                    self.status.set(text);self.connector_status.set(text)
                    messagebox.showinfo('Raccordo centrale creato',f"{path}\n\nDiedro per semiala: {info['diedro_semiala']:g}°\nInnesti: {info['numero_innesti']}\nNervature: {info.get('numero_nervature',0)}\nLarghezza centrale: {info['larghezza_centrale']:.1f} mm\nSTL orientato su una faccia di radice piana.\nEsportati anche .spiral_vase.ini e .verifica_vaso.json. Applicare il frammento al proprio profilo e verificare il G-code.")
                else:
                    path, rib_count, size, spar_count,component = data
                    self.connector_status.set(f"{component.capitalize()} esportato. Gli altri corpi si esportano separatamente.")
                    self.last_dir = Path(path).parent
                    self.status.set(f"STL creato: {size/1024:.0f} KiB | nervature: {rib_count} | longheroni: {spar_count} | mesh chiusa verificata")
                    messagebox.showinfo("STL creato", f"File: {path}\nNervature: {rib_count}\nSedi longheroni: {spar_count}\nMesh chiusa verificata. Verificare i percorsi nello slicer.")
                self.progress_frame.pack_forget()
                return
        except queue.Empty:
            pass
        self.after(100, self.poll_generation)

    def open_dir(self):
        try: os.startfile(str(self.last_dir))
        except Exception: messagebox.showinfo("Cartella output",str(self.last_dir))


