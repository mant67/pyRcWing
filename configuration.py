"""Versioned JSON configuration files. No CAD objects or execution state."""
# File revision: 1
import copy
import json
import math
import os
import tempfile
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from joiners import JOINER_DEFAULTS,joiner_parameters

FORMAT='wing-rc-configuration'
SCHEMA=1
COMPONENTS=('ala','alettone','raccordo')
SPAR_KEYS={'position','diameter','length','angle_deg','angle_auto'}


def validate_configuration(data,wing_keys,connector_keys):
    if not isinstance(data,dict) or data.get('format')!=FORMAT:
        raise ValueError('Il file non è una configurazione Wing RC.')
    if type(data.get('schema_version')) is not int or data['schema_version']!=SCHEMA:
        raise ValueError('Versione del formato configurazione non supportata.')
    def strings(values,keys,label):
        if not isinstance(values,dict) or set(values)!=set(keys):
            raise ValueError('Configurazione '+label+' incompleta o non compatibile con questa versione.')
        if any(not isinstance(value,str) or len(value)>(20000 if key in ('custom_airfoil_root','custom_airfoil_tip') else 1000)
               for key,value in values.items()):
            raise ValueError('Valori non validi nella configurazione '+label+'.')
    # Configurations saved by v75 predate the independent wing mirror switch.
    if isinstance(data.get('wing'),dict) and 'nervature_specchiate_ala' in wing_keys and 'nervature_specchiate_ala' not in data['wing']:
        data=copy.deepcopy(data);data['wing']['nervature_specchiate_ala']='0'
    if not isinstance(data.get('wing'),dict):raise ValueError('Configurazione ala non valida.')
    if isinstance(data.get('wing'),dict) and 'verifica_prusaslicer' not in data['wing']:
        data=copy.deepcopy(data);data['wing']['verifica_prusaslicer']='0'
    if isinstance(data.get('wing'),dict):
        missing=[key for key in ('custom_airfoil_root','custom_airfoil_tip') if key in wing_keys and key not in data['wing']]
        if missing:
            data=copy.deepcopy(data)
            for key in missing:data['wing'][key]=''
    if data.get('wing',{}).get('verifica_prusaslicer') not in ('0','1'):
        raise ValueError('Opzione verifica PrusaSlicer non valida.')
    strings(data.get('wing'),wing_keys,'ala')
    strings(data.get('connector'),connector_keys,'raccordo')
    spars=data.get('spars')
    if not isinstance(spars,dict) or set(spars)!={'count','clearance','rows'}:
        raise ValueError('Configurazione longheroni incompleta.')
    strings({k:spars[k] for k in ('count','clearance')},('count','clearance'),'longheroni')
    try:count=int(spars['count'])
    except ValueError as exc:raise ValueError('Numero longheroni intero tra 0 e 20 richiesto.') from exc
    if not 0<=count<=20:raise ValueError('Numero longheroni compreso tra 0 e 20 richiesto.')
    rows=spars['rows']
    if not isinstance(rows,list) or not max(1,count)<=len(rows)<=20:
        raise ValueError('Elenco dei longheroni incompleto o non valido.')
    if any(isinstance(row,dict) and set(row)=={'position','diameter','length'} for row in rows):
        data=copy.deepcopy(data);spars=data['spars'];rows=spars['rows']
    for row in rows:
        if isinstance(row,dict) and set(row)=={'position','diameter','length'}:
            row['angle_auto']='1';row['angle_deg']=''
        strings(row,SPAR_KEYS,'longheroni')
    cuts=data.get('cuts')
    if not isinstance(cuts,dict) or set(cuts)!=set(COMPONENTS):
        raise ValueError('Configurazione dei piani di taglio incompleta.')
    for values in cuts.values():
        if not isinstance(values,list) or len(values)>10000:
            raise ValueError('Elenco dei piani di taglio non valido.')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=1e-4 for v in values):
            raise ValueError('Le quote dei piani di taglio devono essere numeri positivi e finiti.')
        ordered=sorted(values)
        if any(b-a<1e-4 for a,b in zip(ordered,ordered[1:])):
            raise ValueError('Due piani di taglio coincidono.')
    data=copy.deepcopy(data)
    if 'joiners' not in data:data['joiners']=dict(JOINER_DEFAULTS)
    if 'FemaleRibMargin' not in data['joiners']:data['joiners']['FemaleRibMargin']='1.1'
    strings(data['joiners'],JOINER_DEFAULTS,'giunzioni')
    # Keep editable invalid inputs, as for the other panels; export validates dimensions.
    if any(data['joiners'][k] not in ('0','1') for k in ('JoinerEnabled','FemaleSupportEnabled')):
        raise ValueError('Opzioni giunzioni non valide.')
    return data


