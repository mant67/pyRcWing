"""Historical oval dimensions, with open slit connections for Spiral Vase."""
import math
from spars import has_manual_spar_angles
from planform import elliptical_planform, planform_section
import json
import queue
import re
import threading
import time
import uuid
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def wing_mirrored_enabled(params):
    def enabled(key,default):return str(params.get(key,default)).strip().lower() in ('1','true','yes','on')
    return enabled('create_ribs',True) and enabled('nervature_specchiate_ala',False)


def oval_parameters(params):
    enabled = str(params.get('create_oval_holes', False)).strip().lower() in ('1', 'true', 'yes', 'on')
    ribs = str(params.get('create_ribs', True)).strip().lower() in ('1', 'true', 'yes', 'on')
    if not enabled or not ribs:
        return None
    try:
        count=float(str(params.get('hole_count',3)).replace(',','.'))
    except (ValueError,TypeError) as exc:
        raise ValueError('Numero ovali per nervatura: inserisci un intero da 1 a 50.') from exc
    if not math.isfinite(count) or not count.is_integer() or not 1<=count<=50:
        raise ValueError('Numero ovali per nervatura: inserisci un intero da 1 a 50.')
    result = {'hole_count':int(count)}
    for key, default in (('hole_width', 18.), ('hole_height', 10.)):
        try:
            value = float(str(params.get(key, default)).replace(',', '.'))
        except (ValueError, TypeError) as exc:
            raise ValueError('Dimensioni dei fori ovali non valide.') from exc
        if not math.isfinite(value) or value < 2 * float(params['line_width']):
            raise ValueError('Gli ovali devono avere dimensioni finite e almeno doppie della larghezza linea.')
        result[key] = value
    return result


def oval_positions(count):
    """Uniform normalized chord spacing; three retains the historical positions."""
    if count==1:return (.48,)
    return tuple(.22+.52*i/(count-1) for i in range(count))


def rib_ovals(cq, params, zbase, slab, slit, outer, guards, vase, camber, *, slope_override=None, from_upper=False):
    """Interrupt printed rib returns; never add a closed void to the CAD solid.

    In this inverse representation the filled oval is a missing printed rib.
    Two blind slits enter from opposite skins and remain separated by the
    window. Minimum separation allows their extrusion returns to remain apart.
    """
    from core import planar_vase_loft,exact_shape_bounds
    settings = oval_parameters(params)
    if not settings:
        return slit, []
    span=params['span'];cr=params['root_chord'];ct=params['tip_chord'];sweep=params['sweep']
    slope=math.tan(math.radians(params['rib_angle'])) if slope_override is None else slope_override
    dx=1+slope*sweep/span if slope_override is None else 1.
    dz=slope;length=math.hypot(dx,dz)
    half_z=settings['hole_width']/2*abs(dz)/length
    min_half=vase['legamento']/2
    if settings['hole_height']<=vase['legamento']:
        raise ValueError('Altezza ovale insufficiente per separare i ritorni di estrusione: aumentala oltre il legamento Spiral Vase.')
    gap=vase['fessura_vaso'];half_x=gap*length/abs(dz)
    bounds=exact_shape_bounds(outer);pad=2*max(cr,ct,span)
    records=[];previous_end=None;lower_masks=[];upper_cuts=[]
    positions=oval_positions(settings['hole_count'])
    if slope<0:positions=tuple(reversed(positions))
    for fraction in positions:
        denominator=1-slope*fraction*(ct-cr)/span if slope_override is None else dx-slope*(sweep+fraction*(ct-cr))/span
        if abs(denominator)<1e-6:
            continue
        z=(zbase+slope*fraction*cr)/denominator
        if elliptical_planform(params):
            def residual(zz):
                ch,le,_=planform_section(params,zz)
                return (dx*zz-zbase)/slope-le-fraction*ch
            lo,hi=0.,span
            if residual(lo)*residual(hi)>0:continue
            lower_value=residual(lo)
            for _ in range(50):
                mid=(lo+hi)/2;value=residual(mid)
                if lower_value*value<=0:hi=mid
                else:lo=mid;lower_value=value
            z=(lo+hi)/2
        if z-half_z<=vase['legamento'] or z+half_z>=span-vase['legamento']:
            continue
        if previous_end is not None and z-half_z<previous_end+vase['legamento']:
            raise ValueError('Ovali sovrapposti lungo la nervatura: riduci il numero di ovali o la loro lunghezza.')
        f=z/span;chord,lead,_=planform_section(params,z)
        y0,_=camber(fraction,params['airfoil']);y1,_=camber(fraction,params.get('airfoil_tip',params['airfoil']))
        cy=(y0+(y1-y0)*f)*chord
        # Whole-window exclusion keeps seat/servo/hinge guards continuous.
        # Broad phase geometrica: evita intersezioni CAD con protezioni lontane.
        center_x=(dx*z-zbase)/slope;radius_x=abs(dx*half_z/slope)+half_x
        nearby=[]
        for guard in guards:
            bb=guard.BoundingBox()
            if bb.zmin<=z+half_z and bb.zmax>=z-half_z and bb.xmin<=center_x+radius_x and bb.xmax>=center_x-radius_x:
                nearby.append(guard)
        if nearby:
            zone=cq.Workplane('XY').box(4*pad,4*pad,2*half_z).translate((0,0,z)).val()
            region=slab.intersect(zone).intersect(outer)
            if any(region.intersect(guard).Volume()>1e-8 for guard in nearby):
                continue
        lower=[];upper=[]
        for i in range(33):
            angle=math.pi*(1-i/32);zz=z+half_z*math.cos(angle)
            height=max(min_half,settings['hole_height']/2*math.sin(angle))
            xx=(dx*zz-zbase)/slope
            boundaries=((lower,cy+height),(upper,cy-height)) if from_upper else ((lower,cy-height),(upper,cy+height))
            for wires,yy in boundaries:
                y0,y1=(-pad,yy) if from_upper else (yy,pad)
                wires.append([cq.Vector(x,y,zz) for x,y in
                    ((xx-half_x,y0),(xx+half_x,y0),(xx+half_x,y1),(xx-half_x,y1))])
        lower_mask=planar_vase_loft(cq,lower)
        upper_mask=planar_vase_loft(cq,upper)
        # The upper branch must open onto the outer skin, never terminate as
        # a closed internal slot. Both ends retain a full-width material bridge.
        upper_cut=slab.intersect(upper_mask).intersect(outer)
        lower_masks.append(lower_mask);upper_cuts.append(upper_cut)
        previous_end=z+half_z
        records.append(dict(frazione_corda=fraction,centro=[lead+fraction*chord,cy,z],
                            inizio_z=z-half_z,fine_z=z+half_z,lunghezza=settings['hole_width'],
                            altezza=settings['hole_height'],separazione_minima_ritorni=vase['legamento']))
    # Le finestre accettate hanno intervalli Z disgiunti: operazioni aggregate
    # equivalenti alle singole sottrazioni/unioni, con meno ricostruzioni OCC.
    if lower_masks:slit=slit.cut(*lower_masks).fuse(*upper_cuts,tol=min(1e-6,gap/1000))
    return slit,records


