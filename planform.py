"""Shared nominal planform; all lengths in mm, span along Z."""
# File revision: 6
import json
import math
from functools import lru_cache
from airfoil_editor import profile_from_controls

PLANFORM_EDGES=('leading','trailing')
NODE_TYPES=('cc','ll','lc','cl')


@lru_cache(maxsize=128)
def planform_nodes(raw):
    """Each node stores span fraction and signed offset in mm from the base edge."""
    values=json.loads(raw) if raw else {}
    if not isinstance(values,dict) or set(values)-set((*PLANFORM_EDGES,'trailing_end','tip_apex','node_types')):
        raise ValueError('Nodi della pianta non validi.')
    if 'tip_apex' in values:
        apex=values['tip_apex']
        if (not isinstance(apex,list) or len(apex)!=2
                or any(type(v) not in (int,float) or not .25<=v<=2.5 for v in apex)):
            raise ValueError('Maniglie della punta non valide.')
    if 'trailing_end' in values:
        end=values['trailing_end']
        if (not isinstance(end,list) or len(end)!=2
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in end)
                or not 0<end[1]<1):
            raise ValueError('Tangente terminale non valida.')
    result=[]
    for edge in PLANFORM_EDGES:
        nodes=values.get(edge,[])
        if not isinstance(nodes,list) or len(nodes)>64:raise ValueError('Massimo 64 nodi per bordo.')
        previous=0.
        edge_nodes=[]
        for node in nodes:
            if not isinstance(node,list) or len(node) not in (2,3,5,7) or any(type(value) not in (int,float) or not math.isfinite(value) for value in node):
                raise ValueError('Nodo della pianta non valido.')
            fraction=node[0]
            if not previous<fraction<1:
                raise ValueError('I nodi devono essere ordinati fra radice ed estremità.')
            edge_nodes.append(tuple(node))
            previous=fraction
        result.append(tuple(edge_nodes))
    if 'node_types' in values:
        types=values['node_types']
        if (not isinstance(types,list) or len(types)!=2
                or any(not isinstance(edge,list) or len(edge)!=len(nodes)
                       or any(mode not in NODE_TYPES for mode in edge)
                       for edge,nodes in zip(types,result))):
            raise ValueError('Tipi di nodo della pianta non validi.')
    return tuple(result)


@lru_cache(maxsize=128)
def planform_node_types(raw):
    nodes=planform_nodes(raw)
    values=json.loads(raw) if raw else {}
    return tuple(tuple(edge) for edge in values.get('node_types',[['cc']*len(edge) for edge in nodes]))


def straight_segments(types):
    modes=('cc',*types,'cc')
    return tuple(a[1]=='l' or b[0]=='l' for a,b in zip(modes,modes[1:]))


def node_fractions(p):
    return {node[0] for edge in planform_nodes(p.get('planform_nodes','')) for node in edge}


def edge_offset(nodes,fraction):
    if not nodes or not 0<fraction<1:return 0.
    points=((0.,0.),*(node[:2] for node in nodes),(1.,0.))
    for (a,first),(b,last) in zip(points,points[1:]):
        if fraction<=b:return first+(last-first)*(fraction-a)/(b-a)
    return 0.


@lru_cache(maxsize=128)
def trailing_end_settings(raw):
    planform_nodes(raw)
    return tuple(json.loads(raw).get('trailing_end',())) if raw else ()


