"""Menus, safe close handling and persistent UI preferences."""
import copy,json,os,tempfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox,filedialog,ttk
from i18n import translate,install_dialog_translations
from ui_events import install_ui_notifications

PREFERENCES_PATH=Path(__file__).with_name('preferences.json')

class MenuMixin:
    def setup_menus(self):
        self._base_title=self.title()
        self.language=tk.StringVar(value='it')
        try:
            value=json.loads(PREFERENCES_PATH.read_text(encoding='utf-8')).get('language','it')
            if value in ('it','en'):self.language.set(value)
        except (OSError,ValueError,TypeError,AttributeError):pass
        self._translation_cache={};self._translated_sources={};self._menus_ready=True
        self._translating=False;self._ui_update_pending=None
        self._display_var_watches={};self._model_var_watches={}
        install_dialog_translations();install_ui_notifications()
        self.mark_configuration_clean()
        self.protocol('WM_DELETE_WINDOW',self.request_exit)
        self.bind('<Control-o>',lambda event:self.import_configuration())
        self.bind('<Control-s>',lambda event:self.export_configuration())
        self.build_menus();self.translate_widgets()

    def tr(self,text):return translate(str(text),self.language.get())

    def build_menus(self):
        bar=tk.Menu(self,tearoff=False);self.menu_bar=bar
        file=tk.Menu(bar,tearoff=False);self.file_menu=file
        file.add_command(label=self.tr('Importa…'),accelerator='Ctrl+O',command=self.import_configuration)
        file.add_command(label=self.tr('Esporta…'),accelerator='Ctrl+S',command=self.export_configuration)
        file.add_separator();file.add_command(label=self.tr('Esci…'),command=self.request_exit)
        bar.add_cascade(label='File',menu=file)
        prefs=tk.Menu(bar,tearoff=False);languages=tk.Menu(prefs,tearoff=False)
        for label,code in (('Italiano','it'),('English','en')):
            languages.add_radiobutton(label=label,value=code,variable=self.language,command=lambda c=code:self.set_language(c))
        prefs.add_cascade(label=self.tr('Lingua'),menu=languages)
        bar.add_cascade(label=self.tr('Preferenze'),menu=prefs)
        help=tk.Menu(bar,tearoff=False)
        help.add_command(label='Quick Start' if self.language.get()=='en' else 'Uso rapido',command=self.show_quick_help)
        help.add_command(label=self.tr('Informazioni'),command=self.show_about)
        bar.add_cascade(label=self.tr('Guida'),menu=help);self.configure(menu=bar)
        if hasattr(self,'_previous_menu'):
            try:self._previous_menu.destroy()
            except tk.TclError:pass
        self._previous_menu=bar

    def set_language(self,language):
        if language not in ('it','en'):raise ValueError('Unsupported language')
        self.language.set(language);self.build_menus();self.translate_widgets()
        name=None
        try:
            fd,name=tempfile.mkstemp(prefix='.wing_preferences_',suffix='.tmp',dir=PREFERENCES_PATH.parent)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump({'language':language},stream)
            os.replace(name,PREFERENCES_PATH);name=None
        except OSError as exc:messagebox.showerror('Preferenze','Impossibile salvare la preferenza lingua.\n'+str(exc))
        finally:
            if name and os.path.exists(name):os.unlink(name)

    def _semantic_state(self,data=None):
        state=copy.deepcopy(self._configuration_state() if data is None else data)
        for key in ('saved_at','generator_version'):state.pop(key,None)
        for row in state.get('spars',{}).get('rows',[]):
            if row.get('angle_auto')=='1':row['angle_deg']=''
        return state

    def mark_configuration_clean(self,data=None):
        self._saved_configuration_state=self._semantic_state(data)
        self._schedule_ui_update()

    def has_unsaved_changes(self):
        return self._semantic_state()!=self._saved_configuration_state

    def confirm_unsaved_changes(self):
        if not self.has_unsaved_changes():return True
        answer=messagebox.askyesnocancel('Modifiche non salvate','Ci sono parametri non salvati. Vuoi salvarli prima di continuare?',parent=self)
        if answer is None:return False
        if answer is False:return True
        path=self.configuration_path
        if path is None:
            path=filedialog.asksaveasfilename(parent=self,title='Esporta configurazione ala',defaultextension='.json',initialfile='configurazione_ala.json',filetypes=[('Configurazione ala','*.json')])
        if not path:return False
        try:self.save_configuration_file(path)
        except Exception as exc:
            messagebox.showerror('Configurazione non salvata',str(exc),parent=self);return False
        return not self.has_unsaved_changes()

    def request_exit(self):
        if self.generating:
            messagebox.showinfo('Operazione in corso','Attendi il termine dell’operazione prima di uscire.',parent=self);return
        if not messagebox.askokcancel('Esci','Vuoi chiudere pyRcWing?',parent=self):return
        if self.confirm_unsaved_changes():self.destroy()

    def show_quick_help(self):
        english=self.language.get()=='en'
        previous_guard=self._translating;self._translating=True
        help_title='Quick Start' if english else 'Uso rapido'
        dialog=tk.Toplevel(self);dialog.title(help_title);dialog.transient(self);dialog.geometry('820x700');dialog.minsize(620,440)
        outer=ttk.Frame(dialog,padding=12);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='pyRcWing — Quick Start' if english else 'pyRcWing — Guida rapida',font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(0,4))
        ttk.Label(outer,text='Recommended flow: configure each panel in order, review the previews, then export full components or cut pieces.' if english else 'Percorso consigliato: configura dall’inizio alla fine, controlla le anteprime e poi esporta i componenti o i pezzi sezionati.',wraplength=770).pack(anchor='w',pady=(0,10))
        body=ttk.Frame(outer);body.pack(fill='both',expand=True)
        canvas=tk.Canvas(body,highlightthickness=0);scroll=ttk.Scrollbar(body,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        content=ttk.Frame(canvas,padding=(4,2,16,8));window=canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        sections=(
            ('1. Stampa zero retrazioni','Qui si definiscono le condizioni di estrusione usate nei controlli e nei file ausiliari.','Ugello: diametro fisico dell’ugello. Larghezza linea: larghezza nominale di ogni passata, usata anche per dimensionare le giunzioni. Altezza strato: passo verticale consigliato per la modalità Spiral Vase. Fessura invisibile: piccolo spazio che separa i giri e rende possibile il percorso a spirale. “Adatta valori all’ugello” propone larghezza e altezza proporzionate. La verifica PrusaSlicer è opzionale; disattivandola restano attivi i controlli geometrici e della mesh.','vase'),
            ('2. Geometria','Definisce la pianta, i profili e la struttura interna della semiala.','Pianta trapezoidale/ellittica: sceglie come varia la corda lungo Z. Semiala Z: apertura della semiala principale, senza la punta aggiuntiva. Corda radice/estremità: larghezza dei profili ai due capi. Freccia: arretramento del bordo d’attacco. NACA radice/estremità: profili interpolati progressivamente lungo l’apertura. Punti profilo e stazioni: risoluzione del contorno e della variazione geometrica. Linea pareti alloggiamenti: spessore nominale delle sedi. Passo nervature e angolo diagonali: densità e inclinazione della struttura interna. “Crea nervature interne” può essere disattivato. Gli ovali sono aperture di alleggerimento: numero per nervatura, lunghezza e altezza; vengono esclusi se incompatibili con bordi o sedi. Le nervature specchiate aggiungono una famiglia con inclinazione opposta. Nell’editor della pianta, le maniglie regolano corde, freccia e forma e aggiornano i campi.','geometry'),
            ('3. Washout','Descrive la torsione del profilo dalla radice verso la punta.','Washout finale: rotazione in gradi; 0 disattiva la torsione. Inizio dalla radice: coordinata Z da cui parte la rotazione. Perno: percentuale della corda dal bordo d’attacco attorno a cui ruota il profilo. La rotazione aumenta progressivamente dall’inizio fino all’estremità.','washout'),
            ('4. Punta','Aggiunge una terminazione rastremata oltre la semiala principale.','Attiva punta ellittica: abilita o disabilita l’estensione. Lunghezza aggiuntiva Z: quanto prosegue la punta. Linea centrale: percentuale della corda d’estremità che definisce il riferimento della punta. Le maniglie nell’anteprima impostano lunghezza e linea centrale; la punta mantiene la scelta delle nervature del pannello Geometria.','tip'),
            ('5. Longheroni','Predispone canali per barre o tubi da inserire dopo la stampa.','Numero longheroni: quante sedi creare (0 = nessuna). Posizione: percentuale della corda misurata dal bordo d’attacco. Diametro: diametro nominale della barra/tubo. Lunghezza Z: tratto dalla radice; vuoto indica l’intera semiala. Gioco diametrale: spazio tra sede e barra. Inclinazione in pianta: Auto segue la direzione corrente della semiala; manuale permette di immettere gradi, con 0° perpendicolare alla radice e valori positivi orientati verso il bordo d’uscita. Le maniglie consentono di spostare sede e inclinazione.','spars'),
            ('6. Alettone e chiusure','Definisce il vano nell’ala e il componente alettone separato.','Crea alettone: abilita vano e STL separato. Larghezza lato radice/estremità: quanto alettone occupa la corda, misurata dal bordo d’uscita. Lunghezza nominale Z e distanza dalla radice: posizione e apertura del componente. Gioco lungo cerniera: distanza longitudinale tra alettone e ala. Giochi estremità radice/punta: distanze alle due estremità. Angolo smusso: inclinazione del lato mobile per consentire la rotazione. Chiusura estremità: crea le chiusure superiore e inferiore dell’alettone; spessore chiusure Z ne definisce lo spessore. Le maniglie nell’anteprima regolano posizione e dimensioni; il bordo d’uscita resta allineato.','aileron'),
            ('7. Asole cerniere','Crea tasche abbinate per montare le cerniere tra ala e alettone.','Crea asole: abilita la funzione. Numero coppie: quante cerniere distribuire. Interasse Z: distanza tra i centri; 0 distribuisce uniformemente con margini uguali. Lunghezza asole Z: estensione lungo apertura. Altezza asole: spessore della linguetta della cerniera. Profondità per lato: quanto entra ciascuna tasca. Distanza sotto estradosso: quota del centro rispetto alla superficie superiore. Angolo rampe: determina la lunghezza delle rampe che sostengono le tasche.','hinges'),
            ('8. Servo','Predispone l’alloggiamento del servo e la sede per un futuro coperchio.','Predisponi scasso: abilita la cavità. Tipo servo: preset indicativo, sempre modificabile. Centro dalla radice e dal bordo d’attacco: posizione del corpo. Rotazione Z o in pianta Y: modalità mutuamente esclusive; l’angolo dell’asse non selezionato viene ignorato. Offset profondità: sposta il servo rispetto all’intradosso. Larghezza, altezza e lunghezza corpo: ingombro del servo. Gioco per lato: tolleranza attorno al corpo. Larghezza battuta e profondità sede coperchio: dimensioni del gradino per il pannello, che non viene generato in questa versione. I preset non sono misure standard: controlla le quote reali del tuo servo.','servo'),
            ('9. Diedro e raccordo','Configura il pezzo centrale che collega le semiali.','Genera raccordo centrale: attiva pannello ed esportazione. Diedro per semiala: angolo di ciascuna ala rispetto al centro. Lunghezza innesto: tratto di sovrapposizione delle sedi. Gioco diametrale: tolleranza per inserire barre o tubi. Spazio sedi e fondi: margine strutturale attorno agli innesti. Crea nervature, doppio rinforzo e nervature specchiate controllano la struttura interna del raccordo. Le sedi dei longheroni derivano dalle impostazioni definite nel pannello Longheroni.','connector'),
            ('10. Sezionatura 2D','Definisce i tagli per stampare separatamente ala, alettone e raccordo centrale.','Selettore componente: sceglie quale sagoma modificare. Z locale: quota del piano di taglio rispetto alla base dell’elemento. Aggiungi/Modifica/Elimina: gestisce i piani; nella vista puoi aggiungerli con un clic e trascinarli, oppure eliminarli col tasto destro. “Taglio a fine scasso” colloca il piano alla fine effettiva del vano alettone. Le giunzioni maschio/femmina si applicano a ogni taglio. Lunghezza linguetta: lunghezza dell’innesto. Gioco minimo assemblaggio: tolleranza minima controllata. Gioco aggiuntivo sulla linea: margine che si somma alla larghezza linea effettiva. Larghezza estrusione deriva dal pannello iniziale. Gap supporto removibile e relativa casella controllano i sostegni verticali della femmina; Riserva oltre la linguetta mantiene distanza dalle nervature vicine. I pulsanti in basso esportano separatamente i tre componenti sezionati.','cuts'),
            ('11. Riepilogo ed esportazione','Controlla le scelte ed esporta i modelli.','Esporta STL ala intera e alettone intero: creano i componenti non sezionati. Per i pezzi tagliati usa i pulsanti del pannello Sezionatura 2D. La barra di avanzamento appare solo durante l’esportazione e segue le fasi. Apri cartella output mostra i file STL e i rapporti/impostazioni ausiliari. Il menu File importa o salva l’intera configurazione JSON: questo salvataggio è distinto dai file STL.','export'),
        )
        if english:
            sections=(
                ('1. Zero retraction printing','Set extrusion conditions used by checks and export sidecar files.','Nozzle: physical nozzle diameter. Line width: width of each extrusion path; also used for joints. Layer height: recommended vertical step for Spiral Vase. Hidden gap: small separation that enables the spiral path. “Adapt values to nozzle” proposes proportional line width and layer height. PrusaSlicer verification is optional; geometry and mesh checks always remain active.','vase'),
                ('2. Geometry','Defines the wing planform, airfoils and internal structure.','Trapezoidal/elliptical planform: how chord changes along Z. Semispan: main wing span, excluding the optional tip. Root/tip chord: chord at each end. Leading edge sweep: leading edge offset. Root/tip NACA: airfoils blended along the span. Profile points and stations: contour and spanwise resolution. Rib pitch and diagonal angle: spacing and inclination. Internal ribs can be disabled. Oval count, length and height set lightening holes; incompatible holes are skipped. Mirrored ribs add a second, opposite diagonal family. Planform handles update the numeric fields.','geometry'),
                ('3. Washout','Defines the wing twist from root to tip.','Final washout: rotation angle; 0 disables twist. Start from root: Z position where twist begins. Pivot: chord percentage from the leading edge. Rotation increases progressively from the start to the tip.','washout'),
                ('4. Tip','Adds an optional tapered tip beyond the main semispan.','Elliptical tip: enables the extension. Additional Z length: tip extension. Center line: percentage of tip chord used as reference. Handles edit length and center line. Ribs follow the Geometry panel choice.','tip'),
                ('5. Spars','Creates channels for rods or tubes inserted after printing.','Number: number of channels; 0 means none. Position: chord percentage from leading edge. Diameter: rod/tube diameter. Z length: spanwise length from root; blank means full semispan. Diametral clearance: fit allowance. Planform angle: Auto follows the current wing direction; manual 0° is perpendicular to the root, positive angles point toward the trailing edge. Handles move the channel and set its angle.','spars'),
                ('6. Aileron and end caps','Defines the aileron bay and the separate aileron part.','Create aileron: enables bay and separate STL. Root/tip side width: aileron chordwise width measured from trailing edge. Nominal Z length and root distance: spanwise location and length. Hinge gap: clearance along hinge. Root/tip end gaps: clearances at both ends. Chamfer angle: movable edge bevel for rotation. End caps: closes both sides; cap thickness sets their Z thickness. Handles adjust position and size; trailing edges remain aligned.','aileron'),
                ('7. Hinge slots','Creates matching pockets in wing and aileron for hinges.','Create slots: enable feature. Pair count: number of hinges. Z spacing: center-to-center distance; 0 distributes them evenly with equal margins. Slot Z length: spanwise extent. Slot height: hinge tab thickness. Depth per side: pocket depth on each component. Distance below upper skin: pocket center position. Ramp angle: controls the supporting ramp length.','hinges'),
                ('8. Servo','Creates the servo recess and a ledge for a future cover.','Create recess: enables the cavity. Servo type: editable indicative preset. Root and leading-edge distances: body center position. Z rotation or planform Y rotation: mutually exclusive; inactive angle is ignored. Depth offset: moves servo relative to lower skin. Width, height and length: body envelope. Per-side clearance: fit allowance. Lip width and cover recess depth: cover ledge dimensions; the cover is not generated. Presets are not standard dimensions; check the actual servo.','servo'),
                ('9. Dihedral and center section','Configures the center part joining the wing halves.','Generate center section: enables its settings and export. Dihedral per half: angle of each wing. Join length: spar engagement length. Diametral clearance: rod/tube fit. Seat and end margin: structural material around inserts. Rib, double spar reinforcement and mirrored rib options configure its internal structure. Spar seats follow the Spars panel.','connector'),
                ('10. 2D sectioning','Sets cuts for printing wing, aileron and center section separately.','Component: selects the part. Local Z: cut plane height from component base. Add/Edit/Delete: manage cuts; click or drag planes in the view, right-click to remove. “Cut at bay end” places a wing cut at the actual end of the aileron recess. Male/female joints apply at each cut. Join length: tab length. Minimum assembly clearance: checked minimum fit. Extra line clearance: added to the effective extrusion width. Removable support gap and its checkbox control vertical female supports; rib margin keeps clearance from nearby ribs. The three buttons export the separated components.','cuts'),
                ('11. Summary and export','Review settings and create the models.','Export full wing/aileron STL: creates unsplit components. Use 2D Sectioning for cut pieces. Progress appears only during export and shows its phases. Open output folder to find STL and sidecar reports/settings. File menu imports or saves the full JSON configuration; this is separate from STL export.','export'),
            )
        for heading,intro,parameters,kind in sections:
            ttk.Label(content,text=heading,font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(12,3))
            ttk.Label(content,text=intro,wraplength=750,justify='left').pack(anchor='w',fill='x')
            row=ttk.Frame(content);row.pack(fill='x',pady=(5,3));row.columnconfigure(1,weight=1)
            source=self._help_preview_source(kind)
            links=self._help_preview_links(kind)
            if source is not None and links:
                visual=ttk.Frame(row);visual.grid(row=0,column=0,sticky='nw',padx=(0,10))
                diagram=tk.Canvas(visual,width=205,height=160,background='white',highlightthickness=1,highlightbackground='#d5dce5')
                diagram.pack(anchor='w')
                self._copy_preview(source,diagram)
                for number,(_prefix,x,y,caption) in enumerate(links,1):
                    diagram.create_oval(x-9,y-9,x+9,y+9,fill='#1d4ed8',outline='white',width=2)
                    diagram.create_text(x,y,text=str(number),fill='white',font=('Segoe UI',9,'bold'))
                    ttk.Label(visual,text=f'{number}  {caption}',wraplength=195,foreground='#1d4ed8').pack(anchor='w')
            parameter_list=ttk.Frame(row);parameter_list.grid(row=0,column=1,sticky='nw')
            for parameter in parameters.split('. '):
                parameter=parameter.strip()
                if parameter:
                    marker=next((str(i)+'  ' for i,(prefix,*_) in enumerate(links,1) if parameter.startswith(prefix)), '•  ')
                    ttk.Label(parameter_list,text=marker+parameter,wraplength=500,justify='left').pack(anchor='w',fill='x',pady=1)
        closing_it='Usa Avanti/Indietro o il selettore per navigare. L’asterisco nel titolo indica modifiche non salvate; alla chiusura puoi scegliere se salvarle. La lingua si seleziona da Preferenze → Lingua. Spiral Vase a fessure è una modalità sperimentale: controlla ogni pezzo nello slicer, verifica orientamento e G-code, e stampa prima un provino. Le misure indicative dei servi e i giochi vanno adattati ai componenti e alla stampante reali.'
        closing_en='Use Next/Back or the panel selector to navigate. An asterisk in the window title means there are unsaved changes; when closing, you can choose to save them. Select the interface language from Preferences → Language. Slotted Spiral Vase is experimental: inspect every part in your slicer, check orientation and G-code, and print a test piece first. Adjust indicative servo dimensions and clearances to your actual hardware and printer.'
        ttk.Label(content,text='Navigation and printing' if english else 'Navigazione e stampa',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(14,3))
        ttk.Label(content,text=closing_en if english else closing_it,wraplength=750,justify='left').pack(anchor='w',fill='x')
        buttons=ttk.Frame(outer);buttons.pack(fill='x',pady=(10,0));ttk.Button(buttons,text='Chiudi',command=dialog.destroy).pack(side='right')
        dialog.bind('<Escape>',lambda _e:dialog.destroy());dialog.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
        dialog.grab_set();dialog.focus_set();self._translating=previous_guard

    def _help_preview_source(self,kind):
        mapping={'geometry':getattr(self,'planform_editor',None),'washout':'washout_canvas','tip':'tip','spars':'spars','aileron':'aileron','hinges':'slots','servo':'servo_canvas','connector':'connector_preview_canvas','cuts':'cuts'}
        source=mapping.get(kind)
        if kind=='geometry':return getattr(source,'canvas',None)
        if kind in ('tip','spars','aileron','hinges'):
            previews=getattr(self,'previews',None)
            if previews is None:return None
            key={'hinges':'slots'}.get(kind,kind)
            try:
                previews.draw(key)
                return previews.canvases[key]
            except Exception:return None
        if kind=='cuts':
            panel=getattr(self,'section_panel',None)
            if panel:
                try:panel.refresh();panel.draw_shape('ala');return panel.canvases['ala']
                except Exception:return None
            return None
        if isinstance(source,str):
            canvas=getattr(self,source,None)
            if canvas:
                try:
                    if kind=='washout':self.draw_washout_preview()
                    elif kind=='servo':self.draw_servo_preview()
                    elif kind=='connector':self.previews.draw('connector')
                    return canvas
                except Exception:return None
        return None

    @staticmethod
    def _help_preview_links(kind):
        return {
            'geometry':[('Corda radice/estremità',45,112,'Corde ai due estremi'),('Freccia',145,45,'Bordo d’attacco')],
            'washout':[('Washout finale',150,54,'Profilo ruotato'),('Perno',63,90,'Asse di rotazione')],
            'tip':[('Lunghezza aggiuntiva',162,37,'Estensione della punta'),('Linea centrale',110,79,'Posizione della punta')],
            'spars':[('Posizione',75,50,'Sedi dei longheroni'),('Inclinazione',130,88,'Direzione delle sedi')],
            'aileron':[('Larghezza lato',137,52,'Larghezza dell’alettone'),('Lunghezza nominale',170,91,'Estensione lungo Z')],
            'hinges':[('Numero coppie',100,51,'Distribuzione delle asole'),('Lunghezza asole',143,94,'Dettaglio della tasca')],
            'servo':[('Centro dalla radice',88,57,'Posizione dello scasso'),('Larghezza, altezza',135,101,'Ingombro del corpo')],
            'connector':[('Diedro per semiala',72,38,'Angolo delle semiali'),('Lunghezza innesto',132,105,'Sedi nel raccordo')],
            'cuts':[('Z locale',98,53,'Piano di taglio'),('Lunghezza linguetta',150,101,'Zona della giunzione')],
        }.get(kind,[])

    @staticmethod
    def _copy_preview(source,destination):
        source.update_idletasks()
        items=[item for item in source.find_all() if source.type(item) in ('line','polygon','rectangle','oval')]
        coords_by_item={item:source.coords(item) for item in items}
        xs=[v for coords in coords_by_item.values() for v in coords[::2]]
        ys=[v for coords in coords_by_item.values() for v in coords[1::2]]
        if not xs or not ys:return
        xmin,xmax=min(xs),max(xs);ymin,ymax=min(ys),max(ys)
        scale=min(185/max(1,xmax-xmin),140/max(1,ymax-ymin))
        ox=(205-(xmax-xmin)*scale)/2-xmin*scale
        oy=(150-(ymax-ymin)*scale)/2-ymin*scale
        for item in items:
            kind=source.type(item)
            coords=coords_by_item[item]
            if not coords:continue
            scaled=[(v*scale+(ox if i%2==0 else oy)) for i,v in enumerate(coords)]
            options={}
            for name in ('fill','outline','width','dash','smooth','stipple'):
                try:
                    value=source.itemcget(item,name)
                    if value:options[name]=value
                except tk.TclError:pass
            if 'width' in options:
                try:options['width']=max(1,float(options['width'])*scale)
                except ValueError:pass
            try:
                if kind=='line':destination.create_line(*scaled,**options)
                elif kind=='polygon':destination.create_polygon(*scaled,**options)
                elif kind=='rectangle':destination.create_rectangle(*scaled,**options)
                elif kind=='oval':destination.create_oval(*scaled,**options)
            except tk.TclError:continue

    def _draw_help_diagram(self,canvas,kind):
        canvas.delete('all');w=max(320,canvas.winfo_width());h=105
        blue='#bfdbfe';edge='#2563eb';orange='#fdba74';ink='#334155';green='#0f766e';red='#dc2626'
        def poly(points,fill=blue,outline=edge):canvas.create_polygon(*[v for point in points for v in point],fill=fill,outline=outline,width=2)
        if kind=='geometry':
            poly([(35,30),(w-55,20),(w-35,52),(w-55,82),(35,76)])
            canvas.create_line(35,30,w-55,20,fill=red,width=3);canvas.create_line(35,76,w-55,82,fill=green,width=3)
            canvas.create_text(w/2,13,text='Bordo d’attacco',fill=red);canvas.create_text(w/2,94,text='Radice  →  estremità',fill=ink)
        elif kind in ('vase','hinges','servo','spars'):
            poly([(40,24),(w-65,31),(w-50,78),(40,72)])
            if kind=='vase':
                canvas.create_line(48,40,w-60,46,fill=orange,width=5);canvas.create_line(48,56,w-57,61,fill=orange,width=5);canvas.create_text(w/2,13,text='Parete esterna + nervatura interna',fill=ink)
            elif kind=='spars':
                for x in (w*.34,w*.58,w*.78):canvas.create_line(x,30,x-12,78,fill=orange,width=7)
                canvas.create_text(w/2,13,text='Sedi longheroni: posizione e inclinazione',fill=ink)
            elif kind=='hinges':
                for x in (w*.35,w*.52,w*.69):canvas.create_rectangle(x,43,x+22,56,fill=orange,outline=red,width=2)
                canvas.create_text(w/2,13,text='Tasche abbinate ala ↔ alettone',fill=ink)
            else:
                canvas.create_rectangle(w*.48,38,w*.61,66,fill=orange,outline=red,width=2);canvas.create_rectangle(w*.46,34,w*.63,70,outline=green,width=2)
                canvas.create_text(w/2,13,text='Scasso servo + battuta coperchio',fill=ink)
        elif kind=='washout':
            for y,ang in ((34,0),(67,-12)):
                canvas.create_line(w*.22,y,w*.78,y+ang,fill=edge,width=3,arrow='last');canvas.create_oval(w*.48-4,y-4,w*.48+4,y+4,fill=red,outline=red)
            canvas.create_text(w*.83,50,text='torsione progressiva',fill=ink)
        elif kind=='tip':
            poly([(45,25),(w-95,25),(w-45,52),(w-95,80),(45,80)])
            canvas.create_line(w-95,15,w-45,15,fill=green,arrow='both',width=2);canvas.create_text(w-70,10,text='lunghezza',fill=green)
            canvas.create_line(w-105,30,w-105,75,fill=red,arrow='both',width=2);canvas.create_text(w-130,53,text='linea centrale',fill=red,angle=90)
        elif kind=='aileron':
            poly([(40,22),(w-55,22),(w-35,50),(w-55,80),(40,80)])
            poly([(w*.45,53),(w-37,53),(w-55,80),(w*.45,80)],fill=orange,outline='#c2410c')
            canvas.create_line(w*.45,17,w*.45,84,fill=red,dash=(4,3));canvas.create_text(w*.67,67,text='alettone',fill='#9a3412')
        elif kind=='connector':
            poly([(35,38),(w*.43,38),(w*.43,65),(35,65)])
            poly([(w*.57,65),(w*.57,38),(w-35,38),(w-35,65)])
            canvas.create_line(w*.43,51,w*.57,51,fill=green,width=5);canvas.create_text(w/2,18,text='Raccordo centrale · diedro · innesti',fill=ink)
        elif kind=='cuts':
            poly([(45,15),(w-50,22),(w-50,82),(45,76)])
            for x in (w*.37,w*.63):canvas.create_line(x,12,x,85,fill=red,width=2,dash=(5,3))
            canvas.create_rectangle(w*.37,39,w*.63,57,fill=orange,outline='#c2410c');canvas.create_text(w*.28,49,text='maschio',fill=green);canvas.create_text(w*.73,70,text='femmina',fill=red)
        elif kind=='export':
            for i,label in enumerate(('Modello','Controlli','STL')):
                x=w*.25+i*w*.25;canvas.create_oval(x-25,29,x+25,79,fill=(blue,orange,'#bbf7d0')[i],outline=edge);canvas.create_text(x,54,text=str(i+1),fill=ink,font=('Segoe UI',12,'bold'))
                canvas.create_text(x,92,text=label,fill=ink)
                if i<2:canvas.create_line(x+30,54,x+w*.25-30,54,fill=green,width=3,arrow='last')

    def show_about(self):
        from core import VERSION
        english=self.language.get()=='en'
        dialog=tk.Toplevel(self);dialog.title('About' if english else 'Informazioni');dialog.transient(self);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=f'pyRcWing v{VERSION}',font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(0,4))
        ttk.Label(frame,text='Parametric RC wing and 3D-printable component generator.' if english else 'Generatore parametrico di ali RC e componenti per la stampa 3D.',wraplength=520).pack(anchor='w',pady=(0,12))
        ttk.Label(frame,text='Author and contact' if english else 'Autore e contatto',font=('Segoe UI',10,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Marco Antinori\nmarco.antinori@outlook.it',justify='left').pack(anchor='w',pady=(3,10))
        ttk.Label(frame,text='License and attribution' if english else 'Licenza e attribuzione',font=('Segoe UI',10,'bold')).pack(anchor='w')
        license_text=('You may use, modify and redistribute this software and derivative versions, provided that the copyright and this attribution are retained, and that every publicly distributed derivative clearly credits the original author in its About screen or accompanying documentation: “Originally created by Marco Antinori”. Modified versions must be identified as modified and must not imply that the original author endorses them. This is a custom attribution license, not an OSI-standard open-source license. Third-party components remain subject to their own licenses.' if english else
                      'Puoi usare, modificare e ridistribuire questo software e le versioni derivate, a condizione di mantenere il copyright e questa attribuzione e di citare chiaramente l’autore originale in ogni versione derivata distribuita al pubblico, nella schermata Informazioni o nella documentazione allegata: “Creato originariamente da Marco Antinori”. Le versioni modificate devono essere indicate come tali e non devono suggerire l’approvazione dell’autore originale. È una licenza personalizzata con obbligo di attribuzione, non una licenza open source standard OSI. I componenti di terzi restano soggetti alle rispettive licenze.')
        ttk.Label(frame,text=license_text,wraplength=520,justify='left').pack(anchor='w',pady=(3,10))
        ttk.Label(frame,text='Support development' if english else 'Sostieni lo sviluppo',font=('Segoe UI',10,'bold')).pack(anchor='w')
        support=('Contributions to development are welcome. If you publish a modified version, keep the original author credit above and identify your own changes. Contact the author to coordinate contributions.' if english else
                 'I contributi allo sviluppo sono benvenuti. Se pubblichi una versione modificata, mantieni il credito all’autore originale e indica le modifiche che hai realizzato. Contatta l’autore per coordinare i contributi.')
        ttk.Label(frame,text=support,wraplength=520,justify='left').pack(anchor='w',pady=(3,14))
        ttk.Button(frame,text='Close' if english else 'Chiudi',command=dialog.destroy).pack(anchor='e')
        dialog.bind('<Escape>',lambda _e:dialog.destroy());dialog.grab_set();dialog.focus_set()

    def _render_value(self,key,value,setter):
        value=str(value);previous=self._translation_cache.get(key)
        source=previous[0] if previous and value==previous[1] else self._translated_sources.get(value,value)
        rendered=self.tr(source)
        if rendered!=source:self._translated_sources[rendered]=source
        if rendered!=value:
            previous_guard=self._translating;self._translating=True
            try:setter(rendered)
            finally:self._translating=previous_guard
        self._translation_cache[key]=(source,rendered)

    def translate_widgets(self):
        if self._translating:return
        if self._ui_update_pending is not None:
            self.after_cancel(self._ui_update_pending);self._ui_update_pending=None
        self._translating=True
        try:
            self._watch_model_variables()
            self._translate_widgets_impl()
        finally:self._translating=False

    def _translate_widgets_impl(self):
        visited_vars=set();live=set()
        def visit(widget):
            try:
                kind=widget.winfo_class()
                if kind in ('TLabel','TButton','TCheckbutton','TLabelframe','Label','Button','Checkbutton','Labelframe','TRadiobutton','Radiobutton'):
                    var=widget.cget('textvariable') if 'textvariable' in widget.keys() else ''
                    if var:
                        key=('var',str(var));live.add(key)
                        if var not in visited_vars:
                            visited_vars.add(var)
                            if str(var) not in self._model_var_watches:
                                self._watch_display_variable(str(var))
                                self._render_value(key,self.getvar(var),lambda v,n=var:self.setvar(n,v))
                    else:
                        key=('text',str(widget));live.add(key);self._render_value(key,widget.cget('text'),lambda v:widget.configure(text=v))
                if isinstance(widget,tk.Canvas):
                    for item in widget.find_all():
                        if widget.type(item)=='text':
                            key=('canvas',str(widget),item);live.add(key);self._render_value(key,widget.itemcget(item,'text'),lambda v,i=item:widget.itemconfigure(i,text=v))
                if kind=='Treeview':
                    for col in widget['columns']:
                        key=('heading',str(widget),col);live.add(key);self._render_value(key,widget.heading(col,'text'),lambda v,c=col:widget.heading(c,text=v))
                    for item in widget.get_children():
                        values=list(widget.item(item,'values'));before=list(values)
                        for i,value in enumerate(values):
                            key=('cell',str(widget),item,i);live.add(key)
                            self._render_value(key,value,lambda v,i=i:values.__setitem__(i,v))
                        if values!=before:widget.item(item,values=values)
                for child in widget.winfo_children():visit(child)
            except tk.TclError:return
        visit(self)
        self._translation_cache={k:v for k,v in self._translation_cache.items() if k in live}
        index=self.step_picker.current()
        labels=tuple(self.tr(n) for n in self.step_names)
        if tuple(self.step_picker['values'])!=labels:
            self.step_picker.configure(values=labels)
            if index>=0:self.step_picker.current(index)
        for i,name in enumerate(self.step_names):
            label=self.tr(name)
            if self.tabs.tab(i,'text')!=label:self.tabs.tab(i,text=label)
        self.section_panel.sync_component_picker()
        title=self._base_title+(' *' if self.has_unsaved_changes() else '')
        if self.title()!=title:self.title(title)
        state='disabled' if self.generating else 'normal'
        for i in (0,1,3):
            if str(self.file_menu.entrycget(i,'state'))!=state:self.file_menu.entryconfigure(i,state=state)

    def _schedule_ui_update(self,*_):
        if self._translating or getattr(self,'loading_configuration',False):return
        if self._ui_update_pending is None:self._ui_update_pending=self.after_idle(self._run_ui_update)

    def _run_ui_update(self):
        self._ui_update_pending=None
        if not self.loading_configuration:self.translate_widgets()

    def _watch_display_variable(self,name):
        if name in self._display_var_watches or name in self._model_var_watches:return
        def changed(*_):
            if not self._translating:
                self._render_value(('var',name),self.getvar(name),lambda value:self.setvar(name,value))
        command=self._register(changed)
        self.tk.call('trace','add','variable',name,'write',command)
        self._display_var_watches[name]=command

    def _watch_model_variables(self):
        variables=list(self.vars.values())+list(self.connector_vars.values())+list(self.section_panel.joiner_vars.values())
        variables += [self.spar_count,self.spar_clearance]
        for row in self.spar_rows:variables.extend(row.values())
        for variable in variables:
            name=str(variable)
            if name not in self._model_var_watches:
                command=self._register(self._schedule_ui_update)
                self.tk.call('trace','add','variable',name,'write',command)
                self._model_var_watches[name]=command

    def destroy(self):
        # Cancel callbacks in this application's Tcl interpreter, including
        # delayed preview redraws and progress hiding, before deleting widgets.
        try:
            for token in self.tk.splitlist(self.tk.call('after','info')):
                self.tk.call('after','cancel',token)
        except tk.TclError:pass
        super().destroy()