def _run_slicer(command, progress, timeout=180):
    """Legge l'avanzamento reale CLI, con timeout anche quando non stampa righe."""
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    events=queue.Queue();tail=[]
    def read_output():
        try:
            for line in process.stdout:events.put(line)
        finally:events.put(None)
    reader=threading.Thread(target=read_output,daemon=True);reader.start()
    deadline=time.monotonic()+timeout;done=False;last=-1
    try:
        while not done or process.poll() is None:
            if time.monotonic()>deadline:
                raise RuntimeError('Verifica zero retrazioni scaduta: STL precedente conservato.')
            try:line=events.get(timeout=.1)
            except queue.Empty:continue
            if line is None:done=True;continue
            tail.append(line);tail=tail[-20:]
            match=re.search(r'^\s*(\d{1,3})(?:%|\s*=>)',line)
            if match:
                percent=min(100,int(match.group(1)))
                if percent>last:
                    last=percent
                    if progress:progress('slicer',percent,100)
        return process.wait(),''.join(tail)
    finally:
        if process.poll() is None:process.kill();process.wait()
        reader.join(timeout=1);process.stdout.close()


def _summary(params,summary):
    summary=dict(summary,eseguita=True)
    params.setdefault('_verifica_vaso',{})['verifica_ovali_gcode']=summary
    params['_verifica_vaso']['verifica_slicer']='PASS sulla mesh finale con le impostazioni Spiral Vase selezionate; profilo di sola analisi.'
    return summary


