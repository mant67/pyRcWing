#!/usr/bin/env python3
# pyRcWing v9.1.1 — motore geometrico
# File revision: 1
# Generazione STL con solidi CAD e unioni booleane; non usa OpenSCAD.
# Dipendenza: cadquery (installare con: py -m pip install cadquery)
import math, os
import tempfile
import json
import re
import struct
from collections import Counter
from pathlib import Path

from washout import washout_parameters, washout_angle, washout_point, washout_mesh

from servo import SERVO_PRESETS, SERVO_DEFAULTS, servo_parameters, servo_layout, servo_surface, servo_footprint, make_servo_geometry

from lightening import oval_parameters, rib_ovals, verify_oval_export, wing_mirrored_enabled

from planform import elliptical_planform, planform_parameters, planform_section, planform_stations, planform_outline

from spars import spar_automatic, legacy_spar_angle, spar_axis, has_manual_spar_angles
from airfoil_editor import profile_from_controls

VERSION = "9.1.1"

def naca_profile(code="2412", n=80, trailing_edge_ratio=0.0):
    code = str(code).strip()
    if len(code) != 4 or not code.isdigit():
        raise ValueError("Profilo NACA non valido: usare quattro cifre, per esempio 2412.")
    m, p, t = int(code[0])/100.0, int(code[1])/10.0, int(code[2:])/100.0
    xs = [0.5*(1-math.cos(math.pi*i/n)) for i in range(n+1)]
    upper, lower = [], []
    for x in xs:
        yt = 5*t*(0.2969*math.sqrt(max(0,x))-0.126*x-0.3516*x*x+0.2843*x**3-0.1015*x**4)
        # Impone uno spessore minimo al TE con una correzione liscia x^8:
        # non cambia il bordo d'attacco e raggiunge il valore richiesto a x=1.
        if trailing_edge_ratio > 0:
            yt += 0.5*max(0.0, trailing_edge_ratio - 2.0*(5*t*(0.2969-0.126-0.3516+0.2843-0.1015)))*x**8
        if m == 0 or p == 0:
            yc = dy = 0.0
        elif x < p:
            yc = m/(p*p)*(2*p*x-x*x); dy = 2*m/(p*p)*(p-x)
        else:
            yc = m/((1-p)**2)*((1-2*p)+2*p*x-x*x); dy = 2*m/((1-p)**2)*(p-x)
        th = math.atan(dy)
        upper.append((x-yt*math.sin(th), yc+yt*math.cos(th)))
        lower.append((x+yt*math.sin(th), yc-yt*math.cos(th)))
    # Contorno chiuso esplicito: bordo d'attacco -> dorso -> bordo d'uscita
    # (include il punto inferiore del bordo d'uscita) -> ventre.
    # La versione precedente ometteva il punto inferiore del TE: la wire
    # poteva quindi chiudersi con un segmento diagonale vicino al bordo d'uscita.
    return upper + [lower[-1]] + list(reversed(lower[1:-1]))

def camber_thickness(x, code):
    m, p, t = int(code[0])/100.0, int(code[1])/10.0, int(code[2:])/100.0
    x = max(0.0, min(1.0, x))
    if m == 0 or p == 0: yc = 0.0
    elif x < p: yc = m/(p*p)*(2*p*x-x*x)
    else: yc = m/((1-p)**2)*((1-2*p)+2*p*x-x*x)
    yt = 5*t*(0.2969*math.sqrt(x)-0.126*x-0.3516*x*x+0.2843*x**3-0.1015*x**4)
    return yc, yt

def airfoil_tip_code(params):
    root=str(params['airfoil']).strip()
    code=str(params.get('airfoil_tip',root)).strip()
    naca_profile(root,params.get('points',20))
    try:naca_profile(code,params.get('points',20))
    except ValueError as exc:raise ValueError('Profilo NACA estremità non valido: usare quattro cifre, per esempio 0010.') from exc
    return code


def airfoil_profile(params,end='root',n=None,trailing_edge_ratio=0.):
    """Return a NACA or edited normalized profile at a wing endpoint."""
    key='custom_airfoil_root' if end=='root' else 'custom_airfoil_tip'
    code=str(params['airfoil'] if end=='root' else params.get('airfoil_tip',params['airfoil'])).strip()
    count=int(n or params.get('points',20))
    custom=profile_from_controls(params.get(key,''),count,trailing_edge_ratio)
    return custom if custom is not None else naca_profile(code,count,trailing_edge_ratio)


def profile_camber_thickness(params,x,end='root'):
    profile=airfoil_profile(params,end,max(80,int(params.get('points',20))))
    split=max(range(len(profile)),key=lambda i:profile[i][0])
    upper=profile[:split+1];lower=list(reversed(profile[split+1:]))
    def value(points):
        if x<=points[0][0]:return points[0][1]
        for a,b in zip(points,points[1:]):
            if x<=b[0]:
                t=(x-a[0])/max(1e-12,b[0]-a[0]);return a[1]+(b[1]-a[1])*t
        return points[-1][1]
    top,bottom=value(upper),value(lower)
    return (top+bottom)/2,(top-bottom)/2


def profile_thickness_ratio(params,end='root'):
    return max((2*profile_camber_thickness(params,i/100,end)[1] for i in range(1,100)),default=0.)


def section_profile(params,z,trailing_edge_ratio=0.):
    """Morphing lineare di punti corrispondenti dei due profili normalizzati."""
    root=str(params['airfoil']).strip();tip=airfoil_tip_code(params)
    first=airfoil_profile(params,'root',params['points'],trailing_edge_ratio)
    same_profile=(root==tip and params.get('custom_airfoil_root','')==params.get('custom_airfoil_tip',''))
    if same_profile or z<=0:return first
    last=airfoil_profile(params,'tip',params['points'],trailing_edge_ratio)
    f=max(0.,min(1.,z/params['span']))
    if f>=1:return last
    return [(a+(c-a)*f,b+(d-b)*f) for (a,b),(c,d) in zip(first,last)]


def make_section_wire(cq, z, chord, lead, code, points, skin=0.0, inner=False, trailing_edge_thickness=0.9, profile=None):
    pts = naca_profile(code, points, trailing_edge_thickness/max(chord, 1e-6)) if profile is None else profile
    vectors = [cq.Vector(lead+x*chord, y*chord, z) for x, y in pts]
    cleaned = []
    for v in vectors:
        if not cleaned or (v-cleaned[-1]).Length > 1e-7:
            cleaned.append(v)
    if len(cleaned) > 2 and (cleaned[0]-cleaned[-1]).Length < 1e-7:
        cleaned.pop()
    wire = cq.Wire.makePolygon(cleaned, close=True)
    if inner:
        try:
            offsets = wire.offset2D(-skin, kind="arc")
        except (ValueError, RuntimeError) as exc:
            raise ValueError("Impossibile creare la cavità: riduci la skin o aumenta la corda.") from exc
        if len(offsets) != 1 or not offsets[0].isValid():
            raise ValueError("Skin troppo spessa: la cavità interna si divide o scompare.")
        inner_wire = offsets[0]
        outer_face = cq.Face.makeFromWires(wire)
        inner_face = cq.Face.makeFromWires(inner_wire)
        if inner_face.Area() >= outer_face.Area() or inner_face.cut(outer_face).Area() > 1e-6:
            raise ValueError("Impossibile costruire una cavità interna contenuta nel profilo.")
        return inner_wire
    return wire

def exact_shape_bounds(shape):
    """Precise bounds reused only on the same immutable CadQuery shape."""
    bounds=getattr(shape,'_exact_bounds',None)
    if bounds is None:
        bounds=shape.BoundingBox()
        shape._exact_bounds=bounds
    return bounds


def make_rib_slab(cq, outer, zbase, slope, sweep, span, thickness):
    """Lastra piana non ritagliata, dimensionata per coprire la sagoma."""
    direction_x, direction_z = 1.0+slope*sweep/span, slope
    length = math.hypot(direction_x, direction_z)
    xdir = (direction_x/length, 0, direction_z/length)
    normal = (-direction_z/length, 0, direction_x/length)
    # Il punto appartiene al piano anche quando direction_x è zero.
    origin = cq.Vector(-zbase/slope, 0, 0)
    bounds = exact_shape_bounds(outer)
    corners = [cq.Vector(x,y,z) for x in (bounds.xmin,bounds.xmax)
               for y in (bounds.ymin,bounds.ymax) for z in (bounds.zmin,bounds.zmax)]
    extent = max((v-origin).Length for v in corners)+thickness+1.0
    plane = cq.Plane(origin=origin, xDir=xdir, normal=normal)
    slab = cq.Workplane(plane).rect(2*extent, 2*extent).extrude(thickness/2, both=True).val()
    return slab




def parse_spars(rows, clearance=0.2, span=None):
    """Diametro nominale barra + gioco diametrale, in millimetri."""
    clearance = float(str(clearance).replace(",", "."))
    if not math.isfinite(clearance) or clearance < 0:
        raise ValueError("Il gioco diametrale deve essere finito e non negativo.")
    spars = []
    for index, row in enumerate(rows, 1):
        try:
            position = float(str(row["position"]).replace(",", "."))
            diameter = float(str(row["diameter"]).replace(",", "."))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Longherone {index}: posizione e diametro devono essere numerici.") from exc
        if not math.isfinite(position) or not 0 < position < 100:
            raise ValueError(f"Longherone {index}: posizione compresa tra 0 e 100%, estremi esclusi.")
        if not math.isfinite(diameter) or diameter <= 0:
            raise ValueError(f"Longherone {index}: diametro positivo e finito richiesto.")
        spar = dict(position=position, diameter=diameter,angle_auto=spar_automatic(row))
        if not spar['angle_auto']:
            try:angle=float(str(row.get('angle_deg','')).replace(',','.'))
            except (ValueError,TypeError) as exc:raise ValueError(f'Longherone {index}: inclinazione numerica richiesta.') from exc
            if not math.isfinite(angle) or abs(angle)>=85:
                raise ValueError(f'Longherone {index}: inclinazione richiesta tra -85° e 85° esclusi.')
            spar['angle_deg']=angle
        if str(row.get("length", "")).strip():
            try: length = float(str(row["length"]).replace(",", "."))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Longherone {index}: lunghezza numerica richiesta.") from exc
            if not math.isfinite(length) or length <= 0 or (span is not None and length > span):
                raise ValueError(f"Longherone {index}: lunghezza positiva, finita e non superiore all’apertura Z.")
            spar["length"] = length
        spars.append(spar)
    return spars, clearance


def make_spar_seats(cq, params, outer):
    """Assi rettilinei radice-punta, con verifica continua del contenimento.

    I volumi guard definiscono la superficie esterna dei tubi, poi uniti
    alle anime e alla skin prima dell’apertura dei fori passanti.
    """
    spars, clearance = parse_spars(params.get("spars", []), params.get("spar_clearance", 0.2), params.get("span"))
    if not spars:
        return [], []
    span, cr, ct = params["span"], params["root_chord"], params["tip_chord"]
    skin, line = params["skin"], params["line_width"]
    bounds = exact_shape_bounds(outer)
    margin = max(bounds.xlen, bounds.ylen, span)+1
    bores, guards = [], []
    for index, spar in enumerate(spars, 1):
        length_z = spar.get("length", span)
        clip = cq.Workplane("XY").box(bounds.xlen+2*margin, bounds.ylen+2*margin, length_z).translate(
            ((bounds.xmin+bounds.xmax)/2, (bounds.ymin+bounds.ymax)/2, length_z/2)).val()
        root_values,delta_values=spar_axis(params,spar)
        root=cq.Vector(*root_values);axis=cq.Vector(*delta_values)
        direction = axis.normalized()
        radius = (spar["diameter"]+clearance)/2
        # Una linea di appoggio oltre il foro, più il margine per la skin.
        guard_radius = radius+line
        padding = guard_radius+skin+1
        # Taglio su Z, non perpendicolare all’asse inclinato: ogni sede
        # termina alla quota richiesta rispetto al piano di radice.
        seat_clip = cq.Workplane("XY").box(bounds.xlen+2*margin, bounds.ylen+2*margin,
                                         length_z+padding).translate(
            ((bounds.xmin+bounds.xmax)/2, (bounds.ymin+bounds.ymax)/2, (length_z-padding)/2)).val()
        def cylinder(r):
            solid = cq.Solid.makeCylinder(r, axis.Length+2*padding, root-direction*padding, direction)
            return solid.intersect(seat_clip) if length_z < span else solid
        safety = cylinder(guard_radius+skin).intersect(clip)
        if safety.cut(outer).Volume() > 1e-5:
            raise ValueError(f"Longherone {index} ({spar['position']:g}%): diametro o posizione incompatibili "
                             "con il profilo lungo la semiala. Riduci il diametro o sposta la sede.")
        guard = cylinder(guard_radius)
        for other in guards:
            overlap = guard.intersect(other)
            if overlap.Volume() > 1e-5 and overlap.intersect(clip).Volume() > 1e-5:
                raise ValueError(f"Longherone {index}: sede troppo vicina a un altro longherone.")
        bores.append(cylinder(radius))
        guards.append(guard)
    return bores, guards






def tip_center_percentage(params):
    """Asse di rastremazione, percentuale della corda dal bordo d'attacco."""
    try:value=float(str(params.get('wing_center_line_perc',50.)).replace(',','.'))
    except (ValueError,TypeError) as exc:raise ValueError('Linea centrale punta: percentuale non valida.') from exc
    if not math.isfinite(value) or not 0<=value<=100:
        raise ValueError('Linea centrale punta: inserisci una percentuale tra 0 e 100 dal bordo d’attacco.')
    return value