def curve_controls(nodes,trailing_end=None):
    # Optional final fields on the first/last node preserve the endpoint
    # handles when a Bézier segment is split next to a fixed endpoint.
    start=nodes[0][5] if nodes and len(nodes[0])==7 else 0.
    end=nodes[-1][6] if nodes and len(nodes[-1])==7 else 0.
    points=((0.,0.,0.,0.,start),*nodes,(1.,0.,0.,end,0.))
    controls=[]
    for index,point in enumerate(points):
        if len(point)>=3:
            controls.append((*point[:3],*(point[3:5] if len(point)>=5 else (0.,0.))))
            continue
        f,offset=point
        lo,left=points[index-1][:2]
        hi,right=points[index+1][:2]
        a,b=(offset-left)/(f-lo),(right-offset)/(hi-f)
        slope=2*a*b/(a+b) if a*b>0 else 0.
        controls.append((f,offset,slope,0.,0.))
    if nodes and trailing_end is not None:
        a,y,slope,incoming,outgoing=controls[-2]
        m,length=trailing_end or (-y/(1-a),end)
        terminal=(1.,0.,m,length,0.)
        if trailing_end:
            controls[-1]=terminal
            return controls
        left,right=segment_handles(controls[-2],terminal)
        # Keep the last segment's offset control points between its endpoints.
        # Both adjacent segments use the limited slope at the last editable node.
        sign=1 if y<0 else -1
        travel=abs(y)
        first=min(travel,max(0.,sign*slope*left))
        last=min(travel,max(0.,sign*m*right))
        factor=min(1.,travel/(first+last)) if first+last else 1.
        controls[-2]=(a,y,sign*first*factor/left,incoming,outgoing)
        controls[-1]=(1.,0.,sign*last*factor/right,length,0.)
    return controls


def segment_handles(a,b):
    span=b[0]-a[0]
    left=a[4] if a[4]>0 else span/3
    right=b[3] if b[3]>0 else span/3
    # Keep the control points ordered in span. This makes dx/dt positive,
    # even when a handle is dragged beyond its neighbouring node.
    factor=min(1.,.999*span/(left+right))
    return left*factor,right*factor


def node_handle_lengths(nodes,index,trailing_end=None):
    points=curve_controls(nodes,trailing_end)
    return segment_handles(points[index],points[index+1])[1],segment_handles(points[index+1],points[index+2])[0]


def bezier_controls(a,b):
    left,right=segment_handles(a,b)
    return ((a[0],a[1]),(a[0]+left,a[1]+a[2]*left),
            (b[0]-right,b[1]-b[2]*right),(b[0],b[1]))


def mix_point(a,b,t):
    return tuple(x+(y-x)*t for x,y in zip(a,b))


def bezier_split(points,t):
    a,b,c,d=points
    ab,bc,cd=mix_point(a,b,t),mix_point(b,c,t),mix_point(c,d,t)
    left,right=mix_point(ab,bc,t),mix_point(bc,cd,t)
    knot=mix_point(left,right,t)
    return (a,ab,left,knot),(knot,right,cd,d)


def bezier_parameter(points,fraction):
    lo,hi=0.,1.
    for _ in range(36):
        t=(lo+hi)/2
        u=1-t
        x=u**3*points[0][0]+3*u*u*t*points[1][0]+3*u*t*t*points[2][0]+t**3*points[3][0]
        if x<fraction:lo=t
        else:hi=t
    return (lo+hi)/2


def curve_offset(nodes,fraction,trailing_end=None):
    """Return offset and derivative in mm per unit of span fraction."""
    if not nodes or not 0<fraction<1:return 0.,0.
    return evaluate_curve(curve_controls(nodes,trailing_end),fraction)


def evaluate_curve(controls,fraction):
    for first,last in zip(controls,controls[1:]):
        a,y0,m0=first[:3]
        b,y1,m1=last[:3]
        if fraction<=b:
            h=b-a
            t=(fraction-a)/h
            if not first[4] and not last[3]:
                c=3*(y1-y0)-h*(2*m0+m1)
                d=2*(y0-y1)+h*(m0+m1)
                return y0+t*(h*m0+t*(c+t*d)),m0+t*(2*c+3*t*d)/h
            if fraction==b:return y1,m1
            points=bezier_controls(first,last)
            left,right=bezier_split(points,bezier_parameter(points,fraction))
            knot=left[-1]
            return knot[1],(right[1][1]-left[2][1])/(right[1][0]-left[2][0])
    return 0.,0.


def insert_curve_node(nodes,fraction,trailing_end=None):
    if not nodes:return [(fraction,0.,0.)]
    points=[list(point) for point in curve_controls(nodes,trailing_end)]
    i=next(i for i in range(len(points)-1) if fraction<points[i+1][0])
    segment=bezier_controls(points[i],points[i+1])
    left,right=bezier_split(segment,bezier_parameter(segment,fraction))
    knot=left[-1]
    _,slope=curve_offset(nodes,fraction,trailing_end)
    points[i][4]=left[1][0]-left[0][0]
    points[i+1][3]=right[-1][0]-right[-2][0]
    points.insert(i+1,[fraction,knot[1],slope,fraction-left[-2][0],right[1][0]-fraction])
    result=points[1:-1]
    if len(result)==1:
        result[0].extend((points[0][4],points[-1][3]))
    else:
        result[0].extend((points[0][4],0.))
        result[-1].extend((0.,points[-1][3]))
    return result