def verify_oval_export(params, stl, analyze, write_sidecars, size, progress=None):
    """Verifica la mesh finale; riusa solo PASS dello stesso STL/configurazione/slicer."""
    if str(params.get('verifica_prusaslicer','0')).lower() not in ('1','true','yes'):
        report=params.setdefault('_verifica_vaso',{})
        report['verifica_ovali_gcode']=dict(eseguita=False,esito=None,motivo='Verifica PrusaSlicer disattivata dall’utente')
        report['verifica_slicer']='NON ESEGUITA: PrusaSlicer opzionale disattivato; i controlli geometrici e della mesh restano attivi.'
        return report['verifica_ovali_gcode']
    manual=has_manual_spar_angles(params)
    joiners=bool(params.get('_joiners_active') or params.get('_mesh_sections_required'))
    if (not oval_parameters(params) and not elliptical_planform(params) and not wing_mirrored_enabled(params) and not manual and not joiners) or (params.get('_componente_esportazione')=='raccordo' and not manual and not joiners):return None
    candidates=[os.environ.get('PRUSASLICER_CONSOLE',''),shutil.which('prusa-slicer-console') or '',
                str(Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Prusa3D/PrusaSlicer/prusa-slicer-console.exe')]
    executable=next((p for p in candidates if p and Path(p).is_file()),None)
    if not executable:raise RuntimeError('Verifica zero retrazioni: PrusaSlicer console non trovato. Disattiva la verifica opzionale nel pannello Stampa zero retrazioni per esportare senza PrusaSlicer.')
    if params.get('_componente_esportazione')=='alettone' and str(params.get('chiudi_estremita_alettone','0')).lower() in ('1','true','yes','on'):
        raise ValueError('Disattiva le chiusure piene dell’alettone per esportare questa configurazione con spirale continua.')
    started=time.perf_counter()
    with open(stl,'rb') as stream:mesh_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    with tempfile.TemporaryDirectory(prefix='.oval-check-',dir=Path(stl).resolve().parent) as directory:
        folder=Path(directory);mesh=folder/'analisi_NON_STAMPARE.stl'
        settings,_=write_sidecars(params,mesh)
        bed=max(300.,size[0]+20,size[1]+20);height=max(300.,size[2]+20)
        profile=folder/'SOLO_ANALISI.ini'
        profile.write_text('# SOLO ANALISI: non e un profilo macchina.\n'
            f'gcode_flavor = reprap\nbed_shape = 0x0,{bed:g}x0,{bed:g}x{bed:g},0x{bed:g}\nmax_print_height = {height:g}\n'
            'filament_diameter = 1.75\ntemperature = 210\nfirst_layer_temperature = 210\n'
            'bed_temperature = 60\nfirst_layer_bed_temperature = 60\nstart_gcode =\nend_gcode =\nskirts = 0\nbrim_width = 0\npost_process =\ngcode_substitutions =\n',encoding='utf-8')
        threshold=4*float(str(params.get('altezza_strato_vaso',.2)).replace(',','.'))-1e-7
        stat=Path(executable).stat()
        identity=dict(revisione='planform-gate-v91-1',sha256_stl=mesh_hash,
            impostazioni=settings.read_text(encoding='utf-8'),profilo=profile.read_text(encoding='utf-8'),
            slicer=str(Path(executable).resolve()),slicer_mtime=stat.st_mtime_ns,slicer_size=stat.st_size,soglia=threshold)
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        cache=Path(tempfile.gettempdir())/'oval_checks'/f'{key}.json'
        try:
            cached=json.loads(cache.read_text(encoding='utf-8'));summary=cached['verifica']
            if (cached['chiave']==key and summary['sha256_stl']==mesh_hash and summary['esito'] is True
                and all(summary[k]==0 for k in ('ritrazioni','travel_xy','discese_z'))
                and summary['movimenti_con_crescita_z']>0
                and set(summary['tipi_percorso'])<= {'External perimeter','Overhang perimeter'}):
                summary=dict(summary,verifica_riutilizzata=True,secondi_questa_verifica=time.perf_counter()-started)
                return _summary(params,summary)
        except (OSError,ValueError,TypeError,KeyError):pass
        shutil.copyfile(stl,mesh);gcode=folder/'analisi_NON_STAMPARE.gcode'
        code,output=_run_slicer([executable,'--threads','1','--load',str(profile),'--load',str(settings),
            '--export-gcode','--output',str(gcode),str(mesh)],progress)
        if code or not gcode.exists():raise RuntimeError(f'Verifica zero retrazioni non riuscita (codice {code}): '+(output[-1200:] or 'Nessun G-code prodotto; STL precedente conservato.'))
        result=analyze(gcode,threshold)
        if not result['esito']:
            raise RuntimeError('Configurazione incompatibile con spirale continua: '
                f"{result['ritrazioni']} ritrazioni, {result['travel_xy']} travel XY, {result['discese_z']} discese Z. "
                'Modifica dimensioni o posizione delle nervature; STL precedente conservato.')
        summary={k:result[k] for k in ('esito','ritrazioni','travel_xy','discese_z',
                    'movimenti_estrusi','movimenti_con_crescita_z','strati_analizzati','tipi_percorso')}
        summary.update(sha256_stl=mesh_hash,quota_inizio_analisi=threshold,slicer=Path(executable).name,
            verifica_riutilizzata=False,secondi_questa_verifica=time.perf_counter()-started,
            ambito='Mesh finale, ugello/linea/strato selezionati; escluse basi iniziali e comandi finali. Profilo di sola analisi.')
        try:
            cache.parent.mkdir(parents=True,exist_ok=True)
            temporary=cache.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(dict(chiave=key,verifica=summary)),encoding='utf-8')
            os.replace(temporary,cache)
        except OSError:pass  # La cache è facoltativa, la verifica rimane obbligatoria.
        return _summary(params,summary)