def tip_parameters(params):
    enabled = params.get("elliptical_tip", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("1", "true", "yes")
    if not enabled:
        return False, 0.0
    tip_center_percentage(params)
    try:
        length = float(str(params.get("tip_length",40)).replace(",", "."))
    except (ValueError, TypeError) as exc:
        raise ValueError("Lunghezza della punta ellittica non valida.") from exc
    if not math.isfinite(length) or length <= 2*params["skin"]:
        raise ValueError("La lunghezza della punta deve superare due volte lo spessore della skin.")
    return True, length


def vase_tip_fraction(s):
    """Ellisse invariata fino all'80%; raccordo con derivata nulla in cima."""
    s=max(0.,min(1.,s))
    if s<=.8:return s
    u=(s-.8)/.2
    return .8+.2*(u+u*u-u*u*u)


def vase_tip_sections(terminal_scale):
    end=math.acos(terminal_scale);fractions=[0.,1.]
    for i in range(1,16):
        target=math.sin(end*i/16)/math.sin(end)
        low,high=0.,1.
        for _ in range(40):
            middle=(low+high)/2
            if vase_tip_fraction(middle)<target:low=middle
            else:high=middle
        fractions.append((low+high)/2)
    fractions.extend((.85,.9,.925,.95,.975,.99,.995))
    return [(value,math.sqrt(max(terminal_scale**2,1-(1-terminal_scale**2)*vase_tip_fraction(value)**2)))
            for value in sorted(set(fractions))]


def smooth_tip_sections():
    # Passi angolari uniformi evitano ripiegamenti del loft vicino all'apice.
    return [(math.sin(math.pi*i/64),math.cos(math.pi*i/64)) for i in range(33)]



def smooth_profile_wire(cq,z,xy):
    """Due spline cubiche C1 al naso, con gli stessi parametri su ogni sezione."""
    n=(len(xy)-1)//2
    upper=[cq.Vector(x,y,z) for x,y in xy[:n+1]]
    lower=[cq.Vector(x,y,z) for x,y in xy[n+1:]]+[upper[0]]
    tangent=cq.Vector(xy[1][0]-xy[-1][0],xy[1][1]-xy[-1][1],0)*(n/2)
    parameters=[i/n for i in range(n+1)]
    a=cq.Edge.makeSpline(upper,tangents=(tangent,(upper[-1]-upper[-2])*n),parameters=parameters,scale=False)
    b=cq.Edge.makeLine(upper[-1],lower[0])
    c=cq.Edge.makeSpline(lower,tangents=((lower[1]-lower[0])*n,tangent),parameters=parameters,scale=False)
    return cq.Wire.assembleEdges([a,b,c])


def elliptical_tip_scale(params,fraction):
    f=max(0.,min(1.,fraction))
    ct=params['tip_chord'];dc=-(params['root_chord']**2-ct**2)/(params['span']*ct)
    return math.sqrt(max(0.,1-f*f))*math.exp(dc*tip_parameters(params)[1]/ct*f)


def smooth_tip_profile(params,fraction,points=None):
    """Punta NACA, raccordo tangente iniziale e calotta tonda verso un vertice."""
    n=points or max(80,params['points']);p=dict(params,points=n)
    f=max(0.,min(1.,fraction));scale=math.sqrt(max(0.,1-f*f))
    chord,lead,_=planform_section(p,p['span']);q=tip_center_percentage(p)/100
    length=tip_parameters(p)[1];width=float(str(p.get('larghezza_linea_vaso',p['line_width'])).replace(',','.'))
    te=max(.9,2*width);profile=airfoil_profile(p,'tip',n,te/chord)
    pivot=lead+q*chord
    xy=[(pivot+(x-q)*chord*scale,y*chord*scale) for x,y in profile]
    if elliptical_planform(p):
        # Continue the incoming contraction monotonically, then close at a vertex.
        # A quarter-tip Hermite with a large incoming slope can dip and rebound.
        scale=elliptical_tip_scale(p,f)
        h=min(.01,p['span']/10000);z=p['span']-h
        previous_chord,previous_lead,_=planform_section(p,z)
        previous=[(previous_lead+x*previous_chord,y*previous_chord) for x,y in section_profile(p,z,te/previous_chord)]
        dc=-(p['root_chord']**2-chord**2)/(p['span']*chord)
        root=[(lead+x*chord,y*chord) for x,y in profile]
        correction=length*f*(1-f)**2
        return [(pivot+(x-q)*chord*scale+correction*((rx-px)/h-(x-q)*dc),
                 y*chord*scale+correction*((ry-py)/h-y*dc))
                for (x,y),(rx,ry),(px,py) in zip(profile,root,previous)]
    # Hermite al primo quarto: stessa posizione e tangente della semiala.
    if f<.25:
        duration=length*.25;t=f/.25;end_scale=math.sqrt(1-.25**2)
        h=min(.01,p['span']/10000);z=p['span']-h;ratio=z/p['span']
        previous_chord,previous_lead,_=planform_section(p,z)
        previous=[(previous_lead+x*previous_chord,y*previous_chord) for x,y in section_profile(p,z,te/previous_chord)]
        root=[(lead+x*chord,y*chord) for x,y in profile]
        target=[(pivot+(x-q)*chord*end_scale,y*chord*end_scale) for x,y in profile]
        d_end=[((x-q)*chord*(-.25/end_scale)/length,y*chord*(-.25/end_scale)/length) for x,y in profile]
        h00=2*t**3-3*t*t+1;h10=t**3-2*t*t+t;h01=-2*t**3+3*t*t;h11=t**3-t*t
        xy=[tuple(h00*a+h10*duration*(a-b)/h+h01*c+h11*duration*d for a,b,c,d in zip(a0,b0,c0,d0)) for a0,b0,c0,d0 in zip(root,previous,target,d_end)]
    # La calotta conserva il profilo NACA fino al vertice. La contrazione
    # ellittica chiude la superficie senza una faccia terminale e senza
    # modificare separatamente corda o spessore nell'ultimo tratto.
    return xy


def make_smooth_tip(cq,params):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    builder=BRepOffsetAPI_ThruSections(True,False,1e-7);builder.SetMaxDegree(3)
    builder.CheckCompatibility(False)
    length=tip_parameters(params)[1]
    for fraction,scale in smooth_tip_sections():
        if fraction>=1:continue
        xy=smooth_tip_profile(params,fraction)
        builder.AddWire(smooth_profile_wire(cq,params['span']+length*fraction,xy).wrapped)
    vertex=cq.Vertex.makeVertex(planform_section(params,params['span'])[1]+params['tip_chord']*tip_center_percentage(params)/100,0.,params['span']+length)
    builder.AddVertex(vertex.wrapped);builder.Build()
    if not builder.IsDone():raise RuntimeError('Superficie levigata della punta non riuscita.')
    shape=cq.Shape.cast(builder.Shape())
    if not shape.isValid():raise RuntimeError('Calotta levigata della punta non valida.')
    return shape


def make_elliptical_tip(cq, params, return_geometry=False, outer_only=False, terminal_scale=0.):
    """Punta aggiuntiva: contorno semiellittico e cavità interna chiusa.

    L'apertura Z principale resta invariata. La punta si estende oltre
    l'ultima sezione, rastremata attorno alla linea centrale percentuale selezionata.
    """
    enabled, length = tip_parameters(params)
    if not enabled:
        return None
    if outer_only:return make_smooth_tip(cq,params)
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    span=params["span"];chord,lead,_=planform_section(params,span)
    skin = params["skin"]
    te = max(.9,2*params["line_width"])
    center = cq.Vector(lead+chord*tip_center_percentage(params)/100,0,span)
    outer_profile=airfoil_profile(params,'tip',params['points'],te/chord)
    outer_base = make_section_wire(cq,span,chord,lead,airfoil_tip_code(params),params["points"],trailing_edge_thickness=te,profile=outer_profile)
    def rounded_loft(base, extension):
        builder = BRepOffsetAPI_ThruSections(True, True, 1e-7)
        # Campionamento angolare: più sezioni in prossimità della punta.
        if terminal_scale>0:
            sections=vase_tip_sections(terminal_scale)
        else:sections=[(math.sin(math.pi/2*i/16),math.cos(math.pi/2*i/16)) for i in range(16)]
        for fraction,scale in sections:
            wire = base.translate(-center).scale(scale).translate(center+cq.Vector(0,0,extension*fraction))
            builder.AddWire(wire.wrapped)
        if terminal_scale<=0:
            vertex = cq.Vertex.makeVertex(center.x,center.y,span+extension)
            builder.AddVertex(vertex.wrapped)
        builder.Build()
        if not builder.IsDone():
            raise RuntimeError("Impossibile costruire la punta ellittica.")
        solid = cq.Shape.cast(builder.Shape())
        if not solid.isValid():
            raise RuntimeError("La punta ellittica CAD non è valida.")
        return solid
    outer_tip = rounded_loft(outer_base,length)
    if outer_only:return outer_tip
    inner_base = make_section_wire(cq,span,chord,lead,airfoil_tip_code(params),params["points"],skin,True,te,profile=outer_profile)
    cavity = rounded_loft(inner_base,length-skin)
    tip = outer_tip.cut(cavity).clean()
    if not tip.isValid() or len(tip.Solids()) != 1:
        raise RuntimeError("La skin della punta ellittica non è valida.")
    return (tip, outer_tip, cavity) if return_geometry else tip




ALET_DEFAULTS = dict(larghezza_alettone_radice=30., larghezza_alettone_estremita=30.,
                     lunghezza_alettone=100., inizio_alettone=100., gioco_alettone=.5,
                     angolo_smusso_alettone=30.)


def aileron_parameters(params):
    enabled = str(params.get("crea_alettone",False)).lower() in ("1","true","yes")
    if not enabled:
        return None
    values = {}
    for key,default in ALET_DEFAULTS.items():
        try: value = float(str(params.get(key,default)).replace(",","."))
        except (ValueError,TypeError) as exc: raise ValueError(f"Parametro alettone non valido: {key}.") from exc
        if not math.isfinite(value) or value < 0 or (key != "inizio_alettone" and value == 0):
            raise ValueError(f"Parametro alettone non valido: {key}.")
        values[key]=value
    for key in ('gioco_alettone_radice','gioco_alettone_estremita'):
        try:value=float(str(params.get(key,values['gioco_alettone'])).replace(',','.'))
        except (ValueError,TypeError) as exc:raise ValueError(f'Gioco estremità alettone non valido: {key}.') from exc
        if not math.isfinite(value) or value<0:raise ValueError('I giochi alle estremità dell’alettone devono essere finiti e non negativi.')
        values[key]=value
    end=values['inizio_alettone']+values['lunghezza_alettone']
    total=params['span']+tip_parameters(params)[1]
    if end > total+1e-7:
        raise ValueError(f"L’alettone termina a {end:g} mm dalla radice, ma l’apertura totale è {total:g} mm. "
                         "Riduci inizio/lunghezza alettone oppure aumenta la semiala.")
    if not 1 <= values['angolo_smusso_alettone'] <= 60:
        raise ValueError("Angolo smusso alettone compreso tra 1 e 60 gradi richiesto.")
    if values['lunghezza_alettone'] <= (values['gioco_alettone_radice']+values['gioco_alettone_estremita'])/2+4*params['skin']:
        raise ValueError("Alettone troppo corto per gioco e pareti di chiusura.")
    return values


def aileron_axial_bounds(a):
    """Quote nominali +/- metà del gioco: distanza effettiva fra le facce."""
    start=a['inizio_alettone'];end=start+a['lunghezza_alettone']
    root=a['gioco_alettone_radice']/2;tip=a['gioco_alettone_estremita']/2
    return dict(cut_start=start-root,part_start=start+root,part_end=end-tip,cut_end=end+tip)


def aileron_cap_parameters(params):
    if str(params.get('chiudi_estremita_alettone',False)).lower() not in ('1','true','yes'):
        return None
    a=aileron_parameters(params)
    if a is None:return None
    try:thickness=float(str(params.get('spessore_chiusure_alettone',.8)).replace(',','.'))
    except (TypeError,ValueError) as exc:raise ValueError('Spessore chiusure alettone non valido.') from exc
    if not math.isfinite(thickness) or thickness<=0:
        raise ValueError('Lo spessore delle chiusure deve essere positivo e finito.')
    layer=float(str(params.get('altezza_strato_vaso',.2)).replace(',','.')) if vase_requested(params) else 0.
    if layer and thickness<layer:
        raise ValueError('Le chiusure devono avere almeno lo spessore di uno strato.')
    if 2*thickness>=a['lunghezza_alettone']-(a['gioco_alettone_radice']+a['gioco_alettone_estremita'])/2:
        raise ValueError('Chiusure troppo spesse rispetto alla lunghezza dell’alettone.')
    return dict(spessore=thickness,strati=int(math.ceil(thickness/layer-1e-9)) if layer else None)


def wing_section_at(params,z):
    span,ct=params['span'],params['tip_chord']
    if z <= span:
        return planform_section(params,z)
    length=tip_parameters(params)[1]
    if length <= 0: raise ValueError("Alettone fuori dalla semiala.")
    u=(z-span)/length
    levels=[(math.sin(math.pi*i/32), math.cos(math.pi*i/32)) for i in range(17)]
    scale=0.
    for (za,sa),(zb,sb) in zip(levels,levels[1:]):
        if za <= u <= zb:
            scale=sa+(sb-sa)*(u-za)/(zb-za);break
    if elliptical_planform(params):
        scale=elliptical_tip_scale(params,u)
        dc=-(params['root_chord']**2-ct**2)/(span*ct)
        q=tip_center_percentage(params)/100
        center=float(str(params.get('ellipse_center_perc',50)).replace(',','.'))/100
        shift=length*u*(1-u)**2*(params['sweep']/span+(q-center)*dc) if 0<=u<=1 else 0.
    else:shift=0.
    chord=ct*max(0.,scale)
    return chord,planform_section(params,span)[1]+(ct-chord)*tip_center_percentage(params)/100+shift,max(0.,scale)


def upper_surface_at(params,z,x):
    chord,lead,scale=wing_section_at(params,z)
    te=max(.9,2*params['line_width'])*(scale if z>params['span'] else 1.)
    profile=section_profile(params,z,te/max(chord,1e-6))
    heights=[]
    for (xa,ya),(xb,yb) in zip(profile,profile[1:]+profile[:1]):
        a,b=lead+xa*chord,lead+xb*chord
        if min(a,b)-1e-8 <= x <= max(a,b)+1e-8 and abs(a-b)>1e-10:
            heights.append((ya+(yb-ya)*(x-a)/(b-a))*chord)
    if not heights: raise ValueError("Bordo di cerniera esterno al profilo alare.")
    return max(heights)


ASOLE_DEFAULTS = dict(numero_asole_cerniere=3, interasse_asole_cerniere=0.,
                     lunghezza_asole_cerniere=12., altezza_asole_cerniere=.6,
                     profondita_asole_cerniere=5., distanza_asole_estradosso=2.5,
                     angolo_rampe_sostegno_asole=45.)


def hinge_slot_parameters(params):
    if str(params.get('crea_asole_cerniere',False)).lower() not in ('1','true','yes'):
        return None
    a=aileron_parameters(params)
    if a is None:raise ValueError("Per creare le asole occorre attivare l’alettone.")
    values={}
    for key,default in ASOLE_DEFAULTS.items():
        try:value=float(str(params.get(key,default)).replace(',','.'))
        except (TypeError,ValueError) as exc:raise ValueError(f"Parametro asole non valido: {key}.") from exc
        if not math.isfinite(value) or value<0 or (key!='interasse_asole_cerniere' and value==0):
            raise ValueError(f"Parametro asole non valido: {key}.")
        values[key]=value
    count=values['numero_asole_cerniere']
    if not count.is_integer() or not 1<=count<=20:
        raise ValueError("Il numero di coppie di asole deve essere intero tra 1 e 20.")
    count=int(count);values['numero_asole_cerniere']=count
    length=values['lunghezza_asole_cerniere'];skin=params['skin']
    ramp_angle=values['angolo_rampe_sostegno_asole']
    if not 10 <= ramp_angle <= 60:
        raise ValueError("Angolo rampe sostegno asole compreso tra 10 e 60 gradi richiesto.")
    ends=[]
    for z,width in ((a['inizio_alettone'],a['larghezza_alettone_radice']),
                    (a['inizio_alettone']+a['lunghezza_alettone'],a['larghezza_alettone_estremita'])):
        chord,lead,_=wing_section_at(params,z)
        x=lead+chord-width
        ends.append((x,upper_surface_at(params,z,x)))
    motion=math.hypot(ends[1][0]-ends[0][0],ends[1][1]-ends[0][1])/a['lunghezza_alettone']
    budget=math.tan(math.radians(ramp_angle))-motion
    if budget<=.01:
        raise ValueError("Angolo rampe troppo piccolo rispetto all’inclinazione della cerniera.")
    # La rampa dell'alettone parte da una faccia smussata: al lato alto
    # deve coprire anche la differenza fra le profondità della faccia.
    extra=math.tan(math.radians(a['angolo_smusso_alettone']))*(values['altezza_asole_cerniere']+skin)
    ramp_height=(values['profondita_asole_cerniere']+skin+extra)/budget
    values['lunghezza_rampa_z']=ramp_height
    margin_root=length/2+skin+ramp_height+a['gioco_alettone_radice']/2+skin
    caps=aileron_cap_parameters(params)
    if caps:margin_root+=max(0.,caps['spessore']-skin)
    margin_tip=max(length/2+2*skin,length/2+a['gioco_alettone_estremita']/2+(caps['spessore']+skin if caps else 0.))
    # Uguale distanza fra i bordi delle tasche e le estremità effettive
    # dell'alettone. Il lato più esigente (rampa/chiusura) vincola entrambi.
    axial=aileron_axial_bounds(a)
    clearance=max(margin_root-a['gioco_alettone_radice']/2,
                  margin_tip-a['gioco_alettone_estremita']/2)
    margin_root=clearance+a['gioco_alettone_radice']/2
    margin_tip=clearance+a['gioco_alettone_estremita']/2
    usable=a['lunghezza_alettone']-margin_root-margin_tip
    if usable<0:raise ValueError("Asole e rampe troppo lunghe per l’alettone. Riduci profondità/lunghezza o aumenta l’angolo delle rampe.")
    pitch=values['interasse_asole_cerniere']
    if count>1 and pitch==0:
        pitch=usable/(count-1)
        center=a['inizio_alettone']+margin_root+usable/2
    else:
        center=(axial['part_start']+axial['part_end'])/2
        if count==1:pitch=0.
    if count>1 and pitch<length+2*skin:
        raise ValueError("Interasse o numero di asole incompatibili con la lunghezza dell’alettone e le rampe.")
    centers=[center+(i-(count-1)/2)*pitch for i in range(count)]
    if centers[0]<a['inizio_alettone']+margin_root-1e-7 or centers[-1]>a['inizio_alettone']+a['lunghezza_alettone']-margin_tip+1e-7:
        raise ValueError("Le asole non lasciano spazio alle rampe: riduci numero/interasse o aumenta la lunghezza dell’alettone.")
    values['margine_radice']=margin_root;values['margine_estremita']=margin_tip
    if values['distanza_asole_estradosso']<values['altezza_asole_cerniere']/2+skin:
        raise ValueError("Le asole sono troppo vicine all’estradosso: aumenta la distanza o riduci l’altezza.")
    values['centri']=centers
    values['interasse_effettivo']=pitch
    values['distanza_bordo_radice']=centers[0]-length/2-axial['part_start']
    values['distanza_bordo_estremita']=axial['part_end']-centers[-1]-length/2
    return values


def make_slot_support_ramps(cq,params,p,hinge,center,envelope,wing_cut,selection):
    """Cunei permanenti: partono dalle pareti esistenti prima della tasca.

    L'angolo è misurato dalla verticale di stampa Z. La rampa raggiunge
    l'intera profondità prima che inizi l'alloggiamento rettangolare.
    """
    a=aileron_parameters(params);skin=params['skin'];gap=a['gioco_alettone']
    bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
    depth=p['profondita_asole_cerniere'];height=p['altezza_asole_cerniere']
    top_z=center-p['lunghezza_asole_cerniere']/2-skin
    bottom_z=top_z-p['lunghezza_rampa_z']
    wing_wires=[];movable_wires=[]
    for z,t in ((bottom_z,0.),(top_z,1.),(top_z+skin*.5,1.)):
        x,y=hinge(z);yc=y-p['distanza_asole_estradosso']
        low=yc-height/2-skin;high=yc+height/2+skin
        face=x-gap/2
        left=face-skin-depth*t
        wing_points=[(left,low),(face+skin,low),(face+skin,high),(left,high)]
        face_low=x+gap/2+bevel*(y-low)
        face_high=x+gap/2+bevel*(y-high)
        target=x+gap/2+bevel*(p['distanza_asole_estradosso']+height/2)+depth+skin
        right_low=face_low+skin+(target-face_low-skin)*t
        right_high=face_high+skin+(target-face_high-skin)*t
        movable_points=[(face_low-skin,low),(right_low,low),(right_high,high),(face_high-skin,high)]
        for wires,points in ((wing_wires,wing_points),(movable_wires,movable_points)):
            wires.append(cq.Wire.makePolygon([cq.Vector(px,py,z) for px,py in points],close=True))
    # Clip separato: nessun sostegno attraversa il gioco ala/alettone.
    wing_ramp=cq.Solid.makeLoft(wing_wires,ruled=True).intersect(envelope).cut(wing_cut)
    movable_ramp=cq.Solid.makeLoft(movable_wires,ruled=True).intersect(envelope).intersect(selection)
    return wing_ramp,movable_ramp


def make_hinge_slots(cq,params,envelope,wing,movable,wing_cut,selection,hinge,return_supports=False):
    """Tasche rettangolari abbinate, con alloggiamenti chiusi nella cavità."""
    p=hinge_slot_parameters(params)
    if p is None:return wing,movable,[]
    a=aileron_parameters(params);gap=a['gioco_alettone'];skin=params['skin']
    bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
    height=p['altezza_asole_cerniere'];depth=p['profondita_asole_cerniere'];length=p['lunghezza_asole_cerniere']
    wing_housings=[];movable_housings=[];cutters=[]
    spar_guards=make_spar_seats(cq,params,envelope)[1] if params.get('spars') else []
    for index,center in enumerate(p['centri'],1):
        def prism(padding):
            wires=[]
            for z in (center-length/2-padding,center+length/2+padding):
                x,y=hinge(z);yc=y-p['distanza_asole_estradosso']
                # Profondità misurata nel verso della corda su ciascun lato.
                left=x-gap/2-depth-padding
                right=x+gap/2+bevel*(p['distanza_asole_estradosso']+height/2)+depth+padding
                bottom=yc-height/2-padding;top=yc+height/2+padding
                wire=cq.Wire.makePolygon([cq.Vector(left,bottom,z),cq.Vector(right,bottom,z),
                    cq.Vector(right,top,z),cq.Vector(left,top,z)],close=True)
                wires.append(wire)
            return cq.Solid.makeLoft(wires,ruled=True)
        cutter=prism(0.)
        housing=prism(skin)
        # Le tasche devono rimanere coperte da materiale, senza aprire la skin.
        if housing.cut(envelope).Volume()>1e-5:
            raise ValueError(f"Asole cerniera {index}: alloggiamento fuori dal profilo. "
                             "Riduci profondità/altezza o modifica la distanza dall’estradosso.")
        if any(housing.intersect(guard).Volume()>1e-6 for guard in spar_guards):
            raise ValueError(f"Asola cerniera {index}: alloggiamento in conflitto con un longherone.")
        wing_ramp,movable_ramp=make_slot_support_ramps(cq,params,p,hinge,center,envelope,wing_cut,selection)
        for ramp in (wing_ramp,movable_ramp):
            if not ramp.isValid():raise RuntimeError(f"Rampa sostegno asola {index} non valida.")
            if any(ramp.intersect(guard).Volume()>1e-6 for guard in spar_guards):
                raise ValueError(f"Rampa asola {index} in conflitto con un longherone.")
        wing_housings.append(wing_ramp)
        movable_housings.append(movable_ramp)
        wing_housings.append(housing.cut(wing_cut))
        movable_housings.append(housing.intersect(selection))
        cutters.append(cutter)
    wing=wing.fuse(*wing_housings).cut(*cutters)
    movable=movable.fuse(*movable_housings).cut(*cutters)
    for name,part in (('ala',wing),('alettone',movable)):
        if not part.isValid():part=part.fix()
        if not part.isValid() or len(part.Solids())!=1:
            raise RuntimeError(f"Alloggiamenti delle cerniere non collegati alla skin dell’{name}.")
        if name=='ala':wing=part
        else:movable=part
    if return_supports:return wing,movable,cutters,wing_housings,movable_housings
    return wing,movable,cutters


def hinge_approach_cutters(cq,params,a,slot_details,hinge,gap):
    """Same gradual entry cuts used by the CAD and interference diagnostics."""
    clear=a['gioco_alettone'];cutters=[]
    bevel=math.tan(math.radians(a['angolo_smusso_alettone']))
    for center in slot_details['centri']:
        top_z=center-slot_details['lunghezza_asole_cerniere']/2
        bottom_z=top_z-params['skin']-slot_details['lunghezza_rampa_z']
        wires=[]
        for z,t in ((bottom_z,0.),(top_z-params['skin'],1.),(top_z,1.)):
            hx,hy=hinge(z);yc=hy-slot_details['distanza_asole_estradosso']
            left=hx-clear/2-slot_details['profondita_asole_cerniere']*t
            nose=hx+clear/2+bevel*(slot_details['distanza_asole_estradosso']+slot_details['altezza_asole_cerniere']/2)
            right=nose+slot_details['profondita_asole_cerniere']*t
            wires.append(cq.Wire.makePolygon([cq.Vector(x,y,z) for x,y in
                ((left,yc-gap/2),(right,yc-gap/2),(right,yc+gap/2),(left,yc+gap/2))],close=True))
        cutters.append(cq.Solid.makeLoft(wires,ruled=True))
    return cutters


def aileron_regions(cq,params,envelope):
    """Regioni comuni ai due corpi: vano ala e alettone smussato."""
    p=aileron_parameters(params)
    if p is None:raise ValueError('Attiva Crea alettone separato.')
    start=p['inizio_alettone'];end=start+p['lunghezza_alettone']
    gap=p['gioco_alettone'];skin=params['skin'];angle=math.tan(math.radians(p['angolo_smusso_alettone']))
    hinges=[]
    for z,width in ((start,p['larghezza_alettone_radice']),(end,p['larghezza_alettone_estremita'])):
        chord,lead,_=wing_section_at(params,z)
        if width+2*skin+gap >= chord:
            raise ValueError("Larghezza alettone eccessiva rispetto alla corda locale, soprattutto vicino alla punta.")
        x=lead+chord-width
        hinges.append((x,upper_surface_at(params,z,x)))
    def hinge(z):
        f=(z-start)/(end-start)
        return tuple(a+(b-a)*f for a,b in zip(hinges[0],hinges[1]))
    bounds=envelope.BoundingBox();margin=max(bounds.xlen,bounds.ylen,params['span'])+10
    xmax=bounds.xmax+margin;ymin=bounds.ymin-max(5,bounds.ylen);ymax=bounds.ymax+max(5,bounds.ylen)
    def region(z0,z1,offset,bevel=False):
        wires=[]
        for z in (z0,z1):
            x,y=hinge(z);x+=offset
            points=[(x,ymax),(x,y),(x+angle*(y-ymin) if bevel else x,ymin),(xmax,ymin),(xmax,ymax)]
            wires.append(cq.Wire.makePolygon([cq.Vector(a,b,z) for a,b in points],close=True))
        return cq.Solid.makeLoft(wires,ruled=True)
    axial=aileron_axial_bounds(p)
    cut=region(axial['cut_start'],axial['cut_end'],-gap/2,False)
    selection=region(axial['part_start'],axial['part_end'],gap/2,True)
    # Evita che il taglio raggiunga una sede longherone.
    if params.get('spars'):
        _,guards=make_spar_seats(cq,params,envelope)
        for guard in guards:
            overlap=guard.intersect(cut)
            if overlap.Volume()>1e-6 and overlap.intersect(envelope).Volume()>1e-6:
                raise ValueError("L’alettone interseca un longherone: riduci la larghezza o sposta il longherone.")
    return p,region,cut,selection,hinge




RACCORDO_DEFAULTS = dict(diedro_semiala=5., lunghezza_innesto_longheroni=25.,
                         gioco_innesti_raccordo=.2, spessore_pareti_raccordo=2.)


def connector_parameters(params):
    enabled=str(params.get('genera_raccordo_centrale',False)).lower() in ('1','true','yes')
    if not enabled:raise ValueError("Attiva ‘Genera raccordo centrale’ nel tab del diedro.")
    p={}
    for key,default in RACCORDO_DEFAULTS.items():
        try:value=float(str(params.get(key,default)).replace(',','.'))
        except (ValueError,TypeError) as exc:raise ValueError(f"Parametro raccordo non valido: {key}.") from exc
        if not math.isfinite(value):raise ValueError(f"Parametro raccordo non finito: {key}.")
        p[key]=value
    if not 0<=p['diedro_semiala']<=30:raise ValueError("Diedro per semiala compreso tra 0 e 30 gradi richiesto.")
    if p['lunghezza_innesto_longheroni']<=0 or p['spessore_pareti_raccordo']<=0:
        raise ValueError("Lunghezza innesto e spessore pareti devono essere positivi.")
    if p['gioco_innesti_raccordo']<0:raise ValueError("Il gioco degli innesti non può essere negativo.")
    return p


def connector_ribs_enabled(params):
    """Scelta indipendente dalle nervature della semiala; attiva per compatibilità."""
    return str(params.get('create_connector_ribs',True)).strip().lower() in ('1','true','yes','on')


def connector_half_span(params,settings,profile,directions_z):
    """Ingombro anche senza sedi: riferimento all'asse della semiala."""
    if not directions_z and connector_ribs_enabled(params):
        raise ValueError('Con nervature attive, configura almeno un longherone per il raccordo.')
    angle=math.radians(settings['diedro_semiala'])
    projection=max((abs(z) for z in directions_z),default=abs(math.cos(angle)))
    wall=settings['spessore_pareti_raccordo']
    tilt=max(abs(y*params['root_chord']*math.sin(angle)) for _,y in profile)
    return (settings['lunghezza_innesto_longheroni']+wall)*projection+tilt+2*wall


def connector_structure_parameters(params):
    line=params['line_width']
    skin=float(params.get('skin',line*int(params.get('skin_perimeters',1))))
    thickness=float(params.get('rib_thickness',line*int(params.get('rib_perimeters',1))))
    pitch=float(params.get('rib_pitch',40.)) if connector_ribs_enabled(params) else 40.
    angle=float(params.get('rib_angle',45.)) if connector_ribs_enabled(params) else 45.
    if not all(math.isfinite(v) and v>0 for v in (skin,thickness,pitch)) or not math.isfinite(angle) or not 20<=angle<=70:
        raise ValueError("Skin, passo e spessore nervature devono essere positivi; angolo tra 20 e 70 gradi.")
    return skin,thickness,pitch,angle


def build_central_connector(params,progress=None):
    """Raccordo separato con due sedi cieche specchiate per ogni longherone.

    Coordinate di assemblaggio: X corda, Y verticale, Z apertura. Lo STL
    finale è ruotato per appoggiare una faccia piana di radice sul piatto.
    Labirinto zero retrazioni con sedi collegate al contorno e nervature.
    Lo spessore del raccordo riserva materiale attorno alle sedi e ai fondi.
    """
    import cadquery as cq
    p=connector_parameters(params)
    skin,rib_thickness,rib_pitch,rib_angle=connector_structure_parameters(params)
    spars,_=parse_spars(params.get('spars',[]),0.,params.get('span'))
    if not spars and connector_ribs_enabled(params):raise ValueError("Con nervature attive, configura almeno un longherone nel passo Longheroni.")
    for key in ('span','root_chord','tip_chord','line_width'):
        if not math.isfinite(params[key]) or params[key]<=0:raise ValueError(f"Geometria semiala non valida: {key}.")
    if not math.isfinite(params['sweep']):raise ValueError("Freccia semiala non valida.")
    if params['points']<20:raise ValueError("Usa almeno 20 punti profilo.")
    airfoil_profile(params,'root',params['points'])
    angle=p['diedro_semiala'];radians=math.radians(angle)
    sine,cosine=math.sin(radians),math.cos(radians)
    chord=params['root_chord'];length=p['lunghezza_innesto_longheroni'];wall=p['spessore_pareti_raccordo']
    te=max(.9,2*params['line_width'])
    profile=airfoil_profile(params,'root',params['points'],te/chord)
    directions=[]
    for spar in spars:
        root_values,delta_values=spar_axis(params,spar)
        local=cq.Vector(*delta_values).normalized()
        directions.append(cq.Vector(local.x,local.y*cosine+local.z*sine,-local.y*sine+local.z*cosine))
    # Spazio per due fondi ciechi separati e per l'inclinazione delle radici.
    half=connector_half_span(params,p,profile,[d.z for d in directions])
    root_wire=make_section_wire(cq,0,chord,0,params['airfoil'],params['points'],trailing_edge_thickness=te,profile=profile)
    right_wire=root_wire.rotate((0,0,0),(1,0,0),-angle).translate((0,0,half))
    left_wire=cq.Wire.makePolygon([cq.Vector(x*chord,y*chord*cosine,-half+y*chord*sine) for x,y in profile],close=True)
    if progress:progress("Creazione del raccordo centrale e delle radici inclinate…")
    outer=cq.Solid.makeLoft([left_wire,root_wire,right_wire],ruled=True)
    if not outer.isValid():raise RuntimeError("Profilo esterno del raccordo non valido.")
    bores=[];guards=[];axes=[]
    extent=max(chord,4*half,100.)*3
    for index,(spar,direction) in enumerate(zip(spars,directions),1):
        u=spar['position']/100;yc,_=profile_camber_thickness(params,u,'root')
        for side in (1,-1):
            root=cq.Vector(u*chord,yc*chord*cosine,side*(half-yc*chord*sine))
            outward=cq.Vector(direction.x,direction.y,side*direction.z)
            end=root-outward*length
            radius=(spar['diameter']+p['gioco_innesti_raccordo'])/2
            pad=radius+wall+2
            bore=cq.Solid.makeCylinder(radius,length+pad,end,outward)
            guard=cq.Solid.makeCylinder(radius+wall,length+wall+pad,root-outward*(length+wall),outward)
            normal=cq.Vector(0,sine,side*cosine)
            plane=cq.Plane(origin=(0,0,side*half),normal=normal)
            inside=cq.Workplane(plane).rect(extent,extent).extrude(-extent).val()
            guard=guard.intersect(inside)
            if guard.cut(outer).Volume()>1e-5:
                raise ValueError(f"Innesto {index}: diedro, profondità o diametro non compatibili con il profilo "
                                 "e lo spessore minimo. Riduci questi valori o aumenta la corda radice.")
            if any(guard.intersect(other).Volume()>1e-5 for other in guards):
                raise ValueError("Gli innesti del raccordo sono troppo vicini: riduci diametri/spessore o modifica le posizioni.")
            guards.append(guard);bores.append(bore)
            axes.append(dict(lato='destro' if side==1 else 'sinistro',longherone=index,
                             radice=root.toTuple(),fondo=end.toTuple(),diametro=spar['diameter']+p['gioco_innesti_raccordo']))
    # Una faccia di radice piatta sul piatto; nessun cambio alla semiala.
    rotation=180+angle
    outer=outer.rotate((0,0,0),(1,0,0),rotation)
    shift=-exact_shape_bounds(outer).zmin
    outer=outer.translate((0,0,shift))
    bores=[bore.rotate((0,0,0),(1,0,0),rotation).translate((0,0,shift)) for bore in bores]
    roll=math.radians(rotation)
    def print_point(point):
        x,y,z=point
        return (x,y*math.cos(roll)-z*math.sin(roll),y*math.sin(roll)+z*math.cos(roll)+shift)
    for axis in axes:
        axis['radice_stampa']=print_point(axis['radice'])
        axis['fondo_stampa']=print_point(axis['fondo'])
    result,report=build_connector_labyrinth(cq,params,outer,bores,axes,progress)
    report['parametri_raccordo']=p
    params['_componente_esportazione']='raccordo'
    params['_verifica_vaso']=report
    if params.get('_joiners_active'):
        result._joiner_envelope=outer
        result._joiner_features=[]
        result._joiner_feature_labels=[]
    if has_manual_spar_angles(params):result._oval_params=params
    return result,dict(numero_innesti=len(bores),numero_nervature=report['nervature'],
                       spessore_skin=report['parametri']['legamento'],volume_esterno=outer.Volume(),
                       diedro_semiala=angle,larghezza_centrale=2*half,innesti=axes,
                       rotazione_stampa=rotation,traslazione_stampa=shift,modalita='zero retrazioni')


def build_connector_labyrinth(cq,params,outer,bores,axes,progress=None):
    """Labirinto nella posizione di stampa: sedi aperte al contorno e nervature cieche."""
    bounds=exact_shape_bounds(outer);height=bounds.zmax
    geom=dict(params,span=height,root_chord=params['root_chord'],tip_chord=params['root_chord'],
              sweep=0.,planform='trapezoidal',elliptical_tip=False,tip_length=0.,crea_alettone=False,crea_asole_cerniere=False,spars=[],
              create_ribs=connector_ribs_enabled(params))
    v=vase_parameters(geom);gap=v['fessura_vaso'];ligament=v['legamento']
    pad=3*max(bounds.xlen,bounds.ylen,height)
    if progress:progress('Raccordo zero retrazioni: canali coassiali delle sedi e fondi conici…')
    cutters=[];specs=[];channels=[];levels=[]
    double=str(params.get("doppio_rinforzo_raccordo",True)).lower() in ("1","true","yes")
    ribs_enabled=connector_ribs_enabled(params)
    mirrored=ribs_enabled and str(params.get("nervature_specchiate_raccordo",False)).lower() in ("1","true","yes")
    upper_channels=[];guide_guards=[]
    for bore,axis in zip(bores,axes):
        root=cq.Vector(*axis['radice_stampa']);end=cq.Vector(*axis['fondo_stampa'])
        inward=(end-root).normalized();radius=axis['diametro']/2
        cone=cq.Solid.makeCone(radius,gap/2,radius+v['larghezza_linea_vaso'],end,inward)
        if cone.cut(outer).Volume()>1e-5:raise ValueError('Spazio insufficiente per il fondo conico di un innesto del raccordo.')
        closed=bore.fuse(cone)
        if any(closed.intersect(other).Volume()>1e-6 for other in cutters):
            raise ValueError('Fondi degli innesti troppo vicini: aumenta lo spazio riservato a sedi e fondi.')
        cutters.append(closed)
        intercept=root-inward*(root.z/inward.z)
        delta=inward*(height/inward.z)
        specs.append(dict(bore=closed,root=intercept,delta=delta))
        levels.extend((end.z,(end+inward*(radius+v['larghezza_linea_vaso'])).z))
    for number in sorted({axis['longherone'] for axis in axes}):
        paired=sorted([axis for axis in axes if axis['longherone']==number],key=lambda a:a['radice_stampa'][2])
        low,high=paired
        lr=cq.Vector(*low['radice_stampa']);le=cq.Vector(*low['fondo_stampa'])
        hr=cq.Vector(*high['radice_stampa']);he=cq.Vector(*high['fondo_stampa'])
        ld=(le-lr)/(le.z-lr.z);hd=(he-hr)/(he.z-hr.z)
        settling=low['diametro']/2+v['larghezza_linea_vaso']
        lc=le+(le-lr).normalized()*settling
        hc=he+(he-hr).normalized()*settling
        if lc.z>=hc.z:raise ValueError('Fondi conici troppo vicini: aumenta lo spazio riservato a sedi e fondi.')
        stations=[lr+ld*(-pad-lr.z),le,lc,hc,he,hr+hd*(height+pad-hr.z)]
        stations.sort(key=lambda p:p.z)
        frames=[]
        for center in stations:
            frames.append([cq.Vector(x,y,center.z) for x,y in
                ((center.x-gap/2,bounds.ymin-pad),(center.x+gap/2,bounds.ymin-pad),
                 (center.x+gap/2,center.y),(center.x-gap/2,center.y))])
        channels.append(planar_vase_loft(cq,frames))
        guard_frames=[]
        for center in stations:
            guard_frames.append([cq.Vector(x,y,center.z) for x,y in
                ((center.x-ligament,bounds.ymin-pad),(center.x+ligament,bounds.ymin-pad),
                 (center.x+ligament,bounds.ymax+pad),(center.x-ligament,bounds.ymax+pad))])
        guide_guards.append(planar_vase_loft(cq,guard_frames))
        if double:
            upper_stations=list(stations)
            for start,end,root in ((le,lc,lr),(he,hc,hr)):
                for i in range(1,9):upper_stations.append(start+(end-start)*(i/9))
            upper_stations.sort(key=lambda c:c.z)
            top_frames=[]
            paired_cutters=[cutters[i] for i,a in enumerate(axes) if a['longherone']==number]
            for center in upper_stations:
                radius=low['diametro']/2
                # Il bordo reale della sezione include l'inclinazione del foro
                # e del fondo conico, evitando di incidere la sede dall'alto.
                tops=[]
                for cutter in paired_cutters:
                    if cutter.BoundingBox().zmin+1e-5<center.z<cutter.BoundingBox().zmax-1e-5:
                        sec=cq.Workplane('XY').add(cutter).section(center.z).val()
                        if sec.Edges():tops.append(sec.BoundingBox().ymax)
                if tops:bottom=max(tops)+ligament+gap
                elif center.z<le.z or center.z>he.z:bottom=center.y+radius*max(ld.Length,hd.Length)+ligament+gap
                else:bottom=center.y+ligament+gap
                top_frames.append([cq.Vector(x,y,center.z) for x,y in
                    ((center.x-gap/2,bottom),(center.x+gap/2,bottom),
                     (center.x+gap/2,bounds.ymax+pad),(center.x-gap/2,bounds.ymax+pad))])
            upper_channels.append(planar_vase_loft(cq,top_frames))

    # Una traslazione solo lungo Y abbassa il tetto delle fessure senza
    # separarne l'ingresso dal contorno inferiore, anche presso le radici inclinate.
    roof=outer.translate((0,-ligament,0))
    limit=cq.Workplane('XY').box(2*pad,2*pad,height+2*pad).translate((bounds.xmax-ligament-pad,0,height/2)).val()
    roof=roof.intersect(limit)
    ribs=[];junctions=[];rib_guards=[];rib_bases=[]
    if ribs_enabled:
        slope=math.tan(math.radians(params['rib_angle']))
        base=math.floor((bounds.zmin-slope*bounds.xmax)/params['rib_pitch'])*params['rib_pitch']
        if progress:progress('Raccordo zero retrazioni: nervature e setti agli incroci…')
        while base<=bounds.zmax-slope*bounds.xmin:
            rib_bases.append(base)
            rib_guards.append(make_rib_slab(cq,outer,base,slope,0.,height,2*ligament))
            slit=make_rib_slab(cq,outer,base,slope,0.,height,gap).intersect(roof)
            if slit.Volume()>1e-9:
                slit,details,critical=rib_junction_septa(cq,geom,slit,base,specs,outer)
                junctions.extend(details);levels.extend(critical)
                if slit.Volume()>1e-9:ribs.append(slit)
            base+=params['rib_pitch']
    elif progress:progress('Raccordo zero retrazioni: nervature e setti disattivati; canali delle sedi…')
    upper_boundary=outer.translate((0,ligament,0))
    upper_channels=[channel.intersect(upper_boundary) for channel in upper_channels]
    if rib_guards:upper_channels=[channel.cut(*rib_guards) for channel in upper_channels]
    mirror_ribs=[]
    if mirrored:
        opposite_roof=upper_boundary.intersect(limit)
        seat_guards=[]
        for cutter in cutters:
            bb=cutter.BoundingBox()
            seat_guards.append(cq.Workplane('XY').box(bb.xlen+2*ligament,2*pad,bb.zlen+2*ligament)
                .translate(((bb.xmin+bb.xmax)/2,0,(bb.zmin+bb.zmax)/2)).val())
        opposite=-slope
        for original_base in reversed(rib_bases):
            base=height-original_base
            slit=make_rib_slab(cq,outer,base,opposite,0.,height,gap).intersect(opposite_roof)
            if slit.Volume()>1e-9:
                slit=slit.cut(*rib_guards,*guide_guards,*seat_guards)
                if slit.Volume()>1e-9:mirror_ribs.append(slit)
    if mirrored and not mirror_ribs:raise ValueError('Nessuna nervatura specchiata utile: riduci il passo o modifica l’angolo.')
    all_ribs=ribs+mirror_ribs
    all_cutters=cutters+channels+upper_channels+all_ribs
    result=outer.cut(*all_cutters,tol=min(1e-6,gap/1000)) if all_cutters else outer
    if not result.isValid():result=result.fix()
    if not result.isValid() or len(result.Solids())!=1:
        result=outer.cut(*cutters,tol=min(1e-6,gap/1000))
        result=result.cut(*channels,tol=min(1e-6,gap/1000))
        if upper_channels:result=result.cut(*upper_channels,tol=min(1e-6,gap/1000))
        if all_ribs:result=result.cut(*all_ribs,tol=min(1e-6,gap/1000))
        if not result.isValid():result=result.fix()
    if not result.isValid() or len(result.Solids())!=1:raise RuntimeError(f'Raccordo zero retrazioni non valido: valido={result.isValid()}, solidi={len(result.Solids())}.')
    for channel in channels+upper_channels:
        result=result.cut(channel,tol=min(1e-6,gap/1000))
    if not result.isValid():result=result.fix()
    if not result.isValid() or len(result.Solids())!=1:raise RuntimeError('Raccordo non valido dopo l’apertura dei canali.')
    if any(result.intersect(bore).Volume()>1e-5 for bore in bores):raise RuntimeError('Innesto del raccordo ostruito.')
    if progress:progress('Raccordo zero retrazioni: verifica dei contorni…')
    step=v['altezza_strato_vaso']/2
    samples=validate_vase_sections(cq,result,height,extra_z=[z+d for z in levels for d in (-step,step)])
    if params.get('_joiners_active'):
        result._joiner_pattern=outer  # v85 uses original slit volumes directly; no duplicate boolean.
        result._joiner_ribs=all_ribs
        result._joiner_rib_types=['lower']*len(ribs)+['upper']*len(mirror_ribs)
        result._joiner_support_ribs=[make_rib_slab(cq,outer,b,math.tan(math.radians(params['rib_angle'])),0.,height,gap) for b in rib_bases]
        result._joiner_support_types=['lower']*len(rib_bases)
        if mirrored:
            for b in rib_bases:
                slab=make_rib_slab(cq,outer,height-b,-math.tan(math.radians(params['rib_angle'])),0.,height,gap)
                if rib_guards:slab=slab.cut(*rib_guards)
                result._joiner_support_ribs.append(slab);result._joiner_support_types.append('upper')
        result._joiner_cutters=cutters+channels+upper_channels
        result._joiner_cut_types=['bore']*len(cutters)+['lower']*len(channels)+['upper']*len(upper_channels)
    return result,dict(modalita='Spiral Vase a fessure, raccordo centrale sperimentale',componente='raccordo',
        parametri=v,nervature=len(all_ribs),nervature_attive=ribs_enabled,nervature_originali=len(ribs),nervature_specchiate=len(mirror_ribs),doppio_rinforzo=bool(double and axes),nervature_specchiate_attive=mirrored,angoli_nervature=([float(params['rib_angle'])]+([-float(params['rib_angle'])] if mirrored else []) if ribs_enabled else []),setti_locali=junctions,innesti=axes,campioni_sezione=samples,
        apertura_totale=height,quota_radice_originale=0.,fondi_conici=bool(bores),
        nota=('Canale centrale continuo tra le due sedi. Verificare fusione e resistenza con un provino.' if axes else 'Raccordo senza nervature e senza sedi per longheroni; solo involucro esterno.'),
        verifica_slicer='Da eseguire sul G-code; le sezioni CAD non certificano tutti gli strati.')



def vase_requested(params):
    return True  # Unica modalità supportata; parametro mantenuto per i rapporti storici.


def wing_ribs_enabled(params):
    """Scelta semiala/punta/alettone; le configurazioni precedenti restano attive."""
    return str(params.get('create_ribs',True)).strip().lower() in ('1','true','yes','on')


def vase_parameters(params):
    values={}
    for key,default in dict(diametro_ugello=.4,larghezza_linea_vaso=.55,altezza_strato_vaso=.2,fessura_vaso=.05).items():
        try:value=float(str(params.get(key,default)).replace(',','.'))
        except (ValueError,TypeError) as exc:raise ValueError(f"Parametro Spiral Vase non valido: {key}.") from exc
        if not math.isfinite(value) or value<=0:raise ValueError(f"Parametro Spiral Vase non valido: {key}.")
        values[key]=value
    nozzle=values['diametro_ugello'];width=values['larghezza_linea_vaso'];gap=values['fessura_vaso']
    if not .9*nozzle<=width<=1.8*nozzle:raise ValueError("Larghezza linea vaso richiesta tra 0,9 e 1,8 volte il diametro ugello.")
    if values['altezza_strato_vaso']>=nozzle:raise ValueError("Altezza strato inferiore al diametro ugello richiesta.")
    if not .01<=gap<=.15 or gap>=width/2:raise ValueError("Fessura richiesta tra 0,01 e 0,15 mm e inferiore a metà larghezza linea.")
    hinge_slot_parameters(params)
    aileron_cap_parameters(params)
    aileron_parameters(params)
    spars,_=parse_spars(params.get('spars',[]),params.get('spar_clearance',.2),params['span'])
    for index,spar in enumerate(spars,1):
        if spar.get('length',params['span'])<values['altezza_strato_vaso']:
            raise ValueError(f"Lunghezza sede longherone {index} inferiore all’altezza di strato della prova.")
    ribs_active=connector_ribs_enabled(params) if params.get('_componente_esportazione')=='raccordo' else wing_ribs_enabled(params)
    if ribs_active and params['rib_pitch']<4*width:raise ValueError("Passo nervature troppo piccolo per la larghezza di estrusione vaso.")
    oval=oval_parameters(params)
    if oval and oval['hole_height']<=1.3*width:raise ValueError('Altezza ovale insufficiente per il legamento Spiral Vase.')
    values['legamento']=1.3*width
    tip_parameters(dict(params,skin=values['legamento']/2))
    return values


def validate_vase_sections(cq,solid,span,samples=31,extra_z=()):
    """Campionamento CAD, distinto dalla verifica del G-code dello slicer."""
    sections=[]
    quotes=sorted(set([span*(index+.5)/samples for index in range(samples)]+[float(z) for z in extra_z if 1e-5<z<span-1e-5]))
    from mesh_checks import plan_sections
    planned=plan_sections(solid,span,quotes)
    if planned is not None:return planned
    for z in quotes:
        section=cq.Workplane('XY').add(solid).section(z).val()
        count=len(section.Wires())
        sections.append(dict(z=z,contorni=count))
        if count!=1:
            # Sulla faccia orizzontale di termine di una fessura OCC
            # può restituire anche il wire della faccia stessa. Controlla
            # entrambi i lati, senza tollerare un'isola di altezza finita.
            adjacent=[len(cq.Workplane('XY').add(solid).section(z+d).val().Wires())
                      for d in (-1e-5,1e-5) if 0<z+d<span]
            if adjacent and all(n==1 for n in adjacent):
                sections[-1].update(contorni=1,contorni_sul_piano=count,transizione_coplanare=True)
            else:raise RuntimeError(f"Spiral Vase non valido a Z={z:.4f}: {count} contorni. Esportazione bloccata.")
    return sections


def ordered_vase_loft(cq,wires):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    builder=BRepOffsetAPI_ThruSections(True,True,1e-7)
    builder.CheckCompatibility(False)
    for wire in wires:builder.AddWire(wire.wrapped)
    builder.Build()
    if not builder.IsDone():raise RuntimeError('Diramazione della nervatura non riuscita.')
    shape=cq.Shape.cast(builder.Shape())
    if not shape.isValid():raise RuntimeError('Diramazione della nervatura non valida.')
    return shape


def planar_vase_loft(cq,frames):
    """Collega rettangoli con facce piane, senza superfici spline planari.

    Le spline degeneri prodotte dal loft generale possono invertire i wire
    durante l'unione con il sottile canale della sede.
    """
    if len(frames)<2 or abs(frames[-1][0].z-frames[0][0].z)<1e-6:
        raise ValueError('Canale privo di estensione Z: raccordo degenere non generato.')
    def face(points):return cq.Face.makeFromWires(cq.Wire.makePolygon(points,close=True))
    faces=[face(list(reversed(frames[0]))),face(frames[-1])]
    for a,b in zip(frames,frames[1:]):
        for i in range(4):
            j=(i+1)%4
            faces.append(face([a[i],a[j],b[j],b[i]]))
    solid=cq.Solid.makeSolid(cq.Shell.makeShell(faces))
    if not solid.isValid():solid=solid.fix()
    if not solid.isValid():raise RuntimeError('Raccordo piano della nervatura non valido.')
    return solid


def spar_channel_x(params,root,delta,radius,z):
    """Canale sempre centrato sull'asse rettilineo della barra."""
    return (root+delta*(z/params['span'])).x


def routed_spar_channels(cq,params,root,delta,radius,seat_end,settling,stations,roof,outer):
    """Colonna di accesso fissa sull'asse della sede."""
    v=vase_parameters(params);gap=v['fessura_vaso'];span=params['span']
    bounds=exact_shape_bounds(outer);pad=2*max(params['root_chord'],params['tip_chord'],bounds.zmax)
    lo=bounds.zmin;hi=bounds.zmax
    slope=math.tan(math.radians(params['rib_angle'])) if wing_ribs_enabled(params) else 1.
    a=(1+slope*params['sweep']/span)/slope
    base0=-max(params['root_chord'],params['tip_chord'])*slope
    pitch=params['rib_pitch'] if wing_ribs_enabled(params) else 40.;spacing=pitch/slope;rate=a-delta.x/span
    end_cone=seat_end+settling if settling is not None else hi
    def r_at(z):
        if settling is None:return radius
        f=max(0.,min(1.,(z-seat_end)/settling))
        return radius+(gap/2-radius)*f
    def guide_y(z):
        for (za,ya),(zb,yb) in zip(stations,stations[1:]):
            if za-1e-6<=z<=zb+1e-6:
                va=(root+delta*(za/span)).y if ya is None else ya
                vb=(root+delta*(zb/span)).y if yb is None else yb
                return va+(vb-va)*(z-za)/(zb-za)
        return (root+delta*(z/span)).y
    anchors=[lo,hi]+[z for z,_ in stations if lo<z<hi]
    # Intervalli con raggio e soglia di cattura lineari.
    if settling:
        target=(spacing/2-gap)/5-1.3*v['larghezza_linea_vaso']
        if gap/2<target<radius:
            anchors.append(seat_end+settling*(radius-target)/(radius-gap/2))
        anchors.extend(seat_end+settling*i/24 for i in range(1,24))
    anchors=sorted(set(z for z in anchors if lo<=z<=hi))
    zs=list(anchors)
    maxk=int((params['span']+tip_parameters(params)[1]-base0)/pitch)
    for za,zb in zip(anchors,anchors[1:]):
        ra=r_at(za);rb=r_at(zb);rr=(rb-ra)/(zb-za);rc=ra-rr*za
        for k in range(maxk+1):
            offset=-(base0+k*pitch)/slope-root.x
            for sign in (-1,1):
                for cr,constant in ((0.,0.),(0.,spacing/2),(1.,1.3*v['larghezza_linea_vaso']),
                                    (5.,6.5*v['larghezza_linea_vaso']),(0.,spacing/2-gap)):
                    den=rate-sign*cr*rr
                    if abs(den)>1e-10:
                        z=(sign*(cr*rc+constant)-offset)/den
                        if za+1e-6<z<zb-1e-6:zs.append(z)
    zs=sorted(set(zs));critical_levels=set()
    def frames(zvalues,full=False,connector=False):
        samples=[]
        for z in zvalues:
            c=root+delta*(z/span);x=spar_channel_x(params,root,delta,r_at(z),z)
            if connector:
                left=min(c.x,x)-gap/2;right=max(c.x,x)+gap/2;bottom=c.y-gap/2;top=c.y+gap/2
            else:
                left=x-gap/2;right=x+gap/2;bottom=-pad;top=pad if full else guide_y(z)
            point=(z,left,right,bottom,top)
            if samples and z-samples[-1][0]<1e-6:continue
            samples.append(point)
            while len(samples)>=3:
                sa,sb,sc=samples[-3:];f=(sb[0]-sa[0])/(sc[0]-sa[0])
                if max(abs(sb[i]-(sa[i]+(sc[i]-sa[i])*f)) for i in (1,2,3,4))>1e-8:break
                samples.pop(-2)
        critical_levels.update(z for z,*_ in samples)
        return [[cq.Vector(l,b,z),cq.Vector(r,b,z),cq.Vector(r,t,z),cq.Vector(l,t,z)]
                for z,l,r,b,t in samples]
    pieces=[]
    zfull=sorted(set([z for z in zs if z<seat_end]+[min(hi,seat_end)]))
    if len(zfull)>=2:pieces.append(planar_vase_loft(cq,frames(zfull,full=True)).intersect(roof))
    if seat_end<hi-1e-6:
        zafter=sorted(set([seat_end]+[z for z in zs if z>seat_end]))
        pieces.append(planar_vase_loft(cq,frames(zafter)).intersect(roof))
    zbridge=sorted(set([z for z in zs if z<end_cone]+[min(hi,end_cone)]))
    # Nessun collegamento laterale: canale e foro sono coassiali.
    return pieces,sorted(critical_levels)


def rib_junction_septa(cq,params,slit,zbase,specs,outer):
    """Separa soltanto i due ingressi ai nodi, senza spostare le pareti.

    Un setto nominale lungo 1,3 larghezze di linea lascia i due ritorni
    del perimetro distanti 0,3 larghezze: le estrusioni si sovrappongono.
    La nervatura resta sul proprio piano e il canale resta sull'asse.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    v=vase_parameters(params);gap=v['fessura_vaso'];height=v['legamento']
    slope=math.tan(math.radians(params['rib_angle']))
    a=(1+slope*params['sweep']/params['span'])/slope
    half_rib=gap*math.sqrt(1+a*a)/2
    bounds=exact_shape_bounds(outer);pad=2*max(params['root_chord'],params['tip_chord'],bounds.zmax)
    masks=[];details=[];critical=[]
    for index,spec in enumerate(specs,1):
        op=BRepAlgoAPI_Common(spec['bore'].wrapped,slit.wrapped);op.Build()
        if not op.IsDone():raise RuntimeError('Intersezione nervatura/sede non riuscita.')
        if op.Shape().IsNull():continue
        contact=cq.Shape.cast(op.Shape())
        if not contact.Solids() or contact.Volume()<=1e-12:continue
        bb=contact.BoundingBox();lo=max(bounds.zmin,bb.zmin);hi=min(bounds.zmax,bb.zmax)
        if hi-lo<1e-6:continue
        # Quando le fessure verticali sono già sovrapposte condividono
        # l'ingresso: in quell'intervallo il setto non serve.
        rate=a-spec['delta'].x/params['span'];offset=-zbase/slope-spec['root'].x
        overlap=half_rib+gap/2
        if abs(rate)>1e-12:
            ma,mb=sorted(((-overlap-offset)/rate,(overlap-offset)/rate))
            intervals=[(lo,min(hi,ma)),(max(lo,mb),hi)]
        elif abs(offset)<=overlap:intervals=[]
        else:intervals=[(lo,hi)]
        # Il minimo reale dell'intersezione tiene conto di inclinazione,
        # proiezione del cilindro e riduzione conica, senza approssimarle.
        top=bb.ymin-gap;bottom=top-height
        for za,zb in intervals:
            if zb-za<1e-6:continue
            mask=cq.Workplane('XY').box(bounds.xlen+2*pad,height,zb-za).translate(
                 ((bounds.xmin+bounds.xmax)/2,(top+bottom)/2,(za+zb)/2)).val()
            masks.append(mask)
            critical.extend((za,zb,(za+zb)/2))
            details.append(dict(longherone=index,inizio_z=za,fine_z=zb,
                                fondo_y=bottom,sommità_y=top,lunghezza_setto=height,
                                distanza_prevista_centri_estrusione=height-v['larghezza_linea_vaso']))
    if masks:slit=slit.cut(*masks,tol=min(1e-6,gap/1000))
    return slit,details,critical


def build_spiral_vase_wing(params,progress=None):
    """Solido nominale meno fessure cieche, senza skin cava o isole interne.

    Canali fissi sull'asse delle sedi. Ai nodi si separano localmente le
    fessure con setti dimensionati per sovrapporre i ritorni di estrusione,
    mantenendo nervature sul proprio piano e un unico contorno.
    """
    import cadquery as cq
    planform_parameters(params)
    v=vase_parameters(params)
    span=params['span'];cr=params['root_chord'];ct=params['tip_chord'];sweep=params['sweep']
    if not all(math.isfinite(value) for value in (span,cr,ct,sweep)) or min(span,cr,ct)<=0:
        raise ValueError('Dimensioni semiala finite e positive richieste.')
    if params['points']<20 or params['stations']<8:raise ValueError('Usa almeno 20 punti e 8 stazioni.')
    gap=v['fessura_vaso'];ligament=v['legamento'];points=params['points']
    te=max(.9,2*v['larghezza_linea_vaso'])
    tip_enabled,tip_length=tip_parameters(dict(params,skin=ligament/2))
    total=span+tip_length
    tip_scale=0.
    if tip_enabled:
        nominal_thickness=ct*profile_thickness_ratio(params,'tip')
        if nominal_thickness<=0:raise ValueError('Spessore del profilo non nullo richiesto per la punta Spiral Vase.')
        tip_scale=2*v['larghezza_linea_vaso']/nominal_thickness
        if tip_scale>=.9:raise ValueError('Corda di estremità troppo piccola per la terminazione della punta con questo ugello.')
    wires=[];floors=[];floor_profiles=[];edge_profiles=[];roofs=[];tip_outer=None
    pad=2*max(cr,ct,total);top=pad
    def floor_wire(z,chord,lead,scale=1.):
        # Nella punta il TE si riduce con la stessa scala del profilo.
        if tip_enabled and z>span:
            xy=smooth_tip_profile(params,min(.9999,(z-span)/tip_length),points=points)
        else:xy=[(lead+x*chord,y*chord) for x,y in section_profile(params,z,te*scale/chord)]
        lower=[xy[0]]+list(reversed(xy[points+1:]))
        retreat=max(0.,min(1.,(z-(total-3*v['larghezza_linea_vaso']))/(3*v['larghezza_linea_vaso']))) if tip_enabled else 0.
        offset=ligament+retreat*max(0.,2.5*v['larghezza_linea_vaso']-ligament)
        boundary=[(lead-pad,xy[0][1]+offset)]+[(x,y+offset) for x,y in lower]+[(lead+chord+pad,lower[-1][1]+offset)]
        floor_profiles.append((z,boundary));edge_profiles.append((z,min(x for x,y in xy),max(x for x,y in xy)))
        upper=xy[:points+1]
        roof_boundary=[(lead-pad,xy[0][1]-offset)]+[(x,y-offset) for x,y in upper]+[(lead+chord+pad,upper[-1][1]-offset)]
        roofs.append(cq.Wire.makePolygon([cq.Vector(x,y,z) for x,y in roof_boundary+
                     [(lead+chord+pad,-pad),(lead-pad,-pad)]],close=True))
        polygon=boundary+[(lead+chord+pad,top),(lead-pad,top)]
        return cq.Wire.makePolygon([cq.Vector(x,y,z) for x,y in polygon],close=True)
    for z in planform_stations(params):
        chord,lead,_=planform_section(params,z)
        if tip_enabled:
            high=dict(params,points=max(80,points))
            xy=[(lead+x*chord,y*chord) for x,y in section_profile(high,z,te/chord)]
            wires.append(smooth_profile_wire(cq,z,xy))
        else:wires.append(make_section_wire(cq,z,chord,lead,params['airfoil'],points,trailing_edge_thickness=te,profile=section_profile(params,z,te/chord)))
        floors.append(floor_wire(z,chord,lead))
    if tip_enabled:
        zs=[span+tip_length*fraction for fraction,_ in smooth_tip_sections() if fraction>0]
        zs.extend((total-3*v['larghezza_linea_vaso'],total-1.5*v['larghezza_linea_vaso'],total+v['larghezza_linea_vaso']))
        for z in sorted(set(value for value in zs if value>span+1e-7)):
            f=min(1.,(z-span)/tip_length)
            mapped=vase_tip_fraction(f)
            scale=math.sqrt(max(tip_scale**2,1-(1-tip_scale**2)*mapped*mapped))
            floors.append(floor_wire(z,ct*scale,planform_section(params,span)[1]+ct*(1-scale)*tip_center_percentage(params)/100,scale))
    if progress:progress("Spiral Vase: solido nominale e fondo delle fessure…")
    outer=cq.Solid.makeLoft(wires,ruled=not tip_enabled)
    if tip_enabled:
        if progress:progress("Spiral Vase: punta ellittica nominale e fondo rastremato delle nervature…")
        tip_params=dict(params,skin=ligament/2,line_width=v['larghezza_linea_vaso'])
        tip_outer=make_elliptical_tip(cq,tip_params,outer_only=True,terminal_scale=tip_scale)
        outer=outer.fuse(tip_outer)
        if not outer.isValid():outer=outer.fix()
    floor=cq.Solid.makeLoft(floors,ruled=True)
    # Il TE NACA a spessore finito ha una faccia di chiusura inclinata.
    # Il solo margine verticale sull'intradosso non la protegge: una
    # fessura tangente può staccarne una minuscola isola in alcuni strati.
    # Conserva anche un legamento lungo X davanti al bordo d'uscita.
    trailing_wires=[];left_floor=floor.BoundingBox().xmin-pad
    for index,(z,boundary) in enumerate(floor_profiles):
        limit=(edge_profiles[index][2] if tip_enabled else boundary[-1][0]-pad)-ligament
        trailing_wires.append(cq.Wire.makePolygon([cq.Vector(left_floor,-pad,z),cq.Vector(limit,-pad,z),
                                cq.Vector(limit,pad,z),cq.Vector(left_floor,pad,z)],close=True))
    trailing_limit=ordered_vase_loft(cq,trailing_wires)
    floor=floor.intersect(trailing_limit)
    roof=cq.Solid.makeLoft(roofs,ruled=True).intersect(trailing_limit)
    if tip_enabled:
        leading=[]
        for z,left,right in edge_profiles:
            u=max(0.,min(1.,(z-span)/(tip_length*.2)))
            band=ligament*u*u*u*(10-15*u+6*u*u)
            leading.append(cq.Wire.makePolygon([cq.Vector(x,y,z) for x,y in ((left+band,-pad),(pad,-pad),(pad,pad),(left+band,pad))],close=True))
        roof=roof.intersect(ordered_vase_loft(cq,leading))
    def floor_height(z,x):
        # Stessa interpolazione dei vertici del loft del fondo: il ramo
        # non deve sopravvivere dove perde il collegamento con la sede.
        for (za,pa),(zb,pb) in zip(floor_profiles,floor_profiles[1:]):
            if za-1e-7<=z<=zb+1e-7:
                f=(z-za)/(zb-za)
                points=[(xa+(xb-xa)*f,ya+(yb-ya)*f) for (xa,ya),(xb,yb) in zip(pa,pb)]
                values=[ya+(yb-ya)*(x-xa)/(xb-xa) for (xa,ya),(xb,yb) in zip(points,points[1:])
                        if min(xa,xb)-1e-7<=x<=max(xa,xb)+1e-7 and abs(xb-xa)>1e-10]
                return max(values) if values else pad-gap
        return pad-gap
    component=params.get('_componente_esportazione','ala')
    a=aileron_parameters(params)
    servo=make_servo_geometry(cq,params,ligament) if component=='ala' else None
    servo_removed=None
    if servo:
        if progress:progress('Spiral Vase: predisposizione scasso servo e battuta pannello…')
        servo_removed=outer.intersect(servo['body'].fuse(servo['lip'],servo['entry']))
        if outer.intersect(servo['body']).Volume()<1e-6:
            raise ValueError('Servo troppo esterno: il corpo non interseca l’ala. Riduci l’offset verso l’intradosso.')
        if servo_removed.cut(roof).Volume(tol=1e-7)>1e-5:
            raise ValueError('Scasso servo troppo profondo o vicino al bordo: invade l’estradosso o il margine protetto. Modifica offset, misure o posizione.')
    aileron_bounds=None
    slot_cutters=[];slot_supports=[];slot_details=None
    caps=None;cap_clip=None
    if a:
        if progress:progress('Spiral Vase: separazione del vano e del corpo alettone…')
        a,region,cut,selection,hinge=aileron_regions(cq,params,outer)
        if servo and servo_removed.intersect(selection).Volume()>1e-6:
            raise ValueError('Scasso o battuta servo interferiscono con l’alettone: sposta il servo verso il bordo d’attacco.')
        start=a['inizio_alettone'];end=start+a['lunghezza_alettone'];clear=a['gioco_alettone'];axial=aileron_axial_bounds(a)
        slot_details=hinge_slot_parameters(params)
        if slot_details:
            _,_,slot_cutters,wing_supports,movable_supports=make_hinge_slots(
                cq,params,outer,outer.cut(cut),outer.intersect(selection),cut,selection,hinge,True)
            # Canale di avvicinamento stampabile: prima della tasca il
            # percorso entra gradualmente fino alla profondità richiesta.
            # Una tasca sottratta direttamente al pieno partirebbe sospesa.
            slot_cutters.extend(hinge_approach_cutters(cq,params,a,slot_details,hinge,gap))
            supports=movable_supports if component=='alettone' else wing_supports
            # Estende la protezione lungo Y: troncare solo una porzione
            # dell'altezza della fessura produrrebbe un taglio cieco interno.
            # La nervatura resta sul proprio piano, interrotta presso la tasca.
            for support in supports:
                bb=support.BoundingBox()
                xmin,xmax=(-pad,bb.xmax+ligament) if component=='alettone' else (bb.xmin-ligament,pad)
                slot_supports.append(cq.Workplane('XY').box(xmax-xmin,2*pad,bb.zlen+2*gap)
                    .translate(((xmin+xmax)/2,0,(bb.zmin+bb.zmax)/2)).val())
        if component=='alettone':
            outer=outer.intersect(selection)
            caps=aileron_cap_parameters(params)
            if caps:
                z0=axial['part_start'];z1=axial['part_end'];t=caps['spessore']
                cap_clip=cq.Workplane('XY').box(4*pad,4*pad,z1-z0-2*t).translate((0,0,(z0+z1)/2)).val()
                floor=floor.intersect(cap_clip)
                roof=roof.intersect(cap_clip)
                slot_cutters=[cutter.intersect(cap_clip) for cutter in slot_cutters]
            inset=clear/2+ligament/math.cos(math.radians(a['angolo_smusso_alettone']))
            floor=floor.intersect(region(axial['part_start'],axial['part_end'],inset,True))
            # Le nervature entrano dalla superficie inferiore effettiva,
            # compresa la faccia smussata; un inset qui creerebbe tagli ciechi
            # interni scollegati dal perimetro nell'alettone.
            roof=roof.intersect(selection)
            # Protegge lo spigolo estradosso/smusso dalle incisioni tangenti:
            # il loft nominale e la linea cerniera non coincidono esattamente.
            axis0=cq.Vector(*hinge(start),start)
            axis1=cq.Vector(*hinge(end),end)
            direction=(axis1-axis0).normalized()
            corner_guard=cq.Solid.makeCylinder(3*v['larghezza_linea_vaso'],
                (axis1-axis0).Length+2*pad,axis0-direction*pad,direction)
            roof=roof.cut(corner_guard)
        else:
            outer=outer.cut(cut)
            floor=floor.cut(region(axial['cut_start'],axial['cut_end'],-clear/2-ligament))
            roof=roof.cut(region(axial['cut_start'],axial['cut_end'],-clear/2-ligament))
        aileron_bounds=(axial['cut_start'],axial['part_start'],axial['part_end'],axial['cut_end'])
    bores=[];mouths=[];keepouts=[];transitions=[];seat_details=[];branch_specs=[];junction_details=[]
    oval_guards=[];oval_details=[]
    spars,clearance=parse_spars(params.get('spars',[]),params.get('spar_clearance',.2),span)
    if component=='alettone':spars=[]
    bounds=exact_shape_bounds(outer)
    clip=cq.Workplane('XY').box(4*pad,4*pad,span).translate((sweep/2,0,span/2)).val()
    for index,spar in enumerate(spars,1):
        root_values,delta_values=spar_axis(params,spar)
        root=cq.Vector(*root_values);delta=cq.Vector(*delta_values)
        direction=delta.normalized();radius=(spar['diameter']+clearance)/2
        bore=cq.Solid.makeCylinder(radius,delta.Length+2*pad,root-direction*pad,direction)
        seat_end=spar.get('length',span)
        safety_clip=cq.Workplane('XY').box(4*pad,4*pad,seat_end).translate((sweep/2,0,seat_end/2)).val()
        # Il foro cilindrico termina alla quota scelta; oltre quella quota
        # prosegue solo il canale a vicolo cieco, che si ritira gradualmente.
        safe=cq.Solid.makeCylinder(radius+ligament,delta.Length+2*pad,root-direction*pad,direction).intersect(safety_clip)
        oval_guards.append(safe)
        if safe.cut(outer).Volume()>1e-5:raise ValueError(f"Sede longherone {index} troppo grande o vicina alla skin per Spiral Vase. Modifica diametro, posizione, lunghezza o inclinazione.")
        if servo and servo_removed.intersect(safe).Volume()>1e-6:
            raise ValueError(f'Scasso servo in conflitto con la sede longherone {index}: modifica posizione o dimensioni.')
        stations=[(-pad,None),(span+pad,None)]
        guide_exit=None;settling=None
        if tip_enabled or seat_end<span-1e-7:
            final_y=bounds.ymin-(radius+ligament)-2*ligament
            partial=seat_end<span-1e-7
            settling=radius+v['larghezza_linea_vaso'] if partial else v['larghezza_linea_vaso']
            center_at_end=root+delta*((seat_end+settling)/span)
            withdraw=max(0.,center_at_end.y-final_y)/.75
            exit_z=seat_end+settling+withdraw
            guide_exit=exit_z
            if tip_enabled and exit_z+2*v['altezza_strato_vaso']>=total:
                raise ValueError(f"Spazio insufficiente per ritirare il canale del longherone {index} prima dell’apice. "
                                 "Riduci la lunghezza della sede, aumenta la punta oppure riduci il diametro.")
            body_clip=cq.Workplane('XY').box(4*pad,4*pad,seat_end+pad).translate((sweep/2,0,(seat_end-pad)/2)).val()
            if partial:
                seat_center=root+delta*(seat_end/span)
                cylinder=cq.Solid.makeCylinder(radius,(seat_center-root).Length+pad,root-direction*pad,direction)
                cone=cq.Solid.makeCone(radius,gap/2,settling/direction.z,seat_center,direction)
                closed_bore=cylinder.fuse(cone)
                if not closed_bore.isValid():closed_bore=closed_bore.fix()
                if not closed_bore.isValid():raise RuntimeError('Transizione conica della sede non valida.')
                bores.append(closed_bore)
            else:bores.append(bore.intersect(body_clip))
            stations=[(-pad,None),(seat_end,None),(seat_end+settling,None),(exit_z,final_y)]
            transitions.extend((seat_end,seat_end+settling,exit_z))
        else:bores.append(bore)
        seat_details.append(dict(numero=index,lunghezza_z=seat_end,riduzione_conica_z=(radius+v['larghezza_linea_vaso'] if seat_end<span-1e-7 else 0.),fine_canale_z=guide_exit,canale_aperto_in_estremita=bool(guide_exit is not None and not tip_enabled and guide_exit>total)))
        channels,route_levels=routed_spar_channels(cq,params,root,delta,radius,seat_end,settling,stations,roof,outer)
        mouths.extend(channels)
        transitions.extend(z for z in route_levels if 0<z<total)
        branch_specs.append(dict(bore=bores[-1],root=root,delta=delta))
    if progress:progress("Spiral Vase: fessure delle nervature e collegamenti alle sedi…" if wing_ribs_enabled(params) else "Spiral Vase: fessure delle nervature disattivate; collegamenti alle sedi…")
    ribs_enabled=wing_ribs_enabled(params);ribs=[];lower_branches=[];rib_planes=[];mirror_ribs=[]
    if ribs_enabled:
        slope=math.tan(math.radians(params['rib_angle']));base=-max(cr,ct)*slope
        while base<=total+1e-7:
            slab=make_rib_slab(cq,outer,base,slope,sweep,span,gap)
            if wing_mirrored_enabled(params):rib_planes.append(base)
            slit=slab.intersect(roof)
            if not slit.Solids() or slit.Volume()<=1e-8:
                base+=params['rib_pitch']
                continue
            guards=oval_guards+mouths+slot_supports+([servo['guard']] if servo else [])
            slit,details=rib_ovals(cq,params,base,slab,slit,outer,guards,v,camber_thickness)
            if details:
                oval_details.extend(details)
                for item in details:transitions.extend((item['inizio_z'],item['fine_z'],item['centro'][2]))
            if servo:
                slit=slit.cut(servo['guard'])
                if not slit.Solids() or slit.Volume()<=1e-8:
                    base+=params['rib_pitch']
                    continue
            if slot_supports:slit=slit.cut(*slot_supports)
            slit,junctions,levels=rib_junction_septa(cq,params,slit,base,branch_specs,outer)
            junction_details.extend(junctions);transitions.extend(levels)
            if slit.Volume()>1e-8:
                clipped=slit.intersect(outer)
                # Esclude incisioni tangenti più corte di mezzo strato, che
                # possono staccare scaglie numeriche al bordo d'uscita.
                if clipped.Volume()>1e-8 and clipped.BoundingBox().zlen>=v['altezza_strato_vaso']/2:ribs.append(slit)
            base+=params['rib_pitch']
        if not ribs:raise ValueError("Nessuna fessura interna generata: riduci il passo nervature.")
    if oval_parameters(params) and component=='ala' and not oval_details:
        raise ValueError('Nessun ovale compatibile con i margini e le sedi protette: riduci le dimensioni o modifica le nervature.')
    tip_ribs=0
    component_has_tip=tip_enabled and outer.intersect(tip_outer).Volume()>1e-8
    if component_has_tip and ribs_enabled:
        tip_ribs=sum(slit.intersect(tip_outer).Volume()>1e-8 for slit in ribs)
        if not tip_ribs:
            z=span+tip_length*.35
            fallback_xy=smooth_tip_profile(params,.35)
            x=(min(x for x,y in fallback_xy)+max(x for x,y in fallback_xy))/2
            intercept=(1+slope*sweep/span)*z-slope*x
            slit=make_rib_slab(cq,outer,intercept,slope,sweep,span,gap).intersect(roof)
            if keepouts:slit=slit.cut(*keepouts)
            if slit.intersect(tip_outer).Volume()>1e-8:
                ribs.append(slit);tip_ribs=1
                if wing_mirrored_enabled(params):rib_planes.append(intercept)
        if not tip_ribs:raise ValueError("Punta troppo sottile per una nervatura con la larghezza linea selezionata.")
    if wing_mirrored_enabled(params):
        if progress:progress('Spiral Vase: nervature specchiate e protezioni degli incroci…')
        denominator=1+slope*sweep/span
        if abs(denominator)<1e-6:raise ValueError('Freccia e angolo non consentono nervature specchiate: modifica la freccia o l’angolo.')
        opposite=-slope/denominator
        rib_guards=[make_rib_slab(cq,outer,base,slope,sweep,span,2*ligament) for base in rib_planes]
        guide_guards=[]
        for guard in bores+mouths+slot_cutters+slot_supports:
            protected=guard.intersect(outer)
            if not protected.Solids():continue
            bb=protected.BoundingBox()
            guide_guards.append(cq.Workplane('XY').box(bb.xlen+2*ligament,2*pad,bb.zlen+2*ligament)
                                .translate(((bb.xmin+bb.xmax)/2,0,(bb.zmin+bb.zmax)/2)).val())
        guards=rib_guards+guide_guards+slot_supports+([servo['guard']] if servo else [])
        for original_base in reversed(rib_planes):
            base=total-original_base/denominator
            slab=make_rib_slab(cq,outer,base,opposite,0.,span,gap)
            slit=slab.intersect(floor)
            if not slit.Solids() or slit.Volume()<=1e-8:continue
            slit,details=rib_ovals(cq,params,base,slab,slit,outer,guards,v,camber_thickness,
                                  slope_override=opposite,from_upper=True)
            if guards:slit=slit.cut(*guards,tol=min(1e-6,gap/1000))
            clipped=slit.intersect(outer)
            if clipped.Solids() and clipped.Volume()>1e-8 and clipped.BoundingBox().zlen>=v['altezza_strato_vaso']/2:
                mirror_ribs.append(slit)
                for item in details:item['famiglia']='specchiata'
                oval_details.extend(details)
                for item in details:transitions.extend((item['inizio_z'],item['fine_z'],item['centro'][2]))
        if not mirror_ribs:raise ValueError('Nessuna nervatura specchiata utile: riduci il passo o modifica l’angolo.')
        ribs.extend(mirror_ribs)
    boolean_tolerance=min(1e-6,gap/1000)
    cutters=bores+mouths+ribs+lower_branches
    result=outer.cut(*cutters,tol=boolean_tolerance) if cutters else outer
    if not result.isValid():result=result.fix()
    if not result.isValid():
        if progress:progress('Spiral Vase: ricalcolo separato di sedi e raccordi…')
        result=outer.cut(*bores,*mouths,tol=boolean_tolerance) if bores or mouths else outer
        for cutters in (ribs,lower_branches):
            if cutters:result=result.cut(*cutters,tol=boolean_tolerance)
        if not result.isValid():result=result.fix()
    if servo:
        for cutter in slot_cutters:
            if servo_removed.intersect(cutter).Volume()>1e-6:
                raise ValueError('Lo scasso servo interferisce con le asole delle cerniere.')
        result=result.cut(servo['body'],servo['lip'],servo['entry'],tol=boolean_tolerance)
        if not result.isValid():result=result.fix()
    if slot_cutters:result=result.cut(*slot_cutters)
    if not result.isValid() or len(result.Solids())!=1:raise RuntimeError(f"Labirinto vaso non valido: valido={result.isValid()}, solidi={len(result.Solids())}.")
    if progress:progress("Spiral Vase: controllo dei contorni alle quote campione…")
    extra=[]
    step=v['altezza_strato_vaso']/2
    for z in transitions:extra.extend((z-step,z+step))
    if tip_enabled:
        extra=[span+tip_length*math.sin(math.pi*(i+.5)/32) for i in range(16)]
        for z in transitions:extra.extend((z-step,z+step))
        extra.extend((span-step,span+step,total-step))
    if servo:
        extra.extend(z+d for z in servo['levels'] for d in (-step,step))
    if aileron_bounds:
        for z in aileron_bounds:extra.extend((z-step,z+step))
    if slot_details:
        for center in slot_details['centri']:
            for z in (center-slot_details['lunghezza_asole_cerniere']/2-slot_details['lunghezza_rampa_z']-params['skin'],
                      center-slot_details['lunghezza_asole_cerniere']/2-params['skin'],
                      center-slot_details['lunghezza_asole_cerniere']/2,
                      center+slot_details['lunghezza_asole_cerniere']/2,
                      center+slot_details['lunghezza_asole_cerniere']/2+params['skin']):
                extra.extend((z-step,z+step))
    if caps:extra.extend((axial['part_start']+caps['spessore']-step,axial['part_start']+caps['spessore']+step,axial['part_end']-caps['spessore']-step,axial['part_end']-caps['spessore']+step))
    origin_z=result.BoundingBox().zmin
    if params.get('_joiners_active'):
        shift=(0,0,-origin_z if component=='alettone' else 0)
        result._joiner_envelope=outer.translate(shift)
        result._joiner_pattern=outer.translate(shift)
        result._joiner_ribs=[c.translate(shift) for c in ribs+lower_branches]
        result._joiner_rib_types=['lower']*(len(ribs)-len(mirror_ribs))+['upper']*len(mirror_ribs)+['lower']*len(lower_branches)
        support_bases=[];support_slabs=[]
        support_slope=math.tan(math.radians(params['rib_angle']))
        base=-max(cr,ct)*support_slope
        while base<=total+1e-7:
            support_bases.append(base)
            support_slabs.append(make_rib_slab(cq,outer,base,support_slope,sweep,span,gap))
            base+=params['rib_pitch']
        result._joiner_support_ribs=[c.translate(shift) for c in support_slabs]
        result._joiner_support_types=['lower']*len(support_slabs)
        if wing_mirrored_enabled(params):
            guards=[make_rib_slab(cq,outer,b,support_slope,sweep,span,2*ligament) for b in support_bases]
            denominator=1+support_slope*sweep/span
            for b in support_bases:
                slab=make_rib_slab(cq,outer,total-b/denominator,-support_slope/denominator,0.,span,gap)
                if guards:slab=slab.cut(*guards)
                result._joiner_support_ribs.append(slab.translate(shift));result._joiner_support_types.append('upper')
        result._joiner_cutters=[c.translate(shift) for c in bores+mouths]
        result._joiner_cut_types=['bore']*len(bores)+['lower']*len(mouths)
        result._joiner_features=[c.translate(shift) for c in slot_cutters+([servo_removed] if servo else [])]
        count=len(slot_details['centri']) if slot_details else 0
        result._joiner_feature_labels=[f'Asola cerniera {i+1}' for i in range(count)]+[f'Rampa di invito asola cerniera {i+1}' for i in range(len(slot_cutters)-count)]+(['Scasso e battuta servo'] if servo else [])
    if component=='alettone':
        old_result=result
        result=result.translate((0,0,-origin_z))
        for attr in ('_joiner_envelope','_joiner_pattern','_joiner_cutters','_joiner_features','_joiner_cut_types','_joiner_feature_labels','_joiner_ribs','_joiner_rib_types','_joiner_support_ribs','_joiner_support_types'):
            if hasattr(old_result,attr):setattr(result,attr,getattr(old_result,attr))
        total=result.BoundingBox().zmax
        extra=[z-origin_z for z in extra]
    sections=validate_vase_sections(cq,result,total,extra_z=extra)
    params['_verifica_vaso']=dict(pianta=planform_parameters(params),modalita='Spiral Vase a fessure, sperimentale',parametri=v,profili_naca=dict(radice=params['airfoil'],estremita=airfoil_tip_code(params),transizione='interpolazione lineare dei punti normalizzati'),
         alleggerimenti_ovali=dict(attivi=bool(oval_parameters(params)),parametri=oval_parameters(params),numero_finestre_accettate=len(oval_details),fori=oval_details,strategia='nervature interrotte da finestre ovali; fessure cieche contrapposte e sedi protette'),
         nervature=len(ribs),nervature_attive=ribs_enabled,nervature_originali=len(ribs)-len(mirror_ribs),nervature_specchiate=len(mirror_ribs),nervature_specchiate_attive=wing_mirrored_enabled(params),rami_inferiori_nervature=0,strategia_nervature=('canale coassiale fisso e setti locali agli incroci' if ribs_enabled else 'nervature disattivate; canali sedi mantenuti'),setti_locali=junction_details,nervature_punta=tip_ribs,linea_centrale_punta_percentuale=tip_center_percentage(params) if tip_enabled else None,lunghezza_punta=tip_length if component_has_tip else 0.,apertura_totale=total,corda_terminale_punta=0.,superficie_punta='spline cubiche e calotta arrotondata' if component_has_tip else None,punti_superficie_esterna=max(80,points) if tip_enabled else points,
         quote_transizioni_sedi=transitions,dettagli_sedi=seat_details,longheroni=len(spars),campioni_sezione=sections,
         verifica_slicer='Da eseguire sul G-code; il campionamento CAD non certifica tutti gli strati.',
         giochi_alettone=dict(cerniera=a['gioco_alettone'],radice=a['gioco_alettone_radice'],estremita=a['gioco_alettone_estremita'],quote=aileron_axial_bounds(a)) if a else None,
         servo=servo['details'] if servo else None,
         chiusure_estremita=caps,asole_cerniere=slot_details,componente=component,quota_radice_originale=origin_z,
         sbalzo_sopra_vano=bool(a and component=='ala' and aileron_axial_bounds(a)['cut_end']<span+tip_length),
         note='0,05 mm non è universale; verificare conservazione dei dettagli e fusione del materiale con un provino.')
    if params.get('_joiners_active'):
        from joiners import oval_entry_regions
        result._joiner_opposite_entries,result._joiner_opposite_types=oval_entry_regions(params,oval_details,origin_z if component=='alettone' else 0.)
    return result,len(ribs)


def write_vase_sidecars(params,path):
    """Frammento impostazioni geometriche, non un profilo macchina completo."""
    v=vase_parameters(params);path=Path(path)
    caps=aileron_cap_parameters(params) if params.get('_componente_esportazione')=='alettone' else None
    settings=path.with_suffix('.chiusure.ini' if caps else '.spiral_vase.ini');report=path.with_suffix('.verifica_vaso.json')
    female_joiner=bool(params.get('_female_joiner',False))
    settings.write_text('# Frammento per PrusaSlicer: mantenere il proprio profilo stampante e filamento.\n' +
        (f"spiral_vase = 0\nperimeters = 1\nfill_density = 0%\ntop_solid_layers = {caps['strati']}\nbottom_solid_layers = {caps['strati']}\ntop_solid_min_thickness = 0\nsolid_fill_pattern = rectilinear\ntop_fill_pattern = rectilinear\nbottom_fill_pattern = rectilinear\n" if caps else
         f'spiral_vase = 1\nperimeters = 1\nfill_density = 0%\ntop_solid_layers = 0\nbottom_solid_layers = {0 if female_joiner else 3}\n') +
        'retract_length = 0\nfilament_retract_length = 0\nfilament_retract_layer_change = 0\n'
        f"support_material = 0\nraft_layers = 0\nbottom_solid_min_thickness = 0\narc_fitting = disabled\nperimeter_generator = classic\nthin_walls = 0\ngap_fill_enabled = 0\nextra_perimeters = 0\nextra_perimeters_on_overhangs = 0\nseam_gap_distance = 0\nretract_layer_change = 0\nslice_closing_radius = {min(.005,v['fessura_vaso']/10):g}\nresolution = 0.001\ngcode_resolution = 0.001\n"
        f"nozzle_diameter = {v['diametro_ugello']:g}\nlayer_height = {v['altezza_strato_vaso']:g}\n"
        f"first_layer_height = {v['altezza_strato_vaso']:g}\nexternal_perimeter_extrusion_width = {v['larghezza_linea_vaso']:g}\n"
        f"perimeter_extrusion_width = {v['larghezza_linea_vaso']:g}\n",encoding='utf-8')
    full_report=dict(params.get('_verifica_vaso',{}))
    if 'verifica_ovali_gcode' not in full_report:
        full_report['verifica_ovali_gcode']=dict(eseguita=False,esito=None,motivo='Verifica G-code non eseguita per questa esportazione')
    if not full_report['verifica_ovali_gcode'] or not full_report['verifica_ovali_gcode'].get('eseguita',False):
        full_report['verifica_slicer']='NON ESEGUITA: nessuna certificazione dei percorsi G-code; controlli geometrici e della mesh indipendenti.'
    full_report['impostazioni_slicer']=settings.name
    full_report['spirale_continua']=not bool(caps)
    if female_joiner:
        full_report['ingresso_femmina_aperto']=True
        full_report['strati_pieni_pezzo']=dict(inferiori=0,superiori=0)
    full_report['versione_generatore']=VERSION
    full_report['parametri_generazione']={k:value for k,value in params.items() if not k.startswith('_')}
    report.write_text(json.dumps(full_report,ensure_ascii=False,indent=2),encoding='utf-8')
    return settings,report


def analyze_vase_gcode(path,spiral_from_nominal_z):
    """Verifica G0/G1 e M82/M83; esclude base, transizione e G-code custom.

    Non certifica resistenza, fusione del filamento o compatibilità con la
    stampante. Misura ritrazioni, travel XY e crescita Z nel tratto spirale.
    """
    xyz=[0.,0.,0.];e=0.;absolute_e=True;nominal=0.;role='';layers={}
    moves=travels=descents=spiral_moves=0
    retraction_events=[]
    extrusion_roles=set()
    for raw in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
        line=raw.strip()
        if line.startswith(';Z:'):nominal=float(line[3:]);continue
        if line.startswith(';TYPE:'):role=line[6:];continue
        command=line.split(';',1)[0].strip()
        if not command:continue
        parts=command.split();code=parts[0]
        values={m.group(1):float(m.group(2)) for m in re.finditer(r'([XYZE])(-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))',command)}
        if code=='M82':absolute_e=True;continue
        if code=='M83':absolute_e=False;continue
        if code=='G91':raise ValueError('Analisi G-code: coordinate XYZ relative non supportate.')
        if code=='G92':
            if 'E' in values:e=values['E']
            continue
        if code in ('G2','G3'):raise ValueError('Analisi G-code: archi G2/G3 non supportati; disattiva arc fitting.')
        if code=='G10' and nominal>=spiral_from_nominal_z and role!='Custom':retraction_events.append(moves)
        if code not in ('G0','G1'):continue
        target=[values.get(key,xyz[i]) for i,key in enumerate('XYZ')]
        de=(values['E']-e if absolute_e else values['E']) if 'E' in values else 0.
        if 'E' in values:e=values['E'] if absolute_e else e+values['E']
        length=math.hypot(target[0]-xyz[0],target[1]-xyz[1])
        if nominal>=spiral_from_nominal_z-1e-6 and role!='Custom':
            if de<-1e-5:retraction_events.append(moves)
            if length>.002 and de<=0:travels+=1
            if length>.002 and de>0:
                moves+=1;extrusion_roles.add(role)
                if target[2]>xyz[2]+.00005:spiral_moves+=1
                layers[round(nominal,5)]=layers.get(round(nominal,5),0.)+length
            if target[2]<xyz[2]-.002:descents+=1
        xyz=target
    retracts=sum(count<moves for count in retraction_events)
    return dict(file=str(path),z_nominale_inizio_analisi=spiral_from_nominal_z,
        movimenti_estrusi=moves,movimenti_con_crescita_z=spiral_moves,travel_xy=travels,ritrazioni=retracts,ritrazioni_finali_escluse=len(retraction_events)-retracts,discese_z=descents,
        strati_analizzati=len(layers),tipi_percorso=sorted(extrusion_roles),lunghezze_per_strato=layers,
        esito=bool(spiral_moves and moves and not travels and not retracts and not descents
                   and not (extrusion_roles-set(('External perimeter','Overhang perimeter')))),
        limite='Analisi cinematica del G-code, non prova fisica né profilo macchina pronto alla stampa.')


def build_solid(params, progress=None):
    """CAD nominale a fessure; export_verified_stl applica il washout associato.

    I tagli Z precedono la deformazione e conservano la quota originale.
    """
    params['modalita_vaso_fessure']=True
    w=washout_parameters(params)
    result,count=build_spiral_vase_wing(params,progress)
    params['_verifica_vaso']['washout']=dict(w,progressione='lineare fino alla semiala; costante nella punta',perno='linea di corda Y=0')
    if oval_parameters(params) or elliptical_planform(params) or wing_mirrored_enabled(params) or has_manual_spar_angles(params):result._oval_params=params
    if w['washout_deg']:
        result._washout_params={k:v for k,v in params.items() if not k.startswith('_')}
        result._washout_origin=params['_verifica_vaso']['quota_radice_originale'] if params.get('_componente_esportazione')=='alettone' else 0.
    return result,count


def params_from_ui(values):
    p={k:v.get().strip() for k,v in values.items()}
    p['modalita_vaso_fessure']=True
    for key in ('span','root_chord','tip_chord','sweep','line_width'):
        p[key]=float(p[key].replace(',','.'))
        if not math.isfinite(p[key]):raise ValueError('I parametri numerici devono essere finiti.')
    p['create_ribs']=wing_ribs_enabled(p)
    p['nervature_specchiate_ala']=wing_mirrored_enabled(p)
    oval=oval_parameters(p);p['create_oval_holes']=bool(oval)
    if oval:p.update(oval)
    for key,default in (('rib_pitch',40.),('rib_angle',45.)):
        if p['create_ribs']:
            p[key]=float(p[key].replace(',','.'))
            if not math.isfinite(p[key]):raise ValueError('I parametri nervature devono essere finiti.')
        else:
            try:value=float(p[key].replace(',','.'))
            except (ValueError,TypeError):value=default
            valid=math.isfinite(value) and (value>0 if key=='rib_pitch' else 20<=value<=70)
            p[key]=value if valid else default
    for key in ('points','stations'):p[key]=int(p[key])
    if min(p[k] for k in ('span','root_chord','tip_chord','line_width','rib_pitch'))<=0:
        raise ValueError('Le dimensioni devono essere positive.')
    if p['create_ribs'] and not 20<=p['rib_angle']<=70:raise ValueError('Angolo nervature richiesto tra 20 e 70 gradi.')
    if p['points']<20 or p['stations']<8:raise ValueError('Usa almeno 20 punti profilo e 8 stazioni.')
    # Spessori condivisi da alloggiamenti e raccordo; nessun selettore CAD.
    p['skin_perimeters']=p['rib_perimeters']=1
    p['skin']=p['rib_thickness']=p['line_width']
    airfoil_profile(p,'root',p['points'])
    airfoil_profile(p,'tip',p['points'])
    airfoil_tip_code(p)
    p.update(planform_parameters(p))
    p['elliptical_tip'],p['tip_length']=tip_parameters(p)
    vase_parameters(p)
    p.update(washout_parameters(p))
    servo_parameters(p)
    return p


def mesh_edges(triangles):
    edges, directions = Counter(), Counter()
    for vertices in triangles:
        for a, b in zip(vertices, vertices[1:]+vertices[:1]):
            edge = tuple(sorted((a, b)))
            edges[edge] += 1
            directions[edge] += 1 if a < b else -1
    return edges, directions


def conform_mesh_edges(points, triangles, tolerance=1e-7):
    """Suddivide micro-spigoli con vertici intermedi senza colmare aperture.

    Il mesher può usare A-D su una faccia e A-B-C-D sulla faccia adiacente.
    Si suddivide il triangolo A-D lungo B e C, conservando i suoi vertici,
    l'orientamento e la superficie. Non vengono inseriti tappi o nuove facce.
    """
    for _ in range(8):
        edges, _ = mesh_edges(triangles)
        boundary = {edge for edge, count in edges.items() if count == 1}
        candidates = {v for edge in boundary for v in edge}
        if not boundary:
            return triangles
        changed, result = False, []
        for vertices in triangles:
            split = False
            for j in range(3):
                a, b, c = vertices[j], vertices[(j+1)%3], vertices[(j+2)%3]
                if tuple(sorted((a,b))) not in boundary:
                    continue
                pa, pb = points[a], points[b]
                delta = [pb[k]-pa[k] for k in range(3)]
                length2 = sum(v*v for v in delta)
                if length2<=0:
                    continue
                intermediate = []
                for v in candidates-{a,b,c}:
                    pv = points[v]
                    t = sum((pv[k]-pa[k])*delta[k] for k in range(3))/length2
                    if not 0 < t < 1:
                        continue
                    distance2 = sum((pv[k]-pa[k]-t*delta[k])**2 for k in range(3))
                    if distance2 <= tolerance*tolerance:
                        intermediate.append((t,v))
                if intermediate:
                    chain = [a]+[v for _,v in sorted(intermediate)]+[b]
                    result.extend([[u,v,c] for u,v in zip(chain,chain[1:])])
                    changed = split = True
                    break
            if not split:
                result.append(vertices)
        triangles = result
        if not changed:
            break
    return triangles


def cancel_opposite_triangles(triangles):
    """Rimuove solo coppie di facce identiche con orientamento opposto.

    Una coppia coincidente non delimita volume. OCCT può produrla
    al vertice della cavità dopo la riparazione del solido CAD.
    """
    pending, result = {}, []
    for triangle in triangles:
        a,b,c = triangle
        key = tuple(sorted(triangle))
        orientation = 1 if (b-a)*(c-b)*(a-c) > 0 else -1
        opposite = (key,-orientation)
        if pending.get(opposite):
            result[pending[opposite].pop()] = None
        else:
            pending.setdefault((key,orientation),[]).append(len(result))
            result.append(triangle)
    return [triangle for triangle in result if triangle is not None]


def export_verified_stl(solid, path, tolerance=0.08, progress=None, params=None, z_offset=None):
    """Esporta prima in un file temporaneo e verifica la mesh binaria riletta."""
    import cadquery as cq
    target = Path(path)
    quote_plan=getattr(solid,'_vase_check_quotes',[])
    cache_key=json.dumps(dict(shape=solid.hashCode(),tolerance=tolerance,z_offset=z_offset,
        origin=getattr(solid,'_washout_origin',0.),component=(params or {}).get('_componente_esportazione'),quotes=quote_plan,
        params={k:v for k,v in (params or {}).items() if not k.startswith('_')}),sort_keys=True)
    cached_mesh=getattr(solid,'_verified_stl_cache',None)
    fd, temporary = tempfile.mkstemp(suffix=".stl", dir=target.parent)
    os.close(fd)
    try:
        if cached_mesh and cached_mesh['key']==cache_key:
            Path(temporary).write_bytes(cached_mesh['bytes']);box=solid.BoundingBox()
            if params is not None:
                params['_mesh_sections_required']=bool(quote_plan)
                params.setdefault('_verifica_vaso',{})['campioni_mesh_finale']=cached_mesh['checks']
                params['_verifica_vaso']['mesh_riutilizzata']=True
                if quote_plan:params['_verifica_vaso']['campioni_sezione']=cached_mesh['checks']
            if progress:progress('write',1,1)
            config=params if params is not None else getattr(solid,'_oval_params',None)
            if config is not None and (oval_parameters(config) or elliptical_planform(config) or wing_mirrored_enabled(config) or has_manual_spar_angles(config) or config.get('_joiners_active') or config.get('_mesh_sections_required')):
                if progress:progress('slicer',0,1)
                verify_oval_export(config,temporary,analyze_vase_gcode,write_vase_sidecars,(box.xlen,box.ylen,box.zlen),progress=progress)
                if progress:progress('slicer',1,1)
            size=Path(temporary).stat().st_size;os.replace(temporary,target);return size
        if progress:progress("triangulation",None,None)
        solid.exportStl(temporary,tolerance=tolerance,angularTolerance=.08,
                        ascii=False,relative=False,parallel=False)
        data = Path(temporary).read_bytes()
        if len(data) < 84:
            raise RuntimeError("File STL vuoto o incompleto")
        count = struct.unpack_from("<I", data, 80)[0]
        if count == 0 or len(data) != 84+50*count:
            raise RuntimeError("Struttura STL binaria non valida")
        edges = Counter()
        directions = Counter()
        # La precisione del float32 STL dipende dalla scala delle coordinate.
        # Salda al massimo due ULP, senza superare 1/10 della tolleranza mesh:
        # non vengono colmate aperture geometriche, solo scarti numerici.
        vertex_bins = {}
        welded_points = []
        triangles = []
        box=solid.BoundingBox()
        scale=max(1.,*(abs(c) for c in (box.xmin,box.xmax,box.ymin,box.ymax,box.zmin,box.zmax)))
        float32_ulp=2.**(math.frexp(scale)[1]-24)
        weld_tolerance=min(max(1e-7,2*float32_ulp),max(1e-7,tolerance/10))
        def vertex_id(point):
            cell = tuple(math.floor(c/weld_tolerance) for c in point)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        key = (cell[0]+dx, cell[1]+dy, cell[2]+dz)
                        for other, index in vertex_bins.get(key, ()):
                            if sum((a-b)**2 for a,b in zip(point,other)) <= weld_tolerance**2:
                                return index
            index = vertex_id.count
            vertex_id.count += 1
            welded_points.append(point)
            vertex_bins.setdefault(cell, []).append((point,index))
            return index
        vertex_id.count = 0
        if progress:progress("vertices",0,count)
        for i in range(count):
            if progress and i % max(1,count//100)==0:progress("vertices",i,count)
            coords = struct.unpack_from("<9f", data, 84+50*i+12)
            vertices = [tuple(coords[j:j+3]) for j in (0, 3, 6)]
            if not all(math.isfinite(c) for c in coords):
                raise RuntimeError("Triangolo STL con coordinate non finite")
            vertices = [vertex_id(v) for v in vertices]
            if len(set(vertices)) != 3:
                continue
            triangles.append(vertices)
        if progress:progress("vertices",count,count)
        if progress:progress("mesh_check",None,None)
        def noncollapsed(triangle):
            a,b,c=[welded_points[i] for i in triangle]
            ab=[b[i]-a[i] for i in range(3)];ac=[c[i]-a[i] for i in range(3)]
            return any(value!=0 for value in (ab[1]*ac[2]-ab[2]*ac[1],
                       ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]))
        triangles=[t for t in triangles if noncollapsed(t)]
        for _ in range(4):
            triangles=cancel_opposite_triangles(triangles)
            triangles=conform_mesh_edges(welded_points,triangles,weld_tolerance)
            cleaned=[t for t in triangles if noncollapsed(t)]
            if len(cleaned)==len(triangles):break
            triangles=cleaned
        edges, directions = mesh_edges(triangles)
        if not triangles:
            raise RuntimeError("La mesh STL non contiene triangoli validi")
        if any(n != 2 for n in edges.values()) or any(directions.values()):
            if params is not None and params.get('_mesh_debug'):
                bad=[dict(a=welded_points[a],b=welded_points[b],molteplicita=n,versi=directions[(a,b)]) for (a,b),n in edges.items() if n!=2 or directions[(a,b)]]
                Path(params['_mesh_debug']).write_text(json.dumps(bad,indent=2),encoding='utf-8')
            raise RuntimeError(f"Mesh STL non chiusa: {sum(n != 2 for n in edges.values())} spigoli anomali, {sum(v != 0 for v in directions.values())} orientamenti incoerenti")
        washout=params if params is not None else getattr(solid,'_washout_params',None)
        if washout is not None and washout.get('_componente_esportazione')!='raccordo' and washout_parameters(washout)['washout_deg']:
            origin=getattr(solid,'_washout_origin',0.) if z_offset is None else z_offset
            welded_points,triangles=washout_mesh(washout,welded_points,triangles,origin,tolerance,progress)
            # Quantizzazione float32: salda solo vertici esattamente identici.
            unique={};remap={};final_points=[]
            for index,point in enumerate(welded_points):
                if point not in unique:unique[point]=len(final_points);final_points.append(point)
                remap[index]=unique[point]
            triangles=[[remap[i] for i in triangle] for triangle in triangles]
            welded_points=final_points
            triangles=[t for t in triangles if len(set(t))==3 and noncollapsed(t)]
            for _ in range(4):
                triangles=cancel_opposite_triangles(triangles)
                triangles=conform_mesh_edges(welded_points,triangles,weld_tolerance)
                cleaned=[t for t in triangles if noncollapsed(t)]
                if len(cleaned)==len(triangles):break
                triangles=cleaned
            edges,directions=mesh_edges(triangles)
            if any(n!=2 for n in edges.values()) or any(directions.values()):
                raise RuntimeError(f'Mesh washout non chiusa: {sum(n!=2 for n in edges.values())} spigoli anomali, {sum(d!=0 for d in directions.values())} orientamenti incoerenti. Esportazione bloccata.')
        planned_quotes=getattr(solid,'_vase_check_quotes',[])
        if planned_quotes:
            from mesh_checks import mesh_section_checks
            checks,check_seconds=mesh_section_checks(welded_points,triangles,planned_quotes,progress)
            if params is None:raise ValueError('Parametri necessari per verificare tutte le sezioni della mesh finale.')
            params['_mesh_sections_required']=True
            params.setdefault('_verifica_vaso',{})['campioni_mesh_finale']=checks
            params['_verifica_vaso']['secondi_controllo_sezioni_mesh']=check_seconds
            params['_verifica_vaso']['campioni_sezione']=checks
        # Salva esattamente la mesh saldata che è stata verificata, eliminando
        # i triangoli collassati prodotti occasionalmente dal mesher CAD.
        if progress:progress("write",0,len(triangles))
        with open(temporary, "wb") as stream:
            stream.write(data[:80])
            stream.write(struct.pack("<I", len(triangles)))
            for triangle_index,indices in enumerate(triangles):
                if progress and triangle_index % max(1,len(triangles)//100)==0:progress("write",triangle_index,len(triangles))
                a, b, c = [welded_points[index] for index in indices]
                ab, ac = [b[j]-a[j] for j in range(3)], [c[j]-a[j] for j in range(3)]
                normal = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
                length = math.sqrt(sum(v*v for v in normal))
                if length == 0:
                    raise RuntimeError("Triangolo STL con area nulla")
                normal = tuple(v/length for v in normal)
                stream.write(struct.pack("<12fH", *(normal+a+b+c), 0))
        size = Path(temporary).stat().st_size
        if progress:progress("write",len(triangles),len(triangles))
        config=params if params is not None else getattr(solid,'_oval_params',None)
        if config is not None and (oval_parameters(config) or elliptical_planform(config) or wing_mirrored_enabled(config) or has_manual_spar_angles(config) or config.get('_joiners_active') or config.get('_mesh_sections_required')):
            if progress:progress('slicer',0,1)
            verify_oval_export(config,temporary,analyze_vase_gcode,write_vase_sidecars,(box.xlen,box.ylen,box.zlen),progress=progress)
            if progress:progress('slicer',1,1)
        solid._verified_stl_cache=dict(key=cache_key,bytes=Path(temporary).read_bytes(),checks=(params or {}).get('_verifica_vaso',{}).get('campioni_mesh_finale',[]))
        os.replace(temporary, target)
        return size
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