def read_configuration(path,wing_keys,connector_keys,progress=None):
    path=Path(path);limit=5*1024*1024;size=path.stat().st_size
    if size>limit:raise ValueError('File di configurazione troppo grande.')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Chiave ripetuta nel file di configurazione: '+key)
            result[key]=value
        return result
    chunks=[];received=0
    if progress:progress('read',0,max(1,size))
    with path.open('rb') as stream:
        while True:
            chunk=stream.read(65536)
            if not chunk:break
            received+=len(chunk)
            if received>limit:raise ValueError('File di configurazione troppo grande.')
            chunks.append(chunk)
            if progress:progress('read',received,max(1,size,received))
    if progress:progress('read',1,1);progress('validate',0,1)
    try:
        data=json.loads(b''.join(chunks).decode('utf-8-sig'),object_pairs_hook=pairs)
    except (UnicodeError,json.JSONDecodeError,RecursionError) as exc:
        raise ValueError('Il file di configurazione non contiene dati JSON validi.') from exc
    data=validate_configuration(data,wing_keys,connector_keys)
    if progress:progress('validate',1,1)
    return data


def write_configuration(path,data,progress=None):
    path=Path(path)
    if progress:progress('prepare',0,1)
    content=(json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')
    if progress:progress('prepare',1,1);progress('write',0,len(content))
    fd,name=tempfile.mkstemp(prefix='.wing-config-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            for offset in range(0,len(content),65536):
                chunk=content[offset:offset+65536];stream.write(chunk)
                if progress:progress('write',offset+len(chunk),len(content))
        os.replace(name,path)
        if progress:progress('write',1,1)
    finally:
        if os.path.exists(name):os.unlink(name)


class ConfigurationMixin:
    def create_configuration_ui(self):
        self.configuration_path=None;self.loading_configuration=False
        self._configuration_job=None;self._configuration_progress_hide=None
        self.configuration_note=tk.StringVar(value='Salva e ricarica tutti i pannelli, i longheroni e i piani di taglio.')
        parent=self.pages[0]
        box=ttk.LabelFrame(parent,text='Configurazione ala',padding=8)
        box.pack(fill='x',pady=(0,10),before=parent.winfo_children()[0])
        row=ttk.Frame(box);row.pack(fill='x')
        self.configuration_export_button=ttk.Button(row,text='Esporta configurazione…',command=self.export_configuration)
        self.configuration_export_button.pack(side='left',padx=(0,8))
        self.configuration_import_button=ttk.Button(row,text='Importa configurazione…',command=self.import_configuration)
        self.configuration_import_button.pack(side='left')
        self.configuration_buttons=(self.configuration_export_button,self.configuration_import_button)
        ttk.Label(box,textvariable=self.configuration_note,wraplength=850).pack(anchor='w',pady=(6,0))

    def _configuration_state(self):
        rows=copy.deepcopy(self.spar_cache)
        for index,row in enumerate(self.spar_rows):
            values={k:v.get() for k,v in row.items()}
            if index<len(rows):rows[index]=values
            else:rows.append(values)
        try:count=int(self.spar_count.get())
        except ValueError:count=0
        if not 0<=count<=20:count=0
        while len(rows)<max(1,count):
            rows.append(dict(position=str(min(25+len(rows)*20,85)),diameter='4',length='',angle_auto='1',angle_deg=''))
        from core import VERSION
        data=dict(format=FORMAT,schema_version=SCHEMA,generator_version=VERSION,
                  saved_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                  wing={k:v.get() for k,v in self.vars.items()},
                  connector={k:v.get() for k,v in self.connector_vars.items()},
                  spars=dict(count=self.spar_count.get(),clearance=self.spar_clearance.get(),rows=rows),
                  cuts=copy.deepcopy(self.section_panel.cuts),
                  joiners={k:(self.vars['larghezza_linea_vaso'].get() if k=='NozzleWidth' else v.get()) for k,v in self.section_panel.joiner_vars.items()})
        return data

    def configuration_snapshot(self):
        return validate_configuration(self._configuration_state(),self.vars,self.connector_vars)

    def _apply_configuration(self,data,refresh=True):
        self.loading_configuration=True
        if self.previews.pending is not None:
            self.after_cancel(self.previews.pending);self.previews.pending=None
        try:
            for key,value in data['wing'].items():self.vars[key].set(value)
            for key,value in data['connector'].items():self.connector_vars[key].set(value)
            raw_count=data['spars']['count']
            try:count=int(raw_count)
            except ValueError:count=-1
            self.spar_count.set(raw_count if 0<=count<=20 else str(len(data['spars']['rows'])))
            self.spar_clearance.set(data['spars']['clearance'])
            # Discard current row references before rebuilding so they cannot overwrite the imported cache.
            self.spar_rows=[];self.spar_cache=copy.deepcopy(data['spars']['rows']);self.refresh_spar_rows()
            self.spar_count.set(raw_count)
            self.section_panel.cuts=copy.deepcopy(data['cuts'])
            for key,value in data.get('joiners',JOINER_DEFAULTS).items():self.section_panel.joiner_vars[key].set(value)
            self.section_panel.toggle_joiners()
            self.section_panel.selected=None;self.section_panel.dragging=False;self.section_panel.position.set('')
            self.section_panel.cache.clear();self.planform_editor.drag=None
        finally:self.loading_configuration=False
        if refresh:self._refresh_configuration_views()

    def _refresh_configuration_views(self):
        self.update_spar_angles()
        if hasattr(self.previews,'aileron_editor'):self.previews.aileron_editor.sync_distance(force=True)
        self.toggle_ribs();self.aileron_toggle();self.hinge_toggle();self.toggle_servo();self.toggle_connector()
        self.planform_editor.changed();self.draw_washout_preview();self.refresh_summary()
        # Only this synchronous preview calculation needs the panel's idle guard.
        # No event loop is entered while temporarily lifting it.
        busy=self.generating
        try:
            self.generating=False;self.section_panel.refresh()
        finally:
            self.generating=busy;self.section_panel.set_busy(busy)
        self.previews.schedule()

    def save_configuration_file(self,path):
        if self.generating:raise ValueError('Attendi il termine dell’operazione in corso prima di salvare la configurazione.')
        data=self.configuration_snapshot();write_configuration(path,data)
        self.configuration_path=Path(path)
        self.configuration_note.set('Configurazione salvata: '+str(self.configuration_path))
        self.mark_configuration_clean(data)
        return data

    def load_configuration_file(self,path):
        if self.generating:raise ValueError('Attendi il termine dell’operazione in corso prima di caricare una configurazione.')
        data=read_configuration(path,self.vars,self.connector_vars)
        previous=self._configuration_state()
        try:self._apply_configuration(data)
        except Exception:
            self._apply_configuration(previous)
            raise
        self.configuration_path=Path(path)
        self.configuration_note.set('Configurazione caricata: '+str(self.configuration_path))
        self.mark_configuration_clean()
        return data

    def export_configuration(self):
        if self.generating:return
        path=filedialog.asksaveasfilename(title='Esporta configurazione ala',defaultextension='.json',
             initialfile=self.configuration_path.name if self.configuration_path else 'configurazione_ala.json',
             initialdir=str(self.configuration_path.parent if self.configuration_path else self.last_dir),
             filetypes=[('Configurazione ala','*.json')])
        if not path:return
        self._start_configuration_job('save',path)

    def import_configuration(self):
        if self.generating:return
        if not self.confirm_unsaved_changes():return
        path=filedialog.askopenfilename(title='Importa configurazione ala',
             initialdir=str(self.configuration_path.parent if self.configuration_path else self.last_dir),
             filetypes=[('Configurazione ala','*.json'),('Tutti i file','*.*')])
        if not path:return
        self._start_configuration_job('load',path)


    def _configuration_progress(self,stage,done=0,total=1):
        job=self._configuration_job
        if job is None:return
        maps={'save':{'collect':(1,0,20,'Raccolta dei parametri'),
                      'validate':(2,20,40,'Verifica della configurazione'),
                      'prepare':(3,40,55,'Preparazione del file'),
                      'write':(4,55,95,'Scrittura del file'),
                      'done':(5,95,100,'Configurazione salvata')},
              'load':{'read':(1,0,25,'Lettura del file'),
                      'validate':(2,25,40,'Verifica della configurazione'),
                      'apply':(3,40,70,'Ripristino dei parametri'),
                      'views':(4,70,95,'Aggiornamento delle anteprime'),
                      'done':(5,95,100,'Configurazione caricata')}}
        number,start,end,label=maps[job['kind']][stage]
        fraction=max(0.,min(1.,done/max(1,total)))
        self.progress_value=max(self.progress_value,start+(end-start)*fraction)
        self.progress_stage='configuration_'+stage
        self.progress_bar.configure(mode='determinate',value=self.progress_value)
        text=f'{self.operation_name} — Fase {number}/5: {label} — {self.progress_value:.0f}%'
        self.progress_text.set(text);self.status.set(text)
        self.update_idletasks()

    def _start_configuration_job(self,kind,path):
        if self.generating:return
        label='Esportazione configurazione' if kind=='save' else 'Importazione configurazione'
        self.begin_operation(label)
        self.is_export_operation=True
        self.progress_frame.pack(side='top',fill='x',before=self.back_button,pady=(0,8))
        job=dict(kind=kind,path=Path(path),queue=queue.Queue());self._configuration_job=job
        try:
            if kind=='save':
                self._configuration_progress('collect')
                data=self._configuration_state()
                self._configuration_progress('collect',1)
                self._configuration_progress('validate')
                data=validate_configuration(data,self.vars,self.connector_vars)
                self._configuration_progress('validate',1)
            else:
                data=None;self._configuration_progress('read')
            wing_keys=tuple(self.vars);connector_keys=tuple(self.connector_vars)
            def progress(stage,done,total):job['queue'].put(('progress',(stage,done,total)))
            def worker():
                try:
                    if kind=='save':write_configuration(job['path'],data,progress=progress);result=data
                    else:result=read_configuration(job['path'],wing_keys,connector_keys,progress=progress)
                    job['queue'].put(('done',result))
                except Exception as exc:job['queue'].put(('error',exc))
            threading.Thread(target=worker,daemon=True).start()
            self.after(30,self._poll_configuration_job)
        except Exception as exc:self._finish_configuration_job(False,exc)

    def _poll_configuration_job(self):
        job=self._configuration_job
        if job is None:return
        try:
            while True:
                event,data=job['queue'].get_nowait()
                if event=='progress':self._configuration_progress(*data)
                elif event=='error':self._finish_configuration_job(False,data);return
                else:
                    previous=None
                    try:
                        if job['kind']=='load':
                            previous=self._configuration_state()
                            self._configuration_progress('apply')
                            self._apply_configuration(data,refresh=False)
                            self._configuration_progress('apply',1)
                            self._configuration_progress('views')
                            self._refresh_configuration_views()
                            self._configuration_progress('views',1)
                        self.configuration_path=job['path']
                        self.configuration_note.set(('Configurazione salvata: ' if job['kind']=='save' else 'Configurazione caricata: ')+str(job['path']))
                        self.mark_configuration_clean(data if job['kind']=='save' else None)
                        self._configuration_progress('done',1)
                        self._finish_configuration_job(True)
                    except Exception as exc:
                        if previous is not None:
                            try:self._apply_configuration(previous)
                            except Exception as restore:exc=RuntimeError(str(exc)+'; ripristino non completato: '+str(restore))
                        self._finish_configuration_job(False,exc)
                    return
        except queue.Empty:self.after(30,self._poll_configuration_job)

    def _finish_configuration_job(self,success,error=None):
        job=self._configuration_job
        if job is None:return
        self.finish_operation(success);self.generating=False
        self.section_panel.set_busy(False)
        self.export_button.configure(state='normal')
        self.aileron_export_button.configure(state='normal' if self.vars['crea_alettone'].get()=='1' else 'disabled')
        self.toggle_connector()
        self._configuration_job=None
        if success:self.status.set(self.configuration_note.get())
        else:
            self.status.set(self.operation_name+' non completata')
            self.configuration_note.set(self.operation_name+' non completata: '+str(error))
            messagebox.showerror('Configurazione non salvata' if job['kind']=='save' else 'Configurazione non caricata',str(error))
        # Keep the completed result legible; this timer never advances progress.
        def hide():
            self._configuration_progress_hide=None
            if not self.generating:self.progress_frame.pack_forget()
        self._configuration_progress_hide=self.after(1200,hide)