def curve_stations(edges):
    knots=sorted({0.,1.,*(node[0] for edge in edges for node in edge)})
    if len(knots)==2:return []
    return [a+(b-a)*i/8 for a,b in zip(knots,knots[1:]) for i in range(8) if a or i]

def elliptical_planform(p):
    return str(p.get('planform','trapezoidal')) == 'elliptical'

def planform_parameters(p):
    mode=str(p.get('planform','trapezoidal'))
    if mode not in ('trapezoidal','elliptical'):raise ValueError('Scegli una pianta trapezoidale o ellittica.')
    for fraction in curve_stations(planform_nodes(p.get('planform_nodes',''))):
        if planform_section(p,p['span']*fraction)[0]<=.1:
            raise ValueError('I bordi della pianta si incrociano o la corda è troppo piccola.')
    if not elliptical_planform(p):return dict(planform=mode)
    q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))
    cr,ct=float(p['root_chord']),float(p['tip_chord'])
    if not math.isfinite(q) or not 0<=q<=100:raise ValueError('Linea centrale ellisse richiesta tra 0 e 100%.')
    if not 0<ct<cr:raise ValueError('Pianta ellittica: la corda terminale deve essere positiva e minore della corda radice.')
    # Finite terminal profile avoids a degenerate slit at a mathematical point.
    custom=profile_from_controls(p.get('custom_airfoil_tip',''),80)
    thickness=(max(y for x,y in custom)-min(y for x,y in custom)) if custom else int(str(p.get('airfoil_tip',p.get('airfoil','2412')))[2:])/100
    width=float(str(p.get('larghezza_linea_vaso',.55)).replace(',','.'))
    if ct*thickness<4*width:raise ValueError('Pianta ellittica: aumenta la corda terminale (spessore NACA minimo: quattro larghezze linea).')
    return dict(planform=mode,ellipse_center_perc=q)

def base_planform_section(p,z):
    f=z/p['span'];cr,ct=p['root_chord'],p['tip_chord']
    if not elliptical_planform(p):return cr+(ct-cr)*f,p['sweep']*f,1.
    f=max(0.,min(1.,f))
    q=float(str(p.get('ellipse_center_perc',50)).replace(',','.'))/100
    chord=math.sqrt(max(ct*ct,cr*cr-(cr*cr-ct*ct)*f*f))
    return chord,p['sweep']*f+(cr-chord)*q,1.


def planform_edge_offset(p,side,nodes,types,fraction,end=None):
    if all(mode=='cc' for mode in types) or not 0<fraction<1:
        return curve_offset(nodes,fraction,end)
    controls=curve_controls(nodes,end)
    straight=straight_segments(types)

    def base(f):
        chord,lead,_=base_planform_section(p,f*p['span'])
        return lead+side*chord

    positions=[base(f)+offset for f,offset,*_ in controls]
    slopes=[(b-a)/(last[0]-first[0]) for a,b,first,last in
            zip(positions,positions[1:],controls,controls[1:])]
    for i in range(1,len(controls)-1):
        if straight[i-1]!=straight[i]:
            f,y,_,left,right=controls[i]
            h=min(1e-5,f/2,(1-f)/2)
            slope=slopes[i-1 if straight[i-1] else i]-(base(f+h)-base(f-h))/(2*h)
            controls[i]=(f,y,slope,left,right)
    i=next(i for i,point in enumerate(controls[1:]) if fraction<=point[0])
    if straight[i]:
        h=min(1e-5,fraction/2,(1-fraction)/2)
        return (positions[i]+(fraction-controls[i][0])*slopes[i]-base(fraction),
                slopes[i]-(base(fraction+h)-base(fraction-h))/(2*h))
    return evaluate_curve(controls[i:i+2],fraction)


def planform_section(p,z):
    chord,lead,scale=base_planform_section(p,z)
    raw=p.get('planform_nodes','')
    leading,trailing=planform_nodes(raw)
    leading_types,trailing_types=planform_node_types(raw)
    fraction=z/p['span']
    shift=planform_edge_offset(p,0,leading,leading_types,fraction)[0]
    tail=planform_edge_offset(p,1,trailing,trailing_types,fraction,trailing_end_settings(raw))[0]
    return chord+tail-shift,lead+shift,scale


def with_node_stations(p,levels):
    # Keep the exact node when a regular station is almost coincident.
    nodes=[p['span']*fraction for fraction in curve_stations(planform_nodes(p.get('planform_nodes','')))]
    return sorted([*nodes,*(z for z in levels if all(abs(z-node)>1e-7 for node in nodes))])


def planform_stations(p):
    n=int(p['stations'])
    if not elliptical_planform(p):return with_node_stations(p,[p['span']*i/n for i in range(n+1)])
    # Angular sampling refines the rapidly turning terminal region.
    n=max(24,n);end=math.acos(p['tip_chord']/p['root_chord'])
    return with_node_stations(p,[p['span']*math.sin(end*i/n)/math.sin(end) for i in range(n+1)])

def planform_outline(p,n=80):
    sections=[(z,planform_section(p,z)) for z in with_node_stations(p,[p['span']*i/n for i in range(n+1)])]
    return [(z,lead) for z,(ch,lead,_) in sections]+[(z,lead+ch) for z,(ch,lead,_) in reversed(sections)]


def planform_rib_segments(p):
    """Schematic X/Z traces using the same planes and Z reflection as the CAD."""
    if str(p.get('create_ribs',True)).lower() not in ('1','true','yes','on'):return
    pitch=float(str(p.get('rib_pitch',40)).replace(',','.'))
    angle=float(str(p.get('rib_angle',45)).replace(',','.'))
    if not math.isfinite(pitch) or pitch<=0 or not 20<=angle<=70:return
    mirrored=str(p.get('nervature_specchiate_ala',False)).lower() in ('1','true','yes','on')
    total=p['span']
    if str(p.get('elliptical_tip',False)).lower() in ('1','true','yes','on'):
        total+=float(str(p.get('tip_length',40)).replace(',','.'))
    if not math.isfinite(total) or total<=0:return
    slope=math.tan(math.radians(angle))
    if (total+max(p['root_chord'],p['tip_chord'])*slope)/pitch>2000:return
    poly=planform_outline(p);d=1+slope*p['sweep']/p['span']
    custom_outline=None
    if node_fractions(p):
        try:
            from shapely.geometry import LineString, Polygon
        except ImportError:
            return
        custom_outline=Polygon(poly)
    base=-max(p['root_chord'],p['tip_chord'])*slope
    while base<=total+1e-7:
        for family in ('original','mirrored') if mirrored else ('original',):
            a=(0.,(base if family=='mirrored' else -base)/slope)
            if family=='mirrored':a=(0.,(d*total-base)/slope)
            b=(p['span'],(d*p['span']-base)/slope if family=='original' else (d*(total-p['span'])-base)/slope)
            if custom_outline is not None:
                clipped=custom_outline.intersection(LineString((a,b)))
                for segment in getattr(clipped,'geoms',(clipped,)):
                    if segment.geom_type=='LineString' and segment.length>1e-7:
                        yield family,list(segment.coords)
                continue
            delta=(b[0]-a[0],b[1]-a[1]);lo,hi=0.,1.
            for v,w in zip(poly,poly[1:]+poly[:1]):
                ez,ex=w[0]-v[0],w[1]-v[1]
                initial=ez*(a[1]-v[1])-ex*(a[0]-v[0]);rate=ez*delta[1]-ex*delta[0]
                if abs(rate)<1e-12:
                    if initial < -1e-8:hi=-1.;break
                elif rate>0:lo=max(lo,-initial/rate)
                else:hi=min(hi,-initial/rate)
                if lo>=hi:break
            if hi-lo>1e-7:
                yield family,[(a[0]+t*delta[0],a[1]+t*delta[1]) for t in (lo,hi)]
        base+=pitch
